"""Консультационные сессии, сообщения, run'ы и SSE-события."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import service as auth
from ..core.config import Settings, get_settings
from ..core.errors import ApiError
from ..core.util import now
from ..db.models import (
    AuditEvent,
    BusinessProfile,
    Citation,
    ConsultationSession,
    Export,
    GenerationRun,
    Job,
    JobEvent,
    Message,
    Risk,
)
from ..db.session import SessionLocal, get_db
from ..schemas.api import (
    AnswerBlock,
    CitationChip,
    MessageIn,
    MessageOut,
    RoleChangeIn,
    RunAccepted,
    RunSnapshot,
    SessionCreate,
    SessionOut,
    SessionPatch,
)
from ..services import jobs
from ..services.ingestion.indexer import active_generation
from ..services.portrait import graph
from .deps import current_user, is_busy, require_writable, run_of, session_of

router = APIRouter(tags=["sessions"])
ROLE_TITLE = {"student": "Студент", "entrepreneur": "Предприниматель", "expert": "Эксперт"}


def session_out(db: Session, obj: ConsultationSession) -> SessionOut:
    prof = db.scalar(select(BusinessProfile).where(BusinessProfile.session_id == obj.id).order_by(BusinessProfile.created_at.desc()))
    out = SessionOut.model_validate(obj)
    out.profile = prof.data if prof else None
    out.messages_count = db.scalar(select(func.count()).select_from(Message).where(Message.session_id == obj.id)) or 0
    active = select(Risk.level, func.count()).where(Risk.session_id == obj.id, Risk.status.in_(("open", "in_progress")))
    out.risks_by_level = {str(k): int(v) for k, v in db.execute(active.where(Risk.level.is_not(None)).group_by(Risk.level)).all()}
    out.active_risks = db.scalar(select(func.count()).select_from(Risk).where(Risk.session_id == obj.id, Risk.status.in_(("open", "in_progress")))) or 0
    out.busy = is_busy(db, obj.id)
    return out


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(status: str = Query("active", pattern="^(active|archived|all)$"), ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> list[SessionOut]:
    q = select(ConsultationSession).where(ConsultationSession.user_id == ctx.user.id, ConsultationSession.deleted_at.is_(None)).order_by(ConsultationSession.updated_at.desc())
    if status != "all":
        q = q.where(ConsultationSession.status == status)
    return [session_out(db, x) for x in db.scalars(q)]


@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(body: SessionCreate, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> SessionOut:
    require_writable(db)
    asof = body.as_of_date or date.today()
    obj = ConsultationSession(user_id=ctx.user.id, role=body.role, as_of_date=asof, title=(body.title or f"{ROLE_TITLE[body.role]}, {asof.strftime('%d.%m.%Y')}").strip())
    db.add(obj)
    db.flush()
    if body.profile and body.role == "entrepreneur":
        db.add(BusinessProfile(session_id=obj.id, data=body.profile.model_dump()))
    graph.center(db, obj)
    db.add(AuditEvent(actor=ctx.user.username, action="session.create", object_type="session", object_id=str(obj.id), details={"role": body.role}))
    db.commit()
    return session_out(db, obj)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> SessionOut:
    return session_out(db, session_of(db, ctx, session_id))


@router.patch("/sessions/{session_id}", response_model=SessionOut)
def patch_session(session_id: uuid.UUID, body: SessionPatch, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> SessionOut:
    obj = session_of(db, ctx, session_id)
    if body.title:
        obj.title = body.title.strip()
    if body.status:
        obj.status = body.status
    obj.updated_at = now()
    db.commit()
    return session_out(db, obj)


@router.post("/sessions/{session_id}/change-role", response_model=SessionOut, status_code=201)
def change_role(session_id: uuid.UUID, body: RoleChangeIn, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> SessionOut:
    """Смена роли создаёт НОВУЮ сессию; предыдущая и её данные сохраняются, сведения не переносятся."""
    require_writable(db)
    old = session_of(db, ctx, session_id)
    new = ConsultationSession(user_id=ctx.user.id, role=body.role, as_of_date=old.as_of_date, title=f"{ROLE_TITLE[body.role]}, {date.today().strftime('%d.%m.%Y')}", parent_session_id=old.id)
    db.add(new)
    db.flush()
    prof = db.scalar(select(BusinessProfile).where(BusinessProfile.session_id == old.id).order_by(BusinessProfile.created_at.desc()))
    if prof and body.role == "entrepreneur":
        db.add(BusinessProfile(session_id=new.id, data=prof.data))
    graph.center(db, new)
    db.commit()
    return session_out(db, new)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: uuid.UUID, confirm: str = Query(..., description="Точное название сессии"), ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> None:
    """Мягкое удаление: сессия исчезает из интерфейса, задания отменяются, файлы экспортов стираются.

    Окончательная очистка строк — команда владельца (POST /admin/sessions/purge). Корпус НПА не затрагивается,
    прежние backup и уже выгруженные файлы не изменяются.
    """
    obj = session_of(db, ctx, session_id)
    if confirm.strip() != obj.title.strip():
        raise ApiError(422, "confirm_mismatch", "Для удаления введите точное название сессии")
    run_ids = list(db.scalars(select(GenerationRun.id).where(GenerationRun.session_id == obj.id)))
    for j in db.scalars(select(Job).where(Job.run_id.in_(run_ids))) if run_ids else []:
        jobs.request_cancel(db, j)
    for ex in db.scalars(select(Export).where(Export.session_id == obj.id)):
        if ex.file_path:
            Path(ex.file_path).unlink(missing_ok=True)
            ex.file_path = None
    if run_ids:
        db.execute(delete(Job).where(Job.run_id.in_(run_ids)))
    obj.deleted_at = now()
    db.add(AuditEvent(actor=ctx.user.username, action="session.delete", object_type="session", object_id=str(obj.id), details={"soft": True}))
    db.commit()


# ───────────── сообщения ─────────────
def _chips(db: Session, run_id: uuid.UUID | None) -> list[CitationChip]:
    if not run_id:
        return []
    out = []
    for c in db.scalars(select(Citation).where(Citation.run_id == run_id).order_by(Citation.rank)):
        sn = c.snapshot
        out.append(CitationChip(id=c.id, marker=c.marker, label=sn["short_name"] or sn["act_title"], locator=sn["locator"], revision_label=f"ред. {sn['revision_date']}" if sn["revision_date"] else (f"изд. {sn['edition']}" if sn["edition"] else "дата не указана"), verified=bool(sn["verified_at"]), is_demo=sn["is_demo"]))
    return out


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
def list_messages(session_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> list[MessageOut]:
    obj = session_of(db, ctx, session_id)
    runs = {r.id: r for r in db.scalars(select(GenerationRun).where(GenerationRun.session_id == obj.id))}
    by_user = {r.user_message_id: r for r in runs.values()}
    out = []
    for m in db.scalars(select(Message).where(Message.session_id == obj.id).order_by(Message.seq)):
        run = runs.get(m.run_id) if m.run_id else by_user.get(m.id)
        out.append(MessageOut(
            id=m.id, seq=m.seq, role="user" if m.role == "user" else "assistant", text=m.content, blocks=[AnswerBlock(**b) for b in m.blocks] if m.blocks else None, citations=_chips(db, m.run_id) if m.role == "assistant" else [],
            run_id=run.id if run else None, answer_status=run.answer_status if run else None, analysis_status=run.analysis_status if run else None,
            refusal_reason=run.refusal_reason if run else None, warnings=list(run.warnings) if run and m.role == "assistant" else [], created_at=m.created_at,
        ))
    return out


@router.post("/sessions/{session_id}/messages", response_model=RunAccepted, status_code=202)
def post_message(session_id: uuid.UUID, body: MessageIn, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> RunAccepted:
    require_writable(db)
    obj = session_of(db, ctx, session_id)
    if obj.status != "active":
        raise ApiError(409, "session_archived", "Сессия в архиве: верните её из архива, чтобы продолжить")
    dup = db.scalar(select(Message).where(Message.session_id == obj.id, Message.client_request_id == body.client_request_id))
    if dup:  # идемпотентность: повторный POST (двойной клик, retry) не создаёт второй run
        run = db.scalar(select(GenerationRun).where(GenerationRun.user_message_id == dup.id))
        assert run
        return RunAccepted(run_id=run.id, message_id=dup.id, deduplicated=True)
    if is_busy(db, obj.id):
        raise ApiError(409, "run_in_progress", "В этой сессии уже выполняется запрос (возможно, в другой вкладке). Дождитесь завершения или остановите его")
    gen = active_generation(db)
    seq = (db.scalar(select(func.max(Message.seq)).where(Message.session_id == obj.id)) or 0) + 1
    try:
        m = Message(session_id=obj.id, seq=seq, role="user", content=body.text.strip(), client_request_id=body.client_request_id)
        db.add(m)
        db.flush()
        run = GenerationRun(session_id=obj.id, user_message_id=m.id, corpus_generation_id=gen.id if gen else None, as_of_date=obj.as_of_date, session_version=obj.version)
        db.add(run)
        db.flush()
        m.run_id = run.id
        job = jobs.enqueue(db, "chat_run", {"run_id": str(run.id)}, run_id=run.id, idempotency_key=f"chat:{run.id}")
        run.job_id = job.id
        obj.updated_at = now()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "run_in_progress", "Параллельная отправка в этой сессии; повторите") from None
    return RunAccepted(run_id=run.id, message_id=m.id)


# ───────────── run: snapshot, отмена, повтор аналитики, SSE ─────────────
def _fold_blocks(db: Session, run_id: uuid.UUID) -> tuple[list[dict[str, Any]], int]:
    blocks: dict[str, dict[str, Any]] = {}
    last = 0
    for ev in db.scalars(select(JobEvent).where(JobEvent.run_id == run_id).order_by(JobEvent.id)):
        last = ev.id
        if ev.type in ("answer_delta", "answer_block_replaced"):
            b = ev.data["block"]
            if b.get("removed"):
                blocks.pop(b["id"], None)
            else:
                blocks[b["id"]] = b
        elif ev.type == "answer_completed":
            blocks = {b["id"]: b for b in ev.data.get("blocks", [])}
        elif ev.type == "status" and ev.data.get("stage") == "restarted":
            blocks = {}
    return list(blocks.values()), last


@router.get("/runs/{run_id}", response_model=RunSnapshot)
def run_snapshot(run_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> RunSnapshot:
    run = run_of(db, ctx, run_id)
    blocks, last = _fold_blocks(db, run.id)
    done = run.answer_status in ("validated", "refused", "cancelled", "failed") and run.analysis_status != "running"
    return RunSnapshot(run_id=run.id, session_id=run.session_id, answer_status=run.answer_status, analysis_status=run.analysis_status, refusal_reason=run.refusal_reason, error_code=run.error_code, warnings=list(run.warnings), blocks=[AnswerBlock(**b) for b in blocks], last_event_id=last, done=done, user_message_id=run.user_message_id, assistant_message_id=run.assistant_message_id, timings={"ttft_ms": (run.trace or {}).get("ttft_ms"), **(run.trace or {}).get("stages_ms", {})})


@router.get("/runs/{run_id}/trace")
def run_trace(run_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Аудит ответа (только владельцу): версии prompt/schema/методологии, chunk IDs и scores, модель, тайминги, проверки."""
    run = run_of(db, ctx, run_id)
    cits = db.scalars(select(Citation).where(Citation.run_id == run.id).order_by(Citation.rank)).all()
    return {
        "run_id": str(run.id), "answer_status": run.answer_status, "analysis_status": run.analysis_status, "refusal_reason": run.refusal_reason, "error_code": run.error_code,
        "corpus_generation_id": str(run.corpus_generation_id) if run.corpus_generation_id else None, "as_of_date": run.as_of_date.isoformat(), "session_version": run.session_version,
        "model_info": run.model_info, "trace": run.trace, "warnings": run.warnings, "created_at": run.created_at.isoformat(), "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "citations": [{"id": str(c.id), "marker": c.marker, "chunk_id": str(c.chunk_id) if c.chunk_id else None, "revision_id": str(c.revision_id), "score": c.score, "locator": c.snapshot.get("locator"), "act": c.snapshot.get("short_name") or c.snapshot.get("act_title")} for c in cits],
    }


