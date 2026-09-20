from __future__ import annotations

from dataclasses import dataclass

from ..core.config import get_settings
from .base import LLM as LLMProto
from .base import Embedder, Reranker
from .vectorstore import VectorStore


@dataclass
class Providers:
    llm: LLMProto
    embedder: Embedder
    reranker: Reranker
    vs: VectorStore

    @property
    def is_test(self) -> bool:
        return bool(self.llm.is_test)


_cache: Providers | None = None


def get_providers() -> Providers:
    global _cache  # noqa: PLW0603
    if _cache is None:
        s = get_settings()
        vs = VectorStore(s.qdrant_url)
        if s.provider_mode == "test":
            from .testing import TestEmbedder, TestLLM, TestReranker  # noqa: PLC0415

            _cache = Providers(TestLLM(), TestEmbedder(), TestReranker(), vs)
        else:
            from .embeddings import BgeM3Embedder, CrossEncoderReranker  # noqa: PLC0415
            from .ollama import OllamaLLM  # noqa: PLC0415

            _cache = Providers(OllamaLLM(s), BgeM3Embedder(s), CrossEncoderReranker(s), vs)
    return _cache


def set_providers(p: Providers | None) -> None:
    global _cache  # noqa: PLW0603
    _cache = p
