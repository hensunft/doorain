from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .api import auth, corpus, misc, portrait, sessions
from .core import errors
from .core.config import Settings, get_settings
from .core.middleware import CSP, SecurityMiddleware
from .db.models import Topic
from .db.session import SessionLocal
from .services.risks.methodology import TOPICS

log = logging.getLogger("doorain")


def seed_topics() -> None:
    db = SessionLocal()
    try:
        have = {t for (t,) in db.execute(select(Topic.id))}
        for i, (tid, title) in enumerate(TOPICS):
            if tid not in have:
                db.add(Topic(id=tid, title=title, sort=i))
        db.commit()
    finally:
        db.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    prod = s.env == "production"

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        seed_topics()
        stop = threading.Event()
        t = None
        if _embedded():
            from .worker.main import loop  # noqa: PLC0415

            t = threading.Thread(target=loop, args=(stop,), daemon=True, name="embedded-worker")
            t.start()
        yield
        stop.set()

    app = FastAPI(title="DoorAIn API", version=__version__, docs_url=None if prod else "/api/docs", redoc_url=None, openapi_url=None if prod else "/api/openapi.json", lifespan=lifespan)
    errors.install(app)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=s.allowed_hosts)
    static = _static_dir()
    app.add_middleware(SecurityMiddleware, settings=s, html_csp=CSP if static else None)
    api = APIRouter(prefix="/api/v1")
    for r in (auth.router, sessions.router, portrait.router, corpus.router, misc.router, misc.public):
        api.include_router(r)
    app.include_router(api)
    if static:  # dev/e2e: раздача собранного фронтенда; в production это делает Caddy
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            f = (static / path).resolve()
            return FileResponse(f if f.is_file() and static in f.parents else static / "index.html")

    return app


def _embedded() -> bool:
    import os  # noqa: PLC0415

    return os.environ.get("DOORAIN_EMBEDDED_WORKER") == "1" and get_settings().env != "production"


def _static_dir() -> Path | None:
    import os  # noqa: PLC0415

    d = os.environ.get("DOORAIN_SERVE_STATIC")
    return Path(d).resolve() if d and get_settings().env != "production" and Path(d).is_dir() else None
