"""Серверная проверка блоков ответа: ссылки, прямые цитаты, лексическая опора. Существование ID ≠ верность толкования."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...core.util import norm_ws, stems

MARKER = re.compile(r"\[(C\d+)\]")
QUOTE = re.compile(r"«([^»]{15,})»")
NOTICE_UNSUPPORTED = "Недостаточно данных в базе знаний, чтобы подтвердить этот фрагмент ответа."


@dataclass
class Checked:
    kind: str  # claim | fact | assumption | clarification | notice
    text: str
    markers: list[str] = field(default_factory=list)
    state: str = "verified"  # verified | unsupported
    reason: str | None = None
    quote_checked: bool | None = None


def split_paragraphs(buf: str) -> tuple[list[str], str]:
    """(завершённые абзацы, остаток буфера)."""
    parts = re.split(r"\n\s*\n", buf)
    return [p.strip() for p in parts[:-1] if p.strip()], parts[-1]


def check_paragraph(text: str, sources: dict[str, str]) -> Checked:
    """sources: marker -> исходный текст чанка."""
    markers = list(dict.fromkeys(MARKER.findall(text)))
    clean = re.sub(r"\s*\[C\d+\]", "", text).strip()
    low = clean.lower()
    if low.startswith("допущение"):
        kind = "assumption"
    elif low.startswith("со слов пользователя"):
        kind = "fact"
    elif low.startswith(("уточните", "уточнение", "необходимо уточнить")):
        kind = "clarification"
    else:
        kind = "claim"
    unknown = [m for m in markers if m not in sources]
    if unknown:
        return Checked("notice", NOTICE_UNSUPPORTED, [], "unsupported", f"unknown_marker:{','.join(unknown)}")
    if kind == "claim" and not markers:
        return Checked("notice", NOTICE_UNSUPPORTED, [], "unsupported", "claim_without_citation")
    quote_ok: bool | None = None
    if markers:
        hay = norm_ws(" ".join(sources[m] for m in markers))
        for q in QUOTE.findall(clean):
            quote_ok = norm_ws(q) in hay if quote_ok is None else (quote_ok and norm_ws(q) in hay)
        if quote_ok is False:
            return Checked("notice", NOTICE_UNSUPPORTED, [], "unsupported", "quote_not_in_source", False)
    return Checked(kind, clean, markers, "verified", None, quote_ok)


def lexical_support(clean: str, markers: list[str], sources: dict[str, str], min_ratio: float = 0.2) -> bool:
    """Грубая проверка содержательной опоры: доля основ слов блока, встречающихся в цитируемых источниках."""
    words = stems(clean)
    if len(words) < 5 or not markers:
        return True
    src = stems(" ".join(sources[m] for m in markers if m in sources))
    return len(words & src) / len(words) >= min_ratio
