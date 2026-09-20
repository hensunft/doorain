from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import socket
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Request

from .config import Settings

_ph = PasswordHasher()  # Argon2id, случайная соль, параметры библиотеки по умолчанию
_DUMMY_HASH = _ph.hash("doorain-dummy-password")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(hash_: str | None, password: str) -> bool:
    """Всегда тратит время одного Argon2-сравнения (одинаковая реакция на неверное имя и пароль)."""
    try:
        return _ph.verify(hash_ or _DUMMY_HASH, password) and hash_ is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hash_: str) -> bool:
    return _ph.check_needs_rehash(hash_)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_for(settings: Settings, session_token_hash: str) -> str:
    return hmac.new(settings.secret_key.get_secret_value().encode(), f"csrf:{session_token_hash}".encode(), hashlib.sha256).hexdigest()


_resolved: tuple[float, frozenset[str]] = (0.0, frozenset())


def _trusted_hosts(settings: Settings) -> frozenset[str]:
    """IP доверенных прокси по именам сервисов; кэш на 30 с (контейнер web может получить новый адрес)."""
    global _resolved  # noqa: PLW0603
    if not settings.trusted_proxy_hosts:
        return frozenset()
    if time.monotonic() - _resolved[0] > 30:
        ips: set[str] = set()
        for h in settings.trusted_proxy_hosts:
            try:
                ips |= {str(ai[4][0]) for ai in socket.getaddrinfo(h, None)}
            except OSError:
                pass
        _resolved = (time.monotonic(), frozenset(ips))
    return _resolved[1]


def _trusted(settings: Settings, ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return ip in _trusted_hosts(settings) or any(addr in ipaddress.ip_network(c, strict=False) for c in settings.trusted_proxy_cidrs)


def client_ip(request: Request, settings: Settings) -> str:
    """X-Forwarded-For принимается только если соединение пришло от доверенного прокси (Caddy)."""
    peer = request.client.host if request.client else "unknown"
    if not _trusted(settings, peer):
        return peer
    xff = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    for hop in reversed(xff):
        if not _trusted(settings, hop):
            return hop
    return peer
