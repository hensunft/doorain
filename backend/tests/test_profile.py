"""П. 2 и 11 задания 24.09: регистрация по приглашению с профилем, атомарное погашение кода, редактирование профиля."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import Api
from tests.test_access import USER_PW, _invite, reg_body, register


def _post(client: TestClient, body: dict[str, Any]) -> Any:
    return TestClient(client.app).post("/api/v1/auth/register", json=body)


def test_registration_creates_profile_and_display_name(owner: Api, client: TestClient) -> None:
    code = _invite(owner)
    api = register(client, "Ivan.P", code, first_name="  Иван ", last_name="Петров-Водкин", email="Ivan.P@Example.COM")
    u = api.get("/auth/me").json()["user"]
    assert (u["username"], u["display_name"], u["first_name"], u["last_name"], u["email"]) == ("ivan.p", "Иван Петров-Водкин", "Иван", "Петров-Водкин", "ivan.p@example.com")
    assert "password" not in str(u) and "password_hash" not in u
    from app.db.models import User
    from app.db.session import SessionLocal

    db = SessionLocal()
    row = db.query(User).filter(User.username == "ivan.p").one()
    assert row.terms_accepted_at and row.pd_consent_at and row.legal_version and row.password_hash.startswith("$argon2") and USER_PW not in row.password_hash
    db.close()


@pytest.mark.parametrize(
    ("over", "code"),
    [({"accept_terms": False}, "consent_required"), ({"accept_pd": False}, "consent_required"), ({"password_repeat": "другой пароль 12345"}, "password_mismatch"),
     ({"password": "short", "password_repeat": "short"}, "weak_password"), ({"email": "не-адрес"}, "bad_email"), ({"email": "a@b"}, "bad_email"),
     ({"first_name": "Иван123"}, "bad_name"), ({"last_name": "<script>"}, "bad_name"), ({"first_name": "   "}, "bad_name"), ({"username": "a b"}, "bad_username")],
)
def test_registration_validation_and_failed_attempt_does_not_burn_the_invite(owner: Api, client: TestClient, over: dict[str, Any], code: str) -> None:
    invite = _invite(owner)
    body = reg_body(over.pop("username", "alice"), invite, **over)
    r = _post(client, body)
    assert r.status_code in (422, 409) and r.json()["code"] == code, r.text
    assert [i["state"] for i in owner.get("/admin/invites").json()] == ["active"]  # код не потрачен
    assert _post(client, reg_body("alice", invite)).status_code == 201


def test_missing_profile_fields_are_rejected_by_schema(owner: Api, client: TestClient) -> None:
    invite = _invite(owner)
    for field in ("first_name", "last_name", "email", "password_repeat", "accept_terms", "accept_pd"):
        body = reg_body("alice", invite)
        del body[field]
        assert _post(client, body).status_code == 422, field


def test_username_and_email_are_unique_case_insensitively(owner: Api, client: TestClient) -> None:
    register(client, "alice", _invite(owner), email="Alice@Example.com")
    same_login = _post(client, reg_body("ALICE", _invite(owner)))
    assert same_login.status_code == 409 and same_login.json()["code"] == "username_taken"
    same_mail = _post(client, reg_body("bob", _invite(owner), email="alice@EXAMPLE.com"))
    assert same_mail.status_code == 409 and same_mail.json()["code"] == "email_taken"


def test_invite_states_revoke_expiry_and_single_use(owner: Api, client: TestClient) -> None:
    from app.db.models import Invite
    from app.db.session import SessionLocal

    created = owner.post("/admin/invites", json={"note": "срок", "ttl_days": 3}).json()
    assert created["register_path"] == f"/register#code={created['code']}"  # код во фрагменте: не попадает в журналы сервера
    listing = owner.get("/admin/invites").json()[0]
    assert listing["state"] == "active" and "code" not in listing and (owner.get("/admin/invites").json()[0]["expires_at"] > listing["created_at"])
    owner.delete(f"/admin/invites/{listing['id']}")
    revoked = _post(client, reg_body("carol", created["code"]))
    assert revoked.status_code == 403 and revoked.json()["code"] == "invalid_invite"
    assert owner.get("/admin/invites").json()[0]["state"] == "revoked"

    code = _invite(owner, "истёкший")
    db = SessionLocal()
    for inv in db.query(Invite).filter(Invite.revoked_at.is_(None)):
        inv.expires_at = inv.created_at - timedelta(minutes=1)
    db.commit()
    db.close()
    assert _post(client, reg_body("dave", code)).status_code == 403
    assert {i["note"]: i["state"] for i in owner.get("/admin/invites").json()}["истёкший"] == "expired"

    fresh = _invite(owner, "свежий")
    assert _post(client, reg_body("erin", fresh)).status_code == 201
    assert _post(client, reg_body("frank", fresh)).status_code == 403  # код одноразовый
    states = {i["note"]: i["state"] for i in owner.get("/admin/invites").json()}
    assert states["срок"] == "revoked" and states["свежий"] == "used" and states["истёкший"] == "expired"
    assert owner.post("/admin/invites", json={"ttl_days": 0}).status_code == 422 and owner.post("/admin/invites", json={"ttl_days": 91}).status_code == 422


def test_invite_redemption_is_atomic_when_a_parallel_request_wins(owner: Api, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Между проверкой кода и погашением его успевает использовать параллельный запрос: второй не создаёт учётную запись."""
    from app.auth import service
    from app.db.models import Invite, User
    from app.db.session import SessionLocal

    code = _invite(owner)
    real = service.hash_password

    def racing(pw: str) -> str:
        db = SessionLocal()
        inv = db.query(Invite).one()
        inv.used_at = inv.created_at
        db.commit()
        db.close()
        return real(pw)

    monkeypatch.setattr(service, "hash_password", racing)
    r = _post(client, reg_body("gina", code))
    assert r.status_code == 403 and r.json()["code"] == "invalid_invite"
    db = SessionLocal()
    assert db.query(User).filter(User.username == "gina").count() == 0
    db.close()


