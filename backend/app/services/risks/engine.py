"""Накопительная таблица рисков: дедупликация, однократный бонус P, снятие/повторное открытие, история. Методика экспериментальная."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import ApiError
from ...core.util import now
from ...db.models import (
    Citation,
    ConsultationSession,
    Document,
    Message,
    Risk,
    RiskEvidence,
    RiskStatusEvent,
    SessionFact,
)
from ...schemas.llm import AnalysisResult, RiskCandidate
from ..portrait import graph
from .methodology import RISK_TYPES
from .scoring import METHODOLOGY_VERSION, final_p, level, score

ACTIVE = ("open", "in_progress")
MANUAL_STATUSES = ("open", "in_progress", "resolved")


def slug(s: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", "-", s.lower()).strip("-")[:60] or "general"


def _event(db: Session, r: Risk, kind: str, frm: str | None, to: str | None, reason: str, author: str = "system", msg_id: uuid.UUID | None = None) -> None:
    db.add(RiskStatusEvent(risk_id=r.id, kind=kind, from_value=frm, to_value=to, reason=reason[:1000], author=author, source_message_id=msg_id))


def _evidence(db: Session, r: Risk, role: str, kind: str, ref: uuid.UUID, note: str | None = None) -> bool:
    if db.scalar(select(RiskEvidence).where(RiskEvidence.risk_id == r.id, RiskEvidence.role == role, RiskEvidence.kind == kind, RiskEvidence.ref_id == ref)):
        return False
    db.add(RiskEvidence(risk_id=r.id, role=role, kind=kind, ref_id=ref, note=note))
    db.flush()
    return True


def _family(db: Session, cites: list[Citation]) -> str:
    d = db.get(Document, cites[0].document_id) if cites else None
    return (d.identity_key if d else "unknown")[:120]


def _label(r: Risk) -> str:
    return f"P{r.p}×S{r.s}={r.score}" if r.score else "не оценён"


def _recompute(db: Session, r: Risk) -> None:
    if r.base_p is None or r.s is None:
        r.p = r.score = r.level = None
        return
    ev = db.scalars(select(RiskEvidence).where(RiskEvidence.risk_id == r.id, RiskEvidence.kind == "fact", RiskEvidence.role.in_(("base", "bonus")))).all()
    facts = db.scalars(select(SessionFact).where(SessionFact.id.in_([e.ref_id for e in ev]))).all() if ev else []
    r.p = final_p(r.base_p, r.bonus_p, any(f.ongoing and f.status == "active" and f.value == "yes" for f in facts))
    r.score = score(r.p, r.s)
    r.level = level(r.score)


def apply_facts(db: Session, s: ConsultationSession, run_id: uuid.UUID, msg: Message, result: AnalysisResult) -> tuple[dict[str, SessionFact], dict[str, str]]:
    """Возвращает (актуальные факты по ключу, {key: 'new'|'superseding'}). Повтор того же значения — не новый факт."""
    by_key: dict[str, SessionFact] = {}
    novelty: dict[str, str] = {}
    for f in result.fact_candidates:
        cur = db.scalar(select(SessionFact).where(SessionFact.session_id == s.id, SessionFact.key == f.key, SessionFact.status == "active", SessionFact.kind == "user_fact").order_by(SessionFact.created_at.desc()))
        if cur and cur.value == f.value:
            by_key[f.key] = cur
            continue
        if cur:
            cur.status = "superseded"
            novelty[f.key] = "superseding"
        else:
            novelty[f.key] = "new"
        new = SessionFact(session_id=s.id, message_id=msg.id, run_id=run_id, key=f.key, value=f.value, statement=f.statement, kind="user_fact", ongoing=f.ongoing)
        db.add(new)
        db.flush()
        by_key[f.key] = new
    return by_key, novelty


def apply_analysis(db: Session, s: ConsultationSession, run_id: uuid.UUID, msg: Message, result: AnalysisResult, cites: dict[str, Citation]) -> dict[str, Any]:
    """Одна транзакция (коммит снаружи): факты → риски → граф. Идемпотентно по стабильным ключам."""
    changed: list[str] = []
    ignored = 0
    facts, novelty = apply_facts(db, s, run_id, msg, result)
    q = graph.question(db, s, msg, "answered", list(dict.fromkeys(result.topic_ids)))
    for marker in dict.fromkeys(result.citation_ids or list(cites)):
        c = cites.get(marker)
        if c:
            graph.link(db, s.id, q, graph.norm(db, s, c), "cites")
    for rel in result.relations:
        target = db.get(Message, uuid.UUID(rel.target_message_id)) if rel.target_message_id and re.fullmatch(r"[0-9a-f-]{36}", rel.target_message_id) else None
        if target and target.session_id == s.id and target.id != msg.id:
            tq = graph.node(db, s.id, "question", f"q:{target.id}", target.content[:140], {"message_id": str(target.id), "seq": target.seq})
            graph.link(db, s.id, q, tq, "follow_up_of", {"condition": rel.condition} if rel.kind == "conditional" and rel.condition else {})
    if s.role == "student":
        ignored = len(result.risk_candidates)  # у студента риски — только подтверждённые ошибки самопроверки
    else:
        for cand in result.risk_candidates:
            r = _apply_candidate(db, s, msg, cand, cites, facts, novelty, q)
            if r:
                changed.append(str(r.id))
    s.version += 1
    s.updated_at = now()
    return {"risks_changed": changed, "ignored_candidates": ignored, "facts": len(result.fact_candidates)}


def _clarify(db: Session, s: ConsultationSession, run_id_msg: Message, cand: RiskCandidate, text: str) -> None:
    key = f"clarify_{cand.risk_type}_{slug(cand.scope)}"[:80]
    if not db.scalar(select(SessionFact).where(SessionFact.session_id == s.id, SessionFact.key == key, SessionFact.status == "active")):
        db.add(SessionFact(session_id=s.id, message_id=run_id_msg.id, key=key, value=None, statement=text[:400], kind="clarification"))


def _apply_candidate(db: Session, s: ConsultationSession, msg: Message, cand: RiskCandidate, cites: dict[str, Citation], facts: dict[str, SessionFact], novelty: dict[str, str], qnode: graph.GraphNode) -> Risk | None:
    obl = [cites[m] for m in cand.obligation_citation_ids if m in cites]
    cons = [cites[m] for m in cand.consequence_citation_ids if m in cites]
    scope = slug(cand.scope)
    family = _family(db, obl)
    key = f"{cand.risk_type}|{scope}|{family}"
    existing = db.scalar(select(Risk).where(Risk.session_id == s.id, Risk.dedup_key == key))

    if cand.resolved_by_user or cand.resolution_ambiguous:  # снятие: норма-обязанность не нужна
        r = existing or db.scalar(select(Risk).where(Risk.session_id == s.id, Risk.risk_type == cand.risk_type, Risk.scope_key == scope))
        if r and r.status in ACTIVE:
            if cand.resolved_by_user and not cand.resolution_ambiguous:
                _event(db, r, "status", r.status, "resolved", "Снят по сообщению пользователя (не независимая проверка устранения)", "user_message", msg.id)
                r.status, r.resolved_by, r.resolution_reason, r.resolution_pending = "resolved", "user_message", "Снят по сообщению пользователя", None
            else:
                r.resolution_pending = "Из сообщения неясно, устранён ли риск. Подтвердите снятие вручную."
                _event(db, r, "evidence", None, None, "Неоднозначное сообщение о снятии — нужно подтверждение", "user_message", msg.id)
            r.version += 1
            r.updated_at = now()
            return r
        return None
    if not obl:  # без проверенного нормативного основания строка риска не создаётся → вопрос для уточнения
        _clarify(db, s, msg, cand, cand.needs_clarification or f"Нет нормативного основания в базе знаний для риска «{cand.title}»: уточните вопрос или загрузите нужный акт")
        return None

    basis = [facts[k] for k in cand.factual_basis_keys if k in facts and facts[k].value in ("yes", "no") and facts[k].status == "active"]
    p, sv = cand.proposed_p, cand.proposed_s
    clar = cand.needs_clarification
    p_reason, s_reason = cand.p_reason, cand.s_reason
    if p is None or sv is None:
        clar = clar or "Недостаточно фактов для оценки P/S: уточните обстоятельства"
    elif sv >= 3 and not cons:
        clar = "Нет источника последствий (санкции) в базе знаний: S≥3 не может быть обоснована. Загрузите нормы об ответственности либо уточните"
    elif p >= 4 and not basis:
        p, p_reason = 3, (p_reason + " P ограничена 3: нет подтверждённых фактов пользователя.").strip()
    scored = clar is None and p is not None and sv is not None

    if not existing:
        r = Risk(
            session_id=s.id, kind="legal", risk_type=cand.risk_type, scope_key=scope, norm_family=family, dedup_key=key, title=cand.title[:300],
            category=RISK_TYPES[cand.risk_type][1], scenario=cand.scope[:500], conditions=cand.applicable_conditions, consequences=cand.consequences,
            recommendation=cand.recommendation, status="open" if scored else "needs_clarification", clarification=clar, methodology_version=METHODOLOGY_VERSION,
            base_p=p if scored else None, s=sv if scored else None, p_reason=p_reason, s_reason=s_reason,
        )
        db.add(r)
        db.flush()
        _attach(db, r, msg, obl, cons, basis, "base")
        _recompute(db, r)
        _event(db, r, "created", None, _label(r), "Риск создан по методологии " + METHODOLOGY_VERSION, "system", msg.id)
    else:
        r = existing
        before = _label(r)
        if r.status == "needs_clarification" and scored:
            r.status, r.base_p, r.s, r.clarification, r.p_reason, r.s_reason = "open", p, sv, None, p_reason, s_reason
            _attach(db, r, msg, obl, cons, basis, "base")
        elif scored:
            known = {e.ref_id for e in db.scalars(select(RiskEvidence).where(RiskEvidence.risk_id == r.id, RiskEvidence.kind == "fact"))}
            known_keys = {f.key for f in db.scalars(select(SessionFact).where(SessionFact.id.in_(known)))} if known else set()
            new = [f for f in basis if f.id not in known]
            independent = [f for f in new if f.key not in known_keys and novelty.get(f.key) == "new"]
            superseding = [f for f in new if novelty.get(f.key) == "superseding" or f.key in known_keys]
            if superseding or (independent and p is not None and p < (r.base_p or 0)):
                r.base_p, r.bonus_p, r.p_reason = p, 0, p_reason or r.p_reason
                _attach(db, r, msg, obl, cons, superseding + independent, "base")
            elif independent and r.bonus_p == 0:
                r.bonus_p = 1  # однократный бонус за новый независимый факт; отдельно от базовых evidence
                for f in independent:
                    _evidence(db, r, "bonus", "fact", f.id, "Независимый подтверждающий факт")
                _attach(db, r, msg, obl, cons, [], "context")
            else:
                _attach(db, r, msg, obl, cons, [], "context")  # повтор/перефразирование P не меняет
            if sv != r.s:
                r.s, r.s_reason = sv, s_reason or r.s_reason
            if r.status == "resolved" and (independent or superseding):
                _event(db, r, "status", "resolved", "open", "Повторно открыт: получены новые факты", "system", msg.id)
                r.status, r.resolved_by, r.resolution_reason = "open", None, None
        else:
            _attach(db, r, msg, obl, cons, [], "context")
        _recompute(db, r)
        if _label(r) != before:
            _event(db, r, "score", before, _label(r), (p_reason or s_reason or "Пересчёт по новым данным"), "system", msg.id)
        for attr, val in (("recommendation", cand.recommendation), ("consequences", cand.consequences), ("conditions", cand.applicable_conditions)):
            if val and not getattr(r, attr):
                setattr(r, attr, val)
        r.version += 1
        r.updated_at = now()
    rn = graph.risk_node(db, s, r)
    graph.link(db, s.id, qnode, rn, "evidences")
    for c in obl:
        graph.link(db, s.id, rn, graph.norm(db, s, c), "grounded_in")
    return r


def _attach(db: Session, r: Risk, msg: Message, obl: list[Citation], cons: list[Citation], facts: list[SessionFact], role: str) -> None:
    for f in facts:
        _evidence(db, r, role, "fact", f.id)
    for c in obl:
        _evidence(db, r, "context", "obligation", c.id)
    for c in cons:
        _evidence(db, r, "context", "consequence", c.id)
    _evidence(db, r, "context", "message", msg.id)


def set_status(db: Session, r: Risk, new: str, reason: str, expected_version: int, author: str = "owner") -> Risk:
    if r.version != expected_version:
        raise ApiError(409, "version_conflict", "Риск был изменён; обновите данные и повторите")
    if new not in MANUAL_STATUSES:
        raise ApiError(422, "bad_status", "Статус: open, in_progress или resolved")
    if not reason.strip():
        raise ApiError(422, "reason_required", "Укажите причину изменения статуса")
    if r.status == "needs_clarification":
        raise ApiError(409, "needs_clarification", "Риск ожидает уточнения фактов и не оценён: смена статуса недоступна")
    _event(db, r, "status", r.status, new, reason, author)
    r.status = new
    if new == "resolved":
        r.resolved_by, r.resolution_reason = "owner", reason
    else:
        r.resolved_by = r.resolution_reason = None
    r.resolution_pending = None
    r.version += 1
    r.updated_at = now()
    return r


def record_misconception(db: Session, s: ConsultationSession, concept: str, cit: Citation, severity: int, wrong_attempts: int, note: str) -> Risk:
    """Учебный риск: подтверждённая ошибка в самопроверке. НПА подтверждает верное понимание; P/S — педагогическая рубрика."""
    scope, family = slug(concept), _family(db, [cit])
    key = f"misconception|{scope}|{family}"
    p = 2 if wrong_attempts <= 1 else 4
    r = db.scalar(select(Risk).where(Risk.session_id == s.id, Risk.dedup_key == key))
    if not r:
        r = Risk(session_id=s.id, kind="learning", risk_type="misconception", scope_key=scope, norm_family=family, dedup_key=key, title=f"Ошибка понимания: {concept}"[:300], category=RISK_TYPES["misconception"][1], scenario=concept[:500], status="open", base_p=p, s=severity, p_reason=note, s_reason="Педагогическая рубрика: важность понятия для темы", methodology_version=METHODOLOGY_VERSION, recommendation="Повторите норму по источнику и пройдите самопроверку ещё раз")
        db.add(r)
        db.flush()
        _recompute(db, r)
        _event(db, r, "created", None, _label(r), note, "system")
        _evidence(db, r, "context", "obligation", cit.id, "Норма подтверждает верное понимание")
    else:
        before = _label(r)
        r.base_p, r.p_reason = max(r.base_p or 0, p), note
        if r.status == "resolved":
            r.status = "open"
            _event(db, r, "status", "resolved", "open", "Повторная ошибка в самопроверке", "system")
        _recompute(db, r)
        if _label(r) != before:
            _event(db, r, "score", before, _label(r), note)
        r.version += 1
    rn = graph.risk_node(db, s, r)
    graph.link(db, s.id, rn, graph.norm(db, s, cit), "grounded_in")
    return r
