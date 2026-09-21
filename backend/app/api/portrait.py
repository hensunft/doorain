"""Портрет (граф, хронология), риски, источники."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import service as auth
from ..core.config import get_settings
from ..core.errors import ApiError, not_found
from ..core.util import safe_filename
from ..db.models import (
    AuditEvent,
    Chunk,
    Citation,
    ConsultationSession,
    DocumentRevision,
    GraphEdge,
    GraphNode,
    Message,
    Risk,
    RiskEvidence,
    RiskStatusEvent,
    SessionFact,
)
from ..db.session import get_db
from ..schemas.api import (
    CitationOut,
    GraphOut,
    LayoutIn,
    MatrixCell,
    PlanStep,
    PlanStepIn,
    PlanStepPatch,
    RiskCreate,
    RiskDetail,
    RiskEventOut,
    RiskEvidenceOut,
    RiskOut,
    RiskPatch,
    RisksOut,
    TimelineItem,
)
from ..services.portrait import graph
from ..services.risks import engine
from ..services.risks.methodology import DISCLAIMER, TOPIC_TITLES
from ..services.risks.scoring import LEVEL_RU, METHODOLOGY_VERSION
from .deps import current_user, require_writable, session_of

router = APIRouter(tags=["portrait"])


@router.get("/sessions/{session_id}/graph", response_model=GraphOut)
def get_graph(session_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return graph.view(db, session_of(db, ctx, session_id))


@router.get("/sessions/{session_id}/timeline", response_model=list[TimelineItem])
def get_timeline(session_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return graph.timeline(db, session_of(db, ctx, session_id))


@router.put("/sessions/{session_id}/layout", status_code=204)
def put_layout(session_id: uuid.UUID, body: LayoutIn, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> None:
    s = session_of(db, ctx, session_id)
    valid = {str(i) for i in db.scalars(select(GraphNode.id).where(GraphNode.session_id == s.id))}
    pos = {k: {"x": max(-1e5, min(1e5, v.get("x", 0.0))), "y": max(-1e5, min(1e5, v.get("y", 0.0)))} for k, v in body.positions.items() if k in valid}
    s.layout = {**(s.layout or {}), "positions": pos, "filters": body.filters}  # шаги плана хранятся рядом и не затираются
    db.commit()


# ───────────── риски ─────────────
def _risk_out(db: Session, r: Risk) -> RiskOut:
    out = RiskOut.model_validate(r)
    out.description = r.scenario
    out.rationale = " ".join(x for x in (r.p_reason, r.s_reason) if x).strip()
    out.category = TOPIC_TITLES.get(r.category or "", r.category)
    cmap = {}
    ev = list(db.scalars(select(RiskEvidence).where(RiskEvidence.risk_id == r.id)))
    for e in ev:
        if e.kind == "obligation":
            c = db.get(Citation, e.ref_id)
            if c:
                sn = c.snapshot
                cmap[c.id] = f"{sn['short_name'] or sn['act_title']}, {sn['locator']} (ред. {sn['revision_date'] or sn['edition'] or 'н/д'})"
    out.norms = list(dict.fromkeys(cmap.values()))
    out.mentions = sum(1 for e in ev if e.kind == "message")
    node = db.scalar(select(GraphNode).where(GraphNode.session_id == r.session_id, GraphNode.stable_key == f"risk:{r.id}"))
    if node:
        out.question_ids = [str(x) for x in db.scalars(select(GraphEdge.src_id).where(GraphEdge.dst_id == node.id, GraphEdge.kind == "evidences"))]
    return out


@router.get("/sessions/{session_id}/risks", response_model=RisksOut)
def list_risks(session_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> RisksOut:
    s = session_of(db, ctx, session_id)
    rows = list(db.scalars(select(Risk).where(Risk.session_id == s.id)))
    active = sorted([r for r in rows if r.status in ("open", "in_progress")], key=lambda r: (-(r.score or 0), -(r.s or 0), r.created_at))
    closed = sorted([r for r in rows if r.status in ("resolved", "not_applicable")], key=lambda r: r.closed_at or r.updated_at)
    return RisksOut(
        active=[_risk_out(db, r) for r in active],
        resolved=[_risk_out(db, r) for r in closed],
        needs_clarification=[_risk_out(db, r) for r in rows if r.status == "needs_clarification"],
        clarifications=[f.statement for f in db.scalars(select(SessionFact).where(SessionFact.session_id == s.id, SessionFact.kind == "clarification", SessionFact.status == "active"))],
        methodology=METHODOLOGY_VERSION,
        summary=engine.summary(rows),
        thresholds=list(get_settings().risk_thresholds),
    )


def _risk_of(db: Session, ctx: auth.AuthContext, risk_id: uuid.UUID) -> Risk:
    r = db.get(Risk, risk_id)
    if not r:
        raise not_found("Риск")
    session_of(db, ctx, r.session_id)
    return r


@router.get("/risks/{risk_id}", response_model=RiskDetail)
def risk_detail(risk_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> RiskDetail:
    r = _risk_of(db, ctx, risk_id)
    evs = []
    for e in db.scalars(select(RiskEvidence).where(RiskEvidence.risk_id == r.id).order_by(RiskEvidence.created_at)):
        label, cid, mid = "", None, None
        if e.kind == "fact":
            f = db.get(SessionFact, e.ref_id)
            label = f.statement if f else "факт удалён"
        elif e.kind == "message":
            m = db.get(Message, e.ref_id)
            label, mid = (m.content[:160] if m else "сообщение удалено"), e.ref_id
        else:
            c = db.get(Citation, e.ref_id)
            if c:
                label, cid = f"{c.snapshot['short_name'] or c.snapshot['act_title']}, {c.snapshot['locator']} (ред. {c.snapshot['revision_date'] or c.snapshot['edition'] or 'н/д'})", c.id
        evs.append(RiskEvidenceOut(role=e.role, kind=e.kind, ref_id=e.ref_id, label=label, citation_id=cid, message_id=mid))
    hist = [RiskEventOut.model_validate(x) for x in db.scalars(select(RiskStatusEvent).where(RiskStatusEvent.risk_id == r.id).order_by(RiskStatusEvent.at))]
    return RiskDetail(risk=_risk_out(db, r), events=hist, evidence=evs)


@router.patch("/risks/{risk_id}", response_model=RiskOut)
def patch_risk(risk_id: uuid.UUID, body: RiskPatch, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> RiskOut:
    require_writable(db)
    r = _risk_of(db, ctx, risk_id)
    if body.status is None and (body.p is None or body.s is None):
        raise ApiError(422, "nothing_to_change", "Укажите новый статус либо обе оценки P и S")
    if body.p is not None and body.s is not None:
        engine.set_ps(db, r, body.p, body.s, body.reason, body.version, "owner")
    if body.status is not None:
        engine.set_status(db, r, {"dismissed": "not_applicable", "closed": "resolved"}.get(body.status, body.status), body.reason, r.version if body.p is not None else body.version, "owner")
    s = db.get(ConsultationSession, r.session_id)
    if s:
        s.version += 1
    db.add(AuditEvent(actor=ctx.user.username, action="risk.update", object_type="risk", object_id=str(r.id), details={"status": body.status, "p": body.p, "s": body.s}))
    db.commit()
    return _risk_out(db, r)



@router.post("/sessions/{session_id}/risks", response_model=RiskOut, status_code=201)
def create_risk(session_id: uuid.UUID, body: RiskCreate, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> RiskOut:
    """Риск, добавленный пользователем: помечается как пользовательский и не участвует в метриках качества извлечения."""
    require_writable(db)
    s = session_of(db, ctx, session_id)
    r = engine.create_user_risk(db, s, body.model_dump())
    db.add(AuditEvent(actor=ctx.user.username, action="risk.create_manual", object_type="risk", object_id=str(r.id)))
    db.commit()
    return _risk_out(db, r)


@router.post("/risks/{risk_id}/suggestion/{decision}", response_model=RiskOut)
def decide_suggestion(risk_id: uuid.UUID, decision: Literal["accept", "reject"], ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> RiskOut:
    require_writable(db)
    r = _risk_of(db, ctx, risk_id)
    engine.resolve_suggestion(db, r, decision == "accept", "owner")
    s = db.get(ConsultationSession, r.session_id)
    if s:
        s.version += 1
    db.commit()
    return _risk_out(db, r)


@router.get("/sessions/{session_id}/risks/matrix", response_model=list[MatrixCell])
def risk_matrix(session_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    s = session_of(db, ctx, session_id)
    return engine.matrix(list(db.scalars(select(Risk).where(Risk.session_id == s.id))))


_URGENCY = (("Сделать сейчас", ("critical", "high")), ("В ближайший месяц", ("medium",)), ("Мониторинг", ("low",)))


@router.get("/sessions/{session_id}/risks/export")
def export_risks(session_id: uuid.UUID, format: Literal["csv", "md"] = Query("csv"), ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    """CSV — таблица рисков; Markdown — чек-лист плана (рекомендации по срочности + шаги пользователя)."""
    s = session_of(db, ctx, session_id)
    rows = [_risk_out(db, r) for r in sorted(db.scalars(select(Risk).where(Risk.session_id == s.id)), key=lambda r: (-(r.score or 0), r.created_at))]
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["Риск", "P", "S", "P×S", "Уровень", "Основание", "Последствия", "Рекомендация", "Статус", "Происхождение"])
        for r in rows:
            w.writerow([r.title, r.p or "", r.s or "", r.score or "", LEVEL_RU.get(r.level or "", "не оценён"), "; ".join(r.norms), r.consequences, r.recommendation, r.status, "пользователь" if r.origin == "user" else "агент"])
        w.writerow([])
        w.writerow([DISCLAIMER])
        data, media, ext = "\ufeff" + buf.getvalue(), "text/csv; charset=utf-8", "csv"
    else:
        lines = [f"# План действий: {s.title}", "", f"_{DISCLAIMER}. Оценка рисков носит информационный характер и не является юридическим заключением._", ""]
        for title, levels in _URGENCY:
            group = [r for r in rows if r.status in ("open", "in_progress") and r.level in levels]
            if group:
                lines += [f"## {title}", ""]
                lines += [f"- [ ] {r.recommendation or r.title} — `{'; '.join(r.norms) or 'основание не указано'}` · риск {r.score} ({LEVEL_RU.get(r.level or '', '')})" for r in group]
                lines.append("")
        done = [r for r in rows if r.status in ("resolved", "not_applicable")]
        steps = (s.layout or {}).get("plan_steps", [])
        if steps:
            lines += ["## Шаги, добавленные вами", ""] + [f"- [{'x' if st.get('done') else ' '}] {st['title']}" for st in steps] + [""]
        if done:
            lines += ["## Закрыто", ""] + [f"- [x] {r.recommendation or r.title}" for r in done] + [""]
        data, media, ext = "\n".join(lines), "text/markdown; charset=utf-8", "md"
    name = f"doorain-risks-{stamp}.{ext}"
    return Response(data, media_type=media, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


def _steps(s: ConsultationSession) -> list[dict]:
    # копия каждого шага: JSON-колонка не замечает изменений на месте, поэтому исходник не трогаем
    return [dict(x) for x in (s.layout or {}).get("plan_steps", [])]


@router.get("/sessions/{session_id}/plan/steps", response_model=list[PlanStep])
def list_steps(session_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return _steps(session_of(db, ctx, session_id))


@router.post("/sessions/{session_id}/plan/steps", response_model=PlanStep, status_code=201)
def add_step(session_id: uuid.UUID, body: PlanStepIn, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Шаг, добавленный пользователем: агент его не перезаписывает и не удаляет при достраивании графа."""
    require_writable(db)
    s = session_of(db, ctx, session_id)
    steps = _steps(s)
    if len(steps) >= 100:
        raise ApiError(422, "too_many_steps", "Не более 100 своих шагов в сессии")
    step = {"id": uuid.uuid4().hex, "title": body.title.strip(), "done": False, "due": body.due.isoformat() if body.due else None, "created_at": datetime.now(UTC).isoformat()}
    s.layout = {**(s.layout or {}), "plan_steps": [*steps, step]}
    db.commit()
    return step


