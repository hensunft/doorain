"""Согласованность инфраструктурных файлов: CSP, placeholder-защита, отсутствие секретов в шаблонах."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import ops
from app.core.config import Settings
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


def test_default_llm_is_locked_gguf_with_modelfile() -> None:
    """Тег модели по умолчанию везде один и собирается из закреплённого GGUF: prepare найдёт Modelfile по тегу."""
    tag = re.search(r"DOORAIN_OLLAMA_MODEL:-([^}]+)\}", (ROOT / "compose.yaml").read_text(encoding="utf-8")).group(1)  # type: ignore[union-attr]
    g = next(m for m in json.loads((ROOT / "infra/models.lock.json").read_text(encoding="utf-8"))["gguf"] if m["ollama_tag"] == tag)
    mf = ROOT / g["modelfile"]
    assert mf.name == tag.replace(":", "-") + ".Modelfile"
    assert f"FROM /root/.ollama/models/blobs/sha256-{g['sha256']}\n" in mf.read_text(encoding="utf-8")
    assert Settings.model_fields["ollama_model"].default == tag
    for f in ("compose.prepare.yaml", ".env.example"):
        assert tag in (ROOT / f).read_text(encoding="utf-8"), f


def test_fetch_gguf_keeps_only_verified_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"GGUF test payload"

    def download(repo_id: str, filename: str, revision: str, local_dir: str) -> str:
        out = Path(local_dir) / filename
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return str(out)

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=download, snapshot_download=lambda **_: None))
    lock, olla = tmp_path / "lock.json", tmp_path / "ollama"
    entry = {"repo": "r/m", "revision": "0" * 40, "file": "m.gguf", "size": len(data)}
    lock.write_text(json.dumps({"huggingface": [], "gguf": [{**entry, "sha256": "f" * 64}]}), encoding="utf-8")
    with pytest.raises(SystemExit):
        ops.fetch_models(lock, tmp_path / "models", olla)
    assert not [p for p in olla.rglob("*") if p.is_file()]  # подменённый файл не остаётся ни во временной папке, ни в blobs
    good = hashlib.sha256(data).hexdigest()
    lock.write_text(json.dumps({"huggingface": [], "gguf": [{**entry, "sha256": good}]}), encoding="utf-8")
    ops.fetch_models(lock, tmp_path / "models", olla)
    assert (olla / "models" / "blobs" / f"sha256-{good}").read_bytes() == data
    assert not (olla / "import").exists()
