"""Прогон эталонного набора на уровне поиска: recall@k, отказы, распределение скоров.

Здесь НЕ измеряется юридическая правильность ответа: проверяется, попала ли нужная норма в контекст,
который получит модель, и не отказала ли система при живых основаниях. Полные ответы с проверкой
цитат измеряет evals/run_eval.py на запущенном стенде.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.errors import ApiError
from ...core.util import norm_ws
from ...db.models import Document
from ...providers.registry import Providers
from ..rag.retrieval import retrieve
from .indexer import active_generation, applicable_revisions


def _act_matches(doc: Document, expected: str) -> bool:
    blob = norm_ws(f"{doc.act_number or ''} {doc.short_name or ''} {doc.title}").upper().replace(" ", "")
    return expected.upper().replace(" ", "").replace("-", "") in blob.replace("-", "")


def _article_matches(locator: str, article: str | None, expected: list[str]) -> bool:
    got = {article or ""} | set(re.findall(r"\d+(?:\.\d+)*", locator or ""))
    return any(e in got for e in expected)


def run(db: Session, s: Settings, p: Providers, golden_path: Path, out_dir: Path, *, as_of: date | None = None, k: int = 8) -> dict[str, Any]:
    gen = active_generation(db)
    if not gen:
        raise ApiError(409, "no_generation", "Корпус не проиндексирован: doorain kb reindex")
    data = yaml.safe_load(golden_path.read_text(encoding="utf-8")) or {}
    cases = data.get("cases") or []
    revs = applicable_revisions(db, gen, as_of or date.today())
    docs = {d.id: d for d in db.scalars(select(Document))}
    rmap = {r.id: r for r in revs}
    demo_only = all(d.is_demo for d in docs.values()) if docs else True
    rows: list[dict[str, Any]] = []
    for c in cases:
        r = retrieve(db, p, s, gen, revs, c["question"], c["question"])
        top = r.selected[:k]
        acts, hit = [], False
        for h in top:
            d = docs.get(rmap[h.revision.id].document_id) if h.revision.id in rmap else None
            if d:
                acts.append(d.short_name or d.act_number or d.title[:30])
            if not hit and d and any(_act_matches(d, a) for a in c.get("expect_acts", [])) and (not c.get("expect_articles") or _article_matches(h.chunk.locator, h.chunk.article, c["expect_articles"])):
                hit = True
        refused = not r.sufficient
        rows.append(
            {
                "id": c["id"], "role": c["role"], "expect": c["expect"], "question": c["question"],
                "refused": refused, "confidence": r.confidence, "best_score": round(r.best_score, 3) if r.best_score is not None else None,
                "recall_hit": hit if c["expect"] == "answer" else None,
                "expect_acts": c.get("expect_acts", []), "expect_articles": c.get("expect_articles", []),
                "got": [f"{a}, {h.chunk.locator}" for a, h in zip(acts, top, strict=False)][:k],
                "ok": (not refused and hit) if c["expect"] == "answer" else refused,
            }
        )
    answerable = [x for x in rows if x["expect"] == "answer"]
    traps = [x for x in rows if x["expect"] == "refusal"]
    report = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "golden_set": str(golden_path), "expert_verified": bool(data.get("expert_verified")),
        "generation": gen.seq, "collection": gen.collection_name, "embedder": gen.fingerprint.get("model"),
        "corpus": {"documents": len(docs), "revisions": len(revs), "demo_only": demo_only},
        "thresholds": {"min_rerank_score": s.min_rerank_score, "source": s.threshold_source, "partial_margin": s.partial_answer_margin},
        "metrics": {
            f"recall_at_{k}": round(sum(1 for x in answerable if x["recall_hit"]) / len(answerable), 3) if answerable else None,
            "refusals_on_answerable": sum(1 for x in answerable if x["refused"]),
            "answerable": len(answerable),
            "honest_refusals": {"ok": sum(1 for x in traps if x["refused"]), "of": len(traps)},
            "partial_answers": sum(1 for x in answerable if x["confidence"] == "partial" and not x["refused"]),
        },
        "caveats": [
            "Метрика уровня поиска: попадание нормы в контекст, а не правильность юридического вывода",
            "expect_* — гипотезы автора набора, экспертной разметки нет" if not data.get("expert_verified") else "разметка подтверждена экспертом",
            "Ловушки проверяются по выдаче поиска; отказ классификатора «вне области» измеряет evals/run_eval.py",
        ] + (["ВНИМАНИЕ: в корпусе только демонстрационные данные — прогон характеризует стенд, а не право"] if demo_only else []),
        "cases": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"kb-eval-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    report["report_path"] = str(path)
    return report