@router.post("/runs/{run_id}/cancel", response_model=RunSnapshot)
def cancel_run(run_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> RunSnapshot:
    run = run_of(db, ctx, run_id)
    for j in db.scalars(select(Job).where(Job.run_id == run.id, Job.status.in_(("queued", "running")))):
        was_queued = j.status == "queued"
        jobs.request_cancel(db, j)
        if was_queued and j.type == "chat_run" and run.answer_status == "queued":  # отмена до старта: worker run не увидит
            sess = db.get(ConsultationSession, run.session_id)
            msg = db.get(Message, run.user_message_id)
            if sess and msg:
                blk = {"id": "b1", "version": 1, "kind": "notice", "text": "Запрос отменён до начала обработки.", "citation_ids": [], "markers": [], "state": "unsupported", "reason": None}
                asst = Message(session_id=sess.id, seq=msg.seq + 1, role="assistant", content=blk["text"], blocks=[blk], run_id=run.id)
                db.add(asst)
                db.flush()
                run.assistant_message_id, run.answer_status, run.finished_at = asst.id, "cancelled", now()
                graph.question(db, sess, msg, "cancelled", [])
                sess.version += 1
                db.commit()
    db.refresh(run)
    return run_snapshot(run_id, ctx, db)


@router.post("/runs/{run_id}/analysis/retry", response_model=RunAccepted, status_code=202)
def retry_analysis(run_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> RunAccepted:
    require_writable(db)
    run = run_of(db, ctx, run_id)
    if run.answer_status != "validated" or run.analysis_status not in ("failed", "cancelled"):
        raise ApiError(409, "analysis_not_retryable", "Повторить можно только сбойную или отменённую аналитику проверенного ответа")
    if is_busy(db, run.session_id):
        raise ApiError(409, "run_in_progress", "В сессии выполняется другой запрос")
    n = db.scalar(select(func.count()).select_from(Job).where(Job.run_id == run.id, Job.type == "analysis_run")) or 0
    jobs.enqueue(db, "analysis_run", {"run_id": str(run.id)}, run_id=run.id, idempotency_key=f"analysis:{run.id}:{n + 1}")
    db.commit()
    return RunAccepted(run_id=run.id, message_id=run.user_message_id)


def _fetch(run_id: uuid.UUID, after: int) -> tuple[list[tuple[int, str, dict[str, Any]]], int]:
    db = SessionLocal()
    try:
        evs = [(e.id, e.type, e.data) for e in jobs.events_after(db, run_id, after)]
        return evs, jobs.max_event_id(db, run_id)
    finally:
        db.close()


def _auth_alive(token: str | None) -> bool:
    db = SessionLocal()
    try:
        return auth.resolve(db, token) is not None
    finally:
        db.close()


@router.get("/runs/{run_id}/events")
async def run_events(run_id: uuid.UUID, request: Request, after: int = Query(0, ge=0), last_event_id: str | None = Header(default=None), ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> StreamingResponse:
    run = run_of(db, ctx, run_id)
    rid = run.id
    token = request.cookies.get(s.cookie_name)
    last = after or (int(last_event_id) if last_event_id and last_event_id.isdigit() else 0)

    async def gen() -> AsyncIterator[str]:
        nonlocal last
        _, mx = await run_in_threadpool(_fetch, rid, 0)
        if last > mx:  # клиент опережает БД (потерянный replay) — отдаём snapshot-событие, затем продолжаем
            yield f"event: snapshot\ndata: {json.dumps({'run_id': str(rid), 'reason': 'replay_lost'})}\n\n"
            last = 0
        t_ping = t_auth = time.monotonic()
        while True:
            if await request.is_disconnected():
                return  # отключение браузера ≠ отмена: run продолжает выполняться
            evs, _ = await run_in_threadpool(_fetch, rid, last)
            for eid, typ, data in evs:
                last = eid
                yield f"id: {eid}\nevent: {typ}\ndata: {json.dumps({'run_id': str(rid), **data}, ensure_ascii=False)}\n\n"
                if typ in jobs.TERMINAL_EVENTS:
                    return
            t = time.monotonic()
            if t - t_auth > 20:
                t_auth = t
                if not await run_in_threadpool(_auth_alive, token):
                    yield f"event: failed\ndata: {json.dumps({'run_id': str(rid), 'code': 'auth_revoked', 'message': 'Сессия входа завершена'})}\n\n"
                    return
            if t - t_ping > 15:
                t_ping = t
                yield ": ping\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
