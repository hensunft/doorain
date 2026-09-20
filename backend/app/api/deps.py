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
from ..db.models import AuditEvent, ConsultationSession, GenerationRun, User
from ..db.session import get_db
from ..services.ingestion.indexer import get_state

SAFE = {"GET", "HEAD", "OPTIONS"}
LOCAL_USER = "local"
SINGLE_USER_TOKEN = "single-user-mode"  # noqa: S105 — маркер режима без входа, не секрет: сессия в БД не создаётся


def _single_user(db: Session) -> auth.AuthContext:
    """SINGLE_USER_MODE: вход пропускается, всё работает под локальной учётной записью. В production запрещён (Settings)."""
    user = db.scalar(select(User).where(User.username == LOCAL_USER))
    if not user:
        user = db.scalar(select(User).where(User.access_level == "owner"))
    if not user:
        raise ApiError(503, "no_local_user", "Локальный режим: учётной записи нет. Создайте её командой doorain create-owner")
    return auth.AuthContext(user, auth.AuthSession(user_id=user.id, token_hash=SINGLE_USER_TOKEN, expires_at=user.created_at))


def current_user(request: Request, db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> auth.AuthContext:
    """Любая учётная запись: владелец или пользователь. Доступ к чужим объектам проверяется отдельно."""
    if s.single_user_mode:
        return _single_user(db)
    ctx = auth.resolve(db, request.cookies.get(s.cookie_name))
    if not ctx:
        raise ApiError(401, "not_authenticated", "Требуется вход")
    if ctx.user.disabled_at is not None:
        raise ApiError(403, "account_disabled", "Учётная запись отключена владельцем")
    if request.method not in SAFE:
        given = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(given, csrf_for(s, ctx.session.token_hash)):
            raise ApiError(403, "csrf_failed", "Недействительный CSRF-токен")
    return ctx


def owner(ctx: auth.AuthContext = Depends(current_user)) -> auth.AuthContext:
    """Только владелец: база знаний, учётные записи, системная диагностика и журналы."""
    if ctx.user.access_level != "owner":
        raise ApiError(403, "forbidden", "Действие доступно только владельцу")
    return ctx


def session_of(db: Session, ctx: auth.AuthContext, session_id: uuid.UUID, *, include_deleted: bool = False) -> ConsultationSession:
    obj = db.get(ConsultationSession, session_id)
    if not obj or (obj.deleted_at is not None and not include_deleted):
        raise not_found("Сессия")
    if obj.user_id == ctx.user.id:
        return obj
    s = get_settings()
    if ctx.user.access_level == "owner" and s.owner_can_read_user_sessions:
        # Решение владельца стенда: администратор видит содержимое сессий. Каждый такой доступ журналируется,
        # а пользователи предупреждены об этом в интерфейсе.
        db.add(AuditEvent(actor=ctx.user.username, action="session.read_foreign", object_type="consultation_session", object_id=str(obj.id), details={"user_id": str(obj.user_id)}))
        db.commit()
        return obj
    raise not_found("Сессия")  # чужой/угаданный ID неотличим от несуществующего


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
