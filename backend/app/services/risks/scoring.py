"""Шкала P×S (качественная методика, не вероятность штрафа). Версия методологии: см. METHODOLOGY_VERSION."""

from __future__ import annotations

METHODOLOGY_VERSION = "0.1-experimental"

LEVELS = ("low", "medium", "high", "critical")
LEVEL_RU = {"low": "Низкий", "medium": "Средний", "high": "Высокий", "critical": "Критический"}


def score(p: int, s: int) -> int:
    if not (1 <= p <= 5 and 1 <= s <= 5):
        raise ValueError("P и S должны быть в диапазоне 1–5")
    return p * s


def level(sc: int) -> str:
    """1–4 низкий, 5–9 средний, 10–15 высокий, 16–25 критический."""
    if not 1 <= sc <= 25:
        raise ValueError("score вне диапазона 1–25")
    if sc <= 4:
        return "low"
    if sc <= 9:
        return "medium"
    if sc <= 15:
        return "high"
    return "critical"


def final_p(base_p: int, bonus: int, has_ongoing_evidence: bool) -> int:
    """P = базовая оценка + однократный бонус (макс. 5).

    P=5 допустим только при факте продолжающейся ситуации: арифметика бонуса не доказывает её (см. methodology).
    """
    p = min(5, base_p + (1 if bonus else 0))
    if p == 5 and not has_ongoing_evidence:
        p = 4
    return p


def level_rank(lv: str | None) -> int:
    return LEVELS.index(lv) + 1 if lv in LEVELS else 0
