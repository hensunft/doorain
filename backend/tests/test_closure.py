"""Закрытие риска по ответу пользователя (п. 1 задания 24.09): оценивается смысл ответа, а не непустая строка."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import Api, ask, new_session
from tests.test_access import _invite, register

NO_POLICY = "У нас нет политики обработки персональных данных на сайте."
GOOD = "Опубликовали политику обработки персональных данных."


def _risk(api: Api, sid: str) -> dict[str, Any]:
    return api.get(f"/sessions/{sid}/risks").json()["active"][0]


def _close(api: Api, r: dict[str, Any], answer: str, *, key: str | None = None, version: int | None = None, source: str = "plan") -> Any:
    return api.post(f"/risks/{r['id']}/closure", json={"version": r["version"] if version is None else version, "answer": answer, "source": source, "idempotency_key": key or uuid.uuid4().hex})


def _setup(owner: Api) -> tuple[str, dict[str, Any]]:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    return sid, _risk(owner, sid)


@pytest.mark.parametrize("answer", ["готово", "решено", "нет", "да, всё сделано", "ааа", "фыв", "qwrtpsdfg zxcvbnm hjklzx"])
def test_vacuous_answers_never_close_a_risk(owner: Api, demo: dict, answer: str) -> None:
    sid, r = _setup(owner)
    res = _close(owner, r, answer, source="detail")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["decision"] == "clarify" and body["applied"] is False and body["question"]
    assert body["risk"]["status"] == "open" and _risk(owner, sid)["id"] == r["id"]


def test_meaningful_answer_closes_with_explanation_and_user_claim_label(owner: Api, demo: dict) -> None:
    sid, r = _setup(owner)
    res = _close(owner, r, GOOD, source="plan").json()
    assert res["state"] == "decided" and res["decision"] == "close" and res["applied"] is True
    assert res["verification"] == "user_claim" and res["resolution_kind"] == "remediated" and res["quote"] and res["explanation"] and res["citations"]
    risk = res["risk"]
    assert risk["status"] == "resolved" and risk["resolved_by"] == "closure_user_claim" and risk["closed_at"]
    det = owner.get(f"/risks/{r['id']}").json()
    ev = [e for e in det["events"] if e["kind"] == "status"][-1]
    assert ev["to_value"] == "resolved" and ev["author"] == "closure_user_claim" and "со слов пользователя" in ev["reason"]
    a = det["closures"][0]  # журнал: исходный ответ, решение, основание, версия методики и модели
    assert a["user_answer"] == GOOD and a["initiated_by"] == "owner" and a["source"] == "plan" and a["state"] == "decided"
    from app.db.models import RiskClosureAttempt
    from app.db.session import SessionLocal

    db = SessionLocal()
    row = db.query(RiskClosureAttempt).one()
    assert row.model_info["methodology"] and row.model_info["prompt"]["name"] == "analysis/closure" and row.model_info["schema_version"] == "1"
    db.close()


def test_not_applicable_answer_closes_as_not_applicable(owner: Api, demo: dict) -> None:
    _, r = _setup(owner)
    res = _close(owner, r, "Сайта у нас нет, поэтому политика не требуется.").json()
    assert res["decision"] == "close" and res["resolution_kind"] == "not_applicable" and res["risk"]["status"] == "not_applicable"


def test_answer_about_other_topic_or_unfinished_does_not_close(owner: Api, demo: dict) -> None:
    _, r = _setup(owner)
    other = _close(owner, r, "Мы планируем размещать рекламу у блогеров в соцсетях.").json()
    assert other["decision"] == "other_risk" and other["applied"] is False and "блогер" in other["question"].lower()
    assert other["risk"]["status"] == "open" and other["risk"]["title"] == r["title"]  # старый риск не переименован, новый не создан
    r2 = owner.get(f"/risks/{r['id']}").json()["risk"]
    unfinished = _close(owner, r2, "Политику мы ещё не опубликовали, займёмся позже.", version=r2["version"]).json()
    assert unfinished["decision"] == "keep_open" and unfinished["risk"]["status"] == "open"


def test_server_rejects_model_close_without_real_quote_or_norm(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.registry import get_providers

    llm = get_providers().llm
    real = llm._closure  # type: ignore[attr-defined]
    _, r = _setup(owner)
    forged = {
        "quote": lambda ctx: {**real(ctx), "decision": "remediated", "confidence": "high", "evidence_quote": "Мы всё сделали и всё исправили полностью"},
        "norm": lambda ctx: {**real(ctx), "citation_ids": ["N99"]},
        "low": lambda ctx: {**real(ctx), "confidence": "low"},
    }
    for name, fn in forged.items():
        monkeypatch.setattr(llm, "_closure", fn)
        body = _close(owner, r, GOOD if name != "quote" else "Мы работаем над этим вопросом в нашей компании.").json()
        assert body["decision"] == "clarify" and body["applied"] is False and body["risk"]["status"] == "open", name
        assert "отклонено проверкой сервера" in body["explanation"], name
        r = owner.get(f"/risks/{r['id']}").json()["risk"]


@pytest.mark.parametrize("answer", ["Опубликовали политику обработки персональных данных", "опубликовали", "Политика опубликована"])
def test_plain_statement_of_done_action_is_enough(owner: Api, demo: dict, answer: str) -> None:
    """Достаточно написать, что нужное действие сделано: адрес страницы, дата и документы не требуются."""
    _, r = _setup(owner)
    body = _close(owner, r, answer).json()
    assert body["decision"] == "close" and body["applied"] is True and body["risk"]["status"] == "resolved", body
    assert body["citations"]  # основание закрытия — норма риска, даже если модель её не назвала


@pytest.mark.parametrize("answer", ["ничего пока", "Политику мы ещё не опубликовали, займёмся позже"])
def test_not_done_yet_keeps_risk_open(owner: Api, demo: dict, answer: str) -> None:
    _, r = _setup(owner)
    body = _close(owner, r, answer).json()
    assert body["decision"] == "keep_open" and body["risk"]["status"] == "open", body


def test_model_omissions_are_filled_by_server_not_turned_into_clarification(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Регрессия 24.09: модель решила «закрыть», но не указала норму и цитату — это не повод для уточнения."""
    from app.providers.registry import get_providers

    llm = get_providers().llm
    real = llm._closure  # type: ignore[attr-defined]
    monkeypatch.setattr(llm, "_closure", lambda ctx: {**real(ctx), "citation_ids": [], "evidence_quote": ""})
    _, r = _setup(owner)
    body = _close(owner, r, "Опубликовали политику обработки персональных данных на сайте").json()
    assert body["decision"] == "close" and body["resolution_kind"] == "remediated" and body["citations"] and body["quote"], body


