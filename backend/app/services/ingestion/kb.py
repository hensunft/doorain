"""Операции над базой знаний для локального CLI владельца: манифест, загрузка, редакции, переиндексация, поиск.

Приложение в рантайме в сеть не ходит. Скачивание по URL выполняется только здесь — вручную запущенной командой.
"""

from __future__ import annotations

import json
import random
import shutil
import uuid
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import yaml
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.errors import ApiError
from ...core.util import norm_ws, now, safe_filename
from ...db.models import (
    AuditEvent,
    Chunk,
    ChunkIndex,
    Citation,
    ConsultationSession,
    CorpusGeneration,
    Document,
    DocumentRevision,
    GenerationRevision,
    GenerationRun,
    Message,
    Risk,
    RiskEvidence,
)
from ...providers.registry import Providers
from ..rag.retrieval import retrieve
from ..risks.engine import _event
from . import importer
from .indexer import active_generation, applicable_revisions, build_generation, deactivate_generation

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


def set_excluded(db: Session, doc_id: uuid.UUID, excluded: bool) -> Document:
    """Исключить документ из корпуса (или вернуть). Данные и прежние цитаты остаются целыми; состав меняется после переиндексации."""
    doc = db.get(Document, doc_id)
    if not doc:
        raise ApiError(404, "not_found", "Документ не найден")
    doc.excluded_at = now() if excluded else None
    db.commit()
    return doc


def citing_sessions(db: Session, doc_id: uuid.UUID) -> list[uuid.UUID]:
    """Сессии, в ответах которых есть цитаты этого документа: пока они существуют, документ удалять нельзя."""
    return list(db.scalars(select(Citation.session_id).where(Citation.document_id == doc_id).distinct()))


def remove(db: Session, s: Settings, p: Providers, doc_id: uuid.UUID, *, rebuild: bool = True) -> dict[str, Any]:
    """Безвозвратное удаление документа: фрагменты, векторы, файлы и редакции.

    Отклоняется, если на документ ссылаются сохранённые ответы: иначе цитата перестала бы открывать свой фрагмент.
    """
    doc = db.get(Document, doc_id)
    if not doc:
        raise ApiError(404, "not_found", "Документ не найден")
    used = citing_sessions(db, doc_id)
    if used:
        raise ApiError(409, "document_in_use", f"На документ ссылаются ответы в {len(used)} сессиях. Удалите эти сессии (и очистите их в разделе «Администрирование»), либо исключите документ из корпуса вместо удаления")
    revs = list(db.scalars(select(DocumentRevision).where(DocumentRevision.document_id == doc_id)))
    chunk_ids = list(db.scalars(select(Chunk.id).where(Chunk.revision_id.in_([r.id for r in revs])))) if revs else []
    for coll in db.scalars(select(CorpusGeneration.collection_name).distinct()):
        p.vs.delete_points(coll, chunk_ids)
    if chunk_ids:
        db.execute(delete(ChunkIndex).where(ChunkIndex.chunk_id.in_(chunk_ids)))
        db.execute(delete(Chunk).where(Chunk.id.in_(chunk_ids)))
    removed_files = 0
    for r in revs:
        folder = Path(r.normalized_path).parent if r.normalized_path else None
        if folder and folder.is_dir() and folder.parent == s.documents_dir:
            shutil.rmtree(folder, ignore_errors=True)
            removed_files += 1
        db.execute(delete(GenerationRevision).where(GenerationRevision.revision_id == r.id))
    db.execute(delete(DocumentRevision).where(DocumentRevision.document_id == doc_id))
    db.delete(doc)
    db.commit()
    out = {"document": doc.title, "revisions": len(revs), "chunks": len(chunk_ids), "files": removed_files, "rebuilt": False}
    if rebuild and db.scalar(select(DocumentRevision.id).limit(1)):
        gen = build_generation(db, p, s, None, f"kb remove {doc.title[:50]}")
        out["rebuilt"] = True
        out["generation"] = {"seq": gen.seq, "control_search": gen.control_search}
    return out


