"""Операции над базой знаний для локального CLI владельца: манифест, загрузка, редакции, переиндексация, поиск.

Приложение в рантайме в сеть не ходит. Скачивание по URL выполняется только здесь — вручную запущенной командой.
"""

from __future__ import annotations

import random
import uuid
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.errors import ApiError
from ...core.util import norm_ws, safe_filename
from ...db.models import Chunk, CorpusGeneration, Document, DocumentRevision
from ...providers.registry import Providers
from ..rag.retrieval import retrieve
from . import importer
from .indexer import active_generation, applicable_revisions, build_generation

LICENSES = {
    "public_domain_official": "Официальный документ: не является объектом авторского права (п. 6 ст. 1259 ГК РФ)",
    "open_license": "Открытая лицензия правообладателя",
    "owned_copy": "Экземпляр, которым владелец располагает на законных основаниях",
}
DOC_TYPE_BY_KIND = {"npa": "npa", "practice": "soft_law", "doctrine": "textbook", "soft_law": "soft_law"}


def load_manifest(s: Settings) -> list[dict[str, Any]]:
    data = yaml.safe_load(s.corpus_manifest.read_text(encoding="utf-8")) or {}
    items = data.get("items") or []
    for it in items:
        if not it.get("license"):
            raise ApiError(422, "license_required", f"В манифесте у документа «{it.get('id')}» не заполнено поле license")
    return items


def manifest_entry(s: Settings, key: str) -> dict[str, Any] | None:
    k = norm_ws(key).lower()
    for it in load_manifest(s):
        nums = {norm_ws(x).lower() for x in (it.get("match") or {}).get("act_numbers", [])}
        if it["id"].lower() == k or k in nums:
            return it
    return None


def _fetch(url: str, s: Settings) -> tuple[str, bytes]:
    import httpx  # noqa: PLC0415

    r = httpx.get(url, timeout=120, follow_redirects=True, headers={"User-Agent": "DoorAIn/kb-add"})
    r.raise_for_status()
    if len(r.content) > s.max_upload_mb * 1024 * 1024:
        raise ApiError(413, "file_too_large", f"Документ больше {s.max_upload_mb} МБ")
    name = safe_filename(unquote(Path(urlparse(url).path).name) or "document.html")
    ctype = r.headers.get("content-type", "")
    if "." not in name:
        name += ".pdf" if "pdf" in ctype else ".html"
    return name, r.content


def add(db: Session, s: Settings, p: Providers, src: str, meta: dict[str, Any], *, build: bool = True) -> dict[str, Any]:
    """Загрузка документа из файла или по URL. Без license документ не индексируется."""
    entry = manifest_entry(s, meta["manifest_id"]) if meta.get("manifest_id") else None
    lic = meta.get("license") or (entry or {}).get("license")
    if lic not in LICENSES:
        raise ApiError(422, "license_required", f"Укажите основание включения: --license {' | '.join(LICENSES)} (или запись манифеста с полем license)")
    if src.startswith(("http://", "https://")):
        name, data = _fetch(src, s)
        meta.setdefault("source_url", src)
    else:
        path = Path(src)
        if not path.is_file():
            raise ApiError(404, "not_found", f"Файл не найден: {src}")
        name, data = path.name, path.read_bytes()
    kind = (entry or {}).get("kind", "npa")
    full_meta: dict[str, Any] = {
        "doc_type": meta.get("doc_type") or DOC_TYPE_BY_KIND.get(kind, "npa"),
        "title": meta.get("title") or (entry or {}).get("title") or Path(name).stem,
        "short_name": meta.get("short_name"),
        "act_number": meta.get("act_number"),
        "act_date": meta.get("act_date"),
        "revision_date": meta.get("revision_date"),
        "effective_from": meta.get("effective_from"),
        "verified_at": meta.get("verified_at"),
        "edition": meta.get("edition"),
        "topics": meta.get("topics") or (entry or {}).get("topics") or [],
        "source_url": meta.get("source_url") or (entry or {}).get("source_url"),
        "manifest_id": meta.get("manifest_id"),
        "license_note": f"{LICENSES[lic]} [{lic}]",
    }
    draft = importer.receive_upload(db, s, name, data, enqueue=False)
    importer.run_parse(db, s, draft.id)
    db.refresh(draft)
    if draft.status != "ready":
        raise ApiError(422, "parse_failed", draft.error or "Документ не разобран")
    rev, created = importer.confirm_import(db, s, draft.id, full_meta)
    out = {"document": full_meta["title"], "revision_id": str(rev.id), "created": created, "license": lic, **_revision_summary(db, rev)}
    if build:
        gen = build_generation(db, p, s, None, f"kb add {full_meta['title'][:60]}")
        out["generation"] = {"seq": gen.seq, "collection": gen.collection_name, "control_search": gen.control_search}
    return out


def _revision_summary(db: Session, rev: DocumentRevision) -> dict[str, Any]:
    """Сводка после индексации: сколько фрагментов, средняя длина и три случайных — для глазной проверки."""
    chunks = list(db.scalars(select(Chunk).where(Chunk.revision_id == rev.id).order_by(Chunk.ordinal)))
    lens = [len(c.text) for c in chunks] or [0]
    sample = random.sample(chunks, min(3, len(chunks))) if chunks else []
    return {
        "chunks": len(chunks),
        "avg_chars": sum(lens) // len(lens),
        "revision_date": rev.revision_date.isoformat() if rev.revision_date else None,
        "sample": [{"locator": c.locator, "text": c.text[:200]} for c in sample],
    }