@router.patch("/sessions/{session_id}/plan/steps/{step_id}", response_model=PlanStep)
def patch_step(session_id: uuid.UUID, step_id: str, body: PlanStepPatch, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    s = session_of(db, ctx, session_id)
    steps = _steps(s)
    hit = next((x for x in steps if x["id"] == step_id), None)
    if not hit:
        raise not_found("Шаг")
    hit["done"] = body.done
    s.layout = {**(s.layout or {}), "plan_steps": steps}
    db.commit()
    return hit


@router.delete("/sessions/{session_id}/plan/steps/{step_id}", status_code=204)
def delete_step(session_id: uuid.UUID, step_id: str, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> None:
    s = session_of(db, ctx, session_id)
    s.layout = {**(s.layout or {}), "plan_steps": [x for x in _steps(s) if x["id"] != step_id]}
    db.commit()


# ───────────── источники ─────────────
def _formatted(c: Citation) -> str:
    sn = c.snapshot
    when = f"редакция от {sn['revision_date']}" if sn["revision_date"] else (f"издание: {sn['edition']}" if sn["edition"] else "дата редакции не указана")
    page = f", с. {sn['page']}" if sn.get("page") else ""
    lines = [f"«{c.excerpt.strip()}»", "", f"{sn['act_title']}" + (f" ({sn['act_number']})" if sn["act_number"] else ""), f"{sn['locator']}{page}; {when}", f"Проверена: {sn['verified_at'] or 'актуальность не подтверждена'}", f"Источник (реквизит): {sn['source_url'] or 'не указан'}", f"Происхождение: локальный корпус DoorAIn, контрольная сумма {sn['checksum'][:16]}"]
    if sn["is_demo"]:
        lines.append("Демонстрационные данные — не нормативная база")
    return "\n".join(lines)


def _cit_of(db: Session, ctx: auth.AuthContext, cid: uuid.UUID) -> Citation:
    c = db.get(Citation, cid)
    if not c:
        raise not_found("Источник")
    session_of(db, ctx, c.session_id)
    return c


@router.get("/citations/{citation_id}", response_model=CitationOut)
def get_citation(citation_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> CitationOut:
    c = _cit_of(db, ctx, citation_id)
    ch = db.get(Chunk, c.chunk_id) if c.chunk_id else None
    prev = db.get(Chunk, ch.prev_id) if ch and ch.prev_id else None
    nxt = db.get(Chunk, ch.next_id) if ch and ch.next_id else None
    return CitationOut(id=c.id, marker=c.marker, run_id=c.run_id, session_id=c.session_id, revision_id=c.revision_id, document_id=c.document_id, snapshot=c.snapshot, excerpt=c.excerpt, context_before=prev.text[-600:] if prev else None, context_after=nxt.text[:600] if nxt else None, formatted=_formatted(c), file_url=f"/api/v1/revisions/{c.revision_id}/file")


@router.get("/citations/{citation_id}/export", response_class=PlainTextResponse)
def export_citation(citation_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> PlainTextResponse:
    c = _cit_of(db, ctx, citation_id)
    name = quote(safe_filename(f"citation-{c.snapshot['locator']}.txt", "citation.txt"))
    return PlainTextResponse(_formatted(c), headers={"Content-Disposition": f"attachment; filename=\"citation.txt\"; filename*=UTF-8''{name}"})


@router.get("/revisions/{revision_id}/file")
def revision_file(revision_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> FileResponse:
    """Оригинал документа — только как attachment (не активный документ на origin приложения)."""
    r = db.get(DocumentRevision, revision_id)
    if not r or not Path(r.original_path).is_file():
        raise ApiError(404, "not_found", "Файл не найден")
    return FileResponse(r.original_path, media_type=r.mime or "application/octet-stream", filename=safe_filename(r.original_name), content_disposition_type="attachment", headers={"X-Content-Type-Options": "nosniff"})
