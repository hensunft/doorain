"""Приём файла → разбор (worker) → предпросмотр → подтверждение метаданных → неизменяемая редакция."""

from __future__ import annotations

import shutil
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.errors import ApiError
from ...core.util import est_tokens, new_id, norm_ws, safe_filename, sha256_bytes, sha256_text
from ...db.models import Chunk, Document, DocumentRevision, ImportDraft
from .. import jobs
from . import chunker, metadata, parsers

ALLOWED_EXT = {".txt", ".md", ".markdown", ".html", ".htm", ".pdf", ".docx"}


def receive_upload(db: Session, s: Settings, filename: str, data: bytes, *, enqueue: bool = True) -> ImportDraft:
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise ApiError(413, "file_too_large", f"Файл больше {s.max_upload_mb} МБ")
    if not data:
        raise ApiError(422, "empty_file", "Пустой файл")
    name = safe_filename(filename)
    if Path(name).suffix.lower() not in ALLOWED_EXT:
        raise ApiError(415, "unsupported_type", "Допустимы TXT, Markdown, HTML, PDF с текстовым слоем и DOCX")
    kind = parsers.sniff(data, name)
    if kind in ("zip", "binary"):
        raise ApiError(415, "unsupported_type", "Содержимое файла не соответствует поддерживаемому типу")
    draft_id = new_id()
    folder = s.uploads_dir / str(draft_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    draft = ImportDraft(id=draft_id, filename=name, stored_path=str(path), size=len(data), sha256=sha256_bytes(data))
    db.add(draft)
    if enqueue:
        draft.job_id = jobs.enqueue(db, "parse_document", {"draft_id": str(draft_id)}).id
    db.commit()
    return draft


def run_parse(db: Session, s: Settings, draft_id: uuid.UUID) -> None:
    draft = db.get(ImportDraft, draft_id)
    if not draft:
        return
    try:
        parsed = parsers.parse(Path(draft.stored_path), draft.filename, s)
        pages = [chunker.normalize(p) for p in parsed.pages]
        full = "\f".join(pages)  # \f — границы страниц (нужны для цитат учебников)
        g = metadata.guess(full.replace("\f", "\n"), draft.filename)
        drafts = _chunk(g["doc_type"], full, pages, s)
        norm_path = Path(draft.stored_path).with_suffix(".normalized.txt")
        norm_path.write_text(full, encoding="utf-8")
        draft.normalized_path = str(norm_path)
        draft.mime = parsed.mime
        draft.preview = {
            "guess": g,
            "stats": {"chars": len(full), "pages": len(parsed.pages), "chunks": len(drafts), "articles": len({d.article for d in drafts if d.article})},
            "text_preview": full.replace("\f", "\n\n")[:3000],
            "chunks_preview": [{"locator": d.locator, "text": d.text[:160]} for d in drafts[:8]],
            "paginated": parsed.paginated,
        }
        draft.status = "ready"
    except parsers.UnsupportedDocument as e:
        draft.status, draft.error = "failed", str(e)[:500]
    db.commit()


def _chunk(doc_type: str, full: str, pages: list[str], s: Settings) -> list[chunker.ChunkDraft]:
    if doc_type == "npa":
        return chunker.chunk_npa(full.replace("\f", "\n"), s.chunk_target_tokens, s.chunk_overlap_tokens, s.chars_per_token)
    return chunker.chunk_textbook(pages, s.chunk_target_tokens, s.chunk_overlap_tokens, s.chars_per_token)


def _identity(doc_type: str, meta: dict[str, Any]) -> str:
    num = norm_ws(meta.get("act_number") or "")
    return f"{doc_type}|{num or norm_ws(meta['title'])}|{meta.get('act_date') or ''}|{norm_ws(meta.get('edition') or '') if doc_type != 'npa' else ''}"


def _d(v: Any) -> date | None:
    if not v:
        return None
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def confirm_import(db: Session, s: Settings, draft_id: uuid.UUID, meta: dict[str, Any], *, is_demo: bool = False) -> tuple[DocumentRevision, bool]:
    """Создаёт Document/DocumentRevision. Повторный импорт того же файла идемпотентен."""
    draft = db.get(ImportDraft, draft_id)
    if not draft:
        raise ApiError(404, "not_found", "Черновик импорта не найден")
    if draft.status == "confirmed" and draft.revision_id:
        return db.get(DocumentRevision, draft.revision_id), False  # type: ignore[return-value]
    if draft.status != "ready" or not draft.normalized_path:
        raise ApiError(409, "draft_not_ready", "Документ ещё не разобран либо не поддерживается")
    dt = meta["doc_type"]
    if dt not in ("npa", "textbook", "soft_law"):
        raise ApiError(422, "bad_doc_type", "Тип источника: npa, textbook или soft_law")
    if dt == "textbook" and not (meta.get("edition") or "").strip():
        raise ApiError(422, "edition_required", "Для учебника обязательно указание издания")
    if dt != "npa" and not (meta.get("license_note") or "").strip():
        raise ApiError(422, "license_required", "Для учебника/комментария/мягкого права укажите основание правомерного включения (лицензия, открытый материал)")
    if dt == "npa" and not (meta.get("act_number") or meta.get("title")):
        raise ApiError(422, "requisites_required", "Укажите реквизиты акта")
    full = Path(draft.normalized_path).read_text(encoding="utf-8")
    checksum = draft.sha256
    key = _identity(dt, meta)
    doc = db.scalar(select(Document).where(Document.identity_key == key))
    if not doc:
        doc = Document(identity_key=key, doc_type=dt, title=meta["title"][:500], short_name=(meta.get("short_name") or None), act_number=meta.get("act_number"), act_date=_d(meta.get("act_date")), source_url=meta.get("source_url"), license_note=meta.get("license_note"), manifest_id=meta.get("manifest_id"), topics=meta.get("topics") or [], is_demo=is_demo)
        db.add(doc)
        db.flush()
    existing = db.scalar(select(DocumentRevision).where(DocumentRevision.document_id == doc.id, DocumentRevision.checksum == checksum))
    if existing:
        draft.status, draft.revision_id = "confirmed", existing.id
        db.commit()
        return existing, False
    rdate = _d(meta.get("revision_date"))
    if rdate and db.scalar(select(DocumentRevision).where(DocumentRevision.document_id == doc.id, DocumentRevision.revision_date == rdate)):
        raise ApiError(409, "revision_exists", "Редакция с такой датой уже загружена с другим содержимым. Редакции неизменяемы: укажите корректную дату новой редакции")
    rid = new_id()
    folder = s.documents_dir / str(rid)
    folder.mkdir(parents=True, exist_ok=True)
    ext = Path(draft.filename).suffix.lower()
    shutil.copy2(draft.stored_path, folder / f"original{ext}")
    (folder / "normalized.txt").write_text(full, encoding="utf-8")
    drafts = _chunk(dt, full, full.split("\f"), s)
    if not drafts:
        raise ApiError(422, "no_chunks", "Не удалось выделить фрагменты для индексации")
    rev = DocumentRevision(
        id=rid, document_id=doc.id, revision_date=rdate, edition=(meta.get("edition") or None), publication_date=_d(meta.get("publication_date")),
        effective_from=_d(meta.get("effective_from")) or rdate, effective_to=_d(meta.get("effective_to")), verified_at=_d(meta.get("verified_at")),
        checksum=checksum, text_sha256=sha256_text(full), original_name=draft.filename, original_path=str(folder / f"original{ext}"),
        normalized_path=str(folder / "normalized.txt"), mime=draft.mime or "application/octet-stream", char_count=len(full), chunk_count=len(drafts),
        chunking_version=s.chunking_version,
    )
    db.add(rev)
    db.flush()
    _insert_chunks(db, rev, drafts, doc.topics, s)
    draft.status, draft.revision_id = "confirmed", rev.id
    db.commit()
    return rev, True


def _insert_chunks(db: Session, rev: DocumentRevision, drafts: list[chunker.ChunkDraft], topics: list[Any], s: Settings) -> None:
    rows = [
        Chunk(id=new_id(), revision_id=rev.id, ordinal=i, kind=d.kind, heading_path=d.heading_path[:500], article=d.article, part=d.part, point=d.point, locator=d.locator[:200], page=d.page, text=d.text, text_sha256=sha256_text(d.text), token_est=est_tokens(d.text, s.chars_per_token), topics=topics)
        for i, d in enumerate(drafts)
    ]
    for i, r in enumerate(rows):
        r.prev_id = rows[i - 1].id if i else None
        r.next_id = rows[i + 1].id if i + 1 < len(rows) else None
    db.add_all(rows)
    db.flush()
