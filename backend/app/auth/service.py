"""Единственный владелец, серверные сессии, троттлинг входа (состояние хранится в БД — переживает рестарт)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.errors import ApiError
from ..core.security import hash_password, needs_rehash, new_token, token_hash, verify_password
from ..core.util import now
from ..db.models import AuthSession, LoginAttempt, User

MIN_PASSWORD = 12


@dataclass
class AuthContext:
    user: User
    session: AuthSession


def check_password_policy(password: str) -> None:
    if len(password) < MIN_PASSWORD or len(password) > 256:
        raise ApiError(422, "weak_password", f"Пароль должен содержать не менее {MIN_PASSWORD} символов")


def create_owner(db: Session, username: str, password: str) -> User:
    if db.scalar(select(func.count()).select_from(User)):
        raise ApiError(409, "owner_exists", "Владелец уже создан; для смены пароля используйте reset-password")
    check_password_policy(password)
    user = User(username=username.strip().lower(), password_hash=hash_password(password))
    db.add(user)
    db.commit()
    return user


def revoke_all(db: Session, user_id, except_id=None) -> None:
    q = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if except_id:
        q = q.where(AuthSession.id != except_id)
    db.execute(q.values(revoked_at=now()))


def reset_password(db: Session, username: str, password: str) -> None:
    check_password_policy(password)
    user = db.scalar(select(User).where(User.username == username.strip().lower()))
    if not user:
        raise ApiError(404, "not_found", "Пользователь не найден")
    user.password_hash, user.password_changed_at = hash_password(password), now()
    revoke_all(db, user.id)
    db.commit()


def _throttle(db: Session, s: Settings, ip: str, ukey: str) -> None:
    since = now() - timedelta(minutes=s.login_window_minutes)
    ip_fail = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.ip == ip, LoginAttempt.success.is_(False), LoginAttempt.at > since)) or 0
    retry = {"Retry-After": str(s.login_window_minutes * 60)}
    if ip_fail >= s.login_ip_max_failures:
        raise ApiError(429, "too_many_attempts", "Слишком много попыток входа. Повторите позже", headers=retry)
    acct_fail = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.username_key == ukey, LoginAttempt.success.is_(False), LoginAttempt.at > since)) or 0
    if acct_fail >= s.login_account_max_failures:
        # Блокировка по аккаунту не действует на IP, откуда владелец уже входил: чужие попытки не запрут владельца навсегда.
        known = db.scalar(
            select(func.count())
            .select_from(AuthSession)
            .join(User, User.id == AuthSession.user_id)
            .where(User.username == ukey, AuthSession.ip == ip, AuthSession.created_at > now() - timedelta(days=30))
        )
        if not known:
            raise ApiError(429, "too_many_attempts", "Слишком много попыток входа. Повторите позже", headers=retry)


def login(db: Session, s: Settings, ip: str, ua: str | None, username: str, password: str) -> tuple[str, AuthContext]:
    ukey = username.strip().lower()[:64]
    _throttle(db, s, ip, ukey)
    user = db.scalar(select(User).where(User.username == ukey))
    ok = verify_password(user.password_hash if user else None, password)
    db.add(LoginAttempt(ip=ip, username_key=ukey, success=ok))
    if not ok or not user:
        db.commit()
        raise ApiError(401, "invalid_credentials", "Неверное имя пользователя или пароль")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    token = new_token()  # новый токен при каждом входе = ротация сессии
    sess = AuthSession(user_id=user.id, token_hash=token_hash(token), expires_at=now() + timedelta(hours=s.session_ttl_hours), ip=ip, user_agent=(ua or "")[:300])
    db.add(sess)
    db.execute(delete(LoginAttempt).where(LoginAttempt.at < now() - timedelta(days=7)))
    db.commit()
    return token, AuthContext(user, sess)


def resolve(db: Session, token: str | None) -> AuthContext | None:
    if not token:
        return None
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    if not sess or sess.revoked_at is not None or sess.expires_at <= now():
        return None
    user = db.get(User, sess.user_id)
    if not user:
        return None
    if now() - sess.last_seen_at > timedelta(minutes=1):
        sess.last_seen_at = now()
        db.commit()
    return AuthContext(user, sess)


def logout(db: Session, ctx: AuthContext) -> None:
    ctx.session.revoked_at = now()
    db.commit()


def change_password(db: Session, s: Settings, ctx: AuthContext, current: str, new: str) -> str:
    if not verify_password(ctx.user.password_hash, current):
        raise ApiError(403, "invalid_credentials", "Текущий пароль неверен")
    check_password_policy(new)
    ctx.user.password_hash, ctx.user.password_changed_at = hash_password(new), now()
    revoke_all(db, ctx.user.id)  # все прежние сессии отозваны, включая текущую
    token = new_token()
    sess = AuthSession(user_id=ctx.user.id, token_hash=token_hash(token), expires_at=now() + timedelta(hours=s.session_ttl_hours), ip=ctx.session.ip, user_agent=ctx.session.user_agent)
    db.add(sess)
    db.commit()
    return token
