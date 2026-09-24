from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ..auth import service
from ..core.config import Settings, get_settings
from ..core.security import client_ip, csrf_for, token_hash
from ..db.models import AuditEvent
from ..db.session import get_db
from ..schemas.api import AuthOut, ChangePasswordIn, LoginIn, ProfilePatch, RegisterIn, UserOut
from ..services import legal
from .deps import current_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie(resp: Response, s: Settings, token: str) -> None:
    resp.set_cookie(s.cookie_name, token, httponly=True, secure=s.cookie_secure, samesite="lax", path="/", max_age=s.session_ttl_hours * 3600)


def _out(s: Settings, user, token: str) -> AuthOut:  # noqa: ANN001
    return AuthOut(user=UserOut.model_validate(user), csrf_token=csrf_for(s, token_hash(token)), single_user_mode=s.single_user_mode)


@router.post("/login", response_model=AuthOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> AuthOut:
    token, ctx = service.login(db, s, client_ip(request, s), request.headers.get("user-agent"), body.username, body.password)
    db.add(AuditEvent(actor=ctx.user.username, action="auth.login", object_type="auth_session", object_id=str(ctx.session.id)))
    db.commit()
    _cookie(response, s, token)
    return _out(s, ctx.user, token)


@router.post("/register", response_model=AuthOut, status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> AuthOut:
    """Регистрация только по коду приглашения от владельца: публичной саморегистрации нет."""
    token, ctx = service.register(
        db, s, client_ip(request, s), request.headers.get("user-agent"), username=body.username, first_name=body.first_name, last_name=body.last_name, email=body.email,
        password=body.password, password_repeat=body.password_repeat, invite_code=body.invite_code, accept_terms=body.accept_terms, accept_pd=body.accept_pd,
    )
    db.add(AuditEvent(actor=ctx.user.username, action="auth.register", object_type="user", object_id=str(ctx.user.id), details={"legal_version": legal.version()}))  # без имени, e-mail и пароля
    db.commit()
    _cookie(response, s, token)
    return _out(s, ctx.user, token)


@router.post("/accept-disclaimer", response_model=AuthOut)
def accept_disclaimer(ctx: service.AuthContext = Depends(current_user), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> AuthOut:
    service.accept_disclaimer(db, ctx)
    db.add(AuditEvent(actor=ctx.user.username, action="auth.accept_disclaimer", object_type="user", object_id=str(ctx.user.id)))
    db.commit()
    return AuthOut(user=UserOut.model_validate(ctx.user), csrf_token=csrf_for(s, ctx.session.token_hash), single_user_mode=s.single_user_mode)


@router.post("/logout", status_code=204)
def logout(response: Response, ctx: service.AuthContext = Depends(current_user), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> None:
    service.logout(db, ctx)
    response.delete_cookie(s.cookie_name, path="/")


@router.get("/me", response_model=AuthOut)
def me(request: Request, ctx: service.AuthContext = Depends(current_user), s: Settings = Depends(get_settings)) -> AuthOut:
    return AuthOut(user=UserOut.model_validate(ctx.user), csrf_token=csrf_for(s, ctx.session.token_hash), single_user_mode=s.single_user_mode)


@router.post("/change-password", response_model=AuthOut)
def change_password(body: ChangePasswordIn, response: Response, ctx: service.AuthContext = Depends(current_user), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> AuthOut:
    token = service.change_password(db, s, ctx, body.current_password, body.new_password)
    db.add(AuditEvent(actor=ctx.user.username, action="auth.change_password"))
    db.commit()
    _cookie(response, s, token)
    return _out(s, ctx.user, token)


@router.patch("/profile", response_model=AuthOut)
def patch_profile(body: ProfilePatch, request: Request, ctx: service.AuthContext = Depends(current_user), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> AuthOut:
    """Имя, фамилия, e-mail. В журнал пишутся только названия изменённых полей, не значения."""
    changed = service.update_profile(db, s, ctx, client_ip(request, s), first_name=body.first_name, last_name=body.last_name, email=body.email, current_password=body.current_password)
    if changed:
        db.add(AuditEvent(actor=ctx.user.username, action="auth.profile_update", object_type="user", object_id=str(ctx.user.id), details={"fields": changed}))
        db.commit()
    return AuthOut(user=UserOut.model_validate(ctx.user), csrf_token=csrf_for(s, ctx.session.token_hash), single_user_mode=s.single_user_mode)
