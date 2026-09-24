"""Корпус знаний: импорт, редакции, generation, сравнение, поиск, задания."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import service as auth
from ..core.config import Settings, get_settings
from ..core.errors import not_found
from ..core.util import norm_ws
from ..db.models import AuditEvent, Chunk, CorpusGeneration, Document, DocumentRevision, ImportDraft, Job
from ..db.session import get_db
from ..providers.registry import get_providers
from ..schemas.api import (
    ChunkOut,
    ConfirmImportIn,
    ConfirmImportOut,
    CorpusOverview,
    DocumentOut,
    DocumentPatch,
    DraftOut,
    GenerationOut,
    JobOut,
    ManifestItem,
    RevisionOut,
    RevisionPatch,
    SearchHit,
)
from ..services import jobs
from ..services.ingestion import compare as cmp
from ..services.ingestion import importer, kb
from ..services.ingestion.indexer import active_generation, applicable_revisions
from .deps import owner, require_writable

router = APIRouter(prefix="/corpus", tags=["corpus"])
RANK = {"imported": 1, "indexed": 2, "verified": 3}


@router.get("/overview", response_model=CorpusOverview)
def overview(ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> CorpusOverview:
    act = active_generation(db)
    gens = list(db.scalars(select(CorpusGeneration).order_by(CorpusGeneration.seq.desc()).limit(10)))
    n_rev = db.scalar(select(func.count()).select_from(DocumentRevision).where(DocumentRevision.status == "ready")) or 0
    return CorpusOverview(
        documents=db.scalar(select(func.count()).select_from(Document)) or 0, revisions=n_rev, chunks=db.scalar(select(func.count()).select_from(Chunk)) or 0,
        active_generation=GenerationOut.model_validate(act) if act else None, generations=[GenerationOut.model_validate(g) for g in gens], empty=n_rev == 0,
        index_ready=act is not None,
    )


@router.get("/manifest", response_model=list[ManifestItem])
def manifest(ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> list[ManifestItem]:
    items = kb.load_manifest(s)
    docs = list(db.scalars(select(Document).where(Document.is_demo.is_(False))))
    out = []
    for it in items:
        m = it.get("match", {})
        nums = {norm_ws(x) for x in m.get("act_numbers", [])}
        names = {norm_ws(x) for x in m.get("short_names", [])}
        found = [d for d in docs if d.manifest_id == it["id"] or (d.act_number and norm_ws(d.act_number) in nums) or (d.short_name and norm_ws(d.short_name) in names)]
        revs = list(db.scalars(select(DocumentRevision).where(DocumentRevision.document_id.in_([d.id for d in found]), DocumentRevision.status == "ready"))) if found else []
        state = max((r.corpus_state for r in revs), key=lambda x: RANK[x], default=None)
        out.append(ManifestItem(id=it["id"], tier=it["tier"], title=it["title"], kind=it["kind"], topics=it["topics"], note=it.get("note"), status=cast(Literal["missing", "imported", "indexed", "verified"], state or "missing"), revisions=len(revs)))
    return out


@router.post("/uploads", response_model=DraftOut, status_code=201)
async def upload(file: UploadFile, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> DraftOut:
    require_writable(db)
    data = await file.read(s.max_upload_mb * 1024 * 1024 + 1)
    draft = importer.receive_upload(db, s, file.filename or "file", data)
    db.add(AuditEvent(actor=ctx.user.username, action="corpus.upload", object_type="import_draft", object_id=str(draft.id), details={"size": draft.size, "sha256": draft.sha256}))
    db.commit()
    return DraftOut.model_validate(draft)


def _draft(db: Session, did: uuid.UUID) -> ImportDraft:
    d = db.get(ImportDraft, did)
    if not d:
        raise not_found("Черновик импорта")
    return d


@router.get("/uploads/{draft_id}", response_model=DraftOut)
def get_upload(draft_id: uuid.UUID, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> DraftOut:
    return DraftOut.model_validate(_draft(db, draft_id))


@router.post("/uploads/{draft_id}/confirm", response_model=ConfirmImportOut)
def confirm(draft_id: uuid.UUID, body: ConfirmImportIn, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> ConfirmImportOut:
    require_writable(db)
    _draft(db, draft_id)
    meta = body.model_dump(mode="json")
    rev, created = importer.confirm_import(db, s, draft_id, meta)
    job_id = None
    if body.build_index and rev.corpus_state == "imported":
        j = jobs.enqueue(db, "build_generation", {"note": f"import {rev.id}"}, idempotency_key=f"build:{rev.id}", limit=False)
        job_id = j.id
    db.add(AuditEvent(actor=ctx.user.username, action="corpus.confirm_import", object_type="revision", object_id=str(rev.id), details={"created": created}))
    db.commit()
    return ConfirmImportOut(revision_id=rev.id, document_id=rev.document_id, created=created, job_id=job_id)


@router.get("/documents", response_model=list[DocumentOut])
def documents(ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> list[DocumentOut]:
    out = []
    q = select(Document).order_by(Document.title)
    if s.provider_mode != "test":  # выведенные из рабочей базы тестовые акты не показываются; в тестовом стенде исключение обратимо
        q = q.where(~(Document.is_demo.is_(True) & Document.excluded_at.is_not(None)))
    for d in db.scalars(q):
        revs = db.scalars(select(DocumentRevision).where(DocumentRevision.document_id == d.id).order_by(DocumentRevision.revision_date.desc().nullslast(), DocumentRevision.uploaded_at.desc()))
        out.append(DocumentOut(
            id=d.id, doc_type=d.doc_type, title=d.title, short_name=d.short_name, act_number=d.act_number, act_date=d.act_date,
            license_note=d.license_note, source_url=d.source_url, excluded=d.excluded_at is not None,
            cited_in_sessions=len(kb.citing_sessions(db, d.id)), revisions=[RevisionOut.model_validate(r) for r in revs],
        ))
    return out


@router.patch("/documents/{document_id}", response_model=DocumentOut)
def patch_document(document_id: uuid.UUID, body: DocumentPatch, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> DocumentOut:
    """Исключить документ из корпуса или вернуть. Состав меняется после переиндексации; цитаты прежних ответов не затрагиваются."""
    require_writable(db)
    d = kb.set_excluded(db, document_id, body.excluded)
    db.add(AuditEvent(actor=ctx.user.username, action="corpus.document_excluded" if body.excluded else "corpus.document_included", object_type="document", object_id=str(d.id), details={"title": d.title}))
    db.commit()
    revs = db.scalars(select(DocumentRevision).where(DocumentRevision.document_id == d.id).order_by(DocumentRevision.revision_date.desc().nullslast()))
    return DocumentOut(
        id=d.id, doc_type=d.doc_type, title=d.title, short_name=d.short_name, act_number=d.act_number, act_date=d.act_date,
        license_note=d.license_note, source_url=d.source_url, excluded=d.excluded_at is not None,
        cited_in_sessions=len(kb.citing_sessions(db, d.id)), revisions=[RevisionOut.model_validate(r) for r in revs],
    )


@router.delete("/documents/{document_id}", response_model=dict[str, Any])
def delete_document(document_id: uuid.UUID, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db), s: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Безвозвратное удаление документа и переиндексация. Отклоняется, если на него ссылаются сохранённые ответы."""
    require_writable(db)
    title = (db.get(Document, document_id) or Document()).title
    out = kb.remove(db, s, get_providers(), document_id)
    db.add(AuditEvent(actor=ctx.user.username, action="corpus.document_removed", object_type="document", object_id=str(document_id), details={"title": title, "chunks": out["chunks"]}))
    db.commit()
    return out


