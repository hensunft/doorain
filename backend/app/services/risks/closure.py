"""Проверка ответа о закрытии риска. Модель оценивает смысл ответа; сервер проверяет цитату ответа, id норм и фактов,
версию риска и идемпотентность. Прямой PATCH «resolved» больше не закрывает риск (см. engine.set_status)."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.errors import ApiError
from ...core.util import norm_ws, now
from ...db.models import (
    Citation,
    ConsultationSession,
    Risk,
    RiskClosureAttempt,
    RiskEvidence,
    RiskStatusEvent,
    SessionFact,
)
from ...providers.base import ProviderError
from ...providers.registry import Providers
from ...schemas.llm import SCHEMA_VERSION, ClosureDecision
from ..ingestion.indexer import active_generation, applicable_revisions
from ..rag import prompts
from .engine import ACTIVE, _event, vacuous
from .scoring import METHODOLOGY_VERSION

log = logging.getLogger("doorain.closure")


def _norms(db: Session, r: Risk) -> tuple[list[dict[str, Any]], dict[str, Citation]]:
    """Нормы риска для модели: только цитаты ответа и только не архивные (источник не выведен из базы знаний)."""
    out: list[dict[str, Any]] = []
    by_id: dict[str, Citation] = {}
    for e in db.scalars(select(RiskEvidence).where(RiskEvidence.risk_id == r.id, RiskEvidence.kind.in_(("obligation", "consequence"))).order_by(RiskEvidence.created_at)):
        c = db.get(Citation, e.ref_id)
        if not c or c.snapshot.get("archived") or any(x is c for x in by_id.values()):
            continue
        nid = f"N{len(by_id) + 1}"
        sn = c.snapshot
        by_id[nid] = c
        out.append({"id": nid, "role": e.kind, "title": sn["short_name"] or sn["act_title"], "locator": sn["locator"], "revision": sn["revision_date"] or sn["edition"] or "дата не указана", "excerpt": c.excerpt[:500]})
    return out, by_id


def _call(p: Providers, ctx: dict[str, Any]) -> tuple[ClosureDecision, dict[str, Any]]:
    h = p.llm.health()
    if not h.ok:
        raise ProviderError("unavailable", h.detail)
    pr = prompts.render("analysis/closure")
    base = [{"role": "system", "content": pr.text}, {"role": "user", "content": f"<context>{json.dumps(ctx, ensure_ascii=False)}</context>"}]
    err = ""
    for _ in range(2):  # максимум один корректирующий повтор
        msgs = base + ([{"role": "user", "content": f"Предыдущий ответ отклонён: {err}. Верни корректный JSON по схеме."}] if err else [])
        try:
            return ClosureDecision.model_validate(p.llm.json(msgs, ClosureDecision.model_json_schema(), num_predict=600)), {"llm": h.info, "prompt": pr.meta}
        except ProviderError as e:
            if e.kind != "invalid":
                raise
            err = str(e)
        except ValidationError as e:
            err = str(e)[:300]
    raise ProviderError("invalid", "Модель не вернула корректное решение")


def _judge(d: ClosureDecision, answer: str, norms: dict[str, Citation], facts: dict[str, SessionFact], need_norm: bool) -> dict[str, Any]:
    """Серверная проверка решения модели. «Закрыть» допускается только при выполнении всех условий, иначе решение понижается до уточнения."""
    cites = [n for n in dict.fromkeys(d.citation_ids) if n in norms]
    used = [k for k in dict.fromkeys(d.used_fact_keys) if k in facts]
    quote = d.evidence_quote.strip()
    quote_ok = len(quote) >= 8 and norm_ws(quote) in norm_ws(answer)
    decision, kind, note = d.decision, d.resolution_kind, ""
    if decision == "close":
        if kind == "none" or d.confidence == "low":
            note = "уверенность недостаточна" if d.confidence == "low" else "не указан вид закрытия"
        elif not quote_ok:
            note = "решение не опирается на дословный фрагмент вашего ответа"
        elif need_norm and not cites:
            note = "решение не связано с нормой, на которой основан риск"
        elif (msg := vacuous(answer)) is not None:
            note = msg
        if note:
            decision = "clarify"
    if decision == "other_risk" and not (d.other_risk_hint or "").strip():
        decision, note = "clarify", "не названа иная проблема"
    question = (d.clarification_question or "").strip() or None
    if decision == "clarify" and not question:
        question = "Что именно сделано, где и когда это можно проверить?"
    verification = "corroborated" if decision == "close" and used else "user_claim"
    expl = d.explanation.strip() or "Пояснение не получено."
    if note and d.decision == "close":
        expl += f" Решение «закрыть» отклонено проверкой сервера: {note}."
    if decision == "other_risk":
        question = (d.other_risk_hint or "").strip()
    return {"decision": decision, "kind": kind if decision == "close" else None, "verification": verification if decision == "close" else None, "confidence": d.confidence, "explanation": expl, "question": question, "quote": quote if quote_ok else None, "cites": cites, "facts": used}


def _fail(db: Session, a: RiskClosureAttempt, r: Risk, msg: str, error: str) -> RiskClosureAttempt:
    a.state, a.explanation, a.error, a.finished_at = "failed", msg, error[:300], now()
    _event(db, r, "closure", None, None, f"Проверка закрытия не выполнена: {msg} Риск остаётся открытым.", "system")
    db.commit()
    return a


def propose(db: Session, p: Providers, s: Settings, risk: Risk, *, answer: str, source: str, key: str, expected_version: int, actor: str) -> RiskClosureAttempt:
    """Единая операция «предложить закрытие». До решения риск остаётся активным; повтор с тем же ключом возвращает сохранённый результат."""
    answer = answer.strip()
    prev = db.scalar(select(RiskClosureAttempt).where(RiskClosureAttempt.risk_id == risk.id, RiskClosureAttempt.idempotency_key == key))
    if prev:
        return _repeat(db, s, prev, answer)
    if risk.status not in ACTIVE:
        raise ApiError(409, "not_active", "Риск уже не активен: закрывать нечего. Обновите данные")
    if risk.version != expected_version:
        raise ApiError(409, "version_conflict", "Риск был изменён; обновите данные и повторите")
    window = now() - timedelta(seconds=s.ollama_timeout_s + 30)
    if db.scalar(select(RiskClosureAttempt.id).where(RiskClosureAttempt.risk_id == risk.id, RiskClosureAttempt.state == "pending", RiskClosureAttempt.created_at > window)):
        raise ApiError(409, "closure_in_progress", "Ответ по этому риску уже проверяется. Дождитесь результата")
    a = RiskClosureAttempt(
        risk_id=risk.id, idempotency_key=key, source=source, user_answer=answer, initiated_by=actor, risk_version=risk.version,
        model_info={"methodology": METHODOLOGY_VERSION, "schema_version": SCHEMA_VERSION, "provider": "test" if p.is_test else "ollama"},
    )
    db.add(a)
    try:
        db.commit()
    except IntegrityError:  # параллельный запрос с тем же ключом успел раньше
        db.rollback()
        prev = db.scalar(select(RiskClosureAttempt).where(RiskClosureAttempt.risk_id == risk.id, RiskClosureAttempt.idempotency_key == key))
        if prev:
            return _repeat(db, s, prev, answer)
        raise
    return _evaluate(db, p, s, risk, a, answer)


def _repeat(db: Session, s: Settings, prev: RiskClosureAttempt, answer: str) -> RiskClosureAttempt:
    if prev.user_answer != answer:
        raise ApiError(409, "idempotency_conflict", "Этот ключ запроса уже использован с другим ответом")
    if prev.state == "pending":
        if prev.created_at > now() - timedelta(seconds=s.ollama_timeout_s + 30):
            raise ApiError(409, "closure_in_progress", "Ответ по этому риску уже проверяется. Дождитесь результата")
        risk = db.get(Risk, prev.risk_id)
        assert risk
        return _fail(db, prev, risk, "Проверка не завершилась вовремя.", "abandoned")
    return prev


def _evaluate(db: Session, p: Providers, s: Settings, r: Risk, a: RiskClosureAttempt, answer: str) -> RiskClosureAttempt:
    sess = db.get(ConsultationSession, r.session_id)
    assert sess
    norms, by_id = _norms(db, r)
    need_norm = r.origin == "agent"
    if need_norm:
        gen = active_generation(db)
        if not gen or not applicable_revisions(db, gen, sess.as_of_date):
            return _fail(db, a, r, "База знаний пуста или в ней нет действующих на дату среза редакций, поэтому ответ нельзя сопоставить с нормой.", "corpus_empty")
        if not norms:
            return _fail(db, a, r, "Нормативное основание риска недоступно (источник выведен из базы знаний), поэтому ответ нельзя проверить.", "basis_unavailable")
    if (msg := vacuous(answer)) is not None:  # бессмысленный ответ не отправляется модели и не может закрыть риск
        return _finish(db, a, r, sess, {"decision": "clarify", "kind": None, "verification": None, "confidence": "high", "explanation": msg, "question": "Что именно сделано, где и когда это можно проверить?", "quote": None, "cites": [], "facts": []}, {}, {})
    rows = db.scalars(select(SessionFact).where(SessionFact.session_id == r.session_id, SessionFact.status == "active", SessionFact.kind == "user_fact").order_by(SessionFact.created_at.desc()).limit(20)).all()
    facts = {f.key: f for f in rows}
    hist = db.scalars(select(RiskStatusEvent).where(RiskStatusEvent.risk_id == r.id).order_by(RiskStatusEvent.at.desc()).limit(10)).all()
    ctx = {
        "risk": {"title": r.title, "scenario": r.scenario, "conditions": r.conditions, "consequences": r.consequences, "recommendation": r.recommendation, "status": r.status, "p": r.p, "s": r.s},
        "norms": norms,
        "session_facts": [{"key": f.key, "value": f.value, "statement": f.statement} for f in rows],
        "status_history": [{"at": e.at.isoformat(), "kind": e.kind, "from": e.from_value, "to": e.to_value, "reason": e.reason[:200], "author": e.author} for e in reversed(hist)],
        "user_answer": answer, "role": sess.role,
    }
    try:
        d, meta = _call(p, ctx)
    except ProviderError as e:
        log.warning("closure check failed risk=%s: %s %s", r.id, e.kind, e)
        text = "Языковая модель недоступна или не ответила вовремя." if e.kind in ("unavailable", "timeout", "missing_model") else "Модель не вернула корректное решение."
        return _fail(db, a, r, text, f"{e.kind}: {e}")
    return _finish(db, a, r, sess, _judge(d, answer, by_id, facts, need_norm), by_id, facts, meta)


def _finish(db: Session, a: RiskClosureAttempt, r: Risk, sess: ConsultationSession, j: dict[str, Any], by_id: dict[str, Citation], facts: dict[str, SessionFact], meta: dict[str, Any] | None = None) -> RiskClosureAttempt:
    a.decision, a.resolution_kind, a.verification, a.confidence = j["decision"], j["kind"], j["verification"], j["confidence"]
    a.explanation, a.question, a.quote = j["explanation"], j["question"], j["quote"]
    a.facts = [{"key": k, "statement": facts[k].statement} for k in j["facts"]]
    a.citation_ids = [str(by_id[n].id) for n in j["cites"]]
    a.model_info = {**a.model_info, **(meta or {})}
    a.finished_at = now()
    # Оптимистичная защита версии: если риск изменился за время проверки, результат не применяется.
    res = db.execute(update(Risk).where(Risk.id == r.id, Risk.version == a.risk_version, Risk.status.in_(ACTIVE)).values(version=Risk.version + 1))
    if res.rowcount != 1:  # type: ignore[attr-defined]
        a.state, a.applied = "stale", False
        a.explanation += " Риск изменился во время проверки, результат не применён — повторите."
        db.commit()
        return a
    db.refresh(r)
    a.state, a.applied = "decided", j["decision"] == "close"
    who = "closure_confirmed" if j["verification"] == "corroborated" else "closure_user_claim"
    basis = "подтверждено фактами сессии" if j["verification"] == "corroborated" else "со слов пользователя, независимой проверки нет"
    if j["decision"] == "close":
        new = "resolved" if j["kind"] == "remediated" else "not_applicable"
        _event(db, r, "status", r.status, new, f"Закрыт после проверки ответа ({basis}). {a.explanation} Ответ: «{a.user_answer[:300]}»", who)
        r.status, r.resolved_by, r.resolution_reason, r.closed_at, r.resolution_pending = new, who, a.user_answer[:1000], now(), None
    elif j["decision"] == "keep_open":
        _event(db, r, "closure", None, None, f"Проверка ответа: риск оставлен открытым. {a.explanation}", "system")
    elif j["decision"] == "clarify":
        r.resolution_pending = j["question"]
        _event(db, r, "closure", None, None, f"Проверка ответа: нужно уточнение. {a.explanation}", "system")
    else:
        _event(db, r, "closure", None, None, f"Проверка ответа: описана иная проблема — «{j['question']}»; новый риск создаётся только в диалоге по нормам базы знаний. {a.explanation}", "system")
    r.updated_at = now()
    sess.version += 1
    db.commit()
    return a
