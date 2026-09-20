from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.conftest import PASSWORD, Api, ask, new_session


def _make_owner(name: str = "owner", pw: str = PASSWORD) -> None:
    from app.auth.service import create_owner
    from app.db.session import SessionLocal

    db = SessionLocal()
    create_owner(db, name, pw)
    db.close()


def test_no_public_registration_and_unauthenticated_access(client: TestClient) -> None:
    assert client.post("/api/v1/auth/register", json={"username": "x", "password": "y" * 20}).status_code in (404, 405)
    assert client.get("/api/v1/health/live").json() == {"status": "ok"}
    for path in ("/sessions", "/auth/me", "/corpus/overview", "/system/diagnostics", "/system/status", f"/sessions/{uuid.uuid4()}/graph", f"/exports/{uuid.uuid4()}/download", f"/runs/{uuid.uuid4()}/events", f"/citations/{uuid.uuid4()}"):
        r = client.get("/api/v1" + path)
        assert r.status_code == 401, path
        assert r.json()["code"] == "not_authenticated" and r.json()["request_id"]


def test_login_flags_and_generic_errors(client: TestClient) -> None:
    _make_owner()
    bad_pw = client.post("/api/v1/auth/login", json={"username": "owner", "password": "wrong-password-123"})
    bad_user = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "wrong-password-123"})
    assert bad_pw.status_code == bad_user.status_code == 401
    assert bad_pw.json()["message"] == bad_user.json()["message"]  # одинаковые ошибки
    ok = client.post("/api/v1/auth/login", json={"username": "owner", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["csrf_token"]
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "doorain_session" in cookie
    assert "authorization" not in ok.text.lower()


def test_secure_cookie_prefix_in_production_mode(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    s = Settings(env="production", secret_key="s" * 40, cookie_secure=True, provider_mode="ollama", allowed_hosts=["doorain.test"])  # type: ignore[arg-type]
    assert s.cookie_name == "__Host-doorain_session"


def test_production_guards() -> None:
    from app.core.config import Settings

    good = dict(env="production", secret_key="s" * 40, cookie_secure=True, provider_mode="ollama", allowed_hosts=["doorain.test"])
    Settings(**good)  # type: ignore[arg-type]
    for patch in ({"secret_key": "change-me"}, {"secret_key": "short"}, {"cookie_secure": False}, {"provider_mode": "test"}, {"allowed_hosts": ["example.com"]}, {"allowed_hosts": []}):
        with pytest.raises(ValidationError):
            Settings(**{**good, **patch})  # type: ignore[arg-type]


def test_docs_disabled_in_production(env: Path) -> None:
    from app.core.config import Settings
    from app.main import create_app

    s = Settings(env="production", secret_key="s" * 40, cookie_secure=True, provider_mode="ollama", allowed_hosts=["doorain.test"])  # type: ignore[arg-type]
    with TestClient(create_app(s), base_url="http://doorain.test") as c:
        assert c.get("/api/docs").status_code == 404
        assert c.get("/api/openapi.json").status_code == 404


def test_csrf_required_for_unsafe_methods(owner: Api) -> None:
    r = owner.c.post("/api/v1/sessions", json={"role": "expert"})  # без X-CSRF-Token
    assert r.status_code == 403 and r.json()["code"] == "csrf_failed"
    r = owner.c.post("/api/v1/sessions", json={"role": "expert"}, headers={"X-CSRF-Token": "deadbeef"})
    assert r.status_code == 403
    assert owner.post("/sessions", json={"role": "expert"}).status_code == 201
    assert owner.c.post("/api/v1/auth/logout").status_code == 403  # logout тоже защищён


def test_origin_check(owner: Api) -> None:
    r = owner.c.post("/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["code"] == "bad_origin"
    r = owner.post("/sessions", json={"role": "expert"}, headers={"Origin": "http://localhost:8080"})
    assert r.status_code == 201
    r = owner.c.post("/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_host_header_checked(client: TestClient) -> None:
    assert client.get("/api/v1/health/live", headers={"Host": "evil.example"}).status_code == 400


def test_security_headers_and_error_format(owner: Api) -> None:
    r = owner.get(f"/sessions/{uuid.uuid4()}")
    assert r.status_code == 404
    body = r.json()
    assert set(body) >= {"code", "message", "request_id"} and "Traceback" not in r.text
    h = r.headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["cache-control"] == "no-store" and "frame-ancestors 'none'" in h["content-security-policy"]
    v = owner.post("/sessions", json={"role": "hacker"})
    assert v.status_code == 422 and v.json()["code"] == "validation_error"


def test_logout_revokes_server_side(owner: Api) -> None:
    token = owner.c.cookies.get("doorain_session")
    assert owner.post("/auth/logout").status_code == 204
    fresh = TestClient(owner.c.app)
    fresh.cookies.set("doorain_session", token)
    assert fresh.get("/api/v1/auth/me").status_code == 401


def test_change_password_revokes_all_other_sessions(owner: Api) -> None:
    other = Api(TestClient(owner.c.app))
    assert other.login().status_code == 200
    assert other.get("/auth/me").status_code == 200
    assert owner.post("/auth/change-password", json={"current_password": "nope-nope-nope", "new_password": "another long passphrase 1"}).status_code == 403
    assert owner.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "short"}).status_code == 422
    r = owner.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "another long passphrase 1"})
    assert r.status_code == 200
    owner.csrf = r.json()["csrf_token"]
    assert owner.get("/auth/me").status_code == 200  # текущий клиент получил новую сессию
    assert other.get("/auth/me").status_code == 401  # прежняя отозвана
    assert Api(TestClient(owner.c.app)).login(password=PASSWORD).status_code == 401


def test_login_rate_limit_persisted_in_db(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOORAIN_LOGIN_IP_MAX_FAILURES", "3")
    from app.core.config import reset_settings_cache
    from app.main import create_app

    reset_settings_cache()
    _make_owner()
    with TestClient(create_app()) as c:
        for _ in range(3):
            assert c.post("/api/v1/auth/login", json={"username": "owner", "password": "wrong-password-1"}).status_code == 401
        r = c.post("/api/v1/auth/login", json={"username": "owner", "password": PASSWORD})
        assert r.status_code == 429 and r.headers["retry-after"]
    with TestClient(create_app()) as c2:  # «рестарт»: состояние в БД, а не в памяти процесса
        assert c2.post("/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 429


def test_owner_can_only_be_created_once(env: Path) -> None:
    from app.auth.service import create_owner
    from app.core.errors import ApiError
    from app.db.session import SessionLocal

    db = SessionLocal()
    create_owner(db, "owner", PASSWORD)
    with pytest.raises(ApiError):
        create_owner(db, "second", PASSWORD)
    with pytest.raises(ApiError):
        from app.auth.service import reset_password

        reset_password(db, "owner", "short")
    db.close()


def test_password_is_argon2id_and_tokens_are_hashed(owner: Api) -> None:
    from sqlalchemy import select

    from app.db.models import AuthSession, User
    from app.db.session import SessionLocal

    db = SessionLocal()
    assert db.scalar(select(User.password_hash)).startswith("$argon2id$")  # type: ignore[union-attr]
    token = owner.c.cookies.get("doorain_session")
    assert token and all(token != s.token_hash for s in db.scalars(select(AuthSession)))
    db.close()


def test_object_ownership_isolation(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    snap = ask(owner, sid, "У нас нет политики обработки персональных данных на сайте.")
    cid = owner.get(f"/sessions/{sid}/messages").json()[-1]["citations"][0]["id"]
    from app.auth.service import create_owner
    from app.db.session import SessionLocal

    db = SessionLocal()
    from app.core.security import hash_password
    from app.db.models import User

    db.add(User(username="intruder", password_hash=hash_password("intruder passphrase 123")))
    db.commit()
    db.close()
    other = Api(TestClient(owner.c.app))
    assert other.login("intruder", "intruder passphrase 123").status_code == 200
    rid = snap["run_id"]
    for path in (f"/sessions/{sid}", f"/sessions/{sid}/messages", f"/sessions/{sid}/graph", f"/sessions/{sid}/risks", f"/runs/{rid}", f"/runs/{rid}/events", f"/citations/{cid}", f"/citations/{cid}/export"):
        assert other.get(path).status_code == 404, path
    assert other.post(f"/sessions/{sid}/messages", json={"text": "привет привет", "client_request_id": uuid.uuid4().hex}).status_code == 404
    assert other.delete(f"/sessions/{sid}", params={"confirm": "x"}).status_code == 404
    assert other.get("/sessions").json() == []
    _ = create_owner


def test_client_ip_trusts_forwarded_header_only_from_trusted_proxy() -> None:
    from starlette.requests import Request

    from app.core.config import Settings
    from app.core.security import client_ip

    s = Settings(trusted_proxy_cidrs=["10.0.0.0/8"], trusted_proxy_hosts=["localhost"])  # type: ignore[call-arg]

    def req(peer: str, xff: str) -> Request:
        return Request({"type": "http", "headers": [(b"x-forwarded-for", xff.encode())], "client": (peer, 1234), "method": "GET", "path": "/"})

    assert client_ip(req("10.1.2.3", "203.0.113.9"), s) == "203.0.113.9"  # прокси в доверенной подсети
    assert client_ip(req("10.1.2.3", "1.1.1.1, 203.0.113.9"), s) == "203.0.113.9"  # подделанный левый элемент отбрасывается
    assert client_ip(req("198.51.100.7", "203.0.113.9"), s) == "198.51.100.7"  # недоверенный пир: заголовок игнорируется
    assert client_ip(req("127.0.0.1", "203.0.113.9"), s) == "203.0.113.9"  # доверие по имени сервиса (localhost → 127.0.0.1)
