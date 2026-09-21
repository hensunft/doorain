"""Шкала P×S (качественная методика, не вероятность штрафа). Версия методологии: см. METHODOLOGY_VERSION."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

METHODOLOGY_VERSION = "0.1-experimental"

LEVELS = ("low", "medium", "high", "critical")
LEVEL_RU = {"low": "Низкий", "medium": "Средний", "high": "Высокий", "critical": "Критический"}


def score(p: int, s: int) -> int:
    if not (1 <= p <= 5 and 1 <= s <= 5):
        raise ValueError("P и S должны быть в диапазоне 1–5")
    return p * s


def level(sc: int, thresholds: tuple[int, int, int] | None = None) -> str:
    """По умолчанию 1–4 низкий, 5–9 средний, 10–15 высокий, 16–25 критический; границы — DOORAIN_RISK_THRESHOLDS."""
    if not 1 <= sc <= 25:
        raise ValueError("score вне диапазона 1–25")
    if thresholds is None:
        from ...core.config import get_settings  # noqa: PLC0415

        thresholds = get_settings().risk_thresholds
    low, mid, high = thresholds
    if sc <= low:
        return "low"
    if sc <= mid:
        return "medium"
    if sc <= high:
        return "high"
    return "critical"


def level_from(p: int, s: int) -> str:
    """Уровень считает приложение, а не модель: P и S (1–5) → P × S → порог из app/config/risk.yaml."""
    return level(score(p, s))


def resync_levels(db: Session) -> int:
    """Сохранённые уровни — кэш от порогов: при старте пересчитываются, чтобы смена risk.yaml перекрасила всё сразу."""
    from ...db.models import Risk  # noqa: PLC0415

    n = 0
    for r in db.scalars(select(Risk).where(Risk.score.is_not(None))):
        lv = level(r.score or 1)
        if r.level != lv:
            r.level, n = lv, n + 1
    db.commit()
    return n


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
