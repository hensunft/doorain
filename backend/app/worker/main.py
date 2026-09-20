"""Единственный worker: одна тяжёлая задача за раз на весь сервер. Задания переживают рестарт (lease/heartbeat в PostgreSQL)."""

from __future__ import annotations

import hashlib
import logging
import signal
import threading
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.util import now
from ..db.models import Export, GenerationRun, Job
from ..db.session import SessionLocal
from ..providers.registry import Providers, get_providers
from ..services import jobs, quiz
from ..services.exports.pdf import render_pdf
from ..services.ingestion import importer
from ..services.ingestion.indexer import Cancelled, CorpusEmpty, build_generation, set_state
from ..services.rag import pipeline

log = logging.getLogger("doorain.worker")


def _parse(db: Session, job: Job, p: Providers, s: Settings) -> None:
    importer.run_parse(db, s, uuid.UUID(job.payload["draft_id"]))
    jobs.finish(db, job, "succeeded")
    db.commit()


def _build(db: Session, job: Job, p: Providers, s: Settings) -> None:
    try:
        gen = build_generation(db, p, s, job, job.payload.get("note"))
        jobs.finish(db, job, "succeeded", {"generation_id": str(gen.id), "seq": gen.seq, "control_search": gen.control_search})
    except CorpusEmpty as e:
        jobs.finish(db, job, "failed", error=str(e))
    except Cancelled:
        jobs.finish(db, job, "cancelled")
    db.commit()


def _export(db: Session, job: Job, p: Providers, s: Settings) -> None:
    ex = db.get(Export, uuid.UUID(job.payload["export_id"]))
    assert ex
    ex.status = "running"
    db.commit()
    s.exports_dir.mkdir(parents=True, exist_ok=True)
    out = s.exports_dir / f"{ex.id}.pdf"
    render_pdf(ex.snapshot, out)
    data = out.read_bytes()
    ex.file_path, ex.sha256, ex.size, ex.status = str(out), hashlib.sha256(data).hexdigest(), len(data), "ready"
    jobs.finish(db, job, "succeeded")
    db.commit()


HANDLERS = {
    "chat_run": pipeline.handle_chat_run,
    "analysis_run": pipeline.handle_analysis_job,
    "parse_document": _parse,
    "build_generation": _build,
    "export_pdf": _export,
    "quiz_generate": quiz.handle_generate,
}


def run_one(p: Providers | None = None, s: Settings | None = None) -> bool:
    s, p = s or get_settings(), p or get_providers()
    db = SessionLocal()
    try:
        job = jobs.claim_next(db)
        if not job:
            return False
        try:
            HANDLERS[job.type](db, job, p, s)
        except Exception as e:  # noqa: BLE001
            log.exception("job failed id=%s type=%s", job.id, job.type)
            db.rollback()
            job = db.get(Job, job.id)
            assert job
            run = db.get(GenerationRun, job.run_id) if job.run_id else None
            if run and run.answer_status in ("queued", "running"):
                run.answer_status, run.error_code, run.finished_at = "failed", "internal_error", now()
            if run and run.analysis_status == "running":
                run.analysis_status = "failed"
            if job.attempts < job.max_attempts and job.type in ("parse_document", "build_generation", "export_pdf"):
                job.status, job.lease_until = "queued", None
            else:
                jobs.finish(db, job, "failed", error=f"{type(e).__name__}")
                if job.type == "export_pdf":
                    ex = db.get(Export, uuid.UUID(job.payload["export_id"]))
                    if ex:
                        ex.status, ex.error = "failed", "Не удалось сформировать PDF"
            db.commit()
        return True
    finally:
        db.close()


def run_pending(p: Providers | None = None, s: Settings | None = None, limit: int = 50) -> int:
    """Синхронно выполняет очередь (тесты, dev-режим)."""
    n = 0
    while n < limit and run_one(p, s):
        n += 1
    return n


def loop(stop: threading.Event | None = None) -> None:
    s = get_settings()
    stop = stop or threading.Event()
    last_hb = 0.0
    while not stop.is_set():
        if time.monotonic() - last_hb > 5:
            last_hb = time.monotonic()
            db = SessionLocal()
            try:
                set_state(db, "worker", {"heartbeat": datetime.now(UTC).isoformat()})
                db.commit()
            finally:
                db.close()
        if not run_one():
            stop.wait(s.worker_poll_s)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    log.info("worker started")
    loop(stop)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
