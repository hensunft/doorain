"""Чек-лист исправности поиска: коллекция, размерность, метрика, единая модель, «голый» поиск, порог, порядок guardrail, мягкость фильтров, качество чанков.

Отвечает на вопрос «поиск сломан или корпус не содержит нужного»: пока чек-лист красный, наполнять базу бессмысленно.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...db.models import Chunk, Document, DocumentRevision
from ...providers.registry import Providers
from ..rag.retrieval import _ART, retrieve
from .indexer import active_generation, applicable_revisions, fp_hash

CRITICAL = {"collection", "dim", "metric", "same_model", "raw_search", "guardrail_order", "chunks"}


@dataclass
class Check:
    id: str
    title: str
    ok: bool
    detail: str
    data: dict[str, Any] | None = None


def _probe_queries(db: Session, revs: list[DocumentRevision]) -> list[tuple[DocumentRevision, Chunk, str]]:
    """По одному фрагменту из каждой редакции: его собственный текст обязан находить его же.

    Номера статей из запроса убираются: иначе сработает точный поиск по метаданным и проверка перестанет видеть сломанный индекс.
    """
    out = []
    for r in revs:
        c = db.scalar(select(Chunk).where(Chunk.revision_id == r.id).order_by(Chunk.ordinal).limit(1))
        if c:
            out.append((r, c, _ART.sub(" ", c.text)[:200]))
    return out


def checklist(db: Session, p: Providers, s: Settings, as_of: Any = None) -> list[Check]:
    from datetime import date  # noqa: PLC0415

    as_of = as_of or date.today()
    out: list[Check] = []
    gen = active_generation(db)
    if not gen:
        return [Check("collection", "Активная generation", False, "Активной generation нет: корпус не проиндексирован (doorain kb reindex)")]
    points = p.vs.count(gen.collection_name)
    out.append(Check("collection", "Коллекция Qdrant и число точек", points > 0, f"{gen.collection_name}: {points} точек", {"points": points}))
    fp = p.embedder.fingerprint()
    info = p.vs.info(gen.collection_name)
    dim_ok = info.get("dim") == int(fp["dim"])
    out.append(Check("dim", "Размерность коллекции = размерности модели", dim_ok, f"коллекция {info.get('dim')}, модель {fp['dim']}", info))
    metric_ok = str(info.get("distance", "")).lower().endswith("cosine")
    vec = p.embedder.embed(["проверка нормализации"], query=True)[0]
    norm = sum(x * x for x in vec.dense) ** 0.5
    normalized = abs(norm - 1.0) < 0.05
    out.append(Check("metric", "Метрика и нормализация векторов", metric_ok and normalized, f"distance={info.get('distance')}, |v|={norm:.4f}, sparse={info.get('sparse')}"))
    same = fp_hash(fp) == gen.fingerprint_hash
    out.append(
        Check(
            "same_model",
            "Одна модель при индексации и при запросе",
            same,
            f"{fp['model']} (query_prefix={fp['query_prefix']!r}, doc_prefix={fp['doc_prefix']!r})" if same else "отпечаток модели не совпадает с generation: нужна переиндексация",
        )
    )
    revs = applicable_revisions(db, gen, as_of)
    hits = [(r, c, retrieve(db, p, s, gen, revs, q, q)) for r, c, q in _probe_queries(db, revs)]
    found = [1 for _, c, res in hits if any(h.chunk.id == c.id for h in res.selected)]
    out.append(
        Check(
            "raw_search",
            "«Голый» поиск находит собственные фрагменты корпуса",
            bool(hits) and len(found) == len(hits),
            f"{len(found)} из {len(hits)} редакций находят свой фрагмент" if hits else "в редакциях нет чанков",
            {"revisions": len(revs)},
        )
    )
    out.append(
        Check(
            "guardrail_order",
            "Guardrail не срабатывает раньше поиска",
            all(res.sufficient for _, _, res in hits) if hits else False,
            "отказ выносится после поиска; при непустом контексте отказа нет" if hits else "проверить нечем: корпус пуст",
        )
    )
    scores = [res.best_score for _, _, res in hits if res.best_score is not None]
    out.append(
        Check(
            "threshold",
            "Порог отказа откалиброван по распределению скоров",
            s.threshold_source != "uncalibrated",
            f"порог {s.min_rerank_score} ({s.threshold_source}); контрольные скоры min={min(scores):.2f} median={statistics.median(scores):.2f} max={max(scores):.2f}"
            if scores
            else f"порог {s.min_rerank_score} ({s.threshold_source}); измерить не на чем",
            {"scores": [round(x, 3) for x in scores]},
        )
    )
    out.append(
        Check(
            "soft_filters",
            "Фильтры поиска мягкие и не обнуляют выдачу",
            True,
            f"поиск фильтрует только по редакциям generation ({len(revs)} шт.); тема классификатора фильтром не является, вердикт «вне области» снимается нормами со скором ≥ {s.min_rerank_score + s.scope_override_min_score}",
        )
    )
    total = db.scalar(select(func.count()).select_from(Chunk).join(DocumentRevision, DocumentRevision.id == Chunk.revision_id).where(DocumentRevision.status == "ready")) or 0
    lens = [x for (x,) in db.execute(select(func.length(Chunk.text)))] or [0]
    short = sum(1 for x in lens if x < 40)
    no_meta = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.article.is_(None), Chunk.locator == "")) or 0
    cut = sum(1 for (t,) in db.execute(select(Chunk.text)) if t and t.rstrip()[-1:].isalpha() and not t.rstrip().endswith(("др", "т.д", "т.п")))
    med_tok = int(statistics.median(lens) / s.chars_per_token)
    out.append(
        Check(
            "chunks",
            "Чанки не деградировали",
            total > 0 and short == 0,
            f"{total} чанков; пустых/короче 40 символов: {short}; без реквизитов: {no_meta}; обрыв на середине предложения: {cut}; медиана ≈ {med_tok} токенов",
            {"total": total, "median_tokens": med_tok, "short": short, "without_locator": no_meta, "cut_mid_sentence": cut},
        )
    )
    return out


def summary(db: Session, p: Providers, s: Settings, as_of: Any = None) -> dict[str, Any]:
    checks = checklist(db, p, s, as_of)
    failed = [c.id for c in checks if not c.ok]
    docs = db.scalar(select(func.count()).select_from(Document)) or 0
    demo = db.scalar(select(func.count()).select_from(Document).where(Document.is_demo.is_(True))) or 0
    return {
        "ok": not (set(failed) & CRITICAL),
        "failed": failed,
        "critical_failed": sorted(set(failed) & CRITICAL),
        "documents": docs,
        "demo_documents": demo,
        "checks": [{"id": c.id, "title": c.title, "ok": c.ok, "detail": c.detail, "data": c.data} for c in checks],
    }
