"""Подсказки реквизитов для формы импорта. Всегда требуют подтверждения владельцем."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .chunker import guess_kind

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
_DATE = re.compile(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\s*(?:г\.|года)?", re.I)
_NUM = re.compile(r"№\s*([0-9A-Za-zА-Яа-я\-]+)")
_ACT = re.compile(r"(Федеральный закон|Кодекс|Указ Президента|Постановление|Закон)", re.I)
_REV = re.compile(r"\(?\s*(?:в\s+ред(?:акции)?\.?|ред\.)\s*от\s+(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", re.I)


def _d(m: re.Match[str]) -> str:
    return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()


def guess(text: str, filename: str) -> dict[str, Any]:
    head = text[:4000]
    g: dict[str, Any] = {"doc_type": guess_kind(text), "title": None, "act_number": None, "act_date": None, "revision_date": None, "act_type": None}
    if m := _ACT.search(head):
        g["act_type"] = m.group(1)
    if m := _NUM.search(head):
        g["act_number"] = m.group(1)
    if m := _DATE.search(head):
        try:
            g["act_date"] = _d(m)
        except ValueError:
            pass
    if m := _REV.search(head):
        try:
            g["revision_date"] = _d(m)
        except ValueError:
            pass
    lines = [ln.strip() for ln in head.split("\n") if ln.strip()]
    for i, ln in enumerate(lines[:12]):
        if re.match(r"^(О|Об|О\s)\s?\S", ln) and len(ln) < 250:
            g["title"] = ln
            break
        if _ACT.match(ln) and i + 1 < len(lines) and re.match(r"^(О|Об)\b", lines[i + 1]):
            g["title"] = lines[i + 1]
            break
    if not g["title"]:
        g["title"] = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", filename)[:200]
    g["notes"] = ["Реквизиты определены автоматически по началу текста; проверьте их по официальному источнику."]
    return g
