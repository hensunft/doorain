"""Самопроверка студента: вопросы по источникам сессии; ошибки → учебные риски (не деловые)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.errors import ApiError
from ..db.models import Citation, ConsultationSession, Job, Quiz, QuizAttempt
from ..providers.base import ProviderError
from ..providers.registry import Providers
from ..schemas.llm import QuizResult
from . import jobs
from .rag import prompts
from .risks import engine


def session_citations(db: Session, s: ConsultationSession, limit: int = 12) -> list[Citation]:
    seen, out = set(), []
    for c in db.scalars(select(Citation).where(Citation.session_id == s.id).order_by(Citation.created_at.desc())):
        k = (c.revision_id, c.snapshot.get("locator"))
        if k not in seen:
            seen.add(k)
            out.append(c)
        if len(out) >= limit:
            break
    return out


def handle_generate(db: Session, job: Job, p: Providers, s: Settings) -> None:
    quiz = db.get(Quiz, uuid.UUID(job.payload["quiz_id"]))
    assert quiz
    sess = db.get(ConsultationSession, quiz.session_id)
    assert sess
    cites = session_citations(db, sess)
    if not cites:
        quiz.status, quiz.error = "failed", "В сессии ещё нет источников: задайте вопрос, чтобы получить материал для самопроверки"
        jobs.finish(db, job, "failed", error=quiz.error)
        db.commit()
        return
    by_id = {str(c.id): c for c in cites}
    ctx = {"role": sess.role, "citations": [{"id": str(c.id), "locator": c.snapshot["locator"], "title": c.snapshot["short_name"] or c.snapshot["act_title"], "excerpt": c.excerpt[:500]} for c in cites]}
    pr = prompts.render("analysis/quiz")
    err = ""
    for _ in range(2):
        try:
            res = QuizResult.model_validate(p.llm.json([{"role": "system", "content": pr.text}, {"role": "user", "content": f"<context>{json.dumps(ctx, ensure_ascii=False)}</context>" + (f"\nОшибка прошлой попытки: {err}" if err else "")}], QuizResult.model_json_schema(), num_predict=900))
            qs = []
            for i, q in enumerate(res.questions, 1):
                if q.citation_id not in by_id or q.answer_index >= len(q.options):
                    raise ValueError("неизвестный citation_id или answer_index")
                qs.append({"id": f"q{i}", **q.model_dump(), "citation_id": q.citation_id})
            quiz.questions, quiz.status = qs, "ready"
            jobs.finish(db, job, "succeeded")
            db.commit()
            return
        except ProviderError as e:
            err = f"{e.kind}: {e}"
            if e.kind != "invalid":
                break
        except (ValidationError, ValueError) as e:
            err = str(e)[:300]
    quiz.status, quiz.error = "failed", "Не удалось составить корректные вопросы. Повторите попытку позже"
    jobs.finish(db, job, "failed", error=err)
    db.commit()


def public_questions(quiz: Quiz) -> list[dict[str, Any]]:
    """Без ключа ответа и объяснений: они выдаются только вместе с результатом попытки."""
    return [{"id": q["id"], "question": q["question"], "options": q["options"], "concept": q["concept"]} for q in quiz.questions]


def submit(db: Session, s: ConsultationSession, quiz: Quiz, answers: dict[str, int]) -> QuizAttempt:
    if quiz.status != "ready":
        raise ApiError(409, "quiz_not_ready", "Самопроверка ещё не готова")
    results: list[dict[str, Any]] = []
    prev = db.scalars(select(QuizAttempt).join(Quiz, Quiz.id == QuizAttempt.quiz_id).where(Quiz.session_id == s.id)).all()
    for q in quiz.questions:
        chosen = answers.get(q["id"])
        if chosen is None:
            continue  # без ответа оценка не выставляется
        if not (isinstance(chosen, int) and 0 <= chosen < len(q["options"])):
            raise ApiError(422, "bad_answer", "Некорректный вариант ответа")
        ok = chosen == q["answer_index"]
        cit = db.get(Citation, uuid.UUID(q["citation_id"]))
        risk_id = None
        if not ok and cit:
            wrong = 1 + sum(1 for a in prev for r in a.results if r.get("concept") == q["concept"] and r.get("correct") is False)
            risk_id = str(engine.record_misconception(db, s, q["concept"], cit, q["severity"], wrong, f"Неверный ответ в самопроверке по понятию «{q['concept']}» (попыток с ошибкой: {wrong})").id)
        results.append({"question_id": q["id"], "concept": q["concept"], "correct": ok, "chosen": chosen, "correct_index": q["answer_index"], "explanation": q["explanation"], "citation_id": q["citation_id"], "citation": cit.snapshot if cit else None, "risk_id": risk_id})
    if not results:
        raise ApiError(422, "no_answers", "Ответьте хотя бы на один вопрос")
    att = QuizAttempt(quiz_id=quiz.id, answers=answers, results=results)
    db.add(att)
    s.version += 1
    db.commit()
    return att
