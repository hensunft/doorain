"""BGE-M3 (dense + sparse) и компактный cross-encoder. Только локальные файлы; на CPU; тяжёлые импорты — лениво."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..core.config import Settings
from .base import Embedded, Health, ProviderError


def _dir_hash(path: Path, names: tuple[str, ...]) -> str:
    h = hashlib.sha256()
    for n in names:
        f = path / n
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


class BgeM3Embedder:
    is_test = False

    def __init__(self, s: Settings):
        self.s = s
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            p = Path(self.s.embed_model_path)
            if not p.is_dir():
                raise ProviderError("missing_model", f"Локальная модель embeddings не найдена: {p} (выполните prepare)")
            try:
                from FlagEmbedding import BGEM3FlagModel  # noqa: PLC0415
            except ImportError as e:
                raise ProviderError("unavailable", "FlagEmbedding не установлен (образ без группы ml)") from e
            self._model = BGEM3FlagModel(str(p), use_fp16=False, device="cpu")
        return self._model

    def health(self) -> Health:
        p = Path(self.s.embed_model_path)
        return Health(p.is_dir(), "ok" if p.is_dir() else f"Нет локальных weights: {p}", {"path": str(p)})

    def fingerprint(self) -> dict[str, Any]:
        p = Path(self.s.embed_model_path)
        return {
            "model": "BAAI/bge-m3",
            "revision_hash": _dir_hash(p, ("config.json", "tokenizer.json", "tokenizer_config.json")),
            "dim": 1024,
            "normalize": True,
            "pooling": "cls",
            "query_prefix": "",
            "doc_prefix": "",
            "max_length": self.s.embed_max_len,
            "chunking_version": self.s.chunking_version,
        }

    def embed(self, texts: list[str], *, query: bool = False) -> list[Embedded]:
        m = self._load()
        out = m.encode(texts, batch_size=self.s.embed_batch, max_length=self.s.embed_max_len, return_dense=True, return_sparse=True, return_colbert_vecs=False)
        return [Embedded([float(x) for x in d], {int(k): float(v) for k, v in sp.items()}) for d, sp in zip(out["dense_vecs"], out["lexical_weights"], strict=True)]


class CrossEncoderReranker:
    is_test = False

    def __init__(self, s: Settings):
        self.s = s
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            p = Path(self.s.reranker_model_path)
            if not p.is_dir():
                raise ProviderError("missing_model", f"Локальная модель reranker не найдена: {p} (выполните prepare)")
            try:
                from sentence_transformers import CrossEncoder  # noqa: PLC0415
            except ImportError as e:
                raise ProviderError("unavailable", "sentence-transformers не установлен (образ без группы ml)") from e
            self._model = CrossEncoder(str(p), max_length=512, device="cpu", local_files_only=True)
        return self._model

    def name(self) -> str:
        p = Path(self.s.reranker_model_path)
        cfg = p / "config.json"
        return json.loads(cfg.read_text()).get("_name_or_path", p.name) if cfg.is_file() else p.name

    def health(self) -> Health:
        p = Path(self.s.reranker_model_path)
        return Health(p.is_dir(), "ok" if p.is_dir() else f"Нет локальных weights: {p}", {"path": str(p)})

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        m = self._load()
        return [float(x) for x in m.predict([(query, p) for p in passages], batch_size=4, show_progress_bar=False)]
