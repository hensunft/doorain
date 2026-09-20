"""Границы с локальными моделями. Никакого облачного fallback: недоступность модели = явная ошибка."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

TRUNCATED_MARK = "<<doorain:truncated>>"  # служебный маркер: генерация оборвана лимитом num_predict


class ProviderError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # unavailable | timeout | invalid | missing_model


@dataclass
class Health:
    ok: bool
    detail: str = ""
    info: dict[str, Any] = field(default_factory=dict)


@dataclass
class Embedded:
    dense: list[float]
    sparse: dict[int, float]


class LLM(Protocol):
    is_test: bool

    def health(self) -> Health: ...
    def stream(self, messages: list[dict[str, str]], *, num_predict: int | None = None) -> Iterator[str]: ...
    def json(self, messages: list[dict[str, str]], schema: dict[str, Any], *, num_predict: int | None = None) -> dict[str, Any]: ...


class Embedder(Protocol):
    is_test: bool

    def health(self) -> Health: ...
    def fingerprint(self) -> dict[str, Any]: ...
    def embed(self, texts: list[str], *, query: bool = False) -> list[Embedded]: ...


class Reranker(Protocol):
    is_test: bool

    def health(self) -> Health: ...
    def name(self) -> str: ...
    def score(self, query: str, passages: list[str]) -> list[float]: ...
