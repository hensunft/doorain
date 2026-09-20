"""Согласованность инфраструктурных файлов: CSP, placeholder-защита, отсутствие секретов в шаблонах."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.core.middleware import CSP

ROOT = Path(__file__).resolve().parents[2]


def test_caddy_csp_matches_app_csp() -> None:
    caddy = (ROOT / "infra/caddy/Caddyfile").read_text(encoding="utf-8")
    assert f'Content-Security-Policy "{CSP}"' in caddy
    assert "flush_interval -1" in caddy and "header_up X-Forwarded-For {remote_host}" in caddy  # SSE без буферизации, XFF перезаписывается
    assert "admin off" in caddy


def test_env_example_has_no_secret_values() -> None:
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.startswith(("POSTGRES_PASSWORD=", "DOORAIN_SECRET_KEY=", "DOORAIN_DOMAIN=")):
            assert line.split("=", 1)[1] == "", line
    assert (ROOT / ".gitignore").read_text(encoding="utf-8").count(".env") >= 1


def test_images_are_pinned_by_digest() -> None:
    lock = json.loads((ROOT / "infra/models.lock.json").read_text(encoding="utf-8"))
    for ref in lock["images"].values():
        assert re.search(r"@sha256:[0-9a-f]{64}$", ref), ref
    text = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    for ref in lock["images"].values():
        if ref.split(":")[0] in ("postgres", "qdrant/qdrant", "ollama/ollama"):
            assert ref in text, ref
    for m in lock["huggingface"]:
        assert re.fullmatch(r"[0-9a-f]{40}", m["revision"])


def test_caddy_entrypoint_rejects_placeholder_domain() -> None:
    sh = (ROOT / "infra/caddy/entrypoint.sh").read_text(encoding="utf-8")
    assert "example.com" in sh and "exit 1" in sh


def test_only_web_publishes_ports_in_base_compose() -> None:
    text = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert len(re.findall(r"^\s+ports:", text, flags=re.M)) == 1  # postgres/qdrant/ollama/api не публикуются
    assert '"127.0.0.1:${DOORAIN_HTTP_PORT:-8080}:80"' in text
