"""Единственный владелец, серверные сессии, троттлинг входа (состояние хранится в БД — переживает рестарт)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.errors import ApiError
from ..core.security import hash_password, needs_rehash, new_token, token_hash, verify_password
from ..core.util import now
from ..db.models import AuthSession, Invite, LoginAttempt, User
from ..services import legal

MIN_PASSWORD = 12
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,150}\.[^@\s.]{2,}$")
_NAME = re.compile(r"^[^\W\d_]+(?:[ '\-.][^\W\d_]+)*\.?$")


def _safe_key(username: str) -> str:
    return username.strip().lower()[:50]


@dataclass
class AuthContext:
    user: User
    session: AuthSession


def check_password_policy(password: str) -> None:
    if len(password) < MIN_PASSWORD or len(password) > 256:
        raise ApiError(422, "weak_password", f"Пароль должен содержать не менее {MIN_PASSWORD} символов")


def create_owner(db: Session, username: str, password: str) -> User:
    if db.scalar(select(func.count()).select_from(User).where(User.access_level == "owner")):
        raise ApiError(409, "owner_exists", "Владелец уже создан; для смены пароля используйте reset-password")
    check_password_policy(password)
    user = User(username=_uname(username), password_hash=hash_password(password), access_level="owner", disclaimer_accepted_at=now())
    db.add(user)
    db.commit()
    return user


def _uname(username: str) -> str:
    name = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,64}", name):
        raise ApiError(422, "bad_username", "Логин: 3–64 символа, латиница, цифры, точка, дефис или подчёркивание")
    return name


def norm_email(value: str) -> str:
    email = value.strip().lower()
    if not _EMAIL.fullmatch(email) or len(email) > 200:
        raise ApiError(422, "bad_email", "Укажите корректный адрес электронной почты, например name@example.com")
    return email


def person_name(value: str, label: str) -> str:
    name = " ".join(value.split())
    if not name or len(name) > 80 or not _NAME.fullmatch(name):
        raise ApiError(422, "bad_name", f"{label}: только буквы, пробел, дефис, апостроф или точка; не более 80 символов")
    return name


def create_invite(db: Session, s: Settings, owner_id: uuid.UUID, note: str | None = None, ttl_days: int | None = None) -> tuple[str, Invite]:
    """Код показывается один раз: в базе хранится только его хеш."""
    code = new_token()
    inv = Invite(code_hash=token_hash(code), hint=code[-6:], note=(note or None), created_by=owner_id, expires_at=now() + timedelta(days=ttl_days or s.invite_ttl_days))
    db.add(inv)
    db.commit()
    return code, inv


def register(
    db: Session, s: Settings, ip: str, ua: str | None, *, username: str, first_name: str, last_name: str, email: str,
    password: str, password_repeat: str, invite_code: str, accept_terms: bool, accept_pd: bool,
) -> tuple[str, AuthContext]:
    """Регистрация только по коду приглашения: публичной саморегистрации нет. Код погашается атомарно вместе с созданием учётной записи."""
    _throttle(db, s, ip, f"register:{_safe_key(username)}")
    inv = db.scalar(select(Invite).where(Invite.code_hash == token_hash(invite_code.strip())))
    if not (inv and inv.used_at is None and inv.revoked_at is None and inv.expires_at > now()):
        db.add(LoginAttempt(ip=ip, username_key=f"register:{_safe_key(username)}", success=False))
        db.commit()
        raise ApiError(403, "invalid_invite", "Код приглашения недействителен, уже использован, отозван или истёк")
    name, first, last, mail = _uname(username), person_name(first_name, "Имя"), person_name(last_name, "Фамилия"), norm_email(email)
    check_password_policy(password)
    if password != password_repeat:
        raise ApiError(422, "password_mismatch", "Пароль и его повтор не совпадают")
    if not (accept_terms and accept_pd):
        raise ApiError(422, "consent_required", "Для регистрации нужно ознакомиться с Политикой и Условиями и дать согласие на обработку персональных данных")
    if db.scalar(select(User.id).where(User.username == name)):
        raise ApiError(409, "username_taken", "Такой логин уже занят")
    if db.scalar(select(User.id).where(User.email == mail)):
        raise ApiError(409, "email_taken", "Этот адрес электронной почты уже используется")
    stamp = now()
    user = User(username=name, first_name=first, last_name=last, email=mail, password_hash=hash_password(password), access_level="user", terms_accepted_at=stamp, pd_consent_at=stamp, legal_version=legal.version())
    db.add(user)
    try:
        db.flush()
        # Атомарное погашение: условие в самом UPDATE, поэтому два параллельных запроса с одним кодом не создадут две учётные записи.
        used = db.execute(update(Invite).where(Invite.id == inv.id, Invite.used_at.is_(None), Invite.revoked_at.is_(None), Invite.expires_at > stamp).values(used_at=stamp, used_by=user.id))
        if used.rowcount != 1:  # type: ignore[attr-defined]
            db.rollback()
            raise ApiError(403, "invalid_invite", "Код приглашения недействителен, уже использован, отозван или истёк")
        db.commit()
    except IntegrityError as e:  # параллельная регистрация того же логина или адреса
        db.rollback()
        raise ApiError(409, "username_taken", "Такой логин или адрес электронной почты уже используется") from e
    return login(db, s, ip, ua, name, password)


def update_profile(db: Session, s: Settings, ctx: AuthContext, ip: str, *, first_name: str | None, last_name: str | None, email: str | None, current_password: str | None) -> list[str]:
    """Имя, фамилия и e-mail. Логин не меняется. Смена e-mail — только с проверкой текущего пароля; адрес письмом не подтверждается."""
    user, changed = ctx.user, list[str]()
    if first_name is not None and (v := person_name(first_name, "Имя")) != user.first_name:
        user.first_name, changed = v, [*changed, "first_name"]
    if last_name is not None and (v := person_name(last_name, "Фамилия")) != user.last_name:
        user.last_name, changed = v, [*changed, "last_name"]
    if email is not None:
        new = norm_email(email) if email.strip() else None
        if new != user.email:
            key = f"profile:{user.username}"
            _throttle(db, s, ip, key)
            if not current_password or not verify_password(user.password_hash, current_password):
                db.add(LoginAttempt(ip=ip, username_key=key, success=False))
                db.commit()
                raise ApiError(403, "invalid_credentials", "Для смены адреса электронной почты введите текущий пароль")
            if new and db.scalar(select(User.id).where(User.email == new, User.id != user.id)):
                raise ApiError(409, "email_taken", "Этот адрес электронной почты уже используется")
            user.email, changed = new, [*changed, "email"]
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ApiError(409, "email_taken", "Этот адрес электронной почты уже используется") from e
    return changed


def accept_disclaimer(db: Session, ctx: AuthContext) -> None:
    if ctx.user.disclaimer_accepted_at is None:
        ctx.user.disclaimer_accepted_at = now()
        db.commit()


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
    if user.disabled_at is not None:
        db.commit()
        raise ApiError(403, "account_disabled", "Учётная запись отключена владельцем")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = now()
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
