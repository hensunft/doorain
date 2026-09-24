"""Контракты структурированных вызовов LLM. JSON Schema передаётся Ollama, затем результат валидируется сервером."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, Field

from ..services.risks.methodology import RISK_TYPE_IDS, TOPIC_IDS

SCHEMA_VERSION: Final = "1"

if TYPE_CHECKING:  # Literal из словаря собирается динамически: для mypy это str, для pydantic/JSON Schema — enum
    TopicId = str
    RiskTypeId = str
else:
    TopicId = Literal[tuple(TOPIC_IDS)]
    RiskTypeId = Literal[tuple(RISK_TYPE_IDS)]


class Classification(BaseModel):
    """Один вызов: тема(ы), область, уточнённый поисковый запрос."""

    in_scope: bool = Field(description="Вопрос относится к праву высоких технологий (IT-праву)")
    topics: list[TopicId] = Field(default_factory=list, max_length=4)
    rewritten_query: str = Field(max_length=400, description="Самодостаточный поисковый запрос с учётом истории")
    clarification: str | None = Field(default=None, max_length=300, description="Уточняющий вопрос, если без него нельзя ответить")
    mixed: bool = Field(default=False, description="Вопрос частично вне IT-права")


class FactCandidate(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{2,60}$", description="Стабильный ключ факта, snake_case")
    value: Literal["yes", "no", "unknown"]
    statement: str = Field(max_length=300)
    ongoing: bool = Field(default=False, description="Ситуация продолжается сейчас (со слов пользователя)")


class RiskCandidate(BaseModel):
    risk_type: RiskTypeId
    scope: str = Field(max_length=100, description="Объект/сценарий, например: сайт школы, форма записи")
    title: str = Field(max_length=200)
    factual_basis_keys: list[str] = Field(default_factory=list, max_length=8, description="Ключи подтверждённых фактов")
    applicable_conditions: str = Field(default="", max_length=600)
    obligation_citation_ids: list[str] = Field(default_factory=list, max_length=6)
    consequence_citation_ids: list[str] = Field(default_factory=list, max_length=6)
    proposed_p: int | None = Field(default=None, ge=1, le=5)
    p_reason: str = Field(default="", max_length=500)
    proposed_s: int | None = Field(default=None, ge=1, le=5)
    s_reason: str = Field(default="", max_length=500)
    consequences: str = Field(default="", max_length=600)
    recommendation: str = Field(default="", max_length=600)
    needs_clarification: str | None = Field(default=None, max_length=300)
    resolved_by_user: bool = False
    resolution_ambiguous: bool = False


class Relation(BaseModel):
    kind: Literal["follow_up_of", "evidences", "conditional"]
    target_message_id: str | None = None
    condition: str | None = Field(default=None, max_length=200)


class AnalysisResult(BaseModel):
    schema_version: Literal["1"] = SCHEMA_VERSION
    message_id: str
    topic_ids: list[TopicId] = Field(default_factory=list, max_length=4)
    fact_candidates: list[FactCandidate] = Field(default_factory=list, max_length=12)
    citation_ids: list[str] = Field(default_factory=list, max_length=16)
    risk_candidates: list[RiskCandidate] = Field(default_factory=list, max_length=8)
    relations: list[Relation] = Field(default_factory=list, max_length=6)


class ClosureDecision(BaseModel):
    """Решение о закрытии риска по ответу пользователя. Сервер проверяет цитату ответа, id норм и фактов, а не верит полям на слово."""

    schema_version: Literal["1"] = SCHEMA_VERSION
    decision: Literal["close", "keep_open", "clarify", "other_risk"]
    resolution_kind: Literal["remediated", "not_applicable", "none"] = "none"
    verification: Literal["user_claim", "corroborated"] = "user_claim"
    confidence: Literal["low", "medium", "high"]
    explanation: str = Field(max_length=700, description="Почему принято именно это решение")
    evidence_quote: str = Field(default="", max_length=300, description="Дословный фрагмент ответа пользователя, на который опирается решение")
    used_fact_keys: list[str] = Field(default_factory=list, max_length=8, description="Ключи фактов сессии из контекста")
    citation_ids: list[str] = Field(default_factory=list, max_length=6, description="Идентификаторы норм из списка norms контекста")
    clarification_question: str | None = Field(default=None, max_length=300, description="Что именно нужно уточнить (для decision=clarify)")
    other_risk_hint: str | None = Field(default=None, max_length=300, description="Иная проблема, о которой говорит ответ (для decision=other_risk)")


class QuizQuestion(BaseModel):
    question: str = Field(max_length=400)
    options: list[str] = Field(min_length=2, max_length=5)
    answer_index: int = Field(ge=0, le=4)
    explanation: str = Field(max_length=500)
    citation_id: str
    concept: str = Field(max_length=100)
    severity: int = Field(default=2, ge=1, le=3)


class QuizResult(BaseModel):
    questions: list[QuizQuestion] = Field(min_length=1, max_length=5)
