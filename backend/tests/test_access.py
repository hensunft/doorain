"""Раздельные контуры доступа: владелец и пользователь, изоляция данных, приглашения, локальный режим."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import PASSWORD, Api, ask, new_session, run_jobs

USER_PW = "user passphrase 12345"


def _invite(owner: Api, note: str = "тест") -> str:
    r = owner.post("/admin/invites", json={"note": note})
    assert r.status_code == 201
    return r.json()["code"]


def register(client: TestClient, username: str, code: str, password: str = USER_PW) -> Api:
    api = Api(TestClient(client.app))  # свой клиент: cookie-сессии пользователей не должны перетирать друг друга
    r = api.c.post("/api/v1/auth/register", json={"username": username, "password": password, "invite_code": code})
    assert r.status_code == 201, r.text
    api.csrf = r.json()["csrf_token"]
    return api


def test_registration_requires_valid_invite(owner: Api, client: TestClient) -> None:
    bad = TestClient(client.app).post("/api/v1/auth/register", json={"username": "alice", "password": USER_PW, "invite_code": "нет такого"})
    assert bad.status_code == 403 and bad.json()["code"] == "invalid_invite"

    code = _invite(owner)
    api = register(client, "alice", code)
    me = api.get("/auth/me").json()
    assert me["user"]["access_level"] == "user" and me["user"]["disclaimer_accepted_at"] is None

    again = TestClient(client.app).post("/api/v1/auth/register", json={"username": "bob", "password": USER_PW, "invite_code": code})
    assert again.status_code == 403  # код одноразовый
    assert [i["state"] for i in owner.get("/admin/invites").json()] == ["used"]


def test_user_cannot_reach_another_users_objects(owner: Api, client: TestClient, demo: dict) -> None:
    alice = register(client, "alice", _invite(owner))
    bob = register(client, "bob", _invite(owner))
    sid = new_session(alice)
    snap = ask(alice, sid, "Нужна ли политика обработки персональных данных на сайте?")
    run_id, msgs = snap["run_id"], alice.get(f"/sessions/{sid}/messages").json()
    cid = msgs[-1]["citations"][0]["id"]
    ex = alice.post(f"/sessions/{sid}/exports", json={"kind": "session_pdf"})
    assert ex.status_code == 202
    run_jobs()
    eid = ex.json()["id"]

    for path in (f"/sessions/{sid}", f"/sessions/{sid}/messages", f"/sessions/{sid}/graph", f"/sessions/{sid}/timeline", f"/sessions/{sid}/risks", f"/runs/{run_id}", f"/runs/{run_id}/trace", f"/citations/{cid}", f"/exports/{eid}", f"/exports/{eid}/download"):
        assert bob.get(path).status_code == 404, path  # чужой объект неотличим от несуществующего
    assert bob.post(f"/sessions/{sid}/messages", json={"text": "чужая сессия", "client_request_id": uuid.uuid4().hex}).status_code == 404
    assert bob.delete(f"/sessions/{sid}", params={"confirm": "x"}).status_code == 404
    assert bob.get("/sessions").json() == []  # в списке только свои


def test_admin_endpoints_are_owner_only(owner: Api, client: TestClient) -> None:
    alice = register(client, "alice", _invite(owner))
    for method, path, kw in (
        ("GET", "/admin/users", {}), ("GET", "/admin/invites", {}), ("GET", "/admin/stats", {}), ("GET", "/admin/audit", {}),
        ("POST", "/admin/invites", {"json": {"note": "x"}}), ("POST", "/admin/sessions/purge", {}),
        ("GET", "/system/diagnostics", {}), ("GET", "/corpus/overview", {}), ("GET", "/corpus/manifest", {}),
        ("POST", "/corpus/generations/build", {}),
    ):
        r = alice.req(method, path, **kw)
        assert r.status_code == 403 and r.json()["code"] == "forbidden", f"{method} {path} → {r.status_code}"
    assert owner.get("/admin/users").status_code == 200


def test_owner_reads_user_session_and_access_is_logged(owner: Api, client: TestClient, demo: dict) -> None:
    """Решение владельца стенда: администратор видит чужие сессии; каждый просмотр пишется в журнал."""
    alice = register(client, "alice", _invite(owner))
    sid = new_session(alice)
    ask(alice, sid, "Нужна ли политика обработки персональных данных на сайте?")
    assert owner.get(f"/sessions/{sid}/messages").status_code == 200
    assert any(e["action"] == "session.read_foreign" and e["object_id"] == sid for e in owner.get("/admin/audit").json())
    assert owner.get("/admin/stats").json()["owner_can_read_user_sessions"] is True


def test_owner_cannot_read_user_session_when_disabled(owner: Api, client: TestClient, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    alice = register(client, "alice", _invite(owner))
    sid = new_session(alice)
    monkeypatch.setenv("DOORAIN_OWNER_CAN_READ_USER_SESSIONS", "false")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    assert owner.get(f"/sessions/{sid}/messages").status_code == 404


def test_disabled_account_loses_access_immediately(owner: Api, client: TestClient) -> None:
    alice = register(client, "alice", _invite(owner))
    uid = next(u["id"] for u in owner.get("/admin/users").json() if u["username"] == "alice")
    assert owner.patch(f"/admin/users/{uid}", json={"disabled": True}).json()["disabled_at"]
    assert alice.get("/sessions").status_code == 401  # серверная сессия отозвана
    assert Api(TestClient(client.app)).login("alice", USER_PW).status_code == 403
    owner_id = next(u["id"] for u in owner.get("/admin/users").json() if u["access_level"] == "owner")
    assert owner.patch(f"/admin/users/{owner_id}", json={"disabled": True}).status_code == 409  # владельца отключить нельзя


def test_soft_delete_hides_session_until_owner_purges(owner: Api, client: TestClient, demo: dict) -> None:
    alice = register(client, "alice", _invite(owner))
    sid = new_session(alice)
    title = alice.get(f"/sessions/{sid}").json()["title"]
    assert alice.delete(f"/sessions/{sid}", params={"confirm": title}).status_code == 204
    assert alice.get("/sessions").json() == [] and alice.get(f"/sessions/{sid}").status_code == 404
    st = owner.get("/admin/stats").json()
    assert st["deleted_sessions"] == 1 and st["sessions"] == 0
    assert owner.post("/admin/sessions/purge").json() == {"purged": 1}
    assert owner.get("/admin/stats").json()["deleted_sessions"] == 0


def test_disclaimer_acceptance_is_recorded(owner: Api, client: TestClient) -> None:
    alice = register(client, "alice", _invite(owner))
    assert alice.get("/auth/me").json()["user"]["disclaimer_accepted_at"] is None
    assert alice.post("/auth/accept-disclaimer").json()["user"]["disclaimer_accepted_at"]
    assert alice.get("/auth/me").json()["user"]["disclaimer_accepted_at"]


def test_single_user_mode_skips_login(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOORAIN_SINGLE_USER_MODE", "true")
    from app.auth.service import create_owner
    from app.core.config import Settings, reset_settings_cache
    from app.db.session import SessionLocal
    from app.main import create_app

    reset_settings_cache()
    db = SessionLocal()
    create_owner(db, "owner", PASSWORD)
    db.close()
    with TestClient(create_app()) as c:
        me = c.get("/api/v1/auth/me")
        assert me.status_code == 200 and me.json()["single_user_mode"] is True
        r = c.post("/api/v1/sessions", json={"role": "student"}, headers={"X-CSRF-Token": me.json()["csrf_token"]})
        assert r.status_code == 201  # вход не требуется

    with pytest.raises(ValueError, match="SINGLE_USER_MODE"):  # в production режим запрещён
        Settings(env="production", secret_key="y" * 40, cookie_secure=True, single_user_mode=True, allowed_hosts=["doorain.example"], provider_mode="ollama")


def test_registration_is_rate_limited(owner: Api, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOORAIN_LOGIN_IP_MAX_FAILURES", "3")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    body: dict[str, Any] = {"username": "mallory", "password": USER_PW, "invite_code": "перебор"}
    codes = [TestClient(client.app).post("/api/v1/auth/register", json=body).status_code for _ in range(5)]
    assert codes[0] == 403 and 429 in codes
