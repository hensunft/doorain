"""Серверная проверка блоков ответа: ссылки, прямые цитаты, лексическая опора. Существование ID ≠ верность толкования."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...core.util import norm_ws, stems

MARKER = re.compile(r"\[(C\d+)\]")
GROUPED = re.compile(r"\[\s*(C\d+(?:\s*[,;]\s*C\d+)+)\s*\]")  # «[C1, C2]» (так пишет GigaChat) → «[C1] [C2]»
QUOTE = re.compile(r"«([^»]{15,})»")
NOTICE_UNSUPPORTED = "Недостаточно данных в базе знаний, чтобы подтвердить этот фрагмент ответа."
FACT_PREFIX = re.compile(r"^со слов пользователя\s*[:,—–-]?\s*", re.I)
FACT_NEEDS_SUBJECT = "Уточните: из вопроса не видно, о каком обстоятельстве идёт речь. Опишите его своими словами — например, «сайт не собирает персональные данные»."
_BARE = {"да", "нет", "не", "неизвестно", "не знаю", "знаю", "возможно", "может", "быть", "наверное", "ок", "ага", "угу", "так"}
_REPORTING = {"польз", "сообщ", "указа", "говор", "пишет", "утвер", "отмет", "уточн"}  # «пользователь сообщил, что…» — не содержание факта


def fact_body(text: str) -> str:
    return FACT_PREFIX.sub("", text.strip()).strip()


def fact_has_subject(body: str) -> bool:
    """Факт — это утверждение (субъект + сказуемое), а не односложное «да»/«нет»/«неизвестно» без предмета."""
    words = re.findall(r"[а-яёa-z0-9]+", body.lower())
    return len([w for w in words if w not in _BARE]) >= 2 and len(words) >= 3


def fact_grounded(body: str, user_text: str) -> bool:
    """Содержание факта должно опираться на слова пользователя: непроизнесённое не приписывается ему."""
    own = stems(body) - _REPORTING
    return bool(own) and len(own & stems(user_text)) / len(own) >= 0.5


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


def check_paragraph(text: str, sources: dict[str, str], user_text: str | None = None) -> Checked:
    """sources: marker -> исходный текст чанка; user_text — реплики пользователя (для проверки блока «Со слов пользователя»)."""
    text = GROUPED.sub(lambda m: " ".join(f"[{c}]" for c in re.findall(r"C\d+", m.group(1))), text)
    markers = list(dict.fromkeys(MARKER.findall(text)))
    clean = re.sub(r"\s*\[C\d+\]", "", text).strip()
    low = clean.lower()
    if low.startswith("допущение"):
        kind = "assumption"
    elif low.startswith("со слов пользователя"):
        body = fact_body(clean)
        if not fact_has_subject(body):  # «нет.» без предмета — не факт, а повод уточнить
            return Checked("clarification", FACT_NEEDS_SUBJECT, [], "verified", "fact_without_subject")
        if user_text is not None and not fact_grounded(body, user_text):  # пользователь этого не говорил — это допущение модели
            return Checked("assumption", f"Допущение: {body}", [], "verified", "fact_not_in_user_text")
        kind, clean = "fact", f"Со слов пользователя: {body}"
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
