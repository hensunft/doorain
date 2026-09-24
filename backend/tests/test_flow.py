"""Сквозные сценарии (TEST-провайдеры): доказывают логику приложения, не качество реальной модели."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db import models as m
from app.db.session import SessionLocal
from tests.conftest import Api, ask, new_session, run_jobs

NO_POLICY = "У нас нет политики обработки персональных данных на сайте."


def _sse(api: Api, run_id: str, **params: Any) -> list[dict[str, Any]]:
    out, cur = [], {}
    with api.c.stream("GET", f"/api/v1/runs/{run_id}/events", params=params, headers={"X-CSRF-Token": api.csrf}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("id:"):
                cur["id"] = int(line[3:])
            elif line.startswith("event:"):
                cur["event"] = line[6:].strip()
            elif line.startswith("data:"):
                cur["data"] = json.loads(line[5:])
            elif not line and cur:
                out.append(cur)
                cur = {}
    return out


def _risks(api: Api, sid: str) -> dict[str, Any]:
    return api.get(f"/sessions/{sid}/risks").json()


def test_vertical_scenario_answer_citations_portrait_risk(owner: Api, demo: dict) -> None:
    sid = new_session(owner, profile={"sphere": "онлайн-школа", "has_site_or_app": "yes", "processes_pd": "yes", "servers_location": "abroad"})
    snap = ask(owner, sid, NO_POLICY)
    assert snap["answer_status"] == "validated" and snap["analysis_status"] == "completed" and snap["done"]
    msgs = owner.get(f"/sessions/{sid}/messages").json()
    ans = msgs[-1]
    assert ans["role"] == "assistant" and ans["blocks"] and ans["citations"]
    claim = next(b for b in ans["blocks"] if b["kind"] == "claim")
    assert claim["markers"] and claim["citation_ids"] and "[C" not in claim["text"]
    cur = next(b for b in ans["blocks"] if b["kind"] == "currency")
    assert "Демонстрационные" not in cur["text"] and "ДЕМО-1-ФЗ" in cur["text"]
    # каждая цитата существует, относится к загруженной редакции и открывает правильный фрагмент
    for chip in ans["citations"]:
        c = owner.get(f"/citations/{chip['id']}").json()
        assert c["snapshot"]["locator"].startswith("ст.") and c["excerpt"] and c["snapshot"]["act_number"].startswith("ДЕМО")
        if c["snapshot"]["act_number"] == "ДЕМО-1-ФЗ":
            assert c["snapshot"]["revision_date"] == "2026-03-01"  # на дату среза 20.09.2026 действует последняя загруженная редакция
        assert c["formatted"].startswith("«") and "Демонстрационные" not in c["formatted"]
    # слепок
    g = owner.get(f"/sessions/{sid}/graph").json()
    kinds = {n["kind"] for n in g["nodes"]}
    assert kinds == {"center", "topic", "question", "norm", "risk"}
    assert {e["kind"] for e in g["edges"]} >= {"belongs_to", "asks_about", "cites", "evidences", "grounded_in"}
    risk_node = next(n for n in g["nodes"] if n["kind"] == "risk")
    assert risk_node["risk_level"] == "medium"
    q_node = next(n for n in g["nodes"] if n["kind"] == "question")
    assert q_node["risk_level"] == "medium" and q_node["data"]["result"] == "answered"
    # риск: P4×S2=8, есть основание, evidence, история
    r = _risks(owner, sid)
    assert len(r["active"]) == 1
    risk = r["active"][0]
    assert (risk["p"], risk["s"], risk["score"], risk["level"]) == (4, 2, 8, "medium") and risk["norms"] and risk["methodology"] if "methodology" in risk else True
    det = owner.get(f"/risks/{risk['id']}").json()
    assert {e["kind"] for e in det["evidence"]} >= {"fact", "obligation", "message"} and det["events"][0]["kind"] == "created"
    # хронология использует те же данные
    tl = owner.get(f"/sessions/{sid}/timeline").json()
    assert len(tl) == 1 and tl[0]["result"] == "answered" and tl[0]["risks"]
    # после «перезапуска» всё восстанавливается из БД
    from app.db.session import reset_engine

    reset_engine()
    assert len(owner.get(f"/sessions/{sid}/messages").json()) == 2 and len(_risks(owner, sid)["active"]) == 1


def test_trace_is_stored_for_audit(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    snap = ask(owner, sid, NO_POLICY)
    db = SessionLocal()
    run = db.get(m.GenerationRun, uuid.UUID(snap["run_id"]))
    assert run and run.corpus_generation_id and run.model_info["provider"] == "test" and run.model_info["embedder"]["dim"]
    t = run.trace
    assert {p["name"] for p in t["prompts"]} >= {"analysis/classify", "common/rules", "entrepreneur/answer"} and all(p["version"] and p["sha256"] for p in t["prompts"])
    assert t["retrieval"]["scores"] and t["retrieval"]["timings_ms"] and t["sources"]["C1"] and t["ttft_ms"] is not None and t["analysis"]["attempts"] == 1
    assert t["raw_answer"] and "[C1]" in t["raw_answer"] and t["analysis"]["raw"]  # сырой вывод модели сохранён отдельно
    db.close()


def test_out_of_scope_refusal_creates_question_node_only(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    snap = ask(owner, sid, "Расскажи рецепт борща с говядиной")
    assert snap["answer_status"] == "refused" and snap["refusal_reason"] == "out_of_scope" and snap["analysis_status"] == "not_started"
    g = owner.get(f"/sessions/{sid}/graph").json()
    q = next(n for n in g["nodes"] if n["kind"] == "question")
    assert q["data"]["result"] == "refused" and not [n for n in g["nodes"] if n["kind"] in ("norm", "risk")]
    assert _risks(owner, sid)["active"] == []
    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(m.Citation)) == 0
    db.close()


def test_empty_corpus_and_model_unavailable_are_honest(owner: Api) -> None:
    sid = new_session(owner)
    snap = ask(owner, sid, NO_POLICY)
    assert snap["answer_status"] == "refused" and snap["refusal_reason"] == "corpus_empty"
    from app.providers.registry import get_providers

    get_providers().llm.fail = True  # type: ignore[attr-defined]
    snap2 = ask(owner, sid, "Нужна ли политика обработки персональных данных?")
    assert snap2["answer_status"] == "failed" and snap2["error_code"] == "model_unavailable"
    txt = owner.get(f"/sessions/{sid}/messages").json()[-1]["text"]
    assert "недоступна" in txt and "облач" in txt
    st = owner.get("/system/status").json()
    assert st["model"]["state"] == "test_mode" and st["corpus_empty"] is True


def test_insufficient_grounds_when_threshold_not_met(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOORAIN_MIN_RERANK_SCORE", "0.99")
    monkeypatch.setenv("DOORAIN_PARTIAL_ANSWER_MARGIN", "0")  # проверяется именно жёсткий отказ
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    sid = new_session(owner)
    snap = ask(owner, sid, "Нужна ли политика обработки персональных данных на сайте?")
    assert snap["answer_status"] == "refused" and snap["refusal_reason"] == "insufficient_grounds"
    tr = owner.get(f"/runs/{snap['run_id']}/trace").json()  # трасса отказа сохраняется (для аудита и калибровки порога)
    assert tr["trace"]["retrieval"]["scores"] and tr["trace"]["retrieval"]["reason"] == "below_threshold" and tr["model_info"]["provider"] == "test"
    assert "не отвечаю «по памяти»" in owner.get(f"/sessions/{sid}/messages").json()[-1]["text"]


def test_unsupported_blocks_replaced_and_no_hallucinated_citation(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    snap = ask(owner, sid, "Нужна ли политика НЕПОДДЕРЖИВАЕМЫЙ_ТЕЗИС обработки персональных данных?")
    ans = owner.get(f"/sessions/{sid}/messages").json()[-1]
    assert snap["answer_status"] == "validated"
    unsupported = [b for b in ans["blocks"] if b["state"] == "unsupported"]
    assert len(unsupported) == 1 and unsupported[0]["kind"] == "notice" and unsupported[0]["citation_ids"] == []
    db = SessionLocal()
    ids = {str(i) for (i,) in db.execute(select(m.Citation.id))}
    assert all(cid in ids for b in ans["blocks"] for cid in b["citation_ids"])
    db.close()


def test_dedup_busy_and_cancel_before_start(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    body = {"text": NO_POLICY, "client_request_id": "req-" + uuid.uuid4().hex}
    a = owner.post(f"/sessions/{sid}/messages", json=body)
    b = owner.post(f"/sessions/{sid}/messages", json=body)  # двойной клик / повтор
    assert a.status_code == b.status_code == 202 and a.json()["run_id"] == b.json()["run_id"] and b.json()["deduplicated"] is True
    other_tab = owner.post(f"/sessions/{sid}/messages", json={"text": "Другой вопрос про закон", "client_request_id": "tab-" + uuid.uuid4().hex})
    assert other_tab.status_code == 409 and other_tab.json()["code"] == "run_in_progress"
    c = owner.post(f"/runs/{a.json()['run_id']}/cancel")
    assert c.status_code == 200 and c.json()["answer_status"] == "cancelled"
    assert run_jobs() == 0  # отменённое до старта задание не исполняется
    evs = _sse(owner, a.json()["run_id"])
    assert [e["event"] for e in evs][-1] == "cancelled"
    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(m.Message).where(m.Message.role == "user")) == 1
    assert db.scalar(select(func.count()).select_from(m.Risk)) == 0
    db.close()
    g = owner.get(f"/sessions/{sid}/graph").json()
    assert next(n for n in g["nodes"] if n["kind"] == "question")["data"]["result"] == "cancelled"
    assert owner.post(f"/sessions/{sid}/messages", json={"text": "Новый вопрос по закону о данных", "client_request_id": "n-" + uuid.uuid4().hex}).status_code == 202


def test_sse_events_replay_and_reconnect(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    snap = ask(owner, sid, NO_POLICY)
    evs = _sse(owner, snap["run_id"])
    types = [e["event"] for e in evs]
    assert types[0] == "status" and "answer_delta" in types and types.index("answer_completed") < types.index("analysis_started") < types.index("risk_updated") < types.index("completed")
    assert max(i for i, t in enumerate(types) if t == "portrait_updated") > types.index("analysis_started")  # слепок обновляется после аналитики
    ids = [e["id"] for e in evs]
    assert ids == sorted(ids) and len(set(ids)) == len(ids) and all(e["data"]["run_id"] == snap["run_id"] for e in evs)
    done = next(e for e in evs if e["event"] == "answer_completed")["data"]
    assert done["answer_status"] == "validated" and done["blocks"]
    # реконнект с Last-Event-ID: ничего не запускается повторно, приходит только хвост
    cut = ids[len(ids) // 2]
    tail = _sse(owner, snap["run_id"], after=cut)
    assert [e["id"] for e in tail] == [i for i in ids if i > cut]
    with owner.c.stream("GET", f"/api/v1/runs/{snap['run_id']}/events", headers={"Last-Event-ID": str(cut), "X-CSRF-Token": owner.csrf}) as r:
        assert "id: " + str(cut) not in "".join(r.iter_text())
    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(m.GenerationRun)) == 1
    db.close()
    lost = _sse(owner, snap["run_id"], after=10**9)  # потерянный replay → snapshot-событие
    assert lost[0]["event"] == "snapshot" and lost[-1]["event"] == "completed"
    snapshot = owner.get(f"/runs/{snap['run_id']}").json()
    strip = lambda bs: [{k: v for k, v in b.items() if k != "removed"} for b in bs]  # noqa: E731
    assert strip(snapshot["blocks"]) == strip(done["blocks"]) and snapshot["last_event_id"] == ids[-1]


def test_repeat_does_not_raise_p_and_new_independent_fact_gives_single_bonus(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    ask(owner, sid, NO_POLICY)  # повтор
    ask(owner, sid, "Ещё раз: у нас нет политики обработки персональных данных.")  # перефразирование
    r = _risks(owner, sid)["active"]
    assert len(r) == 1 and (r[0]["p"], r[0]["bonus_p"]) == (4, 0) and r[0]["score"] == 8  # P не вырос
    ask(owner, sid, "Мы ведём рассылку, а у нас нет политики обработки персональных данных.")  # новый независимый факт
    r = _risks(owner, sid)["active"][0]
    assert (r["base_p"], r["bonus_p"], r["p"], r["score"], r["level"]) == (4, 1, 5, 10, "high")
    ask(owner, sid, "Мы ведём рассылку, а у нас нет политики обработки персональных данных.")
    ask(owner, sid, "Рассылка идёт постоянно, у нас нет политики обработки персональных данных.")
    r = _risks(owner, sid)["active"]
    assert len(r) == 1 and r[0]["p"] == 5 and r[0]["bonus_p"] == 1  # бонус однократный, максимум 5
    det = owner.get(f"/risks/{r[0]['id']}").json()
    roles = [(e["role"], e["kind"]) for e in det["evidence"]]
    assert ("bonus", "fact") in roles and roles.count(("bonus", "fact")) == 1
    base_ids = {e["ref_id"] for e in det["evidence"] if e["role"] == "base" and e["kind"] == "fact"}
    bonus_ids = {e["ref_id"] for e in det["evidence"] if e["role"] == "bonus"}
    assert base_ids.isdisjoint(bonus_ids)  # один факт не учитывается дважды
    assert any(e["kind"] == "score" and "P4×S2=8" == e["from_value"] for e in det["events"])


def test_question_alone_is_not_a_fact_or_risk(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    ask(owner, sid, "Нужна ли политика обработки персональных данных на сайте?")
    r = _risks(owner, sid)
    assert r["active"] == [] and len(r["needs_clarification"]) == 1 and r["needs_clarification"][0]["p"] is None and r["needs_clarification"][0]["clarification"]
    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(m.SessionFact).where(m.SessionFact.key == "has_pd_policy")) == 0
    db.close()


def test_resolution_by_message_keeps_history_and_neutral_color(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    before = owner.get(f"/sessions/{sid}/graph").json()
    assert any(n["risk_level"] == "medium" for n in before["nodes"])
    ask(owner, sid, "Мы уже опубликовали политику обработки персональных данных на сайте.")
    r = _risks(owner, sid)
    assert r["active"] == [] and len(r["resolved"]) == 1
    res = r["resolved"][0]
    assert res["status"] == "resolved" and res["resolved_by"] == "user_message" and res["resolution_reason"] == "Снят по сообщению пользователя"
    det = owner.get(f"/risks/{res['id']}").json()
    assert [e["to_value"] for e in det["events"] if e["kind"] == "status"] == ["resolved"] and det["events"][-1]["author"] == "user_message"
    after = owner.get(f"/sessions/{sid}/graph").json()
    assert not any(n["risk_level"] for n in after["nodes"])  # снятые не окрашивают узлы: нейтральный серый
    # повторное появление факта нарушения открывает риск заново с причиной
    ask(owner, sid, NO_POLICY)
    reopened = _risks(owner, sid)["active"]
    assert len(reopened) == 1 and reopened[0]["id"] == res["id"]
    ev = owner.get(f"/risks/{res['id']}").json()["events"]
    assert any(e["kind"] == "status" and e["to_value"] == "open" and "новые факты" in e["reason"].lower() for e in ev)


def test_manual_status_change_requires_reason_and_version(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    risk = _risks(owner, sid)["active"][0]
    p = f"/risks/{risk['id']}"
    assert owner.patch(p, json={"status": "resolved", "reason": "", "version": risk["version"]}).status_code == 422
    assert owner.patch(p, json={"status": "resolved", "reason": "Опубликовали", "version": risk["version"] + 5}).status_code == 409
    ok = owner.patch(p, json={"status": "in_progress", "reason": "Начали работу", "version": risk["version"]})
    assert ok.status_code == 200 and ok.json()["status"] == "in_progress" and ok.json()["version"] == risk["version"] + 1
    assert owner.patch(p, json={"status": "resolved", "reason": "Готово", "version": risk["version"]}).status_code == 409  # устаревшая версия (другая вкладка)
    blocked = owner.patch(p, json={"status": "resolved", "reason": "Политика опубликована", "version": ok.json()["version"]})
    assert blocked.status_code == 409 and blocked.json()["code"] == "closure_check_required"  # прямой PATCH закрытия обходит проверку ответа
    done = owner.patch(p, json={"status": "resolved", "reason": "Политика опубликована", "version": ok.json()["version"], "override": True}).json()
    assert done["resolved_by"] == "owner_override" and done["resolution_reason"] == "Политика опубликована"


def test_analysis_failure_keeps_answer_and_retry_has_no_duplicates(owner: Api, demo: dict) -> None:
    from app.providers.registry import get_providers

    llm = get_providers().llm
    llm._analyze = lambda ctx: {"schema_version": "1", "message_id": "wrong", "topic_ids": [], "fact_candidates": [], "citation_ids": [], "risk_candidates": [], "relations": []}  # type: ignore[attr-defined]
    sid = new_session(owner)
    snap = ask(owner, sid, NO_POLICY)
    assert snap["answer_status"] == "validated" and snap["analysis_status"] == "failed"
    assert owner.get(f"/sessions/{sid}/messages").json()[-1]["blocks"]  # проверенный ответ сохранён
    assert _risks(owner, sid)["active"] == []
    del llm._analyze  # type: ignore[attr-defined]
    r = owner.post(f"/runs/{snap['run_id']}/analysis/retry")
    assert r.status_code == 202
    run_jobs()
    assert owner.get(f"/runs/{snap['run_id']}").json()["analysis_status"] == "completed"
    assert len(_risks(owner, sid)["active"]) == 1
    assert owner.post(f"/runs/{snap['run_id']}/analysis/retry").status_code == 409  # уже выполнена
    exp = owner.post(f"/sessions/{sid}/exports", json={})
    assert exp.status_code == 202  # после успешного retry экспорт не «неполный»
    assert exp.json()["incomplete"] is False


def test_invalid_candidate_never_reaches_domain_tables(owner: Api, demo: dict) -> None:
    from app.providers.registry import get_providers

    llm = get_providers().llm
    real = llm._analyze  # type: ignore[attr-defined]

    def bad(ctx: dict[str, Any]) -> dict[str, Any]:
        res = real(ctx)
        res["risk_candidates"][0]["proposed_p"] = 9  # выход P за диапазон
        return res

    llm._analyze = bad  # type: ignore[attr-defined]
    sid = new_session(owner)
    snap = ask(owner, sid, NO_POLICY)
    assert snap["analysis_status"] == "failed"
    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(m.Risk)) == 0 and db.scalar(select(func.count()).select_from(m.SessionFact)) == 0
    db.close()


def test_risk_without_normative_basis_is_not_created(owner: Api, demo: dict) -> None:
    from app.providers.registry import get_providers

    llm = get_providers().llm
    real = llm._analyze  # type: ignore[attr-defined]

    def no_basis(ctx: dict[str, Any]) -> dict[str, Any]:
        res = real(ctx)
        for rc in res["risk_candidates"]:
            rc["obligation_citation_ids"] = []
        return res

    llm._analyze = no_basis  # type: ignore[attr-defined]
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    r = _risks(owner, sid)
    assert r["active"] == r["needs_clarification"] == r["clarifications"] == []  # без основания кандидат отброшен (в лог), пользователю не показан


def test_severity_3_requires_consequence_source(owner: Api, demo: dict) -> None:
    from app.providers.registry import get_providers

    llm = get_providers().llm
    real = llm._analyze  # type: ignore[attr-defined]

    def s3(ctx: dict[str, Any]) -> dict[str, Any]:
        res = real(ctx)
        for rc in res["risk_candidates"]:
            rc["proposed_s"], rc["consequence_citation_ids"] = 4, []
        return res

    llm._analyze = s3  # type: ignore[attr-defined]
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    r = _risks(owner, sid)
    assert r["active"] == [] and r["needs_clarification"][0]["s"] is None and "санкц" in r["needs_clarification"][0]["clarification"]


def test_student_gets_no_business_risks_and_quiz_creates_learning_risk(owner: Api, demo: dict) -> None:
    sid = new_session(owner, role="student")
    ask(owner, sid, NO_POLICY)
    assert _risks(owner, sid)["active"] == []  # вопрос ≠ подтверждённая ошибка
    q = owner.post(f"/sessions/{sid}/quiz")
    assert q.status_code == 202
    run_jobs()
    quiz = owner.get(f"/quizzes/{q.json()['id']}").json()
    assert quiz["status"] == "ready" and 1 <= len(quiz["questions"]) <= 5
    assert all("answer_index" not in x and "explanation" not in x for x in quiz["questions"])
    wrong = {x["id"]: 2 for x in quiz["questions"]}  # заведомо неверный вариант
    att = owner.post(f"/quizzes/{quiz['id']}/attempts", json={"answers": wrong}).json()
    assert att["correct"] == 0 and all(r["explanation"] and r["citation"]["locator"] for r in att["results"])
    r = _risks(owner, sid)["active"]
    assert r and all(x["kind"] == "learning" and x["norms"] for x in r)
    # повторная ошибка по тому же понятию повышает P; правильный ответ рисков не создаёт
    owner.post(f"/quizzes/{quiz['id']}/attempts", json={"answers": wrong})
    assert max(x["p"] for x in _risks(owner, sid)["active"]) == 4
    good = {x["id"]: 0 for x in quiz["questions"]}
    n = len(_risks(owner, sid)["active"])
    assert owner.post(f"/quizzes/{quiz['id']}/attempts", json={"answers": good}).json()["correct"] == len(good)
    assert len(_risks(owner, sid)["active"]) == n
    ent = new_session(owner)
    assert owner.post(f"/sessions/{ent}/quiz").status_code == 422  # только для студента


def test_expert_direct_quote_is_verified_against_source(owner: Api, demo: dict) -> None:
    sid = new_session(owner, role="expert")
    ask(owner, sid, "Статья 7 ДЕМО-1-ФЗ: какие обязанности оператора по политике?")
    ans = owner.get(f"/sessions/{sid}/messages").json()[-1]
    claim = next(b for b in ans["blocks"] if b["kind"] == "claim")
    assert "«" in claim["text"] and claim["state"] == "verified"
    db = SessionLocal()
    ev = db.scalars(select(m.ClaimEvidence)).all()
    assert ev and any(e.quote_verified is True for e in ev) and not any(e.quote_verified is False for e in ev)
    exact = db.scalar(select(m.Citation).where(m.Citation.snapshot["article"].as_string() == "7"))
    assert exact is not None
    db.close()
    txt = owner.get(f"/citations/{ans['citations'][0]['id']}/export")
    assert txt.status_code == 200 and "attachment" in txt.headers["content-disposition"] and "Происхождение" in txt.text and "Демонстрационные" not in txt.text


def test_roles_produce_different_answer_forms_from_same_evidence(owner: Api, demo: dict) -> None:
    forms = {}
    for role in ("student", "entrepreneur", "expert"):
        sid = new_session(owner, role=role)
        ask(owner, sid, "Нужна ли политика обработки персональных данных на сайте?")
        ans = owner.get(f"/sessions/{sid}/messages").json()[-1]
        forms[role] = next(b["text"] for b in ans["blocks"] if b["kind"] == "claim")
    assert forms["student"].startswith("Простыми словами") and forms["entrepreneur"].startswith("Вывод") and "«" in forms["expert"]


def test_old_citations_survive_new_revision_and_generation(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    chip = owner.get(f"/sessions/{sid}/messages").json()[-1]["citations"][0]
    before = owner.get(f"/citations/{chip['id']}").json()
    # новая редакция акта → новая generation; сессия на прошлую дату получает прошлую редакцию, старая цитата не меняется
    from app.demo import DEMO_META, load_demo
    from tests.conftest import DEMO_DIR

    new_text = (DEMO_DIR / "demo-data-act-2026.txt").read_text(encoding="utf-8").replace("сведения о хранении и контакты", "сведения о хранении, сроках и контакты").replace("1 марта 2026", "1 марта 2027")
    p = Path(DEMO_DIR).parent / "_tmp"
    p.mkdir(exist_ok=True)
    (p / "demo-data-act-2027.txt").write_text(new_text, encoding="utf-8")
    DEMO_META["demo-data-act-2027.txt"] = {**DEMO_META["demo-data-act-2026.txt"], "revision_date": "2027-03-01"}
    try:
        load_demo(p)
    finally:
        DEMO_META.pop("demo-data-act-2027.txt")
        (p / "demo-data-act-2027.txt").unlink()
        p.rmdir()
    after = owner.get(f"/citations/{chip['id']}").json()
    assert after["snapshot"] == before["snapshot"] and after["excerpt"] == before["excerpt"]
    ov = owner.get("/corpus/overview").json()
    assert ov["active_generation"]["seq"] == 2 and ov["revisions"] == 5
    sid2 = new_session(owner)
    ask(owner, sid2, NO_POLICY)  # as_of=2026-09-20 → редакция 2027 ещё не действует
    c2 = owner.get(f"/sessions/{sid2}/messages").json()[-1]["citations"][0]
    assert owner.get(f"/citations/{c2['id']}").json()["snapshot"]["revision_date"] == "2026-03-01"


def test_delete_session_cascades_but_keeps_corpus(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    owner.post(f"/sessions/{sid}/exports", json={})
    run_jobs()
    title = owner.get(f"/sessions/{sid}").json()["title"]
    assert owner.delete(f"/sessions/{sid}", params={"confirm": "не то"}).status_code == 422
    assert owner.delete(f"/sessions/{sid}", params={"confirm": title}).status_code == 204
    assert owner.get(f"/sessions/{sid}").status_code == 404
    db = SessionLocal()
    assert db.scalar(select(func.count()).select_from(m.ConsultationSession).where(m.ConsultationSession.deleted_at.is_not(None))) == 1  # мягкое удаление
    db.close()
    assert owner.post("/admin/sessions/purge").json() == {"purged": 1}  # окончательную очистку выполняет владелец
    db = SessionLocal()
    for model in (m.Message, m.GenerationRun, m.Citation, m.Risk, m.RiskEvidence, m.RiskStatusEvent, m.GraphNode, m.GraphEdge, m.SessionFact, m.Export, m.ClaimEvidence, m.Job, m.JobEvent):
        assert db.scalar(select(func.count()).select_from(model).where(*([model.type.in_(("chat_run",))] if model is m.Job else []))) == 0, model.__name__  # type: ignore[attr-defined]
    assert db.scalar(select(func.count()).select_from(m.DocumentRevision)) == 4 and db.scalar(select(func.count()).select_from(m.Chunk)) > 0
    db.close()


def test_role_change_creates_new_session_without_mixing_data(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    new = owner.post(f"/sessions/{sid}/change-role", json={"role": "expert"}).json()
    assert new["id"] != sid and new["role"] == "expert" and new["parent_session_id"] == sid and new["messages_count"] == 0 and new["active_risks"] == 0
    assert owner.get(f"/sessions/{sid}").json()["active_risks"] == 1  # прежняя сохранена
    assert len(owner.get(f"/sessions/{new['id']}/graph").json()["nodes"]) == 1
    owner.patch(f"/sessions/{sid}", json={"title": "Переименовано", "status": "archived"})
    assert [s["id"] for s in owner.get("/sessions", params={"status": "archived"}).json()] == [sid]
    assert owner.post(f"/sessions/{sid}/messages", json={"text": "вопрос про закон", "client_request_id": "a" * 10}).status_code == 409


def test_layout_persisted_and_validated(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    g = owner.get(f"/sessions/{sid}/graph").json()
    nid = g["nodes"][0]["id"]
    assert owner.put(f"/sessions/{sid}/layout", json={"positions": {nid: {"x": 10.5, "y": -3}, "bogus": {"x": 1, "y": 1}}, "filters": {"topic": "personal_data"}}).status_code == 204
    g2 = owner.get(f"/sessions/{sid}/graph").json()
    assert g2["positions"] == {nid: {"x": 10.5, "y": -3}} and g2["filters"] == {"topic": "personal_data"}


def test_diagnostics_and_maintenance_mode(owner: Api, demo: dict) -> None:
    d = owner.get("/system/diagnostics").json()
    assert d["database"]["ok"] and d["qdrant"]["ok"] and d["llm"]["test"] is True and d["corpus"]["revisions"] == 4 and d["corpus"]["control_search"]["passed"] >= 1
    assert d["thresholds"]["source"] == "uncalibrated"
    from app.services.ingestion.indexer import set_state

    db = SessionLocal()
    set_state(db, "maintenance", {"on": True})
    db.commit()
    db.close()
    r = owner.post("/sessions", json={"role": "expert"})
    assert r.status_code == 503 and r.json()["code"] == "maintenance"
    assert owner.get("/sessions").status_code == 200  # чтение доступно


def test_partial_grounds_answer_carries_explicit_caveat(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Мягкая деградация: при средних скорах отвечаем, но помечаем неполноту оснований; жёсткий отказ остаётся для пустой выдачи."""
    monkeypatch.setenv("DOORAIN_MIN_RERANK_SCORE", "0.9")
    monkeypatch.setenv("DOORAIN_PARTIAL_ANSWER_MARGIN", "0.9")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    sid = new_session(owner)
    snap = ask(owner, sid, "Нужна ли политика обработки персональных данных на сайте?")
    assert snap["answer_status"] == "validated"
    msg = owner.get(f"/sessions/{sid}/messages").json()[-1]
    assert any(b["kind"] == "notice" and "лишь частично" in b["text"] for b in msg["blocks"])
    assert any("неполных основаниях" in w for w in msg["warnings"])
    tr = owner.get(f"/runs/{snap['run_id']}/trace").json()
    assert tr["trace"]["retrieval"]["confidence"] == "partial"


def test_scope_verdict_is_overridden_only_by_strong_norms(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Вердикт классификатора «вне области» снимается найденными нормами; ловушка со слабой выдачей по-прежнему отклоняется."""
    monkeypatch.setenv("DOORAIN_SCOPE_OVERRIDE_MIN_SCORE", "0.2")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    sid = new_session(owner)
    snap = ask(owner, sid, "Что считается условными данными и кто их оператор?")  # тем классификатора нет, но нормы есть
    assert snap["answer_status"] == "validated" and snap["refusal_reason"] is None
    tr = owner.get(f"/runs/{snap['run_id']}/trace").json()
    assert tr["trace"]["classification"]["in_scope"] is False and tr["trace"]["scope_override"]["best_score"] > 0
    assert ask(owner, sid, "Расскажи рецепт борща с говядиной")["refusal_reason"] == "out_of_scope"
