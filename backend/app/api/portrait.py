"""Портрет (граф, хронология), риски, источники."""

from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import service as auth
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
from ..services.risks.methodology import TOPIC_TITLES
from ..services.risks.scoring import METHODOLOGY_VERSION
from .deps import owner, require_writable, session_of

router = APIRouter(tags=["portrait"])


@router.get("/sessions/{session_id}/graph", response_model=GraphOut)
def get_graph(session_id: uuid.UUID, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> dict:
    return graph.view(db, session_of(db, ctx, session_id))


@router.get("/sessions/{session_id}/timeline", response_model=list[TimelineItem])
def get_timeline(session_id: uuid.UUID, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> list[dict]:
    return graph.timeline(db, session_of(db, ctx, session_id))


@router.put("/sessions/{session_id}/layout", status_code=204)
def put_layout(session_id: uuid.UUID, body: LayoutIn, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> None:
    s = session_of(db, ctx, session_id)
    valid = {str(i) for i in db.scalars(select(GraphNode.id).where(GraphNode.session_id == s.id))}
    pos = {k: {"x": max(-1e5, min(1e5, v.get("x", 0.0))), "y": max(-1e5, min(1e5, v.get("y", 0.0)))} for k, v in body.positions.items() if k in valid}
    s.layout = {"positions": pos, "filters": body.filters}
    db.commit()


# ───────────── риски ─────────────
def _risk_out(db: Session, r: Risk) -> RiskOut:
    out = RiskOut.model_validate(r)
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
    node = db.scalar(select(GraphNode).where(GraphNode.session_id == r.session_id, GraphNode.stable_key == f"risk:{r.id}"))
    if node:
        out.question_ids = [str(x) for x in db.scalars(select(GraphEdge.src_id).where(GraphEdge.dst_id == node.id, GraphEdge.kind == "evidences"))]
    return out


@router.get("/sessions/{session_id}/risks", response_model=RisksOut)
def list_risks(session_id: uuid.UUID, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> RisksOut:
    s = session_of(db, ctx, session_id)
    rows = list(db.scalars(select(Risk).where(Risk.session_id == s.id)))
    active = sorted([r for r in rows if r.status in ("open", "in_progress")], key=lambda r: (-(r.score or 0), -(r.s or 0), r.created_at))
    return RisksOut(
        active=[_risk_out(db, r) for r in active],
        resolved=[_risk_out(db, r) for r in rows if r.status in ("resolved", "not_applicable")],
        needs_clarification=[_risk_out(db, r) for r in rows if r.status == "needs_clarification"],
        clarifications=[f.statement for f in db.scalars(select(SessionFact).where(SessionFact.session_id == s.id, SessionFact.kind == "clarification", SessionFact.status == "active"))],
        methodology=METHODOLOGY_VERSION,
    )


def _risk_of(db: Session, ctx: auth.AuthContext, risk_id: uuid.UUID) -> Risk:
    r = db.get(Risk, risk_id)
    if not r:
        raise not_found("Риск")
    session_of(db, ctx, r.session_id)
    return r


@router.get("/risks/{risk_id}", response_model=RiskDetail)
def risk_detail(risk_id: uuid.UUID, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> RiskDetail:
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
def patch_risk(risk_id: uuid.UUID, body: RiskPatch, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> RiskOut:
    require_writable(db)
    r = _risk_of(db, ctx, risk_id)
    engine.set_status(db, r, body.status, body.reason, body.version, "owner")
    s = db.get(ConsultationSession, r.session_id)
    if s:
        s.version += 1
    db.add(AuditEvent(actor=ctx.user.username, action="risk.status", object_type="risk", object_id=str(r.id), details={"status": body.status}))
    db.commit()
    return _risk_out(db, r)


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
def get_citation(citation_id: uuid.UUID, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> CitationOut:
    c = _cit_of(db, ctx, citation_id)
    ch = db.get(Chunk, c.chunk_id) if c.chunk_id else None
    prev = db.get(Chunk, ch.prev_id) if ch and ch.prev_id else None
    nxt = db.get(Chunk, ch.next_id) if ch and ch.next_id else None
    return CitationOut(id=c.id, marker=c.marker, run_id=c.run_id, session_id=c.session_id, revision_id=c.revision_id, document_id=c.document_id, snapshot=c.snapshot, excerpt=c.excerpt, context_before=prev.text[-600:] if prev else None, context_after=nxt.text[:600] if nxt else None, formatted=_formatted(c), file_url=f"/api/v1/revisions/{c.revision_id}/file")


@router.get("/citations/{citation_id}/export", response_class=PlainTextResponse)
def export_citation(citation_id: uuid.UUID, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> PlainTextResponse:
    c = _cit_of(db, ctx, citation_id)
    name = quote(safe_filename(f"citation-{c.snapshot['locator']}.txt", "citation.txt"))
    return PlainTextResponse(_formatted(c), headers={"Content-Disposition": f"attachment; filename=\"citation.txt\"; filename*=UTF-8''{name}"})


@router.get("/revisions/{revision_id}/file")
def revision_file(revision_id: uuid.UUID, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> FileResponse:
    """Оригинал документа — только как attachment (не активный документ на origin приложения)."""
    r = db.get(DocumentRevision, revision_id)
    if not r or not Path(r.original_path).is_file():
        raise ApiError(404, "not_found", "Файл не найден")
    return FileResponse(r.original_path, media_type=r.mime or "application/octet-stream", filename=safe_filename(r.original_name), content_disposition_type="attachment", headers={"X-Content-Type-Options": "nosniff"})