def test_passwords_and_personal_data_do_not_reach_logs_or_audit(owner: Api, client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    code = _invite(owner)
    api = register(client, "harry", code, first_name="Гарри", last_name="Поттер", email="harry@example.com", password="s3cret passphrase 777")
    api.patch("/auth/profile", json={"first_name": "Гарольд"})
    text = caplog.text + str(owner.get("/admin/audit").json())
    for secret in ("s3cret passphrase 777", code, "harry@example.com", "Поттер", "Гарольд"):
        assert secret not in text, secret
    assert "harry@example.com" not in str(owner.get("/admin/users").json())  # владельцу виден логин и имя, но не e-mail и не хеш
    assert any(e["action"] == "auth.profile_update" and e["details"] == {"fields": ["first_name"]} for e in owner.get("/admin/audit").json())
    assert next(u for u in owner.get("/admin/users").json() if u["username"] == "harry")["display_name"] == "Гарольд Поттер"  # имя — да, e-mail — нет


def test_profile_edit_login_is_immutable_and_changes_survive_relogin(owner: Api, client: TestClient) -> None:
    api = register(client, "ivan", _invite(owner))
    me = api.patch("/auth/profile", json={"first_name": "Пётр", "last_name": "Иванов-Сидоров", "username": "hacker"}).json()["user"]
    assert me["username"] == "ivan" and me["display_name"] == "Пётр Иванов-Сидоров"
    assert api.patch("/auth/profile", json={"first_name": "x1"}).json()["code"] == "bad_name"
    again = Api(TestClient(client.app))
    assert again.login("ivan", USER_PW).status_code == 200  # изменения переживают повторный вход
    assert again.get("/auth/me").json()["user"]["display_name"] == "Пётр Иванов-Сидоров"


def test_email_change_requires_current_password_and_is_unique(owner: Api, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    alice = register(client, "alice", _invite(owner))
    register(client, "bob", _invite(owner), email="bob@example.com")
    denied = alice.patch("/auth/profile", json={"email": "new@example.com"})
    assert denied.status_code == 403 and denied.json()["code"] == "invalid_credentials"
    assert alice.patch("/auth/profile", json={"email": "new@example.com", "current_password": "неверный пароль 123"}).status_code == 403
    assert alice.get("/auth/me").json()["user"]["email"] == "alice@example.com"
    dup = alice.patch("/auth/profile", json={"email": "BOB@example.com", "current_password": USER_PW})
    assert dup.status_code == 409 and dup.json()["code"] == "email_taken"
    ok = alice.patch("/auth/profile", json={"email": "  New@Example.com ", "current_password": USER_PW})
    assert ok.status_code == 200 and ok.json()["user"]["email"] == "new@example.com"
    same = alice.patch("/auth/profile", json={"email": "new@example.com"})  # тот же адрес: пароль не нужен, ничего не меняется
    assert same.status_code == 200
    cleared = alice.patch("/auth/profile", json={"email": "", "current_password": USER_PW})
    assert cleared.json()["user"]["email"] is None
    assert alice.patch("/auth/profile", json={"email": "не-адрес", "current_password": USER_PW}).json()["code"] == "bad_email"


def test_profile_password_guessing_is_throttled(owner: Api, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOORAIN_LOGIN_ACCOUNT_MAX_FAILURES", "3")
    monkeypatch.setenv("DOORAIN_LOGIN_IP_MAX_FAILURES", "100")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    alice = register(client, "alice", _invite(owner))
    codes = [alice.patch("/auth/profile", json={"email": f"x{i}@example.com", "current_password": f"неверный {i} пароль"}).status_code for i in range(6)]
    assert codes[0] == 403 and 429 in codes


def test_legacy_accounts_without_profile_still_work(owner: Api, client: TestClient) -> None:
    """Владелец и прежние пользователи: имя не выдумывается, интерфейс показывает логин; профиль можно заполнить позже."""
    me = owner.get("/auth/me").json()["user"]
    assert me["display_name"] == "owner" and me["first_name"] is None and me["email"] is None and me["access_level"] == "owner"
    users = owner.get("/admin/users").json()
    assert users[0]["display_name"] == "owner"
    filled = owner.patch("/auth/profile", json={"first_name": "Анна", "last_name": "Смирнова"}).json()["user"]
    assert filled["display_name"] == "Анна Смирнова" and filled["access_level"] == "owner"
    assert owner.get("/admin/users").status_code == 200  # права владельца не затронуты