@router.get("/revisions/{revision_id}/chunks", response_model=list[ChunkOut])
def revision_chunks(revision_id: uuid.UUID, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> list[Chunk]:
    return list(db.scalars(select(Chunk).where(Chunk.revision_id == revision_id).order_by(Chunk.ordinal).offset(offset).limit(limit)))


@router.patch("/revisions/{revision_id}", response_model=RevisionOut)
def patch_revision(revision_id: uuid.UUID, body: RevisionPatch, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> DocumentRevision:
    """Текст редакции неизменяем; допускается только отметка проверки и дата утраты силы (с аудитом)."""
    require_writable(db)
    r = db.get(DocumentRevision, revision_id)
    if not r:
        raise not_found("Редакция")
    if body.verified_at is not None:
        r.verified_at = body.verified_at
        if r.corpus_state == "indexed":
            r.corpus_state = "verified"
    if body.clear_effective_to:
        r.effective_to = None
    elif body.effective_to is not None:
        r.effective_to = body.effective_to
    db.add(AuditEvent(actor=ctx.user.username, action="corpus.patch_revision", object_type="revision", object_id=str(r.id), details=body.model_dump(mode="json")))
    db.commit()
    return r


@router.get("/compare")
def compare(left: uuid.UUID, right: uuid.UUID, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> dict:
    return cmp.compare(db, left, right)


@router.post("/generations/build", response_model=JobOut, status_code=202)
def build(ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> Job:
    require_writable(db)
    j = jobs.enqueue(db, "build_generation", {"note": "manual"})
    db.commit()
    return j


@router.get("/search", response_model=list[SearchHit])
def search(q: str = Query(..., min_length=2, max_length=200), as_of: date | None = None, limit: int = Query(30, ge=1, le=100), ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> list[SearchHit]:
    """Поиск по базе: точная статья/подстрока (PostgreSQL). Семантический поиск выполняется worker'ом в диалоге."""
    gen = active_generation(db)
    applicable = {r.id for r in applicable_revisions(db, gen, as_of or date.today())} if gen else set()
    like = f"%{q.strip()}%"
    rows = db.execute(
        select(Chunk, DocumentRevision, Document).join(DocumentRevision, DocumentRevision.id == Chunk.revision_id).join(Document, Document.id == DocumentRevision.document_id)
        .where(or_(Chunk.text.ilike(like), Chunk.locator.ilike(like), Chunk.article == q.strip().removeprefix("ст.").strip())).order_by(Document.title, Chunk.ordinal).limit(limit)
    ).all()
    return [SearchHit(chunk_id=c.id, revision_id=r.id, document_title=d.title, locator=c.locator, revision_date=r.revision_date, edition=r.edition, verified_at=r.verified_at, excerpt=c.text[:400], applicable=r.id in applicable) for c, r, d in rows]


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> list[Job]:
    return list(db.scalars(select(Job).where(Job.type.in_(("parse_document", "build_generation"))).order_by(Job.created_at.desc()).limit(30)))


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> Job:
    j = db.get(Job, job_id)
    if not j or j.type not in ("parse_document", "build_generation", "export_pdf", "quiz_generate"):
        raise not_found("Задание")
    return j


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: uuid.UUID, ctx: auth.AuthContext = Depends(owner), db: Session = Depends(get_db)) -> Job:
    j = get_job(job_id, ctx, db)
    jobs.request_cancel(db, j)
    db.refresh(j)
    return j
