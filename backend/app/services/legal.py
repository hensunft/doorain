"""Реквизиты оператора и версия правовых текстов (app/config/legal.yaml). Пустые поля не подменяются выдуманными значениями."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PATH = Path(__file__).resolve().parents[1] / "config" / "legal.yaml"
FIELDS = ("name", "legal_status", "inn", "ogrn", "address", "email", "rkn_notice")


@lru_cache
def load() -> dict[str, Any]:
    data = yaml.safe_load(PATH.read_text(encoding="utf-8")) or {}
    op = data.get("operator") or {}
    return {"version": str(data["version"]), "operator": {k: str(op.get(k) or "").strip() for k in FIELDS}}


def version() -> str:
    return str(load()["version"])
