"""Текстовое сравнение двух реально загруженных редакций одного документа. Отсутствующая редакция не генерируется."""

from __future__ import annotations

import difflib
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import ApiError
from ...core.util import norm_ws
from ...db.models import Chunk, Document, DocumentRevision


def _by_locator(db: Session, rev_id: uuid.UUID) -> dict[str, Chunk]:
    out: dict[str, Chunk] = {}
    for c in db.scalars(select(Chunk).where(Chunk.revision_id == rev_id).order_by(Chunk.ordinal)):
        key, n = c.locator, 1
        while key in out:
            n += 1
            key = f"{c.locator} #{n}"
        out[key] = c
    return out


def _ops(a: str, b: str) -> list[dict[str, str]]:
    ta, tb = re.findall(r"\S+|\s+", a), re.findall(r"\S+|\s+", b)
    sm = difflib.SequenceMatcher(a=ta, b=tb, autojunk=False)
    ops: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            ops.append({"op": "equal", "text": "".join(ta[i1:i2])})
        else:
            if i2 > i1:
                ops.append({"op": "delete", "text": "".join(ta[i1:i2])})
            if j2 > j1:
                ops.append({"op": "insert", "text": "".join(tb[j1:j2])})
    return ops


def _label(db: Session, r: DocumentRevision) -> dict[str, Any]:
    d = db.get(Document, r.document_id)
    return {"revision_id": str(r.id), "title": d.title if d else "", "revision_date": r.revision_date.isoformat() if r.revision_date else None, "edition": r.edition, "effective_from": r.effective_from.isoformat() if r.effective_from else None, "verified_at": r.verified_at.isoformat() if r.verified_at else None}


def compare(db: Session, left_id: uuid.UUID, right_id: uuid.UUID) -> dict[str, Any]:
    left, right = db.get(DocumentRevision, left_id), db.get(DocumentRevision, right_id)
    if not left or not right:
        raise ApiError(404, "revision_not_found", "Одна из редакций не найдена: сравниваются только реально загруженные редакции")
    if left.document_id != right.document_id:
        raise ApiError(422, "different_documents", "Редакции принадлежат разным документам")
    lc, rc = _by_locator(db, left.id), _by_locator(db, right.id)
    items: list[dict[str, Any]] = []
    same = 0
    for loc in list(lc) + [k for k in rc if k not in lc]:
        a, b = lc.get(loc), rc.get(loc)
        if a and not b:
            items.append({"locator": loc, "status": "removed", "left_text": a.text, "right_text": None, "ops": []})
        elif b and not a:
            items.append({"locator": loc, "status": "added", "left_text": None, "right_text": b.text, "ops": []})
        elif a and b:
            if norm_ws(a.text) == norm_ws(b.text):
                same += 1
            else:
                items.append({"locator": loc, "status": "changed", "left_text": a.text, "right_text": b.text, "ops": _ops(a.text, b.text)})
    summary = {s: sum(1 for i in items if i["status"] == s) for s in ("added", "removed", "changed")} | {"unchanged": same}
    return {"left": _label(db, left), "right": _label(db, right), "summary": summary, "items": items}
