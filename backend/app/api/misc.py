"""Самопроверка, экспорт PDF, система (liveness/статус/диагностика)."""

from __future__ import annotations

import shutil
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import __version__
from ..auth import service as auth
from ..core.config import Settings, get_settings
from ..core.errors import ApiError, not_found
from ..db.models import AuditEvent, ConsultationSession, Export, GenerationRun, Job, Quiz, QuizAttempt
from ..db.session import get_db
from ..providers.registry import get_providers
from ..schemas.api import (
    Diagnostics,
    ExportCreate,
    ExportOut,
    ModelStatus,
    QuizAttemptIn,
    QuizAttemptOut,
    QuizOut,
    QuizQuestionOut,
    SystemStatus,
)
from ..services import jobs, quiz
from ..services.exports import pdf
from ..services.ingestion.indexer import active_generation, get_state
from ..services.risks.methodology import DISCLAIMER
from .deps import current_user, owner, require_writable, session_of

router = APIRouter(tags=["misc"])
public = APIRouter(tags=["system"])


# ───────────── самопроверка ─────────────
def _quiz_out(q: Quiz) -> QuizOut:
    return QuizOut(id=q.id, status=q.status, error=q.error, job_id=q.job_id, questions=[QuizQuestionOut(**x) for x in quiz.public_questions(q)] if q.status == "ready" else [])


