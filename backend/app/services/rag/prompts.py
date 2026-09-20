"""Версионируемые промпты из backend/prompts/**. Версия + подстановки достаточны, чтобы восстановить отправленный prompt."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ...core.config import get_settings
from ...core.util import sha256_text

_VER = re.compile(r"<!--\s*version:\s*(\S+)\s*-->")


@dataclass
class Rendered:
    text: str
    meta: dict[str, str]


@lru_cache
def _load(name: str) -> tuple[str, str, str]:
    raw = (Path(get_settings().prompts_dir) / f"{name}.md").read_text(encoding="utf-8")
    m = _VER.search(raw)
    return _VER.sub("", raw).strip(), (m.group(1) if m else "0"), sha256_text(raw)[:12]


def render(name: str, **vars_: str) -> Rendered:
    body, ver, sha = _load(name)
    for k, v in vars_.items():
        body = body.replace("{{" + k + "}}", v)
    return Rendered(body, {"name": name, "version": ver, "sha256": sha})
