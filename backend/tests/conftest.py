"""Тесты работают на TEST-провайдерах (детерминированные заглушки), SQLite и in-memory Qdrant.

Это проверка логики приложения, а не качества реальной модели/RAG: для него есть evals/ и интеграционный путь с Ollama.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
DEMO_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "demo"
PASSWORD = "correct horse battery staple"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    pg = os.environ.get("DOORAIN_TEST_DATABASE_URL")  # интеграционный прогон на PostgreSQL (схема из Alembic)
    monkeypatch.setenv("DOORAIN_ENV", "test")
    monkeypatch.setenv("DOORAIN_DATABASE_URL", pg or f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("DOORAIN_QDRANT_URL", ":memory:")
    monkeypatch.setenv("DOORAIN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOORAIN_PROVIDER_MODE", "test")
    monkeypatch.setenv("DOORAIN_MIN_RERANK_SCORE", "0.15")
    monkeypatch.setenv("DOORAIN_SECRET_KEY", "x" * 40)
    monkeypatch.setenv("DOORAIN_ALLOWED_HOSTS", '["testserver","localhost"]')
    from app.core.config import reset_settings_cache
    from app.db import models  # noqa: F401  — регистрирует таблицы в metadata
    from app.db.base import Base
    from app.db.session import get_engine, reset_engine
    from app.providers.registry import set_providers

    reset_settings_cache()
    reset_engine()
    set_providers(None)
    engine = get_engine()
    if pg:
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import text

        Base.metadata.drop_all(engine)
        with engine.begin() as c:
            c.execute(text("drop table if exists alembic_version"))
        cfg = Config(str(BACKEND / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND / "migrations"))
        command.upgrade(cfg, "head")
    else:
        Base.metadata.create_all(engine)
    yield tmp_path
    set_providers(None)
    reset_engine()
    reset_settings_cache()


class Api:
    """Клиент с CSRF-токеном и cookie-сессией."""

    def __init__(self, c: TestClient):
        self.c, self.csrf = c, ""

    def login(self, user: str = "owner", password: str = PASSWORD) -> Any:
        r = self.c.post("/api/v1/auth/login", json={"username": user, "password": password})
        if r.status_code == 200:
            self.csrf = r.json()["csrf_token"]
        return r

    def req(self, method: str, url: str, **kw: Any) -> Any:
        h = {"X-CSRF-Token": self.csrf, **kw.pop("headers", {})}
        return self.c.request(method, "/api/v1" + url, headers=h, **kw)

    def get(self, url: str, **kw: Any) -> Any:
        return self.req("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> Any:
        return self.req("POST", url, **kw)

    def patch(self, url: str, **kw: Any) -> Any:
        return self.req("PATCH", url, **kw)

    def put(self, url: str, **kw: Any) -> Any:
        return self.req("PUT", url, **kw)

    def delete(self, url: str, **kw: Any) -> Any:
        return self.req("DELETE", url, **kw)


@pytest.fixture
def client(env: Path) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def owner(env: Path, client: TestClient) -> Api:
    from app.auth.service import create_owner
    from app.db.session import SessionLocal

    db = SessionLocal()
    create_owner(db, "owner", PASSWORD)
    db.close()
    api = Api(client)
    assert api.login().status_code == 200
    return api


@pytest.fixture
def demo(env: Path) -> dict[str, Any]:
    from app.demo import load_demo

    return load_demo(DEMO_DIR)


def run_jobs() -> int:
    from app.worker.main import run_pending

    return run_pending()


def ask(api: Api, session_id: str, text: str) -> dict[str, Any]:
    """Отправить вопрос, прогнать worker, вернуть snapshot run."""
    r = api.post(f"/sessions/{session_id}/messages", json={"text": text, "client_request_id": uuid.uuid4().hex})
    assert r.status_code == 202, r.text
    run_jobs()
    snap = api.get(f"/runs/{r.json()['run_id']}")
    assert snap.status_code == 200
    return snap.json()


def new_session(api: Api, role: str = "entrepreneur", **kw: Any) -> str:
    r = api.post("/sessions", json={"role": role, "as_of_date": "2026-09-20", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]
