"""Нормализованная схема. JSONB — только для схемных метаданных и снимков, связи — через FK.

Связи детей с ConsultationSession каскадные на уровне БД (ondelete=CASCADE): удаление сессии удаляет
сообщения, факты, риски, граф, цитаты и т. д.; общий корпус НПА не затрагивается.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..core.util import new_id, now
from .base import Base, BigIntPK, JSONType

J = JSONType


def _sfk() -> ForeignKey:
    return ForeignKey("consultation_sessions.id", ondelete="CASCADE")


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=new_id)


def _ts() -> Mapped[datetime]:
    return mapped_column(default=now)


# ───────────── доступ ─────────────
class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    access_level: Mapped[str] = mapped_column(String(10), default="user")  # owner | user (уровень доступа, не роль диалога)
    email: Mapped[str | None] = mapped_column(String(200))
    disclaimer_accepted_at: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    disabled_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = _ts()
    password_changed_at: Mapped[datetime] = _ts()


class Invite(Base):
    """Код приглашения: публичной саморегистрации нет, учётную запись открывает код от владельца."""

    __tablename__ = "invites"
    id: Mapped[uuid.UUID] = _pk()
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    hint: Mapped[str] = mapped_column(String(12), default="")  # последние символы кода: чтобы владелец узнал свой код в списке
    note: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None]


class AuthSession(Base):
    """Серверная сессия входа (не путать с ConsultationSession)."""

    __tablename__ = "auth_sessions"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime]
    last_seen_at: Mapped[datetime] = _ts()
    revoked_at: Mapped[datetime | None]
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(64))
    username_key: Mapped[str] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime] = _ts()
    __table_args__ = (Index("ix_login_ip_at", "ip", "at"), Index("ix_login_user_at", "username_key", "at"))


# ───────────── консультации ─────────────
class ConsultationSession(Base):
    __tablename__ = "consultation_sessions"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # student | entrepreneur | expert
    as_of_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | archived
    version: Mapped[int] = mapped_column(Integer, default=0)
    layout: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    parent_session_id: Mapped[uuid.UUID | None]  # сессия, из которой создана смена роли
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()
    deleted_at: Mapped[datetime | None]  # мягкое удаление: окончательную очистку выполняет владелец


class BusinessProfile(Base):
    __tablename__ = "business_profile_snapshots"
    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(_sfk(), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    created_at: Mapped[datetime] = _ts()


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(_sfk(), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    blocks: Mapped[list[Any] | None] = mapped_column(J, nullable=True)
    client_request_id: Mapped[str | None] = mapped_column(String(64))
    run_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (
        UniqueConstraint("session_id", "seq"),
        UniqueConstraint("session_id", "client_request_id"),
    )


class GenerationRun(Base):
    __tablename__ = "generation_runs"
    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(_sfk(), index=True)
    user_message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    assistant_message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    job_id: Mapped[uuid.UUID | None]
    answer_status: Mapped[str] = mapped_column(String(12), default="queued")  # queued/running/validated/refused/cancelled/failed
    analysis_status: Mapped[str] = mapped_column(String(12), default="not_started")
    refusal_reason: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(60))
    corpus_generation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("corpus_generations.id"))
    as_of_date: Mapped[date] = mapped_column(Date)
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    model_info: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    trace: Mapped[dict[str, Any]] = mapped_column(J, default=dict)  # prompt versions, chunk ids/scores, тайминги, проверки
    warnings: Mapped[list[Any]] = mapped_column(J, default=list)
    created_at: Mapped[datetime] = _ts()
    finished_at: Mapped[datetime | None]


class SessionFact(Base):
    __tablename__ = "session_facts"
    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(_sfk(), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None]
    key: Mapped[str] = mapped_column(String(80))
    value: Mapped[str | None] = mapped_column(String(10))  # yes | no | unknown
    statement: Mapped[str] = mapped_column(String(400))
    kind: Mapped[str] = mapped_column(String(20), default="user_fact")  # user_fact|assumption|learning_note|clarification|profile
    ongoing: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | superseded
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (Index("ix_fact_session_key", "session_id", "key"),)


# ───────────── корпус ─────────────
class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = _pk()
    identity_key: Mapped[str] = mapped_column(String(300), unique=True)
    doc_type: Mapped[str] = mapped_column(String(12))  # npa | textbook | soft_law
    title: Mapped[str] = mapped_column(String(500))
    short_name: Mapped[str | None] = mapped_column(String(80))
    act_number: Mapped[str | None] = mapped_column(String(60))
    act_date: Mapped[date | None] = mapped_column(Date)
    jurisdiction: Mapped[str] = mapped_column(String(8), default="RU")
    source_url: Mapped[str | None] = mapped_column(String(500))
    license_note: Mapped[str | None] = mapped_column(String(500))
    manifest_id: Mapped[str | None] = mapped_column(String(60))
    topics: Mapped[list[Any]] = mapped_column(J, default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded_at: Mapped[datetime | None]  # исключён из корпуса: не попадает в новые generation, прежние цитаты остаются целыми
    created_at: Mapped[datetime] = _ts()


class DocumentRevision(Base):
    __tablename__ = "document_revisions"
    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    revision_date: Mapped[date | None] = mapped_column(Date)
    edition: Mapped[str | None] = mapped_column(String(120))
    publication_date: Mapped[date | None] = mapped_column(Date)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    verified_at: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="ready")  # ready | failed
    corpus_state: Mapped[str] = mapped_column(String(12), default="imported")  # imported | indexed | verified
    checksum: Mapped[str] = mapped_column(String(64))
    text_sha256: Mapped[str] = mapped_column(String(64))
    original_name: Mapped[str] = mapped_column(String(200))
    original_path: Mapped[str] = mapped_column(String(400))
    normalized_path: Mapped[str] = mapped_column(String(400))
    mime: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    chunking_version: Mapped[str] = mapped_column(String(30), default="")
    uploaded_at: Mapped[datetime] = _ts()
    __table_args__ = (
        UniqueConstraint("document_id", "checksum"),
        UniqueConstraint("document_id", "revision_date"),
    )


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[uuid.UUID] = _pk()
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_revisions.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(12))  # article | part | point | section | text
    heading_path: Mapped[str] = mapped_column(String(500), default="")
    article: Mapped[str | None] = mapped_column(String(20))
    part: Mapped[str | None] = mapped_column(String(20))
    point: Mapped[str | None] = mapped_column(String(20))
    locator: Mapped[str] = mapped_column(String(200))
    page: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64))
    token_est: Mapped[int] = mapped_column(Integer)
    prev_id: Mapped[uuid.UUID | None]
    next_id: Mapped[uuid.UUID | None]
    topics: Mapped[list[Any]] = mapped_column(J, default=list)
    __table_args__ = (UniqueConstraint("revision_id", "ordinal"), Index("ix_chunk_rev_article", "revision_id", "article"))


class CorpusGeneration(Base):
    __tablename__ = "corpus_generations"
    id: Mapped[uuid.UUID] = _pk()
    seq: Mapped[int] = mapped_column(Integer, unique=True)
    status: Mapped[str] = mapped_column(String(12), default="building")  # building|ready|failed|retired
    fingerprint: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    fingerprint_hash: Mapped[str] = mapped_column(String(64))
    collection_name: Mapped[str] = mapped_column(String(120))
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    control_search: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _ts()
    activated_at: Mapped[datetime | None]


class GenerationRevision(Base):
    """Неизменяемый manifest generation: набор редакций и контрольная сумма их чанков."""

    __tablename__ = "generation_revisions"
    generation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("corpus_generations.id", ondelete="CASCADE"), primary_key=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_revisions.id"), primary_key=True)
    chunk_count: Mapped[int] = mapped_column(Integer)
    chunks_sha256: Mapped[str] = mapped_column(String(64))


class ChunkIndex(Base):
    """Чанк уже проиндексирован в коллекции этого embedding-пространства (повторное использование embeddings)."""

    __tablename__ = "chunk_index"
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    indexed_at: Mapped[datetime] = _ts()


class ImportDraft(Base):
    __tablename__ = "import_drafts"
    id: Mapped[uuid.UUID] = _pk()
    filename: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(400))
    normalized_path: Mapped[str | None] = mapped_column(String(400))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(12), default="parsing")  # parsing|ready|failed|confirmed
    error: Mapped[str | None] = mapped_column(String(500))
    preview: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    job_id: Mapped[uuid.UUID | None]
    revision_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = _ts()


# ───────────── источники ответов ─────────────
class Citation(Base):
    __tablename__ = "citations"
    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(_sfk(), index=True)
    marker: Mapped[str] = mapped_column(String(8))
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id"))
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_revisions.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    snapshot: Mapped[dict[str, Any]] = mapped_column(J, default=dict)  # реквизиты на момент ответа
    excerpt: Mapped[str] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (UniqueConstraint("run_id", "marker"),)


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"), index=True)
    block_id: Mapped[str] = mapped_column(String(20))
    citation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("citations.id", ondelete="CASCADE"))
    quote_verified: Mapped[bool | None] = mapped_column(Boolean)


# ───────────── портрет ─────────────
class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    sort: Mapped[int] = mapped_column(Integer, default=0)


class GraphNode(Base):
    __tablename__ = "graph_nodes"
    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(_sfk(), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # center|topic|question|norm|risk
    stable_key: Mapped[str] = mapped_column(String(200))
    label: Mapped[str] = mapped_column(String(400))
    data: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (UniqueConstraint("session_id", "stable_key"),)


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(_sfk(), index=True)
    src_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"))
    dst_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("graph_nodes.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # belongs_to|asks_about|cites|follow_up_of|evidences|grounded_in
    data: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (UniqueConstraint("session_id", "src_id", "dst_id", "kind"),)


# ───────────── риски ─────────────
class Risk(Base):
    __tablename__ = "risks"
    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(_sfk(), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="legal")  # legal | learning
    risk_type: Mapped[str] = mapped_column(String(60))
    scope_key: Mapped[str] = mapped_column(String(120))
    norm_family: Mapped[str] = mapped_column(String(120))
    dedup_key: Mapped[str] = mapped_column(String(320))
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(40))
    scenario: Mapped[str] = mapped_column(String(500), default="")
    conditions: Mapped[str] = mapped_column(Text, default="")
    consequences: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|in_progress|resolved|needs_clarification|not_applicable
    base_p: Mapped[int | None] = mapped_column(Integer)
    bonus_p: Mapped[int] = mapped_column(Integer, default=0)
    p: Mapped[int | None] = mapped_column(Integer)
    s: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[int | None] = mapped_column(Integer)
    level: Mapped[str | None] = mapped_column(String(10))
    p_reason: Mapped[str] = mapped_column(Text, default="")
    s_reason: Mapped[str] = mapped_column(Text, default="")
    clarification: Mapped[str | None] = mapped_column(Text)
    resolution_reason: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(20))  # user_message | owner
    resolution_pending: Mapped[str | None] = mapped_column(Text)  # неоднозначное «снято» — ждёт подтверждения
    methodology_version: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()
    __table_args__ = (UniqueConstraint("session_id", "dedup_key"),)


class RiskEvidence(Base):
    __tablename__ = "risk_evidence"
    id: Mapped[uuid.UUID] = _pk()
    risk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risks.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # base | bonus | context
    kind: Mapped[str] = mapped_column(String(20))  # fact | message | obligation | consequence
    ref_id: Mapped[uuid.UUID]
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (UniqueConstraint("risk_id", "role", "kind", "ref_id"),)


class RiskStatusEvent(Base):
    __tablename__ = "risk_status_events"
    id: Mapped[uuid.UUID] = _pk()
    risk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risks.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # created | status | score | evidence
    from_value: Mapped[str | None] = mapped_column(String(200))
    to_value: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(20), default="system")  # system | user_message | owner
    source_message_id: Mapped[uuid.UUID | None]
    at: Mapped[datetime] = _ts()


# ───────────── задания ─────────────
class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = _pk()
    type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)  # queued|running|succeeded|failed|cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_until: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]
    progress: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(J, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    created_at: Mapped[datetime] = _ts()
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    type: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    created_at: Mapped[datetime] = _ts()


# ───────────── экспорт, самопроверка, аудит ─────────────
class Export(Base):
    __tablename__ = "exports"
    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(_sfk(), index=True)
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued|running|ready|failed
    options: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    snapshot: Mapped[dict[str, Any]] = mapped_column(J, default=dict)  # версии/ID на момент снимка
    incomplete: Mapped[bool] = mapped_column(Boolean, default=False)
    file_path: Mapped[str | None] = mapped_column(String(400))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(500))
    job_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = _ts()


class Quiz(Base):
    __tablename__ = "quizzes"
    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(_sfk(), index=True)
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued | ready | failed
    questions: Mapped[list[Any]] = mapped_column(J, default=list)  # с ключом ответа: наружу отдаётся без него до попытки
    error: Mapped[str | None] = mapped_column(String(300))
    job_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = _ts()


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    id: Mapped[uuid.UUID] = _pk()
    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    answers: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
    results: Mapped[list[Any]] = mapped_column(J, default=list)
    created_at: Mapped[datetime] = _ts()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = _ts()
    actor: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(60), index=True)
    object_type: Mapped[str | None] = mapped_column(String(40))
    object_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(J, default=dict)


class AppState(Base):
    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(J, default=dict)
