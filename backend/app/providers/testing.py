"""ТЕСТОВЫЕ провайдеры (DOORAIN_PROVIDER_MODE=test). Не модель: детерминированные заглушки для тестов/e2e/UI.

Интерфейс явно маркируется в UI («Тестовый режим — ответы формирует шаблонная заглушка, не языковая модель»).
Запуск в production запрещён (см. Settings). Прохождение тестов на этих заглушках не доказывает качество RAG.
"""

from __future__ import annotations

import json
import math
import re
import zlib
from collections.abc import Iterator
from typing import Any

from ..core.util import stems
from .base import Embedded, Health, ProviderError

DIM = 128


def _h(tok: str, mod: int) -> int:
    return zlib.crc32(tok.encode()) % mod


class TestEmbedder:
    is_test = True
    __test__ = False

    def health(self) -> Health:
        return Health(True, "test-embedder", {})

    def fingerprint(self) -> dict[str, Any]:
        return {"model": "test-hash-embedder", "revision_hash": "v1", "dim": DIM, "normalize": True, "pooling": "bow", "query_prefix": "", "doc_prefix": "", "max_length": 512, "chunking_version": "npa-v1"}

    def embed(self, texts: list[str], *, query: bool = False) -> list[Embedded]:
        out = []
        for t in texts:
            words = [w[:5] for w in re.findall(r"[а-яёa-z0-9]{3,}", t.lower())]
            dense = [0.0] * DIM
            sparse: dict[int, float] = {}
            for w in words:
                dense[_h(w, DIM)] += 1.0
                sparse[_h(w, 1_000_003)] = sparse.get(_h(w, 1_000_003), 0.0) + 1.0
            n = math.sqrt(sum(x * x for x in dense)) or 1.0
            out.append(Embedded([x / n for x in dense], {k: 1 + math.log(v) for k, v in sparse.items()}))
        return out


class TestReranker:
    is_test = True
    __test__ = False

    def health(self) -> Health:
        return Health(True, "test-reranker", {})

    def name(self) -> str:
        return "test-overlap-reranker"

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = stems(query)
        return [len(q & stems(p)) / max(1, len(q)) for p in passages]


_TOPIC_KW = {
    "personal_data": r"персональн|пдн|политик|согласи|e-?mail|почт|сервер|хостинг|биометр|роскомнадзор",
    "internet_business": r"реклам|блогер|маркировк|сайт|интернет",
    "ip_it": r"код|программ|авторск|лицензи|исключительн",
    "kii": r"кии|критическ",
    "esign": r"подпис|электронн\w* документ",
    "ai": r"искусственн|нейросет|\bии\b",
    "liability": r"штраф|уголовн|ответственност|коап",
    "info_security": r"информаци|защит",
    "digital_assets": r"цифров\w* (актив|валют)|криптовалют",
}
_IT_KW = "|".join(_TOPIC_KW.values()) + r"|закон|норм|стать"


