"""Шкалы P и S по ролям диалога: тексты хранятся в scales/<role>.yaml и подставляются в промпт извлечения."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DIR = Path(__file__).resolve().parent / "scales"


@lru_cache
def load(role: str) -> dict[str, Any]:
    path = DIR / f"{role}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else yaml.safe_load((DIR / "entrepreneur.yaml").read_text(encoding="utf-8"))
    for key in ("probability", "severity"):
        if sorted(int(k) for k in data[key]) != [1, 2, 3, 4, 5]:
            raise ValueError(f"Шкала {key} роли {role}: нужны формулировки для значений 1–5")
    return {"measure": data["measure"], "probability": {int(k): v for k, v in data["probability"].items()}, "severity": {int(k): v for k, v in data["severity"].items()}}
