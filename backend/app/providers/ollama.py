from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from ..core.config import Settings
from .base import TRUNCATED_MARK, Health, ProviderError


class OllamaLLM:
    is_test = False

    def __init__(self, s: Settings):
        self.s = s
        self._timeout = httpx.Timeout(s.ollama_timeout_s, connect=5.0)

    def _opts(self, num_predict: int | None) -> dict[str, Any]:
        return {"num_ctx": self.s.ollama_num_ctx, "num_predict": num_predict or self.s.ollama_num_predict, "temperature": 0.2, "seed": 7}

    def health(self) -> Health:
        try:
            r = httpx.get(f"{self.s.ollama_url}/api/tags", timeout=5.0)
            r.raise_for_status()
        except httpx.HTTPError as e:
            return Health(False, f"Ollama недоступен: {type(e).__name__}")
        models = {m["name"]: m for m in r.json().get("models", [])}
        m = models.get(self.s.ollama_model)
        if not m:
            return Health(False, f"Модель {self.s.ollama_model} не загружена (выполните prepare)", {"available": sorted(models)})
        det = m.get("details", {})
        return Health(True, "ok", {"name": m["name"], "digest": m.get("digest"), "quantization": det.get("quantization_level"), "parameter_size": det.get("parameter_size"), "num_ctx": self.s.ollama_num_ctx})

    def stream(self, messages: list[dict[str, str]], *, num_predict: int | None = None) -> Iterator[str]:
        payload = {"model": self.s.ollama_model, "think": False, "keep_alive": "10m", "messages": messages, "stream": True, "options": self._opts(num_predict)}
        try:
            with httpx.stream("POST", f"{self.s.ollama_url}/api/chat", json=payload, timeout=self._timeout) as r:
                if r.status_code == 404:
                    raise ProviderError("missing_model", f"Модель {self.s.ollama_model} не найдена в Ollama")
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    d = json.loads(line)
                    if d.get("error"):
                        raise ProviderError("unavailable", str(d["error"])[:200])
                    if piece := d.get("message", {}).get("content"):
                        yield piece
                    if d.get("done"):
                        if d.get("done_reason") == "length":
                            yield TRUNCATED_MARK  # служебный маркер: ответ обрезан num_predict
                        return
        except httpx.TimeoutException as e:
            raise ProviderError("timeout", "Таймаут ответа модели") from e
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", f"Ollama недоступен: {type(e).__name__}") from e

    def json(self, messages: list[dict[str, str]], schema: dict[str, Any], *, num_predict: int | None = None) -> dict[str, Any]:
        payload = {"model": self.s.ollama_model, "think": False, "keep_alive": "10m", "messages": messages, "stream": False, "format": schema, "options": self._opts(num_predict or 900)}
        try:
            r = httpx.post(f"{self.s.ollama_url}/api/chat", json=payload, timeout=self._timeout)
            r.raise_for_status()
        except httpx.TimeoutException as e:
            raise ProviderError("timeout", "Таймаут ответа модели") from e
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", f"Ollama недоступен: {type(e).__name__}") from e
        try:
            return json.loads(r.json()["message"]["content"])
        except (KeyError, ValueError) as e:
            raise ProviderError("invalid", "Модель вернула невалидный JSON") from e
