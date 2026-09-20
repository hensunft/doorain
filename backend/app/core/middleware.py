"""Pure-ASGI middleware (не ломает SSE): request-id, проверка Origin для изменяющих запросов, лимит частоты, заголовки безопасности."""

from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict, deque
from typing import Any
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings
from .security import client_ip

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# Единая политика для UI: Caddy (production) и раздача frontend/dist в dev/e2e. Совпадение проверяется тестом.
CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings, html_csp: str | None = None):
        self.app, self.s, self.html_csp = app, settings, html_csp
        self._hits: dict[str, deque[float]] = defaultdict(deque)  # ponytail: в памяти процесса; вход/задания ограничены через БД

    async def _reject(self, send: Send, rid: str, status: int, code: str, msg: str, extra: list[tuple[bytes, bytes]] | None = None) -> None:
        body = json.dumps({"code": code, "message": msg, "details": None, "request_id": rid}, ensure_ascii=False).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"x-request-id", rid.encode())] + (extra or [])
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["request_id"] = rid
        path: str = scope["path"]
        is_api = path.startswith("/api/")
        h = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if is_api and scope["method"] in UNSAFE:
            origin = h.get("origin")
            if origin:
                host = (urlparse(origin).hostname or "").lower()
                if host not in [a.lower() for a in self.s.allowed_hosts]:
                    return await self._reject(send, rid, 403, "bad_origin", "Недопустимый Origin запроса")
            elif h.get("sec-fetch-site") == "cross-site":
                return await self._reject(send, rid, 403, "bad_origin", "Кросс-сайтовый запрос запрещён")
        if is_api and path != "/api/v1/health/live":
            ip = client_ip(Request(scope), self.s)
            q, t = self._hits[ip], time.monotonic()
            while q and t - q[0] > 60:
                q.popleft()
            if len(q) >= self.s.api_rate_per_minute:
                return await self._reject(send, rid, 429, "rate_limited", "Слишком много запросов", [(b"retry-after", b"30")])
            q.append(t)
            if len(self._hits) > 5000:  # чистка старых ключей
                for k in [k for k, v in self._hits.items() if not v or t - v[-1] > 60]:
                    self._hits.pop(k, None)

        async def wrapped(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                hs: list[Any] = list(msg.get("headers", []))
                extra = [(b"x-request-id", rid.encode()), (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"), (b"x-frame-options", b"DENY")]
                if is_api:
                    extra += [(b"cache-control", b"no-store"), (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")]
                elif self.html_csp:
                    extra.append((b"content-security-policy", self.html_csp.encode()))
                have = {k.lower() for k, _ in hs}
                msg["headers"] = hs + [(k, v) for k, v in extra if k not in have]
            await send(msg)

        await self.app(scope, receive, wrapped)
