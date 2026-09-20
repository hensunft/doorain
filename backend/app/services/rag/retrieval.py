"""Гибридный поиск (dense + sparse, RRF) + точные ссылки на статьи + rerank + отбор в токенный бюджет."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.util import est_tokens, stems
from ...db.models import Chunk, CorpusGeneration, Document, DocumentRevision
from ...providers.registry import Providers
from ...providers.vectorstore import rrf

_ART = re.compile(r"(?:ст\.|статьи|статья|статье|статью)\s*(\d+(?:\.\d+)*)", re.I)
_NUM = re.compile(r"\b(\d{1,4}\s?-\s?ФЗ)\b", re.I)
_SHORT = re.compile(r"\b(КоАП|УК|ГК|ТК|НК)\b")


@dataclass
class Hit:
    chunk: Chunk
    revision: DocumentRevision
    document: Document
    fused: float = 0.0
    rerank: float = 0.0
    via: list[str] = field(default_factory=list)


@dataclass
class Retrieval:
    selected: list[Hit]
    considered: int
    sufficient: bool
    reason: str | None
    timings_ms: dict[str, int]
    scores: list[dict[str, Any]]
    confidence: str = "high"  # high | partial (найденное лишь частично соответствует вопросу — отвечаем с оговоркой)
    best_score: float | None = None


def rerank_passage(text: str, query: str, max_chars: int = 1200) -> str:
    """Для длинных фрагментов: заголовок + окно предложений с наибольшим пересечением с запросом (норма остаётся целой в БД)."""
    if len(text) <= max_chars:
        return text
    head, _, body = text.partition("\n")
    q = stems(query)
    sents = re.split(r"(?<=[.;])\s+", body)
    best_i = max(range(len(sents)), key=lambda i: len(q & stems(sents[i])), default=0)
    win, total = [], len(head)
    for s in sents[best_i:] + sents[:best_i]:
        if total + len(s) > max_chars:
            break
        win.append(s)
        total += len(s)
    return head + "\n" + " ".join(win)


def _exact(db: Session, question: str, rev_ids: list[uuid.UUID]) -> list[Chunk]:
    arts = [a for a in _ART.findall(question)]
    if not arts:
        return []
    nums = {n.replace(" ", "").upper() for n in _NUM.findall(question)}
    shorts = {x.upper() for x in _SHORT.findall(question)}
    q = select(Chunk, Document).join(DocumentRevision, DocumentRevision.id == Chunk.revision_id).join(Document, Document.id == DocumentRevision.document_id).where(Chunk.revision_id.in_(rev_ids), Chunk.article.in_(arts))
    out = []
    for c, d in db.execute(q).all():
        blob = f"{d.act_number or ''} {d.short_name or ''} {d.title}".upper().replace(" ", "")
        if (nums or shorts) and not (any(n in blob for n in nums) or any(x in blob for x in shorts)):
            continue
        out.append(c)
    return out[:6]


def retrieve(db: Session, p: Providers, s: Settings, gen: CorpusGeneration, revisions: list[DocumentRevision], query: str, question: str) -> Retrieval:
    t: dict[str, int] = {}
    rev_ids = [r.id for r in revisions]
    revmap = {r.id: r for r in revisions}
    t0 = time.monotonic()
    e = p.embedder.embed([query], query=True)[0]
    t["embed_ms"] = int((time.monotonic() - t0) * 1000)
    t0 = time.monotonic()
    dense, sparse = p.vs.search(gen.collection_name, e, rev_ids, s.retrieval_top_k)
    fused = rrf([dense, sparse])[: s.retrieval_top_k]
    exact = _exact(db, question, rev_ids)
    t["search_ms"] = int((time.monotonic() - t0) * 1000)
    order: dict[uuid.UUID, Hit] = {}
    ids = [c.id for c in exact] + [cid for cid, _ in fused]
    chunks = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_(ids)))} if ids else {}
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_({r.document_id for r in revisions})))}
    for c in exact:
        r = revmap[c.revision_id]
        order[c.id] = Hit(c, r, docs[r.document_id], via=["exact"])
    for cid, sc in fused:
        ch = chunks.get(cid)
        if not ch or ch.revision_id not in revmap:
            continue
        h = order.setdefault(cid, Hit(ch, revmap[ch.revision_id], docs[revmap[ch.revision_id].document_id]))
        h.fused = sc
        h.via.append("hybrid")
    hits = list(order.values())
    considered = len(hits)
    t0 = time.monotonic()
    if hits:
        scores = p.reranker.score(query, [rerank_passage(h.chunk.heading_path + "\n" + h.chunk.text, query) for h in hits])
        for h, sc in zip(hits, scores, strict=True):
            h.rerank = sc
    t["rerank_ms"] = int((time.monotonic() - t0) * 1000)
    hits.sort(key=lambda h: (-(h.rerank), -h.fused))
    scores_dump = [{"chunk_id": str(h.chunk.id), "rerank": round(h.rerank, 4), "fused": round(h.fused, 5), "via": h.via} for h in hits[: s.rerank_keep + 4]]
    if not hits:
        return Retrieval([], 0, False, "no_candidates", t, scores_dump)
    best = hits[0]
    lexical_ok = bool(stems(query) & stems(best.chunk.heading_path + " " + best.chunk.text)) or "exact" in best.via
    floor = s.min_rerank_score - s.partial_answer_margin  # жёсткий отказ — только при действительно нерелевантной выдаче
    if best.rerank < floor or not lexical_ok:
        return Retrieval([], considered, False, "below_threshold", t, scores_dump, best_score=best.rerank)
    conf = "high" if best.rerank >= s.min_rerank_score else "partial"
    sel: list[Hit] = []
    used = 0
    for h in hits:
        if len(sel) >= s.rerank_keep:
            break
        if h.rerank < floor and "exact" not in h.via:
            continue
        need = est_tokens(h.chunk.text, s.chars_per_token)
        if used + need > s.context_budget_tokens:
            if not sel and need <= int(s.context_budget_tokens * 1.5):  # норма не режется: первая допустима до 1.5× бюджета
                sel.append(h)
                used += need
            continue
        sel.append(h)
        used += need
    return Retrieval(sel, considered, bool(sel), None if sel else "budget", t, scores_dump, conf, best.rerank)
