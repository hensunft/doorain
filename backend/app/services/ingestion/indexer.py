"""Corpus generation: неизменяемый manifest редакций, embeddings (dense+sparse), контрольный поиск, атомарное переключение."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.util import now
from ...db.models import AppState, Chunk, ChunkIndex, CorpusGeneration, DocumentRevision, GenerationRevision
from ...providers.base import Embedded
from ...providers.registry import Providers
from ...providers.vectorstore import rrf
from .. import jobs

ACTIVE_KEY = "active_generation_id"
BATCH = 16


class Cancelled(Exception):
    pass


class CorpusEmpty(Exception):
    pass


def get_state(db: Session, key: str) -> dict:
    row = db.get(AppState, key)
    return dict(row.value) if row else {}


def set_state(db: Session, key: str, value: dict) -> None:
    row = db.get(AppState, key)
    if row:
        row.value = value
    else:
        db.add(AppState(key=key, value=value))


def active_generation(db: Session) -> CorpusGeneration | None:
    gid = get_state(db, ACTIVE_KEY).get("id")
    return db.get(CorpusGeneration, uuid.UUID(gid)) if gid else None


def fp_hash(fp: dict) -> str:
    return hashlib.sha256(json.dumps(fp, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def applicable_revisions(db: Session, gen: CorpusGeneration, as_of: date) -> list[DocumentRevision]:
    """Редакции generation, действующие на as_of: по документу — последняя с effective_from <= as_of и не утратившая силу."""
    revs = db.scalars(select(DocumentRevision).join(GenerationRevision, GenerationRevision.revision_id == DocumentRevision.id).where(GenerationRevision.generation_id == gen.id)).all()
    best: dict[uuid.UUID, DocumentRevision] = {}
    for r in revs:
        start = r.effective_from or r.revision_date
        if start and start > as_of:
            continue
        if r.effective_to and r.effective_to <= as_of:
            continue
        cur = best.get(r.document_id)
        if cur is None or (start or date.min) > ((cur.effective_from or cur.revision_date) or date.min):
            best[r.document_id] = r
    return list(best.values())


def _manifest(db: Session, revs: list[DocumentRevision]) -> list[tuple[uuid.UUID, int, str]]:
    out = []
    for r in sorted(revs, key=lambda x: str(x.id)):
        rows = db.execute(select(Chunk.text_sha256).where(Chunk.revision_id == r.id).order_by(Chunk.ordinal)).scalars().all()
        out.append((r.id, len(rows), hashlib.sha256("".join(rows).encode()).hexdigest()))
    return out


def build_generation(db: Session, p: Providers, s: Settings, job: jobs.Job | None = None, note: str | None = None) -> CorpusGeneration:
    revs = list(db.scalars(select(DocumentRevision).where(DocumentRevision.status == "ready")).all())
    if not revs:
        raise CorpusEmpty("Корпус пуст: загрузите документы")
    fp = p.embedder.fingerprint()
    fh = fp_hash(fp)
    coll = f"doorain_{fh[:12]}"
    manifest = _manifest(db, revs)
    msha = hashlib.sha256(json.dumps([[str(a), b, c] for a, b, c in manifest]).encode()).hexdigest()
    same = db.scalar(select(CorpusGeneration).where(CorpusGeneration.manifest_sha256 == msha, CorpusGeneration.fingerprint_hash == fh, CorpusGeneration.status.in_(("ready", "retired"))))
    if same:  # идемпотентно: тот же состав и то же embedding-пространство
        cur = active_generation(db)
        if not cur or cur.id != same.id:
            _activate(db, same, revs)
        return same
    p.vs.ensure(coll, int(fp["dim"]))
    done = {c for (c,) in db.execute(select(ChunkIndex.chunk_id).where(ChunkIndex.fingerprint_hash == fh))}
    todo = [c for c in db.scalars(select(Chunk).where(Chunk.revision_id.in_([r.id for r in revs])).order_by(Chunk.revision_id, Chunk.ordinal)) if c.id not in done]
    for i in range(0, len(todo), BATCH):
        batch = todo[i : i + BATCH]
        embs = p.embedder.embed([c.text for c in batch])
        p.vs.upsert(coll, [(c.id, e, {"revision_id": str(c.revision_id), "ordinal": c.ordinal, "locator": c.locator}) for c, e in zip(batch, embs, strict=True)])
        db.add_all([ChunkIndex(chunk_id=c.id, fingerprint_hash=fh) for c in batch])
        db.commit()
        if job and jobs.heartbeat(db, job, {"stage": "embedding", "done": i + len(batch), "total": len(todo)}):
            raise Cancelled()
    seq = (db.scalar(select(func.max(CorpusGeneration.seq))) or 0) + 1
    gen = CorpusGeneration(seq=seq, status="building", fingerprint=fp, fingerprint_hash=fh, collection_name=coll, manifest_sha256=msha, note=note)
    db.add(gen)
    db.flush()
    db.add_all([GenerationRevision(generation_id=gen.id, revision_id=a, chunk_count=b, chunks_sha256=c) for a, b, c in manifest])
    db.commit()
    gen.control_search = control_search(db, p, gen, revs)
    if gen.control_search["passed"] != gen.control_search["checked"]:
        gen.status = "failed"
        db.commit()
        raise RuntimeError("Контрольный поиск не пройден; generation не активирована")
    _activate(db, gen, revs)
    return gen


def control_search(db: Session, p: Providers, gen: CorpusGeneration, revs: list[DocumentRevision]) -> dict:
    """Каждая из выбранных редакций должна находить собственный фрагмент по его тексту."""
    details, ok = [], 0
    sample = sorted(revs, key=lambda r: str(r.id))[:5]
    rev_ids = [r.id for r in revs]
    for r in sample:
        c = db.scalar(select(Chunk).where(Chunk.revision_id == r.id).order_by(Chunk.ordinal).limit(1))
        if not c:
            continue
        e: Embedded = p.embedder.embed([c.text[:300]], query=True)[0]
        d, sp = p.vs.search(gen.collection_name, e, rev_ids, 10)
        hit = c.id in [x for x, _ in rrf([d, sp])][:10]
        ok += int(hit)
        details.append({"revision_id": str(r.id), "chunk_id": str(c.id), "hit": hit})
    return {"checked": len(details), "passed": ok, "details": details}


def _activate(db: Session, gen: CorpusGeneration, revs: list[DocumentRevision]) -> None:
    prev = active_generation(db)
    if prev and prev.id != gen.id:
        prev.status = "retired"
    gen.status, gen.activated_at = "ready", now()
    set_state(db, ACTIVE_KEY, {"id": str(gen.id)})
    for r in revs:
        r.corpus_state = "verified" if r.verified_at else "indexed"
    db.commit()
