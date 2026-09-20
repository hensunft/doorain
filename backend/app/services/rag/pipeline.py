"""Путь одного сообщения. Исполняется worker'ом. Все события пишутся в job_events (replay для SSE)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...core.config import Settings
from ...core.util import est_tokens, now
from ...db.models import (
    BusinessProfile,
    Citation,
    ClaimEvidence,
    ConsultationSession,
    CorpusGeneration,
    DocumentRevision,
    GenerationRun,
    Job,
    Message,
    Risk,
    SessionFact,
)
from ...providers.base import TRUNCATED_MARK, ProviderError
from ...providers.registry import Providers
from ...schemas.llm import AnalysisResult, Classification
from .. import jobs
from ..ingestion.indexer import Cancelled, applicable_revisions, fp_hash
from ..portrait import graph
from ..risks import engine
from ..risks.methodology import DEMO_NOTICE, RISK_TYPES
from . import prompts, verify
from .retrieval import retrieve

log = logging.getLogger("doorain.pipeline")

REFUSALS = {
    "out_of_scope": "Вопрос выходит за пределы права высоких технологий, поэтому я не отвечаю на него. Задайте вопрос по IT-праву: персональные данные, защита информации, КИИ, ИИ, электронная подпись, интеллектуальная собственность в IT, интернет-реклама, цифровые активы, ответственность.",
    "corpus_empty": "База знаний пуста, поэтому ответить по источникам невозможно. Загрузите нормативные документы в разделе «База знаний».",
    "revision_unavailable": "В базе знаний нет редакции документов, действующей на выбранную дату правового среза. Загрузите нужную редакцию или измените дату среза.",
    "insufficient_grounds": "В базе знаний не найдено достаточных оснований для ответа на этот вопрос. Я не отвечаю «по памяти». Уточните вопрос или загрузите подходящие источники; для оценки конкретной ситуации обратитесь к юристу.",
    "needs_clarification": "Для ответа нужно уточнение.",
    "index_incompatible": "Индекс построен другой моделью embeddings или другой версией разбиения, поэтому поиск заблокирован до переиндексации (База знаний → «Переиндексировать»). Чужие векторы не используются.",
}
PARTIAL_NOTICE = "Оснований в базе знаний недостаточно для уверенного ответа: найденные фрагменты соответствуют вопросу лишь частично. Ниже — только то, что удалось подтвердить источниками; проверьте применимость и при необходимости загрузите более точные документы."
FAIL_TEXT = {"model_unavailable": "Локальная модель сейчас недоступна. Ответ не сформирован; облачный сервис не используется.", "internal_error": "Внутренняя ошибка при обработке запроса."}


class _Emit:
    def __init__(self, db: Session, job: Job):
        self.db, self.job = db, job

    def __call__(self, type_: str, data: dict[str, Any] | None = None) -> None:
        jobs.emit(self.db, self.job, type_, data or {})
        self.db.commit()


def _block(idx: int, kind: str, text: str, cits: list[Citation], markers: list[str], state: str = "verified", reason: str | None = None) -> dict[str, Any]:
    return {"id": f"b{idx}", "version": 1, "kind": kind, "text": text, "citation_ids": [str(c.id) for c in cits], "markers": markers, "state": state, "reason": reason}


def _snapshot(h: Any) -> dict[str, Any]:
    d, r, c = h.document, h.revision, h.chunk
    return {
        "act_title": d.title, "short_name": d.short_name, "act_number": d.act_number, "act_date": d.act_date.isoformat() if d.act_date else None, "doc_type": d.doc_type,
        "revision_date": r.revision_date.isoformat() if r.revision_date else None, "edition": r.edition, "effective_from": r.effective_from.isoformat() if r.effective_from else None,
        "effective_to": r.effective_to.isoformat() if r.effective_to else None, "verified_at": r.verified_at.isoformat() if r.verified_at else None,
        "locator": c.locator, "article": c.article, "part": c.part, "point": c.point, "page": c.page, "heading_path": c.heading_path,
        "is_demo": d.is_demo, "source_url": d.source_url, "checksum": r.checksum,
    }


def _profile_text(db: Session, s: ConsultationSession) -> str:
    p = db.scalar(select(BusinessProfile).where(BusinessProfile.session_id == s.id).order_by(BusinessProfile.created_at.desc()))
    if not p or not p.data:
        return "не указан"
    names = {"sphere": "сфера", "has_site_or_app": "сайт/приложение", "processes_pd": "работа с ПДн", "mailings": "рассылки", "servers_location": "размещение серверов"}
    return "; ".join(f"{names.get(k, k)}: {v}" for k, v in p.data.items() if v not in (None, ""))


def _history(db: Session, s: ConsultationSession, before_seq: int, n: int = 6) -> list[dict[str, str]]:
    rows = db.scalars(select(Message).where(Message.session_id == s.id, Message.seq < before_seq).order_by(Message.seq.desc()).limit(n)).all()
    out = []
    for m in reversed(rows):
        if m.role == "user":
            out.append({"message_id": str(m.id), "role": "user", "text": m.content[:300]})
        elif m.blocks:
            txt = " ".join(b["text"] for b in m.blocks if b.get("state") == "verified" and b["kind"] in ("claim", "fact", "assumption"))[:400]
            if txt:
                out.append({"message_id": str(m.id), "role": "assistant", "text": txt})
    return out


def handle_chat_run(db: Session, job: Job, p: Providers, s: Settings) -> None:
    run = db.get(GenerationRun, job.run_id)
    assert run is not None
    emit = _Emit(db, job)
    if run.answer_status in ("validated", "refused"):  # ответ уже готов (повтор после сбоя на аналитике)
        _finish_after_answer(db, job, p, s, run, emit)
        return
    if run.answer_status == "running":  # предыдущая попытка оборвалась: чистим частичное
        db.execute(delete(ClaimEvidence).where(ClaimEvidence.run_id == run.id))
        db.execute(delete(Citation).where(Citation.run_id == run.id))
        emit("status", {"stage": "restarted", "message": "Обработка перезапущена после сбоя"})
    run.answer_status = "running"
    db.commit()
    session = db.get(ConsultationSession, run.session_id)
    msg = db.get(Message, run.user_message_id)
    assert session and msg
    t0 = time.monotonic()
    try:
        _answer(db, job, p, s, run, session, msg, emit, t0)
    except Cancelled:
        _cancel(db, job, run, session, msg, emit)
        return
    except ProviderError as e:
        _fail(db, job, run, session, msg, emit, "model_unavailable", f"{e.kind}: {e}")
        return
    except Exception as e:  # noqa: BLE001
        log.exception("chat_run failed run=%s", run.id)
        _fail(db, job, run, session, msg, emit, "internal_error", type(e).__name__)
        return
    _finish_after_answer(db, job, p, s, run, emit)


def _finish_after_answer(db: Session, job: Job, p: Providers, s: Settings, run: GenerationRun, emit: _Emit) -> None:
    if run.answer_status == "validated" and run.analysis_status in ("not_started", "failed", "running", "cancelled"):
        try:
            run_analysis(db, job, p, s, run, emit)
        except Cancelled:
            run.analysis_status = "cancelled"
            db.commit()
            emit("cancelled", {"phase": "analysis", "message": "Аналитика отменена; проверенный ответ сохранён"})
            jobs.finish(db, job, "cancelled")
            db.commit()
            return
        except Exception:  # noqa: BLE001 — сбой аналитики не должен портить проверенный ответ и блокировать сессию
            log.exception("analysis failed run=%s", run.id)
            db.rollback()
            run.analysis_status = "failed"
            db.commit()
            emit("status", {"stage": "analysis_failed", "message": "Аналитика не выполнена; проверенный ответ сохранён. Можно повторить анализ."})
    emit("completed", {"answer_status": run.answer_status, "analysis_status": run.analysis_status, "refusal_reason": run.refusal_reason})
    run.finished_at = now()
    jobs.finish(db, job, "succeeded", {"answer_status": run.answer_status, "analysis_status": run.analysis_status})
    db.commit()


def _refuse(db: Session, job: Job, run: GenerationRun, session: ConsultationSession, msg: Message, emit: _Emit, reason: str, text: str | None = None, topics: list[str] | None = None) -> None:
    blk = _block(1, "refusal", text or REFUSALS[reason], [], [])
    emit("answer_delta", {"block": blk})
    asst = Message(session_id=session.id, seq=msg.seq + 1, role="assistant", content=blk["text"], blocks=[blk], run_id=run.id)
    db.add(asst)
    db.flush()
    run.assistant_message_id, run.answer_status, run.refusal_reason = asst.id, "refused", reason
    graph.question(db, session, msg, "refused", topics or [])  # вопрос виден в слепке; норм и рисков при отказе нет
    session.version += 1
    db.commit()
    emit("answer_completed", {"message_id": str(asst.id), "blocks": [blk], "answer_status": "refused", "refusal_reason": reason, "warnings": []})
    emit("portrait_updated", {"question_result": "refused"})


def _cancel(db: Session, job: Job, run: GenerationRun, session: ConsultationSession, msg: Message, emit: _Emit) -> None:
    db.rollback()
    blocks = _saved_blocks.pop(run.id, [])
    blocks.append(_block(len(blocks) + 1, "notice", "Генерация остановлена пользователем. Ответ неполный и не используется в слепке и рисках.", [], [], "unsupported"))
    asst = Message(session_id=session.id, seq=msg.seq + 1, role="assistant", content="", blocks=blocks, run_id=run.id)
    db.add(asst)
    db.flush()
    run.assistant_message_id, run.answer_status, run.analysis_status, run.finished_at = asst.id, "cancelled", "not_started", now()
    graph.question(db, session, msg, "cancelled", [])
    session.version += 1
    jobs.finish(db, job, "cancelled")
    db.commit()
    emit("cancelled", {"message_id": str(asst.id), "blocks": blocks})


def _fail(db: Session, job: Job, run: GenerationRun, session: ConsultationSession, msg: Message, emit: _Emit, code: str, detail: str) -> None:
    db.rollback()
    _saved_blocks.pop(run.id, None)
    blk = _block(1, "notice", FAIL_TEXT.get(code, FAIL_TEXT["internal_error"]), [], [], "unsupported")
    asst = Message(session_id=session.id, seq=msg.seq + 1, role="assistant", content=blk["text"], blocks=[blk], run_id=run.id)
    db.add(asst)
    db.flush()
    run.assistant_message_id, run.answer_status, run.error_code, run.finished_at = asst.id, "failed", code, now()
    run.trace = {**(run.trace or {}), "error": detail[:300]}
    graph.question(db, session, msg, "failed", [])
    session.version += 1
    jobs.finish(db, job, "failed", error=code)
    db.commit()
    emit("failed", {"code": code, "message": blk["text"], "message_id": str(asst.id)})


_saved_blocks: dict[uuid.UUID, list[dict[str, Any]]] = {}  # частичные блоки текущего run (только в памяти worker'а)


def _answer(db: Session, job: Job, p: Providers, s: Settings, run: GenerationRun, session: ConsultationSession, msg: Message, emit: _Emit, t0: float) -> None:
    trace: dict[str, Any] = {"prompts": [], "stages_ms": {}}
    h = p.llm.health()
    if not h.ok:
        raise ProviderError("unavailable", h.detail)
    run.model_info = {**h.info, "provider": "test" if p.is_test else "ollama", "num_ctx": s.ollama_num_ctx, "num_predict": s.ollama_num_predict, "embedder": p.embedder.fingerprint(), "reranker": p.reranker.name(), "thresholds": {"min_rerank_score": s.min_rerank_score, "source": s.threshold_source}}
    emit("status", {"stage": "classifying", "message": "Определяю тему вопроса"})
    hist = _history(db, session, msg.seq)
    profile = _profile_text(db, session)
    t1 = time.monotonic()
    cr = prompts.render("analysis/classify")
    ctx = json.dumps({"question": msg.content, "history": [h_["text"] for h_ in hist], "profile": profile}, ensure_ascii=False)
    try:
        cls = Classification.model_validate(p.llm.json([{"role": "system", "content": cr.text}, {"role": "user", "content": f"<context>{ctx}</context>"}], Classification.model_json_schema(), num_predict=300))
    except (ValidationError, ProviderError) as e:
        if isinstance(e, ProviderError) and e.kind in ("unavailable", "timeout", "missing_model"):
            raise
        cls = Classification(in_scope=True, topics=[], rewritten_query=msg.content[:400])
        trace["classification_fallback"] = True
    trace["prompts"].append({**cr.meta, "vars": {"question": msg.content, "history_ids": [h_["message_id"] for h_ in hist]}})
    trace["classification"] = cls.model_dump()
    trace["stages_ms"]["classify"] = int((time.monotonic() - t1) * 1000)
    run.trace = dict(trace)  # копия: JSON-колонка не отслеживает мутацию на месте
    if jobs.is_cancelled(db, job):
        raise Cancelled()
    if cls.clarification and cls.in_scope:
        return _refuse(db, job, run, session, msg, emit, "needs_clarification", cls.clarification, cls.topics)
    gen = db.get(CorpusGeneration, run.corpus_generation_id) if run.corpus_generation_id else None
    revs = applicable_revisions(db, gen, run.as_of_date) if gen else []
    corpus_problem = None
    if not gen or not db.scalar(select(DocumentRevision.id).where(DocumentRevision.status == "ready").limit(1)):
        corpus_problem = "corpus_empty"
    elif not revs:
        corpus_problem = "revision_unavailable"
    elif fp_hash(p.embedder.fingerprint()) != gen.fingerprint_hash:  # совпадение размерности не означает совместимость векторов
        corpus_problem = "index_incompatible"
    if corpus_problem or gen is None:  # без корпуса проверить вердикт классификатора нечем
        return _refuse(db, job, run, session, msg, emit, (corpus_problem or "corpus_empty") if cls.in_scope else "out_of_scope", topics=cls.topics)
    emit("status", {"stage": "retrieval", "message": "Ищу нормы в базе знаний"})
    retr = retrieve(db, p, s, gen, revs, cls.rewritten_query or msg.content, msg.content)
    trace["retrieval"] = {"timings_ms": retr.timings_ms, "considered": retr.considered, "reason": retr.reason, "scores": retr.scores, "generation_id": str(gen.id), "query": cls.rewritten_query, "confidence": retr.confidence}
    # Вердикт «вне области» — мягкий: он снимается только сильными нормами, иначе ловушки перестали бы отклоняться.
    override = not cls.in_scope and retr.sufficient and (retr.best_score or 0.0) >= s.min_rerank_score + s.scope_override_min_score
    if not cls.in_scope and not override:
        run.trace = dict(trace)
        return _refuse(db, job, run, session, msg, emit, "out_of_scope", topics=cls.topics)
    if override:
        trace["scope_override"] = {"best_score": round(retr.best_score or 0.0, 4), "min": s.min_rerank_score + s.scope_override_min_score}
    run.trace = dict(trace)  # копия: JSON-колонка не отслеживает мутацию на месте
    if not retr.sufficient:
        return _refuse(db, job, run, session, msg, emit, "insufficient_grounds", topics=cls.topics)
    hits = retr.selected
    role_prompt = prompts.render(f"{session.role}/answer", profile=profile)
    rules = prompts.render("common/rules", as_of=run.as_of_date.isoformat())
    hist_txt = "\n".join(f"{'Пользователь' if x['role'] == 'user' else 'Ассистент'}: {x['text']}" for x in hist[-4:]) or "нет"
    system = rules.text + "\n\n" + role_prompt.text
    fixed = est_tokens(system + hist_txt + msg.content, s.chars_per_token) + s.ollama_num_predict + 120
    hits_used: list[Any] = []
    used = fixed
    for hit in hits:  # бюджет контекста: целые фрагменты, без обрезки норм
        need = est_tokens(hit.chunk.text, s.chars_per_token) + 40
        if used + need > s.ollama_num_ctx and hits_used:
            continue
        hits_used.append(hit)
        used += need
    trace["budget"] = {"num_ctx": s.ollama_num_ctx, "est_prompt_tokens": used, "sources": len(hits_used), "dropped_for_budget": len(hits) - len(hits_used)}
    cits: list[Citation] = []
    for i, hit in enumerate(hits_used, 1):
        c = Citation(run_id=run.id, session_id=session.id, marker=f"C{i}", chunk_id=hit.chunk.id, revision_id=hit.revision.id, document_id=hit.document.id, snapshot=_snapshot(hit), excerpt=hit.chunk.text, score=hit.rerank, rank=i)
        db.add(c)
        cits.append(c)
    db.flush()
    src_txt = "\n".join(
        f"[{c.marker}] {c.snapshot['short_name'] or c.snapshot['act_title']}, {c.snapshot['locator']} (ред. {c.snapshot['revision_date'] or c.snapshot['edition'] or 'дата не указана'})\n{c.excerpt}\n" for c in cits
    )
    user = f"ИСТОЧНИКИ:\n<<<SOURCES\n{src_txt}\n<<<END_SOURCES\n\nИСТОРИЯ ДИАЛОГА:\n{hist_txt}\n\nВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{msg.content}"
    trace["prompts"] += [{**rules.meta, "vars": {"as_of": run.as_of_date.isoformat()}}, {**role_prompt.meta, "vars": {"profile": profile}}]
    trace["sources"] = {c.marker: str(c.chunk_id) for c in cits}
    run.trace = dict(trace)  # копия: JSON-колонка не отслеживает мутацию на месте
    db.commit()
    emit("status", {"stage": "generation", "message": "Формирую ответ (проверка ссылок по абзацам)"})
    sources = {c.marker: c.excerpt for c in cits}
    by_marker = {c.marker: c for c in cits}
    blocks: list[dict[str, Any]] = []
    _saved_blocks[run.id] = blocks
    state: dict[str, Any] = {"first_ms": None, "unsupported": 0, "truncated": False}
    if retr.confidence == "partial":  # мягкая деградация вместо отказа: отвечаем, но оговариваем неполноту оснований
        blocks.append(_block(1, "notice", PARTIAL_NOTICE, [], [], "unsupported"))
        run.warnings = [*run.warnings, "Ответ дан при неполных основаниях: найденные фрагменты лишь частично соответствуют вопросу"]
        emit("answer_delta", {"block": blocks[0], "provisional": True})

    def push(para: str) -> None:
        ck = verify.check_paragraph(para, sources)
        if ck.state == "unsupported":
            state["unsupported"] += 1
            if any(b["kind"] == "notice" and b["state"] == "unsupported" for b in blocks):
                return
        blk = _block(len(blocks) + 1, ck.kind, ck.text, [by_marker[m] for m in ck.markers], ck.markers, ck.state, ck.reason)
        blocks.append(blk)
        for m in ck.markers:
            db.add(ClaimEvidence(run_id=run.id, block_id=blk["id"], citation_id=by_marker[m].id, quote_verified=ck.quote_checked))
        if state["first_ms"] is None:
            state["first_ms"] = int((time.monotonic() - t0) * 1000)
        emit("answer_delta", {"block": blk, "provisional": True})

    buf, last_hb, gen_t = "", time.monotonic(), time.monotonic()
    raw_parts: list[str] = []  # фактическая выдача модели — отдельно от финального (проверенного) результата
    for piece in p.llm.stream([{"role": "system", "content": system}, {"role": "user", "content": user}]):
        if piece == TRUNCATED_MARK:
            state["truncated"] = True
            continue
        raw_parts.append(piece)
        buf += piece
        done, buf = verify.split_paragraphs(buf)
        for para in done:
            push(para)
        if time.monotonic() - last_hb > 1.0:
            last_hb = time.monotonic()
            if jobs.heartbeat(db, job, {"stage": "generation", "blocks": len(blocks)}):
                raise Cancelled()
    if buf.strip() and not state["truncated"]:
        push(buf.strip())
    if state["truncated"]:
        run.warnings = [*run.warnings, "Ответ обрезан лимитом длины генерации; последний неполный абзац отброшен"]
        blocks.append(_block(len(blocks) + 1, "notice", "Ответ достиг лимита длины и может быть неполным.", [], [], "unsupported"))
        emit("answer_delta", {"block": blocks[-1], "provisional": True})
    trace["stages_ms"]["generation"] = int((time.monotonic() - gen_t) * 1000)
    trace["ttft_ms"], trace["unsupported_blocks"] = state["first_ms"], state["unsupported"]
    trace["raw_answer"] = "".join(raw_parts)[:20000]
    run.trace = dict(trace)
    if jobs.is_cancelled(db, job):
        raise Cancelled()
    # финальная проверка: лексическая опора; при полном провале — отказ
    emit("status", {"stage": "validation", "message": "Проверяю опору утверждений в источниках"})
    for b in blocks:
        if b["kind"] == "claim" and b["state"] == "verified" and not verify.lexical_support(b["text"], b["markers"], sources):
            b["version"] += 1
            b["kind"], b["text"], b["state"], b["reason"] = "notice", verify.NOTICE_UNSUPPORTED, "unsupported", "low_lexical_support"
            db.execute(delete(ClaimEvidence).where(ClaimEvidence.run_id == run.id, ClaimEvidence.block_id == b["id"]))
            b["citation_ids"], b["markers"] = [], []
            emit("answer_block_replaced", {"block": b})
    if not any(b["kind"] == "claim" and b["state"] == "verified" for b in blocks):
        for b in blocks:
            emit("answer_block_replaced", {"block": {**b, "version": b["version"] + 1, "removed": True}})
        db.execute(delete(ClaimEvidence).where(ClaimEvidence.run_id == run.id))
        db.execute(delete(Citation).where(Citation.run_id == run.id))
        _saved_blocks.pop(run.id, None)
        return _refuse(db, job, run, session, msg, emit, "insufficient_grounds", topics=cls.topics)
    cited = {m for b in blocks for m in b["markers"]}
    for c in cits:
        if c.marker not in cited:  # неиспользованные источники не хранятся как «цитаты ответа»
            db.execute(delete(ClaimEvidence).where(ClaimEvidence.citation_id == c.id))
    notice, warns = _currency_notice([c for c in cits if c.marker in cited])
    if cls.mixed:
        warns.append("Вопрос частично вне IT-права: ответ ограничен покрытой частью")
    blocks.append(_block(len(blocks) + 1, "currency", notice, [c for c in cits if c.marker in cited], sorted(cited)))
    emit("answer_delta", {"block": blocks[-1], "provisional": True})
    plain = "\n\n".join(b["text"] for b in blocks)
    asst = Message(session_id=session.id, seq=msg.seq + 1, role="assistant", content=plain, blocks=blocks, run_id=run.id)
    db.add(asst)
    db.flush()
    run.assistant_message_id, run.answer_status, run.warnings = asst.id, "validated", [*run.warnings, *warns]
    run.trace = dict(trace)  # копия: JSON-колонка не отслеживает мутацию на месте
    q = graph.question(db, session, msg, "answered", list(dict.fromkeys(cls.topics)))
    for c in cits:
        if c.marker in cited:
            graph.link(db, session.id, q, graph.norm(db, session, c), "cites")
    session.version += 1
    db.commit()
    _saved_blocks.pop(run.id, None)
    emit("answer_completed", {"message_id": str(asst.id), "blocks": blocks, "answer_status": "validated", "warnings": run.warnings})
    emit("portrait_updated", {"question_result": "answered"})


def _currency_notice(cits: list[Citation]) -> tuple[str, list[str]]:
    seen: dict[str, str] = {}
    warns: list[str] = []
    for c in cits:
        sn = c.snapshot
        key = f"{sn['act_title']}|{sn['revision_date']}|{sn['edition']}"
        if key in seen:
            continue
        name = sn["short_name"] or sn["act_title"]
        when = f"редакция от {sn['revision_date']}" if sn["revision_date"] else (f"издание: {sn['edition']}" if sn["edition"] else "дата редакции не указана")
        ver = f"проверена {sn['verified_at']}" if sn["verified_at"] else "актуальность не подтверждена"
        seen[key] = f"{name} — {when}; {ver}"
        if not sn["verified_at"]:
            warns.append(f"{name}: актуальность редакции не подтверждена")
        if sn["is_demo"]:
            warns.append(DEMO_NOTICE)
    text = "Источники и редакции: " + "; ".join(seen.values()) + "."
    if any("не подтверждена" in w for w in warns):
        text += " Актуальность не подтверждена: ответ нельзя считать актуальным на сегодняшнюю дату."
    if DEMO_NOTICE in warns:
        text += f" {DEMO_NOTICE}."
    return text, list(dict.fromkeys(warns))


def run_analysis(db: Session, job: Job | None, p: Providers, s: Settings, run: GenerationRun, emit: _Emit) -> None:
    if run.analysis_status == "completed":
        return
    run.analysis_status = "running"
    db.commit()
    emit("analysis_started", {})
    session = db.get(ConsultationSession, run.session_id)
    msg = db.get(Message, run.user_message_id)
    asst = db.get(Message, run.assistant_message_id) if run.assistant_message_id else None
    assert session and msg and asst
    cites = {c.marker: c for c in db.scalars(select(Citation).where(Citation.run_id == run.id))}
    facts = db.scalars(select(SessionFact).where(SessionFact.session_id == session.id, SessionFact.status == "active", SessionFact.kind == "user_fact").order_by(SessionFact.created_at.desc()).limit(20)).all()
    risks = db.scalars(select(Risk).where(Risk.session_id == session.id)).all()
    ctx = {
        "message_id": str(msg.id), "question": msg.content, "role": session.role,
        "answer": " ".join(b["text"] for b in (asst.blocks or []) if b["kind"] in ("claim", "fact", "assumption") and b["state"] == "verified")[:1500],
        "citations": [{"id": m, "locator": c.snapshot["locator"], "title": c.snapshot["short_name"] or c.snapshot["act_title"], "excerpt": c.excerpt[:300]} for m, c in cites.items()],
        "known_facts": [{"key": f.key, "value": f.value, "statement": f.statement} for f in facts],
        "existing_risks": [{"risk_type": r.risk_type, "scope": r.scope_key, "status": r.status, "p": r.p, "s": r.s} for r in risks],
        "history": _history(db, session, msg.seq, 4),
        "profile": _profile_text(db, session),
        "risk_types": {k: v[0] for k, v in RISK_TYPES.items()},  # ключ → описание: модель выбирает тип по смыслу
    }
    pr = prompts.render("analysis/analyze")
    base = [{"role": "system", "content": pr.text}, {"role": "user", "content": f"<context>{json.dumps(ctx, ensure_ascii=False)}</context>"}]
    result: AnalysisResult | None = None
    err = ""
    attempts = 0
    raw_dump = ""
    trace = dict(run.trace or {})
    while attempts < 2 and result is None:  # максимум один корректирующий повтор
        attempts += 1
        msgs = base + ([{"role": "user", "content": f"Предыдущий ответ отклонён: {err}. Верни корректный JSON по схеме."}] if err else [])
        try:
            raw = p.llm.json(msgs, AnalysisResult.model_json_schema(), num_predict=900)
            raw_dump = json.dumps(raw, ensure_ascii=False)[:8000]
            r = AnalysisResult.model_validate(raw)
            allowed = set(cites)
            used = set(r.citation_ids) | {m for rc in r.risk_candidates for m in (*rc.obligation_citation_ids, *rc.consequence_citation_ids)}
            if r.message_id != str(msg.id):
                raise ValueError("message_id не совпадает")
            if used - allowed:
                raise ValueError(f"неизвестные citation_ids: {sorted(used - allowed)}")
            result = r
        except ProviderError as e:
            err = f"{e.kind}: {e}"
            if e.kind != "invalid":
                break  # модель недоступна/таймаут — повтор бессмыслен
        except (ValidationError, ValueError) as e:
            err = str(e)[:300]
    trace["analysis"] = {"prompt": pr.meta, "attempts": attempts, "error": (None if result else err), "raw": raw_dump}
    if result is None:
        run.analysis_status, run.trace = "failed", trace
        db.commit()
        emit("status", {"stage": "analysis_failed", "message": "Аналитика не выполнена; проверенный ответ сохранён. Можно повторить анализ."})
        return
    summary = engine.apply_analysis(db, session, run.id, msg, result, cites, (run.trace or {}).get("classification", {}).get("topics"))  # одна транзакция
    run.analysis_status, run.trace = "completed", trace
    db.commit()
    emit("portrait_updated", {"question_result": "answered", **summary})
    emit("risk_updated", {"risk_ids": summary["risks_changed"]})


def handle_analysis_job(db: Session, job: Job, p: Providers, s: Settings) -> None:
    run = db.get(GenerationRun, job.run_id)
    assert run is not None
    emit = _Emit(db, job)
    _finish_after_answer(db, job, p, s, run, emit)
