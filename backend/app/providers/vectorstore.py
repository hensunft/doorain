"""Qdrant: dense + sparse, фильтр по revision_id. Индекс восстанавливаем из PostgreSQL."""

from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import QdrantClient, models

from .base import Embedded


class VectorStore:
    def __init__(self, url: str):
        self.client = QdrantClient(location=":memory:") if url == ":memory:" else QdrantClient(url=url, timeout=30)

    def health(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:  # noqa: BLE001
            return False

    def ensure(self, name: str, dim: int) -> None:
        if not self.client.collection_exists(name):
            self.client.create_collection(
                name,
                vectors_config={"dense": models.VectorParams(size=dim, distance=models.Distance.COSINE)},
                sparse_vectors_config={"sparse": models.SparseVectorParams()},
            )

    def upsert(self, name: str, items: list[tuple[uuid.UUID, Embedded, dict[str, Any]]]) -> None:
        pts = [
            models.PointStruct(
                id=str(cid),
                vector={"dense": e.dense, "sparse": models.SparseVector(indices=list(e.sparse), values=list(e.sparse.values()))},
                payload=payload,
            )
            for cid, e, payload in items
        ]
        self.client.upsert(name, pts, wait=True)

    def _filter(self, revision_ids: list[uuid.UUID]) -> models.Filter:
        return models.Filter(must=[models.FieldCondition(key="revision_id", match=models.MatchAny(any=[str(r) for r in revision_ids]))])

    def search(self, name: str, e: Embedded, revision_ids: list[uuid.UUID], limit: int) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
        """Возвращает (dense-ранжирование, sparse-ранжирование) как списки chunk_id."""
        if not revision_ids or not self.client.collection_exists(name):
            return [], []
        flt = self._filter(revision_ids)
        d = self.client.query_points(name, query=e.dense, using="dense", query_filter=flt, limit=limit, with_payload=False).points
        sp = models.SparseVector(indices=list(e.sparse), values=list(e.sparse.values()))
        s = self.client.query_points(name, query=sp, using="sparse", query_filter=flt, limit=limit, with_payload=False).points if e.sparse else []
        return [uuid.UUID(str(p.id)) for p in d], [uuid.UUID(str(p.id)) for p in s]

    def delete_points(self, name: str, chunk_ids: list[uuid.UUID]) -> None:
        """Убрать векторы удалённых фрагментов; коллекция остаётся для остальных документов."""
        if not chunk_ids or not self.client.collection_exists(name):
            return
        self.client.delete(name, points_selector=models.PointIdsList(points=[str(c) for c in chunk_ids]), wait=True)

    def info(self, name: str) -> dict[str, Any]:
        """Фактические параметры коллекции — для чек-листа исправности поиска."""
        if not self.client.collection_exists(name):
            return {}
        cfg = self.client.get_collection(name).config.params
        dense = (cfg.vectors or {}).get("dense") if isinstance(cfg.vectors, dict) else cfg.vectors
        return {"dim": getattr(dense, "size", None), "distance": str(getattr(dense, "distance", "")), "sparse": sorted((cfg.sparse_vectors or {}).keys())}

    def count(self, name: str) -> int:
        return self.client.count(name, exact=True).count if self.client.collection_exists(name) else 0

    def drop(self, name: str) -> None:
        if self.client.collection_exists(name):
            self.client.delete_collection(name)


def rrf(rankings: list[list[uuid.UUID]], k: int = 60) -> list[tuple[uuid.UUID, float]]:
    """Reciprocal Rank Fusion: объединение dense и sparse списков."""
    acc: dict[uuid.UUID, float] = {}
    for r in rankings:
        for i, cid in enumerate(r):
            acc[cid] = acc.get(cid, 0.0) + 1.0 / (k + i + 1)
    return sorted(acc.items(), key=lambda x: -x[1])
