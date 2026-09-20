from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ..auth import service
from ..core.config import Settings, get_settings
from ..core.security import client_ip, csrf_for, token_hash
from ..db.models import AuditEvent
from ..db.session import get_db
from ..schemas.api import AuthOut, ChangePasswordIn, LoginIn, UserOut
from .deps import owner

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie(resp: Response, s: Settings, token: str) -> None:
    resp.set_cookie(s.cookie_name, token, httponly=True, secure=s.cookie_secure, samesite="lax", path="/", max_age=s.session_ttl_hours * 3600)


def _out(s: Settings, user, token: str) -> AuthOut:  # noqa: ANN001
    return AuthOut(user=UserOut.model_validate(user), csrf_token=csrf_for(s, token_hash(token)))


@router.post("/login", response_model=AuthOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> AuthOut:
    token, ctx = service.login(db, s, client_ip(request, s), request.headers.get("user-agent"), body.username, body.password)
    db.add(AuditEvent(actor=ctx.user.username, action="auth.login", object_type="auth_session", object_id=str(ctx.session.id)))
    db.commit()
    _cookie(response, s, token)
    return _out(s, ctx.user, token)


@router.post("/logout", status_code=204)
def logout(response: Response, ctx: service.AuthContext = Depends(owner), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> None:
    service.logout(db, ctx)
    response.delete_cookie(s.cookie_name, path="/")


@router.get("/me", response_model=AuthOut)
def me(request: Request, ctx: service.AuthContext = Depends(owner), s: Settings = Depends(get_settings)) -> AuthOut:
    return AuthOut(user=UserOut.model_validate(ctx.user), csrf_token=csrf_for(s, ctx.session.token_hash))


@router.post("/change-password", response_model=AuthOut)
def change_password(body: ChangePasswordIn, response: Response, ctx: service.AuthContext = Depends(owner), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> AuthOut:
    token = service.change_password(db, s, ctx, body.current_password, body.new_password)
    db.add(AuditEvent(actor=ctx.user.username, action="auth.change_password"))
    db.commit()
    _cookie(response, s, token)
    return _out(s, ctx.user, token)
