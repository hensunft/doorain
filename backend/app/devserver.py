"""Локальный стенд для e2e/разработки UI: SQLite, in-memory Qdrant, TEST-провайдеры, встроенный worker, раздача frontend/dist.

НЕ для production (Settings отклоняет такую конфигурацию). Пароль владельца берётся из E2E_PASSWORD, а не из кода.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    data = Path(os.environ.get("E2E_DATA", str(root / ".tmp" / "e2e-data")))
    password = os.environ.get("E2E_PASSWORD")
    if not password:
        sys.exit("E2E_PASSWORD не задан (пароль не хранится в коде)")
    port = int(os.environ.get("E2E_PORT", "8765"))
    shutil.rmtree(data, ignore_errors=True)
    data.mkdir(parents=True)
    os.environ.update(
        DOORAIN_ENV="dev",
        DOORAIN_DATABASE_URL=f"sqlite:///{(data / 'e2e.db').as_posix()}",
        DOORAIN_QDRANT_URL=":memory:",
        DOORAIN_DATA_DIR=str(data),
        DOORAIN_PROVIDER_MODE="test",
        DOORAIN_MIN_RERANK_SCORE="0.15",
        DOORAIN_EMBEDDED_WORKER="1",
        DOORAIN_SERVE_STATIC=str(root / "frontend" / "dist"),
        DOORAIN_ALLOWED_HOSTS=json.dumps(["127.0.0.1", "localhost"]),
        DOORAIN_SECRET_KEY=secrets.token_urlsafe(48),
    )
    from .auth.service import create_owner
    from .db import models  # noqa: F401
    from .db.base import Base
    from .db.session import SessionLocal, get_engine

    Base.metadata.create_all(get_engine())
    db = SessionLocal()
    create_owner(db, os.environ.get("E2E_USER", "e2e"), password)
    db.close()
    if os.environ.get("E2E_DEMO") == "1":
        from .demo import load_demo

        load_demo(root / "tests" / "fixtures" / "demo")
    import uvicorn

    from .main import create_app

    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
