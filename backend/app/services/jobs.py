"""Durable-задания в PostgreSQL: очередь, lease/heartbeat, повторы, отмена, идемпотентность, события."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.errors import ApiError
from ..core.util import now
from ..db.models import Job, JobEvent

TERMINAL_EVENTS = {"completed", "failed", "cancelled"}
ACTIVE = ("queued", "running")


def enqueue(
    db: Session,
    type_: str,
    payload: dict[str, Any],
    *,
    run_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    limit: bool = True,
) -> Job:
    s = get_settings()
    if idempotency_key:
        existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
        if existing:
            return existing
    if limit:
        active = db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(ACTIVE))) or 0
        if active >= s.max_active_jobs:
            raise ApiError(429, "queue_full", "Очередь заданий заполнена, повторите позже", headers={"Retry-After": "30"})
    job = Job(type=type_, payload=payload, run_id=run_id, idempotency_key=idempotency_key, max_attempts=s.job_max_attempts)
    db.add(job)
    db.flush()
    return job


def emit(db: Session, job: Job, type_: str, data: dict[str, Any] | None = None) -> JobEvent:
    ev = JobEvent(job_id=job.id, run_id=job.run_id, type=type_, data=data or {})
    db.add(ev)
    db.flush()
    return ev


def reap_expired(db: Session) -> int:
    """Просроченные lease: вернуть в очередь либо провалить при исчерпании попыток."""
    n = 0
    for job in db.scalars(select(Job).where(Job.status == "running", Job.lease_until < now())).all():
        if job.attempts >= job.max_attempts:
            finish(db, job, "failed", error="Исчерпаны попытки (worker не отвечал)")
            if job.run_id:
                emit(db, job, "failed", {"code": "worker_lost", "message": "Сбой обработчика, попытки исчерпаны"})
        else:
            job.status, job.lease_until = "queued", None
        n += 1
    db.commit()
    return n


def claim_next(db: Session) -> Job | None:
    reap_expired(db)
    q = select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(1).with_for_update(skip_locked=True)
    job = db.scalar(q)
    if not job:
        return None
    s = get_settings()
    job.status, job.attempts = "running", job.attempts + 1
    job.started_at = job.started_at or now()
    job.heartbeat_at = now()
    job.lease_until = now() + timedelta(seconds=s.job_lease_s)
    db.commit()
    return job


def heartbeat(db: Session, job: Job, progress: dict[str, Any] | None = None) -> bool:
    """Продлевает lease; возвращает True, если запрошена отмена."""
    s = get_settings()
    vals: dict[str, Any] = {"heartbeat_at": now(), "lease_until": now() + timedelta(seconds=s.job_lease_s)}
    if progress is not None:
        vals["progress"] = progress
    db.execute(update(Job).where(Job.id == job.id).values(**vals))
    db.commit()
    db.refresh(job)
    return bool(job.cancel_requested)


def is_cancelled(db: Session, job: Job) -> bool:
    db.refresh(job)
    return bool(job.cancel_requested)


def finish(db: Session, job: Job, status: str, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    job.status, job.result, job.error = status, result, (error or None) and error[:500]
    job.finished_at, job.lease_until = now(), None


def request_cancel(db: Session, job: Job) -> None:
    if job.status in ("succeeded", "failed", "cancelled"):
        return
    job.cancel_requested = True
    if job.status == "queued":
        finish(db, job, "cancelled")
        emit(db, job, "cancelled", {"message": "Отменено до начала обработки"})
    db.commit()


def events_after(db: Session, run_id: uuid.UUID, after: int, limit: int = 200) -> list[JobEvent]:
    return list(db.scalars(select(JobEvent).where(JobEvent.run_id == run_id, JobEvent.id > after).order_by(JobEvent.id).limit(limit)))


def max_event_id(db: Session, run_id: uuid.UUID) -> int:
    return db.scalar(select(func.max(JobEvent.id)).where(JobEvent.run_id == run_id)) or 0