class TestLLM:
    is_test = True
    __test__ = False

    def __init__(self) -> None:
        self.fail = False  # тесты могут имитировать недоступность

    def health(self) -> Health:
        return Health(not self.fail, "test-llm" if not self.fail else "имитация недоступности", {"name": "test-template-llm", "digest": "test", "quantization": "n/a", "num_ctx": 4096})

    # ── ответ ──
    def stream(self, messages: list[dict[str, str]], *, num_predict: int | None = None) -> Iterator[str]:
        if self.fail:
            raise ProviderError("unavailable", "имитация недоступности модели")
        blob = "\n".join(m["content"] for m in messages)
        role = re.search(r"РОЛЬ:\s*(\w+)", blob)
        role_s = role.group(1) if role else "student"
        srcs = re.findall(r"^\[(C\d+)\]\s*(.*?)\n(.*?)(?=^\[C\d+\]|\n<<<END_SOURCES|\Z)", blob, flags=re.S | re.M)
        if "НЕПОДДЕРЖИВАЕМЫЙ_ТЕЗИС" in blob:  # тест валидатора
            yield "Это утверждение без ссылки на источник.\n\n"
        paras = []
        for marker, head, body in srcs[:2]:
            sents = [x for x in re.split(r"(?<=[.;])\s", " ".join(body.split())) if len(x) >= 40]
            first = (sents[0] if sents else " ".join(body.split()))[:220].rstrip()
            if role_s == "expert":
                paras.append(f"{head.strip()}: «{first}» [{marker}]")
            elif role_s == "entrepreneur":
                paras.append(f"Вывод по источнику ({head.strip()}): {first} [{marker}]")
            else:
                paras.append(f"Простыми словами ({head.strip()}): {first} [{marker}]")
        if role_s == "entrepreneur" and srcs:
            paras.append("Допущение: сведения о вашей ситуации получены только из вопроса; уточните детали.")
        text = "\n\n".join(paras) or "Источники не найдены."
        for i in range(0, len(text), 16):
            yield text[i : i + 16]

    # ── структурированные вызовы ──
    def json(self, messages: list[dict[str, str]], schema: dict[str, Any], *, num_predict: int | None = None) -> dict[str, Any]:
        if self.fail:
            raise ProviderError("unavailable", "имитация недоступности модели")
        title = schema.get("title", "")
        found = [m for m in (re.search(r"<context>(.*?)</context>", x["content"], flags=re.S) for x in messages) if m]
        ctx = json.loads(found[-1].group(1)) if found else {}
        if title == "Classification":
            return self._classify(ctx)
        if title == "AnalysisResult":
            return self._analyze(ctx)
        if title == "QuizResult":
            return self._quiz(ctx)
        raise ProviderError("invalid", f"test-llm не знает схему {title}")

    @staticmethod
    def _topics(text: str) -> list[str]:
        return [t for t, kw in _TOPIC_KW.items() if re.search(kw, text.lower())][:3]

    def _classify(self, ctx: dict[str, Any]) -> dict[str, Any]:
        q = ctx.get("question", "")
        in_scope = bool(re.search(_IT_KW, q.lower()))
        hist = ctx.get("history", [])
        rq = q if len(q.split()) > 4 or not hist else f"{hist[-1]} {q}"
        return {"in_scope": in_scope, "topics": self._topics(q) or (self._topics(" ".join(hist)) if in_scope else []), "rewritten_query": rq[:400], "clarification": None, "mixed": False}

    def _quiz(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cites = ctx.get("citations", [])[:3]
        qs = []
        for c in cites:
            qs.append({
                "question": f"Какая норма регулирует вопрос: {c['locator']}?",
                "options": [c["title"], "Норма, не связанная с вопросом", "Норма отсутствует"],
                "answer_index": 0,
                "explanation": f"Правильный вариант подтверждается источником {c['locator']}.",
                "citation_id": c["id"],
                "concept": c["locator"][:80],
                "severity": 2,
            })
        return {"questions": qs}

    def _analyze(self, ctx: dict[str, Any]) -> dict[str, Any]:
        q = ctx.get("question", "").lower()
        cites = [c["id"] for c in ctx.get("citations", [])]
        first = cites[:1]
        conseq = [c["id"] for c in ctx.get("citations", []) if re.search(r"штраф|ответственност|наказан|санкци", c.get("excerpt", "").lower())][:1]
        facts: list[dict[str, Any]] = []
        risks: list[dict[str, Any]] = []

        def about(pattern: str) -> list[str]:
            hit = [c["id"] for c in ctx.get("citations", []) if re.search(pattern, c.get("excerpt", "").lower())]
            return hit[:1] or first

        def risk(rt: str, scope: str, title: str, p: int | None, s: int | None, **kw: Any) -> None:
            pat = {"pd_no_policy": "политик", "pd_no_consent": "согласи", "pd_localization": "сервер", "ad_marking": "реклам", "ip_ownership": "программ|код"}.get(rt, "")
            risks.append({"risk_type": rt, "scope": scope, "title": title, "factual_basis_keys": kw.pop("keys", []), "applicable_conditions": kw.pop("cond", ""), "obligation_citation_ids": about(pat) if pat else first, "consequence_citation_ids": conseq, "proposed_p": p, "p_reason": kw.pop("p_reason", "Пользователь описал действия по сценарию."), "proposed_s": s, "s_reason": kw.pop("s_reason", "Оценка по методологии."), "consequences": kw.pop("consequences", ""), "recommendation": kw.pop("recommendation", "Проверить и устранить несоответствие."), **kw})

        if re.search(r"нет (у нас )?политик|политики нет|не опубликова", q):
            facts.append({"key": "has_pd_policy", "value": "no", "statement": "Политика обработки ПДн не опубликована (со слов пользователя)", "ongoing": True})
            keys = ["has_pd_policy"]
            if re.search(r"рассылк", q):  # новый независимый факт по тому же сценарию
                facts.append({"key": "sends_mailings", "value": "yes", "statement": "Ведётся email-рассылка (со слов пользователя)", "ongoing": True})
                keys.append("sends_mailings")
            risk("pd_no_policy", "сайт", "Нет опубликованной политики обработки ПДн", 4, 2, keys=keys, recommendation="Разработать и опубликовать политику.")
        elif re.search(r"(политик\w+ .*(опубликовал|разместил|есть)|уже опубликовал)", q):
            facts.append({"key": "has_pd_policy", "value": "yes", "statement": "Политика опубликована (со слов пользователя)", "ongoing": False})
            risk("pd_no_policy", "сайт", "Нет опубликованной политики обработки ПДн", None, None, resolved_by_user=True)
        elif re.search(r"нужна ли .*политик", q):
            risk("pd_no_policy", "сайт", "Нет опубликованной политики обработки ПДн", None, None, needs_clarification="Есть ли у вас опубликованная политика?")
        if re.search(r"(собира\w+|собрал\w+).*(e-?mail|почт)", q) and re.search(r"без (отдельн\w+ )?согласи", q):
            facts.append({"key": "collects_email_without_consent", "value": "yes", "statement": "E-mail собирается без согласия (со слов пользователя)", "ongoing": True})
            risk("pd_no_consent", "форма записи", "Сбор e-mail без надлежащего согласия", 4, 2, keys=["collects_email_without_consent"])
        if re.search(r"сервер.*(за рубеж|европ|германи|зарубежн)", q):
            facts.append({"key": "server_abroad", "value": "yes", "statement": "Сервер размещён за рубежом (со слов пользователя)", "ongoing": True})
            risk("pd_localization", "хостинг", "ПДн граждан РФ хранятся на зарубежном сервере", 4, 3 if conseq else 2, keys=["server_abroad"])
        if re.search(r"реклам\w+.*блогер|блогер.*реклам", q):
            risk("ad_marking", "реклама у блогеров", "Не выполнена маркировка интернет-рекламы", None, None, needs_clarification="Планируете ли вы маркировать рекламные материалы?")
        if re.search(r"код.*студент|студент.*код", q):
            risk("ip_ownership", "студенческие проекты", "Неурегулированы права на код студентов", 2, 2, keys=[])
        return {
            "schema_version": "1",
            "message_id": ctx["message_id"],
            "topic_ids": self._topics(q),
            "fact_candidates": facts,
            "citation_ids": cites,
            "risk_candidates": risks if cites else [],
            "relations": [],
        }