def update_revision(db: Session, s: Settings, p: Providers, doc_key: str, src: str, revision_date: str, verified_at: str | None = None) -> dict[str, Any]:
    """Новая редакция существующего документа: прежние чанки сохраняются, действие старой редакции закрывается днём раньше."""
    doc = db.get(Document, uuid.UUID(doc_key)) if _is_uuid(doc_key) else db.scalar(select(Document).where(Document.manifest_id == doc_key))
    if not doc:
        raise ApiError(404, "not_found", f"Документ не найден: {doc_key} (см. doorain kb list)")
    new_from = date.fromisoformat(revision_date)
    prev = list(db.scalars(select(DocumentRevision).where(DocumentRevision.document_id == doc.id).order_by(DocumentRevision.revision_date)))
    meta = {
        "doc_type": doc.doc_type, "title": doc.title, "short_name": doc.short_name, "act_number": doc.act_number,
        "act_date": doc.act_date, "revision_date": revision_date, "verified_at": verified_at, "topics": doc.topics,
        "source_url": doc.source_url, "manifest_id": doc.manifest_id, "license": _license_key(doc.license_note),
    }
    out = add(db, s, p, src, {k: v for k, v in meta.items() if v}, build=False)
    for r in prev:  # редакции не удаляются: помечается конец действия прежней
        if r.effective_to is None and (r.effective_from or r.revision_date or date.min) < new_from:
            r.effective_to = new_from
    db.commit()
    gen = build_generation(db, p, s, None, f"kb update {doc.short_name or doc.title[:40]}")
    return {**out, "superseded": len([r for r in prev if r.effective_to == new_from]), "generation": {"seq": gen.seq, "control_search": gen.control_search}}


def _is_uuid(v: str) -> bool:
    try:
        uuid.UUID(v)
    except ValueError:
        return False
    return True


def _license_key(note: str | None) -> str | None:
    if note and note.endswith("]") and "[" in note:
        key = note.rsplit("[", 1)[1][:-1]
        return key if key in LICENSES else None
    return None


def documents(db: Session) -> list[dict[str, Any]]:
    out = []
    for d in db.scalars(select(Document).order_by(Document.created_at)):
        revs = list(db.scalars(select(DocumentRevision).where(DocumentRevision.document_id == d.id).order_by(DocumentRevision.revision_date)))
        out.append(
            {
                "document_id": str(d.id), "title": d.title, "short_name": d.short_name, "act_number": d.act_number, "doc_type": d.doc_type,
                "is_demo": d.is_demo, "license_note": d.license_note, "manifest_id": d.manifest_id,
                "revisions": [
                    {"id": str(r.id), "revision_date": r.revision_date.isoformat() if r.revision_date else None, "edition": r.edition, "chunks": r.chunk_count, "state": r.corpus_state, "superseded_at": r.effective_to.isoformat() if r.effective_to else None}
                    for r in revs
                ],
            }
        )
    return out


def reindex(db: Session, s: Settings, p: Providers, only: str | None = None) -> dict[str, Any]:
    note = f"kb reindex {only}" if only else "kb reindex"
    gen = build_generation(db, p, s, None, note)
    return {"generation": gen.seq, "collection": gen.collection_name, "fingerprint": gen.fingerprint_hash[:12], "control_search": gen.control_search, "status": gen.status}


def search(db: Session, s: Settings, p: Providers, query: str, *, limit: int = 10, as_of: date | None = None) -> dict[str, Any]:
    gen: CorpusGeneration | None = active_generation(db)
    if not gen:
        raise ApiError(409, "no_generation", "Корпус не проиндексирован: doorain kb reindex")
    revs = applicable_revisions(db, gen, as_of or date.today())
    r = retrieve(db, p, s, gen, revs, query, query)
    ids = [uuid.UUID(x["chunk_id"]) for x in r.scores[:limit]]
    chunks = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_(ids)))} if ids else {}
    docs = {d.id: d for d in db.scalars(select(Document))}
    rmap = {x.id: x for x in revs}
    rows = []
    for sc in r.scores[:limit]:
        c = chunks.get(uuid.UUID(sc["chunk_id"]))
        if not c:
            continue
        rev = rmap.get(c.revision_id)
        d = docs.get(rev.document_id) if rev else None
        rows.append(
            {
                "rerank": sc["rerank"], "fused": sc["fused"], "via": sc["via"],
                "act": (d.short_name or d.title[:40]) if d else "?", "locator": c.locator,
                "revision_date": rev.revision_date.isoformat() if rev and rev.revision_date else None,
                "is_demo": bool(d and d.is_demo), "text": c.text[:220],
            }
        )
    return {
        "query": query, "considered": r.considered, "sufficient": r.sufficient, "confidence": r.confidence, "reason": r.reason,
        "threshold": {"min_rerank_score": s.min_rerank_score, "source": s.threshold_source, "partial_floor": s.min_rerank_score - s.partial_answer_margin},
        "timings_ms": r.timings_ms, "generation": gen.seq, "revisions": len(revs), "hits": rows,
    }
