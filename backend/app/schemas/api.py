"""Контракты REST API (/api/v1). OpenAPI из этих моделей — источник типов фронтенда."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["student", "entrepreneur", "expert"]
Tri = Literal["yes", "no", "unknown"]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── доступ ──
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(Out):
    id: uuid.UUID
    username: str  # стабильный идентификатор, не меняется
    display_name: str  # «Имя Фамилия»; у прежних учётных записей — логин
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None  # адрес не подтверждается письмом
    access_level: Literal["owner", "user"]
    disclaimer_accepted_at: datetime | None = None


class AuthOut(BaseModel):
    user: UserOut
    csrf_token: str
    single_user_mode: bool = False


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    password_repeat: str = Field(min_length=1, max_length=256)  # только сверяется, не сохраняется
    invite_code: str = Field(min_length=1, max_length=128)
    accept_terms: bool  # ознакомление с Политикой и Условиями
    accept_pd: bool  # отдельное согласие на обработку персональных данных


class ProfilePatch(BaseModel):
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=200)  # пустая строка — удалить адрес
    current_password: str | None = Field(default=None, max_length=256)  # обязателен при смене e-mail


class InviteCreate(BaseModel):
    note: str | None = Field(default=None, max_length=200)
    ttl_days: int | None = Field(default=None, ge=1, le=90)  # срок действия; по умолчанию — из настроек


class InviteCreated(BaseModel):
    code: str  # показывается один раз: в базе хранится только хеш
    hint: str
    expires_at: datetime
    register_path: str  # путь регистрации с кодом во фрагменте (#code=…): фрагмент не попадает в журналы сервера


class InviteOut(Out):
    id: uuid.UUID
    hint: str
    note: str | None
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
    used_by: str | None
    revoked_at: datetime | None
    state: Literal["active", "used", "revoked", "expired"]


class UserAdminOut(Out):
    id: uuid.UUID
    username: str
    display_name: str
    access_level: str
    created_at: datetime
    last_login_at: datetime | None
    disclaimer_accepted_at: datetime | None
    disabled_at: datetime | None
    sessions: int
    deleted_sessions: int


class UserPatch(BaseModel):
    disabled: bool | None = None


class AdminStats(BaseModel):
    users: int
    active_users: int
    sessions: int
    deleted_sessions: int
    messages: int
    risks_active: int
    sessions_by_role: dict[str, int]
    risks_by_level: dict[str, int]
    owner_can_read_user_sessions: bool


class AuditEventOut(Out):
    id: int
    at: datetime
    actor: str
    action: str
    object_type: str | None
    object_id: str | None
    details: dict[str, Any]


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


# ── сессии ──
class BusinessProfileIn(BaseModel):
    sphere: str | None = Field(default=None, max_length=200)
    has_site_or_app: Tri = "unknown"
    processes_pd: Tri = "unknown"
    mailings: Tri = "unknown"
    servers_location: Literal["ru", "abroad", "both", "unknown"] = "unknown"


class SessionCreate(BaseModel):
    role: Role
    title: str | None = Field(default=None, max_length=200)
    as_of_date: date | None = None
    profile: BusinessProfileIn | None = None


class SessionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "archived"] | None = None


class RoleChangeIn(BaseModel):
    role: Role


class SessionOut(Out):
    id: uuid.UUID
    title: str
    role: Role
    as_of_date: date
    status: Literal["active", "archived"]
    version: int
    created_at: datetime
    updated_at: datetime
    parent_session_id: uuid.UUID | None = None
    profile: dict[str, Any] | None = None
    messages_count: int = 0
    active_risks: int = 0
    risks_by_level: dict[str, int] = {}  # для полосы распределения рисков в «Моих сессиях»
    busy: bool = False


# ── сообщения / run ──
class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    client_request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")


class RunAccepted(BaseModel):
    run_id: uuid.UUID
    message_id: uuid.UUID
    deduplicated: bool = False


class CitationChip(BaseModel):
    id: uuid.UUID
    marker: str
    label: str
    locator: str
    revision_label: str
    verified: bool
    archived: bool = False  # источник выведен из базы знаний: основание недействительно


class AnswerBlock(BaseModel):
    id: str
    version: int
    kind: str
    text: str
    citation_ids: list[str] = []
    markers: list[str] = []
    state: str = "verified"
    reason: str | None = None
    removed: bool = False


class MessageOut(BaseModel):
    id: uuid.UUID
    seq: int
    role: Literal["user", "assistant"]
    text: str
    blocks: list[AnswerBlock] | None = None
    citations: list[CitationChip] = []
    run_id: uuid.UUID | None = None
    answer_status: str | None = None
    analysis_status: str | None = None
    refusal_reason: str | None = None
    warnings: list[str] = []
    created_at: datetime


class RunSnapshot(BaseModel):
    run_id: uuid.UUID
    session_id: uuid.UUID
    answer_status: str
    analysis_status: str
    refusal_reason: str | None = None
    error_code: str | None = None
    warnings: list[str] = []
    blocks: list[AnswerBlock] = []
    last_event_id: int = 0
    done: bool = False
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID | None = None
    timings: dict[str, Any] = {}


# ── портрет / риски ──
class GraphNodeOut(BaseModel):
    id: str
    kind: Literal["center", "topic", "question", "norm", "risk"]
    label: str
    weight: int
    risk_level: Literal["low", "medium", "high", "critical"] | None = None
    resolved_level: Literal["low", "medium", "high", "critical"] | None = None  # след снятого риска: узел светлеет, обводка остаётся
    risk_count: int = 0  # активных рисков на узле — бейдж вместо отдельных узлов риска
    data: dict[str, Any] = {}


class GraphEdgeOut(BaseModel):
    id: str
    source: str
    target: str
    kind: str
    data: dict[str, Any] = {}


class GraphOut(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    positions: dict[str, dict[str, float]] = {}
    filters: dict[str, Any] = {}
    topics: list[dict[str, str]] = []


class LayoutIn(BaseModel):
    positions: dict[str, dict[str, float]] = Field(default_factory=dict, max_length=2000)
    filters: dict[str, Any] = Field(default_factory=dict)


class TimelineItem(BaseModel):
    node_id: str
    message_id: str | None
    seq: int = 0
    at: datetime | None = None
    text: str
    result: str | None
    topics: list[str]
    norms: list[str]
    risks: list[dict[str, Any]]
    follow_up_of: str | None = None
    condition: str | None = None


class RiskOut(Out):
    id: uuid.UUID
    kind: Literal["legal", "learning"]
    risk_type: str
    title: str
    category: str | None
    scenario: str
    conditions: str
    consequences: str
    recommendation: str
    status: str
    base_p: int | None
    bonus_p: int
    p: int | None
    s: int | None
    score: int | None
    level: Literal["low", "medium", "high", "critical"] | None
    p_reason: str
    s_reason: str
    clarification: str | None
    resolution_reason: str | None
    resolved_by: str | None
    resolution_pending: str | None
    origin: Literal["agent", "user"] = "agent"
    manual_ps: bool = False
    pending_suggestion: dict[str, Any] | None = None
    closed_at: datetime | None = None
    description: str = ""  # суть риска (для агентских — сценарий)
    rationale: str = ""  # почему такие P и S
    mentions: int = 0  # в скольких сообщениях риск всплывал (дубли схлопываются в одну строку)
    methodology_version: str
    version: int
    created_at: datetime
    updated_at: datetime
    norms: list[str] = []
    question_ids: list[str] = []


class RisksOut(BaseModel):
    active: list[RiskOut]
    resolved: list[RiskOut]
    needs_clarification: list[RiskOut]
    clarifications: list[str]
    methodology: str
    summary: dict[str, Any] = {}
    thresholds: list[int] = [4, 9, 15]


class MatrixRisk(BaseModel):
    id: str
    title: str


class MatrixCell(BaseModel):
    p: int
    s: int
    level: Literal["low", "medium", "high", "critical"]  # уровень координат ячейки, а не её содержимого
    count: int  # открытые риски в ячейке; закрытые сюда не входят
    risks: list[MatrixRisk]


class RiskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    description: str = Field(default="", max_length=500)
    p: int = Field(ge=1, le=5)
    s: int = Field(ge=1, le=5)
    consequences: str = Field(default="", max_length=1000)
    recommendation: str = Field(default="", max_length=1000)


class PlanStepIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    due: date | None = None


class PlanStepPatch(BaseModel):
    done: bool


class PlanStep(BaseModel):
    id: str
    title: str
    done: bool = False
    due: date | None = None
    created_at: datetime


class RiskEventOut(Out):
    id: uuid.UUID
    kind: str
    from_value: str | None
    to_value: str | None
    reason: str
    author: str
    source_message_id: uuid.UUID | None
    at: datetime


class RiskEvidenceOut(BaseModel):
    role: str
    kind: str
    ref_id: uuid.UUID
    label: str
    citation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None


class ClosureCitation(BaseModel):
    id: uuid.UUID
    label: str


class ClosureAttemptOut(Out):
    """Проверка ответа о закрытии риска. verification: user_claim — «со слов пользователя», corroborated — подтверждено фактами сессии."""

    id: uuid.UUID
    state: Literal["pending", "decided", "failed", "stale"]
    decision: Literal["close", "keep_open", "clarify", "other_risk"] | None
    resolution_kind: Literal["remediated", "not_applicable"] | None
    verification: Literal["user_claim", "corroborated"] | None
    confidence: Literal["low", "medium", "high"] | None
    explanation: str
    question: str | None
    quote: str | None
    applied: bool
    source: str
    initiated_by: str
    user_answer: str
    facts: list[dict[str, Any]]
    citations: list[ClosureCitation] = []
    created_at: datetime
    finished_at: datetime | None


class ClosureIn(BaseModel):
    version: int
    answer: str = Field(min_length=1, max_length=2000)
    source: Literal["plan", "detail"]
    idempotency_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")


class ClosureResult(ClosureAttemptOut):
    risk: RiskOut


class RiskDetail(BaseModel):
    risk: RiskOut
    events: list[RiskEventOut]
    evidence: list[RiskEvidenceOut]
    closures: list[ClosureAttemptOut] = []


class RiskPatch(BaseModel):
    """Смена статуса и/или ручная оценка P и S. dismissed — синоним not_applicable («неприменимо ко мне»)."""

    status: Literal["open", "in_progress", "resolved", "closed", "not_applicable", "dismissed"] | None = None
    p: int | None = Field(default=None, ge=1, le=5)
    s: int | None = Field(default=None, ge=1, le=5)
    reason: str = Field(min_length=1, max_length=1000)
    version: int
    override: bool = False  # административное закрытие без проверки ответа: только владелец, пишется в журнал


class CitationOut(BaseModel):
    id: uuid.UUID
    marker: str
    run_id: uuid.UUID
    session_id: uuid.UUID
    revision_id: uuid.UUID
    document_id: uuid.UUID
    snapshot: dict[str, Any]
    excerpt: str
    context_before: str | None = None
    context_after: str | None = None
    formatted: str
    file_url: str


# ── корпус ──
class DraftOut(Out):
    id: uuid.UUID
    filename: str
    size: int
    sha256: str
    status: Literal["parsing", "ready", "failed", "confirmed"]
    error: str | None
    preview: dict[str, Any]
    revision_id: uuid.UUID | None
    created_at: datetime


class ConfirmImportIn(BaseModel):
    doc_type: Literal["npa", "textbook", "soft_law"]
    title: str = Field(min_length=1, max_length=500)
    short_name: str | None = Field(default=None, max_length=80)
    act_number: str | None = Field(default=None, max_length=60)
    act_date: date | None = None
    revision_date: date | None = None
    edition: str | None = Field(default=None, max_length=120)
    publication_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    verified_at: date | None = None
    source_url: str | None = Field(default=None, max_length=500)
    license_note: str | None = Field(default=None, max_length=500)
    manifest_id: str | None = Field(default=None, max_length=60)
    topics: list[str] = Field(default_factory=list, max_length=6)
    build_index: bool = True


class ConfirmImportOut(BaseModel):
    revision_id: uuid.UUID
    document_id: uuid.UUID
    created: bool
    job_id: uuid.UUID | None = None


class RevisionOut(Out):
    id: uuid.UUID
    revision_date: date | None
    edition: str | None
    publication_date: date | None
    effective_from: date | None
    effective_to: date | None
    verified_at: date | None
    corpus_state: str
    chunk_count: int
    char_count: int
    original_name: str
    checksum: str
    uploaded_at: datetime


class DocumentOut(BaseModel):
    id: uuid.UUID
    doc_type: str
    title: str
    short_name: str | None
    act_number: str | None
    act_date: date | None
    license_note: str | None
    source_url: str | None
    excluded: bool = False  # исключён из корпуса: не попадает в новые generation
    cited_in_sessions: int = 0  # сколько сессий ссылается на документ: пока > 0, удаление отклоняется
    revisions: list[RevisionOut]


class DocumentPatch(BaseModel):
    excluded: bool


class RevisionPatch(BaseModel):
    verified_at: date | None = None
    effective_to: date | None = None
    clear_effective_to: bool = False


class ChunkOut(Out):
    id: uuid.UUID
    ordinal: int
    kind: str
    locator: str
    heading_path: str
    page: int | None
    text: str


class GenerationOut(Out):
    id: uuid.UUID
    seq: int
    status: str
    fingerprint: dict[str, Any]
    collection_name: str
    manifest_sha256: str | None
    control_search: dict[str, Any]
    created_at: datetime
    activated_at: datetime | None
    note: str | None


class ManifestItem(BaseModel):
    id: str
    tier: Literal["start", "extended"]
    title: str
    kind: str
    topics: list[str]
    note: str | None = None
    status: Literal["missing", "imported", "indexed", "verified"]
    revisions: int = 0


class CorpusOverview(BaseModel):
    documents: int
    revisions: int
    chunks: int
    active_generation: GenerationOut | None
    generations: list[GenerationOut]
    empty: bool
    index_ready: bool


class JobOut(Out):
    id: uuid.UUID
    type: str
    status: str
    attempts: int
    progress: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    cancel_requested: bool
    created_at: datetime
    finished_at: datetime | None


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    revision_id: uuid.UUID
    document_title: str
    locator: str
    revision_date: date | None
    edition: str | None
    verified_at: date | None
    excerpt: str
    applicable: bool


# ── самопроверка / экспорт / система ──
class QuizQuestionOut(BaseModel):
    id: str
    question: str
    options: list[str]
    concept: str


class QuizOut(BaseModel):
    id: uuid.UUID
    status: str
    error: str | None = None
    questions: list[QuizQuestionOut] = []
    job_id: uuid.UUID | None = None


class QuizAttemptIn(BaseModel):
    answers: dict[str, int] = Field(max_length=10)


class QuizAttemptOut(BaseModel):
    id: uuid.UUID
    results: list[dict[str, Any]]
    correct: int
    total: int


class ExportCreate(BaseModel):
    allow_incomplete: bool = False  # реплик диалога в документе нет: опции «приложить диалог» не существует


class ExportOut(Out):
    id: uuid.UUID
    session_id: uuid.UUID
    status: str
    incomplete: bool
    size: int | None
    sha256: str | None
    error: str | None
    created_at: datetime
    job_id: uuid.UUID | None = None


class ModelStatus(BaseModel):
    state: Literal["ready", "unavailable", "test_mode"]
    name: str | None = None
    detail: str = ""


class SystemStatus(BaseModel):
    model: ModelStatus
    corpus_empty: bool
    corpus_as_of: date | None
    generation_seq: int | None
    worker_alive: bool
    maintenance: bool
    provider_mode: str
    disclaimer: str
    version: str


class Diagnostics(BaseModel):
    version: str
    provider_mode: str
    database: dict[str, Any]
    qdrant: dict[str, Any]
    llm: dict[str, Any]
    embedder: dict[str, Any]
    reranker: dict[str, Any]
    worker: dict[str, Any]
    corpus: dict[str, Any]
    jobs: dict[str, int]
    disk: dict[str, Any]
    maintenance: bool
    thresholds: dict[str, Any]


class LegalOut(BaseModel):
    """Данные для публичных страниц Политики, Условий и Контактов. missing — поля оператора, которые нужно заполнить до публичного запуска."""

    version: str
    operator: dict[str, str]
    missing: list[str]
    owner_can_read_user_sessions: bool
    session_ttl_hours: int
    invite_ttl_days: int
    login_attempts_days: int
    disclaimer: str


class RiskLevelRange(BaseModel):
    level: Literal["low", "medium", "high", "critical"]
    label: str
    min: int
    max: int


class RiskMethodologyOut(BaseModel):
    """Шкалы и пороги оценки из backend-конфигураций (app/config/risk.yaml, services/risks/scales/<роль>.yaml)."""

    version: str
    role: str
    measure: str
    probability: dict[int, str]
    severity: dict[int, str]
    levels: list[RiskLevelRange]
    rules: list[str]
