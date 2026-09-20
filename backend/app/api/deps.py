from __future__ import annotations

import hmac
import uuid

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import service as auth
from ..core.config import Settings, get_settings
from ..core.errors import ApiError, not_found
from ..core.security import csrf_for
from ..db.models import ConsultationSession, GenerationRun
from ..db.session import get_db
from ..services.ingestion.indexer import get_state

SAFE = {"GET", "HEAD", "OPTIONS"}


def owner(request: Request, db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> auth.AuthContext:
    ctx = auth.resolve(db, request.cookies.get(s.cookie_name))
    if not ctx:
        raise ApiError(401, "not_authenticated", "Требуется вход")
    if request.method not in SAFE:
        given = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(given, csrf_for(s, ctx.session.token_hash)):
            raise ApiError(403, "csrf_failed", "Недействительный CSRF-токен")
    return ctx


def session_of(db: Session, ctx: auth.AuthContext, session_id: uuid.UUID) -> ConsultationSession:
    obj = db.get(ConsultationSession, session_id)
    if not obj or obj.user_id != ctx.user.id:  # чужой/угаданный ID неотличим от несуществующего
        raise not_found("Сессия")
    return obj


def run_of(db: Session, ctx: auth.AuthContext, run_id: uuid.UUID) -> GenerationRun:
    run = db.get(GenerationRun, run_id)
    if not run:
        raise not_found("Запрос")
    session_of(db, ctx, run.session_id)
    return run


def require_writable(db: Session) -> None:
    if get_state(db, "maintenance").get("on"):
        raise ApiError(503, "maintenance", "Идёт резервное копирование или обслуживание: запись временно недоступна", headers={"Retry-After": "60"})


def is_busy(db: Session, session_id: uuid.UUID) -> bool:
    return db.scalar(select(GenerationRun.id).where(GenerationRun.session_id == session_id, (GenerationRun.answer_status.in_(("queued", "running"))) | (GenerationRun.analysis_status == "running")).limit(1)) is not None
