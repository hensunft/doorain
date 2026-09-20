"""Администрирование: учётные записи, коды приглашений, обезличенная статистика, журнал действий.

Владелец видит статистику и журнал всегда. Доступ к содержимому чужого диалога открыт настройкой
DOORAIN_OWNER_CAN_READ_USER_SESSIONS (по умолчанию включена на этом стенде): каждый такой просмотр
пишется в журнал, а пользователи предупреждены об этом в интерфейсе.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import service as auth
from ..core.config import Settings, get_settings
from ..core.errors import ApiError, not_found
from ..core.util import now
from ..db.models import AuditEvent, ConsultationSession, Invite, Message, Risk, User
from ..db.session import get_db
from ..schemas.api import (
    AdminStats,
    AuditEventOut,
    InviteCreate,
    InviteCreated,
    InviteOut,
    UserAdminOut,
    UserPatch,
)
from .deps import owner

router = APIRouter(prefix="/admin", tags=["admin"])


def _user_out(db: Session, u: User) -> UserAdminOut:
    q = select(func.count()).select_from(ConsultationSession).where(ConsultationSession.user_id == u.id)
    return UserAdminOut(
        id=u.id, username=u.username, access_level=u.access_level, created_at=u.created_at, last_login_at=u.last_login_at,
        disclaimer_accepted_at=u.disclaimer_accepted_at, disabled_at=u.disabled_at,
        sessions=db.scalar(q.where(ConsultationSession.deleted_at.is_(None))) or 0,
        deleted_sessions=db.scalar(q.where(ConsultationSession.deleted_at.is_not(None))) or 0,
    )


@router.get("/users", response_model=list[UserAdminOut])
def users(ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> list[UserAdminOut]:
    return [_user_out(db, u) for u in db.scalars(select(User).order_by(User.created_at))]


@router.patch("/users/{user_id}", response_model=UserAdminOut)
def patch_user(user_id: uuid.UUID, body: UserPatch, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> UserAdminOut:
    u = db.get(User, user_id)
    if not u:
        raise not_found("Пользователь")
    if u.access_level == "owner":
        raise ApiError(409, "owner_immutable", "Учётную запись владельца нельзя отключить")
    if body.disabled is not None:
        u.disabled_at = now() if body.disabled else None
        if body.disabled:
            auth.revoke_all(db, u.id)  # отключение немедленно завершает все сессии входа
    db.add(AuditEvent(actor=ctx.user.username, action="admin.user_patch", object_type="user", object_id=str(u.id), details={"disabled": body.disabled}))
    db.commit()
    return _user_out(db, u)


@router.get("/invites", response_model=list[InviteOut])
def invites(ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> list[InviteOut]:
    names = {u.id: u.username for u in db.scalars(select(User))}
    return [
        InviteOut(
            id=i.id, hint=i.hint, note=i.note, created_at=i.created_at, expires_at=i.expires_at, used_at=i.used_at,
            used_by=names.get(i.used_by) if i.used_by else None, revoked_at=i.revoked_at,
            state="used" if i.used_at else "revoked" if i.revoked_at else "expired" if i.expires_at <= now() else "active",
        )
        for i in db.scalars(select(Invite).order_by(Invite.created_at.desc()))
    ]


@router.post("/invites", response_model=InviteCreated, status_code=201)
def create_invite(body: InviteCreate, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> InviteCreated:
    code, inv = auth.create_invite(db, s, ctx.user.id, body.note)
    db.add(AuditEvent(actor=ctx.user.username, action="admin.invite_create", object_type="invite", object_id=str(inv.id)))
    db.commit()
    return InviteCreated(code=code, expires_at=inv.expires_at, hint=inv.hint)  # код показывается один раз


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(invite_id: uuid.UUID, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> None:
    inv = db.get(Invite, invite_id)
    if not inv:
        raise not_found("Приглашение")
    if inv.used_at is None:
        inv.revoked_at = now()
    db.add(AuditEvent(actor=ctx.user.username, action="admin.invite_revoke", object_type="invite", object_id=str(inv.id)))
    db.commit()


@router.get("/stats", response_model=AdminStats)
def stats(ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> AdminStats:
    """Обезличенная статистика: количества и распределения, без текстов вопросов и ответов."""
    by_role = {str(k): int(v) for k, v in db.execute(select(ConsultationSession.role, func.count()).where(ConsultationSession.deleted_at.is_(None)).group_by(ConsultationSession.role)).all()}
    by_level = {str(k): int(v) for k, v in db.execute(select(Risk.level, func.count()).where(Risk.level.is_not(None), Risk.status.in_(("open", "in_progress"))).group_by(Risk.level)).all()}
    return AdminStats(
        users=db.scalar(select(func.count()).select_from(User)) or 0,
        active_users=db.scalar(select(func.count()).select_from(User).where(User.disabled_at.is_(None))) or 0,
        sessions=db.scalar(select(func.count()).select_from(ConsultationSession).where(ConsultationSession.deleted_at.is_(None))) or 0,
        deleted_sessions=db.scalar(select(func.count()).select_from(ConsultationSession).where(ConsultationSession.deleted_at.is_not(None))) or 0,
        messages=db.scalar(select(func.count()).select_from(Message)) or 0,
        risks_active=db.scalar(select(func.count()).select_from(Risk).where(Risk.status.in_(("open", "in_progress")))) or 0,
        sessions_by_role=by_role,
        risks_by_level=by_level,
        owner_can_read_user_sessions=s.owner_can_read_user_sessions,
    )


@router.get("/audit", response_model=list[AuditEventOut])
def audit(ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=500)) -> list[AuditEventOut]:
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.at.desc()).limit(limit))
    return [AuditEventOut.model_validate(r) for r in rows]


@router.post("/sessions/purge", response_model=dict[str, int])
def purge(ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> dict[str, int]:
    """Окончательное удаление мягко удалённых сессий (со всеми сообщениями, фактами, рисками и графом)."""
    rows = list(db.scalars(select(ConsultationSession).where(ConsultationSession.deleted_at.is_not(None))))
    for r in rows:
        db.delete(r)
    db.add(AuditEvent(actor=ctx.user.username, action="admin.purge", details={"sessions": len(rows)}))
    db.commit()
    return {"purged": len(rows)}