def retire_demo(db: Session, s: Settings, p: Providers, out_dir: Path) -> dict[str, Any]:
    """Вывести синтетические (тестовые) акты из рабочей базы знаний.

    Порядок: отчёт с резервной копией затронутых строк → основания в прежних ответах, цитатах и рисках помечаются архивными
    (сообщения не удаляются) → документы без ссылок удаляются, со ссылками исключаются → generation пересобирается либо снимается.
    Повторный запуск безопасен: демо-актов не останется — ничего не изменится.
    """
    demo = list(db.scalars(select(Document).where(Document.is_demo.is_(True))))
    docs = [d for d in demo if d.excluded_at is None]  # уже выведенные (исключённые) повторно не обрабатываются
    cits = [c for c in db.scalars(select(Citation).where(Citation.document_id.in_([d.id for d in demo]))) if not c.snapshot.get("archived")] if demo else []
    if not docs and not cits:
        return {"items": [], "note": "Тестовых актов в рабочей базе нет", "report": None}
    # резерв и удаление векторов — по всем тестовым актам, включая исключённые ранее: их векторы могли остаться в Qdrant
    revs = list(db.scalars(select(DocumentRevision).where(DocumentRevision.document_id.in_([d.id for d in demo]))))
    chunks = list(db.scalars(select(Chunk).where(Chunk.revision_id.in_([r.id for r in revs])))) if revs else []
    cit_ids = {c.id for c in cits}
    runs = list(db.scalars(select(GenerationRun).where(GenerationRun.id.in_({c.run_id for c in cits})))) if cits else []
    msgs = list(db.scalars(select(Message).where(Message.id.in_([r.assistant_message_id for r in runs if r.assistant_message_id])))) if runs else []
    ev = list(db.scalars(select(RiskEvidence).where(RiskEvidence.kind.in_(("obligation", "consequence")), RiskEvidence.ref_id.in_(cit_ids)))) if cit_ids else []
    risks = list(db.scalars(select(Risk).where(Risk.id.in_({e.risk_id for e in ev})))) if ev else []
    report: dict[str, Any] = {
        "created_at": now().isoformat(),
        "documents": [{"id": str(d.id), "title": d.title, "act_number": d.act_number, "short_name": d.short_name, "doc_type": d.doc_type, "excluded_before": d.excluded_at is not None} for d in demo],
        "revisions": [{"id": str(r.id), "document_id": str(r.document_id), "revision_date": r.revision_date, "checksum": r.checksum, "original_path": r.original_path} for r in revs],
        "chunks": [{"id": str(c.id), "revision_id": str(c.revision_id), "locator": c.locator, "text": c.text} for c in chunks],  # резервная копия текстов
        "citations": sorted(str(c) for c in cit_ids),
        "sessions": sorted({str(c.session_id) for c in cits}),
        "messages": sorted(str(m.id) for m in msgs),
        "risks": [{"id": str(r.id), "session_id": str(r.session_id), "status": r.status, "title": r.title} for r in risks],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"retired-demo-{now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    stamp = now().isoformat()
    for c in cits:  # снимок цитаты сохраняется, но основание помечается архивным и не считается нормой
        c.snapshot = {**c.snapshot, "archived": True, "archived_reason": "Источник выведен из базы знаний: тестовый документ", "archived_at": stamp}
    note = "Источник выведен из базы знаний: ответ опирался на тестовый документ и не является правовым основанием."
    for m in msgs:
        if not any(b.get("reason") == "source_archived" for b in (m.blocks or [])):
            m.blocks = [*(m.blocks or []), {"id": f"b{len(m.blocks or []) + 1}", "version": 1, "kind": "notice", "text": note, "citation_ids": [], "markers": [], "state": "unsupported", "reason": "source_archived"}]
    by_risk: dict[uuid.UUID, set[uuid.UUID]] = {}
    for e in db.scalars(select(RiskEvidence).where(RiskEvidence.kind == "obligation", RiskEvidence.risk_id.in_([r.id for r in risks]))) if risks else []:
        by_risk.setdefault(e.risk_id, set()).add(e.ref_id)
    for r in risks:
        if by_risk.get(r.id) and by_risk[r.id] <= cit_ids:  # других норм у риска нет: основание недействительно
            if r.status in ("open", "in_progress"):
                r.status, r.clarification = "needs_clarification", "Нормативное основание риска было тестовым и выведено из базы знаний. Задайте вопрос заново после загрузки НПА."
                r.resolution_pending = None
            _event(db, r, "evidence", None, None, "Основание выведено из базы знаний (тестовый источник): риск не подтверждён нормативной базой", "system")
            r.version += 1
    for sid in {c.session_id for c in cits}:
        sess = db.get(ConsultationSession, sid)
        if sess:
            sess.version += 1
    db.add(AuditEvent(actor="cli", action="corpus.demo_retired", details={"documents": len(demo), "citations": len(cit_ids), "sessions": len(report["sessions"]), "risks": len(risks), "report": path.name}))
    db.commit()

    items: list[dict[str, Any]] = []
    chunk_ids = [c.id for c in chunks]
    for doc in docs:
        used = citing_sessions(db, doc.id)
        if used:
            set_excluded(db, doc.id, True)
            items.append({"document": doc.title, "action": "excluded", "cited_in_sessions": len(used)})
        else:
            items.append({"document": doc.title, "action": "removed", **remove(db, s, p, doc.id, rebuild=False)})
    for coll in db.scalars(select(CorpusGeneration.collection_name).distinct()):
        p.vs.delete_points(coll, chunk_ids)  # векторы синтетических актов не должны оставаться в Qdrant
    if chunk_ids:
        db.execute(delete(ChunkIndex).where(ChunkIndex.chunk_id.in_(chunk_ids)))
        db.commit()
    if db.scalar(select(DocumentRevision.id).join(Document, Document.id == DocumentRevision.document_id).where(DocumentRevision.status == "ready", Document.excluded_at.is_(None)).limit(1)):
        gen = build_generation(db, p, s, None, "kb retire-demo")
        return {"items": items, "report": str(path), "generation": {"seq": gen.seq, "control_search": gen.control_search}}
    deactivate_generation(db)
    return {"items": items, "report": str(path), "generation": None, "note": "Корпус пуст: загрузите НПА и выполните переиндексацию. До этого сервис честно отказывает в правовых ответах"}


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


def coverage_gaps(db: Session, s: Settings, topics: list[str]) -> str | None:
    """Темы вопроса, по которым в рабочей базе нет ни одного документа, и акты из манифеста, которые их покрывают.
    Акты не загружаются автоматически: их добавляет администратор."""
    from ..risks.methodology import TOPIC_TITLES  # noqa: PLC0415

    covered: set[str] = set()
    for d in db.scalars(select(Document).where(Document.excluded_at.is_(None))):
        if s.provider_mode == "test" or not d.is_demo:
            covered.update(d.topics or [])
    try:
        items = load_manifest(s)
    except (OSError, ApiError):
        items = []
    parts = []
    for t in dict.fromkeys(topics):
        if t in covered:
            continue
        acts = [it["title"] for it in items if t in (it.get("topics") or []) and it.get("layer") == 1][:4]
        parts.append(f"«{TOPIC_TITLES.get(t, t)}»" + (f" (нужны: {'; '.join(acts)})" if acts else ""))
    if not parts:
        return None
    return "Не покрыты базой знаний темы: " + ", ".join(parts) + ". Эти акты загружает администратор; до этого ответ по теме не даётся."