@router.post("/sessions/{session_id}/quiz", response_model=QuizOut, status_code=202)
def create_quiz(session_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> QuizOut:
    require_writable(db)
    s = session_of(db, ctx, session_id)
    if s.role != "student":
        raise ApiError(422, "student_only", "Самопроверка доступна в роли «Студент»")
    q = Quiz(session_id=s.id)
    db.add(q)
    db.flush()
    j = jobs.enqueue(db, "quiz_generate", {"quiz_id": str(q.id)})
    q.job_id = j.id
    db.commit()
    return _quiz_out(q)


def _quiz_of(db: Session, ctx: auth.AuthContext, qid: uuid.UUID) -> tuple[Quiz, ConsultationSession]:
    q = db.get(Quiz, qid)
    if not q:
        raise not_found("Самопроверка")
    return q, session_of(db, ctx, q.session_id)


@router.get("/quizzes/{quiz_id}", response_model=QuizOut)
def get_quiz(quiz_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> QuizOut:
    return _quiz_out(_quiz_of(db, ctx, quiz_id)[0])


@router.get("/sessions/{session_id}/quizzes", response_model=list[QuizOut])
def list_quizzes(session_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> list[QuizOut]:
    s = session_of(db, ctx, session_id)
    return [_quiz_out(q) for q in db.scalars(select(Quiz).where(Quiz.session_id == s.id).order_by(Quiz.created_at.desc()))]


@router.post("/quizzes/{quiz_id}/attempts", response_model=QuizAttemptOut, status_code=201)
def submit_attempt(quiz_id: uuid.UUID, body: QuizAttemptIn, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> QuizAttemptOut:
    require_writable(db)
    q, s = _quiz_of(db, ctx, quiz_id)
    att: QuizAttempt = quiz.submit(db, s, q, body.answers)
    return QuizAttemptOut(id=att.id, results=att.results, correct=sum(1 for r in att.results if r["correct"]), total=len(att.results))


# ───────────── экспорт ─────────────
@router.post("/sessions/{session_id}/exports", response_model=ExportOut, status_code=202)
def create_export(session_id: uuid.UUID, body: ExportCreate, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> Export:
    require_writable(db)
    s = session_of(db, ctx, session_id)
    pending = db.scalar(select(GenerationRun.id).where(GenerationRun.session_id == s.id, (GenerationRun.answer_status.in_(("queued", "running"))) | (GenerationRun.analysis_status == "running")).limit(1))
    failed = db.scalar(select(GenerationRun.id).where(GenerationRun.session_id == s.id, GenerationRun.analysis_status == "failed").limit(1))
    reason = "анализ сессии выполняется" if pending else ("анализ одного из ответов завершился ошибкой" if failed else None)
    if reason and not body.allow_incomplete:
        raise ApiError(409, "analysis_pending", f"Экспорт неполный: {reason}. Дождитесь завершения либо выгрузите неполный снимок явно", {"reason": reason})
    snap = pdf.build_snapshot(db, s, body.model_dump(), reason)  # согласованный снимок в одной транзакции чтения
    ex = Export(session_id=s.id, options=body.model_dump(), snapshot=snap, incomplete=reason is not None)
    db.add(ex)
    db.flush()
    j = jobs.enqueue(db, "export_pdf", {"export_id": str(ex.id)})
    ex.job_id = j.id
    db.add(AuditEvent(actor=ctx.user.username, action="export.create", object_type="export", object_id=str(ex.id), details={"incomplete": ex.incomplete}))
    db.commit()
    return ex


def _export_of(db: Session, ctx: auth.AuthContext, eid: uuid.UUID) -> Export:
    ex = db.get(Export, eid)
    if not ex:
        raise not_found("Экспорт")
    session_of(db, ctx, ex.session_id)
    return ex


@router.get("/exports/{export_id}", response_model=ExportOut)
def get_export(export_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> Export:
    return _export_of(db, ctx, export_id)


@router.get("/sessions/{session_id}/exports", response_model=list[ExportOut])
def list_exports(session_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> list[Export]:
    s = session_of(db, ctx, session_id)
    return list(db.scalars(select(Export).where(Export.session_id == s.id).order_by(Export.created_at.desc())))


@router.get("/exports/{export_id}/download")
def download_export(export_id: uuid.UUID, ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> FileResponse:
    ex = _export_of(db, ctx, export_id)  # права проверяются при каждом скачивании
    if ex.status != "ready" or not ex.file_path or not Path(ex.file_path).is_file():
        raise ApiError(409, "export_not_ready", "PDF ещё не готов")
    return FileResponse(ex.file_path, media_type="application/pdf", filename=f"doorain-portrait-{ex.created_at:%Y%m%d-%H%M}.pdf", content_disposition_type="attachment", headers={"X-Content-Type-Options": "nosniff"})


# ───────────── система ─────────────
@public.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


def _worker_alive(db: Session) -> tuple[bool, str | None]:
    hb = get_state(db, "worker").get("heartbeat")
    if not hb:
        return False, None
    age = (datetime.now(UTC) - datetime.fromisoformat(hb)).total_seconds()
    return age < 30, hb


@router.get("/system/status", response_model=SystemStatus)
def status(ctx: auth.AuthContext = Depends(current_user), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> SystemStatus:
    p = get_providers()
    h = p.llm.health()
    gen = active_generation(db)
    from ..db.models import Document  # noqa: PLC0415

    state: Literal["ready", "unavailable", "test_mode"] = "test_mode" if p.is_test else ("ready" if h.ok else "unavailable")
    alive, _ = _worker_alive(db)
    return SystemStatus(
        model=ModelStatus(state=state, name=h.info.get("name") if h.ok else s.ollama_model, detail=h.detail), corpus_empty=gen is None, corpus_as_of=date.today() if gen else None, generation_seq=gen.seq if gen else None,
        has_demo=bool(db.scalar(select(Document.id).where(Document.is_demo.is_(True), Document.excluded_at.is_(None)).limit(1))), worker_alive=alive or s.env == "test", maintenance=bool(get_state(db, "maintenance").get("on")), provider_mode=s.provider_mode, disclaimer=DISCLAIMER, version=__version__,
    )


@router.get("/system/diagnostics", response_model=Diagnostics)
def diagnostics(ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> Diagnostics:
    from ..db.models import Chunk, DocumentRevision  # noqa: PLC0415

    p = get_providers()
    try:
        db.execute(text("select 1"))
        dbi = {"ok": True, "dialect": db.bind.dialect.name if db.bind else None}
    except Exception as e:  # noqa: BLE001
        dbi = {"ok": False, "error": type(e).__name__}
    hl, he, hr = p.llm.health(), p.embedder.health(), p.reranker.health()
    alive, hb = _worker_alive(db)
    gen = active_generation(db)
    du = shutil.disk_usage(s.data_dir if s.data_dir.exists() else Path("."))
    jc = {st: n for st, n in db.execute(select(Job.status, func.count()).group_by(Job.status)).all()}
    n_rev = db.scalar(select(func.count()).select_from(DocumentRevision).where(DocumentRevision.status == "ready")) or 0
    return Diagnostics(
        version=__version__, provider_mode=s.provider_mode, database=dbi, qdrant={"ok": p.vs.health(), "collection": gen.collection_name if gen else None, "points": p.vs.count(gen.collection_name) if gen else 0},
        llm={"ok": hl.ok, "detail": hl.detail, **hl.info, "test": p.llm.is_test}, embedder={"ok": he.ok, "detail": he.detail, "fingerprint_hash": gen.fingerprint_hash[:16] if gen else None}, reranker={"ok": hr.ok, "detail": hr.detail, "name": p.reranker.name()},
        worker={"alive": alive, "heartbeat": hb}, corpus={"revisions": n_rev, "chunks": db.scalar(select(func.count()).select_from(Chunk)) or 0, "empty": n_rev == 0, "generation_seq": gen.seq if gen else None, "control_search": gen.control_search if gen else None},
        jobs=jc, disk={"free_gb": round(du.free / 1e9, 1), "total_gb": round(du.total / 1e9, 1)}, maintenance=bool(get_state(db, "maintenance").get("on")),
        thresholds={"min_rerank_score": s.min_rerank_score, "source": s.threshold_source, "num_ctx": s.ollama_num_ctx, "num_predict": s.ollama_num_predict, "top_k": s.retrieval_top_k, "rerank_keep": s.rerank_keep},
    )