def test_closure_context_has_no_texts_of_previous_attempts(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Регрессия 24.09: модель переносила в пояснение детали прежних ответов («на странице … 24 сентября») из истории риска."""
    from app.providers.registry import get_providers

    llm = get_providers().llm
    real = llm._closure  # type: ignore[attr-defined]
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(llm, "_closure", lambda ctx: (seen.append(ctx), real(ctx))[1])
    _, r = _setup(owner)
    _close(owner, r, "На странице контактов в сентябре что-то поменяли на сайте")
    r = owner.get(f"/risks/{r['id']}").json()["risk"]
    _close(owner, r, "ничего пока")
    assert "сентябр" not in json.dumps(seen[-1], ensure_ascii=False) and all(set(e) == {"at", "kind", "from", "to"} for e in seen[-1]["status_history"])


def test_corroborated_only_with_real_session_facts(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.registry import get_providers

    llm = get_providers().llm
    real = llm._closure  # type: ignore[attr-defined]
    _, r = _setup(owner)
    monkeypatch.setattr(llm, "_closure", lambda ctx: {**real(ctx), "verification": "corroborated", "used_fact_keys": ["выдуманный_ключ"]})
    body = _close(owner, r, GOOD).json()
    assert body["decision"] == "close" and body["verification"] == "user_claim"  # неизвестный факт не даёт «подтверждено»
    _, r2 = _setup(owner)
    monkeypatch.setattr(llm, "_closure", lambda ctx: {**real(ctx), "verification": "corroborated", "used_fact_keys": [f["key"] for f in ctx["session_facts"]][:1]})
    ok = _close(owner, r2, GOOD).json()
    assert ok["verification"] == "corroborated" and ok["facts"] and ok["risk"]["resolved_by"] == "closure_confirmed"


def test_retry_with_same_key_is_idempotent_and_conflicts_are_reported(owner: Api, demo: dict) -> None:
    sid, r = _setup(owner)
    first = _close(owner, r, GOOD, key="retry-key-0001")
    again = _close(owner, r, GOOD, key="retry-key-0001", version=r["version"])
    assert first.status_code == again.status_code == 200 and first.json()["id"] == again.json()["id"]
    assert len(owner.get(f"/risks/{r['id']}").json()["closures"]) == 1
    assert _close(owner, r, "Совсем другой ответ про сайт компании", key="retry-key-0001").status_code == 409  # тот же ключ с другим ответом
    assert _close(owner, r, GOOD).status_code == 409  # риск уже закрыт: закрывать нечего
    assert owner.get(f"/sessions/{sid}/risks").json()["active"] == []


def test_stale_version_is_rejected_and_pending_blocks_parallel_attempt(owner: Api, demo: dict) -> None:
    from app.db.models import RiskClosureAttempt
    from app.db.session import SessionLocal

    sid, r = _setup(owner)
    assert _close(owner, r, GOOD, version=r["version"] + 3).status_code == 409
    db = SessionLocal()
    db.add(RiskClosureAttempt(risk_id=uuid.UUID(r["id"]), idempotency_key="parallel-0001", source="plan", user_answer="x", initiated_by="owner", risk_version=r["version"], state="pending"))
    db.commit()
    db.close()
    busy = _close(owner, r, GOOD)
    assert busy.status_code == 409 and busy.json()["code"] == "closure_in_progress"
    assert _risk(owner, sid)["status"] == "open"


def test_risk_changed_during_check_is_not_closed(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.models import Risk
    from app.db.session import SessionLocal
    from app.providers.registry import get_providers

    llm = get_providers().llm
    real = llm._closure  # type: ignore[attr-defined]
    _, r = _setup(owner)

    def racing(ctx: dict[str, Any]) -> dict[str, Any]:  # другая вкладка меняет риск, пока идёт проверка
        db = SessionLocal()
        row = db.get(Risk, uuid.UUID(r["id"]))
        assert row
        row.version += 1
        db.commit()
        db.close()
        return real(ctx)

    monkeypatch.setattr(llm, "_closure", racing)
    body = _close(owner, r, GOOD).json()
    assert body["state"] == "stale" and body["applied"] is False and body["risk"]["status"] == "open"


def test_llm_failure_keeps_risk_open_and_is_journaled(owner: Api, demo: dict) -> None:
    from app.providers.registry import get_providers

    _, r = _setup(owner)
    get_providers().llm.fail = True  # type: ignore[attr-defined]
    body = _close(owner, r, GOOD).json()
    assert body["state"] == "failed" and body["applied"] is False and body["risk"]["status"] == "open" and "недоступна" in body["explanation"]
    get_providers().llm.fail = False  # type: ignore[attr-defined]
    events = owner.get(f"/risks/{r['id']}").json()["events"]
    assert any(e["kind"] == "closure" and "не выполнена" in e["reason"] for e in events)
    assert _close(owner, owner.get(f"/risks/{r['id']}").json()["risk"], GOOD).json()["decision"] == "close"  # после восстановления модели можно повторить


def test_archived_basis_never_closes(owner: Api, demo: dict) -> None:
    from app.db.models import Citation
    from app.db.session import SessionLocal

    _, r = _setup(owner)
    db = SessionLocal()
    for c in db.query(Citation).all():  # основание выведено из базы знаний
        c.snapshot = {**c.snapshot, "archived": True}
    db.commit()
    db.close()
    body = _close(owner, r, GOOD).json()
    assert body["state"] == "failed" and body["risk"]["status"] == "open" and "основание" in body["explanation"].lower()


def test_direct_patch_cannot_bypass_check_and_override_is_owner_only_and_audited(owner: Api, client: TestClient, demo: dict) -> None:
    sid, r = _setup(owner)
    p = f"/risks/{r['id']}"
    for status in ("resolved", "not_applicable", "dismissed", "closed"):
        blocked = owner.patch(p, json={"status": status, "reason": "готово", "version": r["version"]})
        assert blocked.status_code == 409 and blocked.json()["code"] == "closure_check_required", status
    alice = register(client, "alice", _invite(owner))
    asid = new_session(alice)
    ask(alice, asid, NO_POLICY)
    ar = alice.get(f"/sessions/{asid}/risks").json()["active"][0]
    denied = alice.patch(f"/risks/{ar['id']}", json={"status": "resolved", "reason": "мимо проверки", "version": ar["version"], "override": True})
    assert denied.status_code == 403
    assert alice.get(f"/risks/{ar['id']}").json()["risk"]["status"] == "open"
    ok = owner.patch(p, json={"status": "resolved", "reason": "Закрыто владельцем вручную", "version": r["version"], "override": True})
    assert ok.status_code == 200 and ok.json()["resolved_by"] == "owner_override"
    assert any(e["action"] == "risk.closure_override" for e in owner.get("/admin/audit").json())
    assert [e["author"] for e in owner.get(p).json()["events"] if e["kind"] == "status"][-1] == "owner_override"


def test_foreign_user_cannot_check_closure(owner: Api, client: TestClient, demo: dict) -> None:
    _, r = _setup(owner)
    bob = register(client, "bob", _invite(owner))
    assert _close(bob, r, GOOD).status_code == 404


def test_vacuous_chat_message_does_not_close_a_risk(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.registry import get_providers

    llm = get_providers().llm
    real = llm._analyze  # type: ignore[attr-defined]
    sid, r = _setup(owner)
    monkeypatch.setattr(llm, "_analyze", lambda ctx: {**real({**ctx, "question": "Мы уже опубликовали политику обработки персональных данных на сайте."}), "message_id": ctx["message_id"]})
    monkeypatch.setattr(llm, "_classify", lambda ctx: {"in_scope": True, "topics": ["personal_data"], "rewritten_query": "политика обработки персональных данных", "clarification": None, "mixed": False})
    ask(owner, sid, "готово")  # общее слово без предмета
    data = owner.get(f"/sessions/{sid}/risks").json()
    assert data["resolved"] == [] and data["active"][0]["id"] == r["id"] and data["active"][0]["resolution_pending"]
