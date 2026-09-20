"""Детерминированная радиальная раскладка на сервере (для PDF): координаты вычисляются из доверенных узлов, не принимаются от клиента."""

from __future__ import annotations

import math
from typing import Any


def radial(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    pos: dict[str, tuple[float, float]] = {}
    ids = {n["id"]: n for n in nodes}
    for n in nodes:
        if n["kind"] == "center":
            pos[n["id"]] = (0.0, 0.0)
    topics = [n for n in nodes if n["kind"] == "topic"]
    step = 2 * math.pi / max(1, len(topics))
    tang: dict[str, float] = {}
    for i, t in enumerate(topics):
        a = i * step
        tang[t["id"]] = a
        pos[t["id"]] = (math.cos(a) * 150, math.sin(a) * 150)
    qparent: dict[str, str] = {}
    for e in edges:
        if e["kind"] == "asks_about" and e["target"] in tang and e["source"] in ids:
            qparent.setdefault(e["source"], e["target"])
    per: dict[str, int] = {}
    for n in nodes:
        if n["kind"] != "question":
            continue
        par = qparent.get(n["id"])
        base = tang.get(par or "", 0.0)
        k = per.get(par or "", 0)
        per[par or ""] = k + 1
        off = (k - 1.5) * 0.22
        rad = 260 + (k % 2) * 30
        pos[n["id"]] = (math.cos(base + off) * rad, math.sin(base + off) * rad)
    for n in nodes:
        if n["kind"] not in ("norm", "risk"):
            continue
        anchor = next((pos[e["source"]] for e in edges if e["target"] == n["id"] and e["source"] in pos), None) or next((pos[e["target"]] for e in edges if e["source"] == n["id"] and e["target"] in pos), (0.0, 0.0))
        idx = per.get("x" + n["kind"], 0)
        per["x" + n["kind"]] = idx + 1
        ang = math.atan2(anchor[1], anchor[0]) + (0.25 if n["kind"] == "norm" else -0.25) + (idx % 3) * 0.08
        r = math.hypot(*anchor) + (70 if n["kind"] == "norm" else 95)
        pos[n["id"]] = (math.cos(ang) * r, math.sin(ang) * r)
    return pos
