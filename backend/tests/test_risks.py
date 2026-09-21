"""Модуль риск-менеджмента: приёмка части B (основание из контекста, дедупликация, ручная оценка,
предложения агента, лимит новых рисков, матрица, статусы, экспорт, изоляция)."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import Api, ask, new_session
from tests.test_access import _invite, register

NO_POLICY = "У нас нет политики обработки персональных данных на сайте."


def _risks(api: Api, sid: str) -> dict[str, Any]:
    return api.get(f"/sessions/{sid}/risks").json()


def _patch_analysis(monkeypatch: pytest.MonkeyPatch, change: Any) -> None:
    from app.providers.registry import get_providers

    llm = get_providers().llm
    real = llm._analyze  # type: ignore[attr-defined]
    monkeypatch.setattr(llm, "_analyze", lambda ctx: change(real(ctx), ctx))


def test_risk_basis_must_come_from_the_actual_answer_context(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменённый контекст: ссылка на фрагмент, которого не было в ответе, не создаёт риск."""

    def forged(res: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        for c in res["risk_candidates"]:
            c["obligation_citation_ids"] = ["C99"]  # такого фрагмента модель не получала
        return res

    _patch_analysis(monkeypatch, forged)
    sid = new_session(owner)
    assert ask(owner, sid, NO_POLICY)["analysis_status"] == "completed"
    data = _risks(owner, sid)
    assert data["active"] == [] and data["clarifications"]  # вместо риска — вопрос для уточнения


def test_same_risk_from_two_questions_is_one_row_with_two_sources(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    ask(owner, sid, "Ещё раз: у нас нет политики обработки персональных данных.")
    active = _risks(owner, sid)["active"]
    assert len(active) == 1 and len(active[0]["question_ids"]) == 2


def test_manual_ps_survives_agent_answers_and_divergence_becomes_suggestion(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    r = _risks(owner, sid)["active"][0]
    assert (r["p"], r["s"], r["manual_ps"]) == (4, 2, False)
    upd = owner.patch(f"/risks/{r['id']}", json={"p": 2, "s": 1, "reason": "Политика уже на согласовании", "version": r["version"]})
    assert upd.status_code == 200 and (upd.json()["p"], upd.json()["s"], upd.json()["score"], upd.json()["level"]) == (2, 1, 2, "low")
    for i in range(5):  # пять последующих ответов агента по тому же риску
        ask(owner, sid, f"Уточнение {i}: у нас нет политики обработки персональных данных.")
    r = _risks(owner, sid)["active"][0]
    assert (r["p"], r["s"], r["manual_ps"]) == (2, 1, True)  # ручная оценка не перезаписана
    assert r["pending_suggestion"] and (r["pending_suggestion"]["p"], r["pending_suggestion"]["s"]) == (4, 2)
    acc = owner.post(f"/risks/{r['id']}/suggestion/accept").json()
    assert (acc["p"], acc["s"], acc["pending_suggestion"]) == (4, 2, None)
    events = owner.get(f"/risks/{r['id']}").json()["events"]
    assert any("Принято предложение агента" in e["reason"] for e in events)
    assert owner.post(f"/risks/{r['id']}/suggestion/reject").status_code == 409  # предложения больше нет


def test_status_change_recolors_graph_and_summary(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    r = _risks(owner, sid)["active"][0]
    q = next(n for n in owner.get(f"/sessions/{sid}/graph").json()["nodes"] if n["kind"] == "question")
    assert q["risk_level"] == "medium" and q["risk_count"] == 1
    assert owner.patch(f"/risks/{r['id']}", json={"status": "resolved", "reason": "Политика опубликована", "version": r["version"]}).status_code == 200
    data = _risks(owner, sid)
    assert data["active"] == [] and data["resolved"][0]["closed_at"] and data["summary"]["closed"] == 1
    q = next(n for n in owner.get(f"/sessions/{sid}/graph").json()["nodes"] if n["kind"] == "question")
    assert q["risk_level"] is None and q["resolved_level"] == "medium" and q["risk_count"] == 0  # узел высветлен, след остался


def test_matrix_matches_list_and_manual_risk(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    manual = owner.post(f"/sessions/{sid}/risks", json={"title": "Нет договора с подрядчиком о правах на код", "p": 3, "s": 3, "recommendation": "Заключить договор об отчуждении"})
    assert manual.status_code == 201 and manual.json()["origin"] == "user" and manual.json()["norms"] == []
    active = _risks(owner, sid)["active"]
    cells = owner.get(f"/sessions/{sid}/risks/matrix").json()
    assert len(cells) == 25 and sum(c["count"] for c in cells) == len(active) == 2
    cell = next(c for c in cells if (c["p"], c["s"]) == (3, 3))
    assert cell["count"] == 1 and cell["level"] == "medium" and cell["risks"][0]["title"].startswith("Нет договора")


def test_dismissed_status_needs_reason_and_closes_risk(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    r = owner.post(f"/sessions/{sid}/risks", json={"title": "Риск для проверки статуса", "p": 2, "s": 2}).json()
    bad = owner.patch(f"/risks/{r['id']}", json={"status": "dismissed", "reason": "", "version": r["version"]})
    assert bad.status_code == 422
    ok = owner.patch(f"/risks/{r['id']}", json={"status": "dismissed", "reason": "Сайта у нас нет", "version": r["version"]}).json()
    assert ok["status"] == "not_applicable" and ok["closed_at"]


def test_at_most_three_new_risks_per_answer(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    def five(res: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        base = res["risk_candidates"][0]
        types = ["pd_no_policy", "pd_no_consent", "pd_localization", "pd_no_notification", "pd_security_measures"]
        res["risk_candidates"] = [{**base, "risk_type": t, "scope": f"сценарий {i}", "title": f"Риск {i}", "proposed_p": 1 + i % 3, "proposed_s": 2} for i, t in enumerate(types)]
        return res

    _patch_analysis(monkeypatch, five)
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    active = _risks(owner, sid)["active"]
    assert len(active) == 3  # остальные — в лог, а не в таблицу
    assert sorted(r["score"] for r in active) == [4, 4, 6]  # из P × S = 2, 4, 6, 2, 4 оставлены три наибольших


def test_exports_and_user_plan_steps(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    step = owner.post(f"/sessions/{sid}/plan/steps", json={"title": "Согласовать текст оферты с бухгалтером"})
    assert step.status_code == 201
    assert owner.patch(f"/sessions/{sid}/plan/steps/{step.json()['id']}", json={"done": True}).json()["done"] is True
    owner.put(f"/sessions/{sid}/layout", json={"positions": {}, "filters": {}})  # сохранение раскладки не затирает шаги
    assert [s["title"] for s in owner.get(f"/sessions/{sid}/plan/steps").json()] == ["Согласовать текст оферты с бухгалтером"]

    c = owner.get(f"/sessions/{sid}/risks/export", params={"format": "csv"})
    assert c.status_code == 200 and "attachment" in c.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(c.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][:5] == ["Риск", "P", "S", "P×S", "Уровень"] and rows[1][0] == "Нет опубликованной политики обработки ПДн"
    assert any("не заменяют профессиональную юридическую помощь" in " ".join(r) for r in rows)
    md = owner.get(f"/sessions/{sid}/risks/export", params={"format": "md"}).text
    assert "## В ближайший месяц" in md and "- [ ]" in md and "- [x] Согласовать текст оферты с бухгалтером" in md


def test_foreign_risks_are_not_reachable(owner: Api, client: TestClient, demo: dict) -> None:
    alice = register(client, "alice", _invite(owner))
    bob = register(client, "bob", _invite(owner))
    sid = new_session(alice)
    ask(alice, sid, NO_POLICY)
    r = _risks(alice, sid)["active"][0]
    assert bob.get(f"/risks/{r['id']}").status_code == 404
    assert bob.patch(f"/risks/{r['id']}", json={"p": 1, "s": 1, "reason": "чужое", "version": r["version"]}).status_code == 404
    assert bob.post(f"/risks/{r['id']}/suggestion/accept").status_code == 404
    for path in (f"/sessions/{sid}/risks/matrix", f"/sessions/{sid}/risks/export", f"/sessions/{sid}/plan/steps"):
        assert bob.get(path).status_code == 404, path
    assert bob.post(f"/sessions/{sid}/risks", json={"title": "Чужой риск", "p": 1, "s": 1}).status_code == 404


def test_risk_thresholds_are_configurable(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings, reset_settings_cache
    from app.services.risks.scoring import level

    assert [level(x) for x in (4, 5, 9, 10, 15, 16)] == ["low", "medium", "medium", "high", "high", "critical"]
    monkeypatch.setenv("DOORAIN_RISK_THRESHOLDS", "[3, 8, 14]")
    reset_settings_cache()
    assert [level(x) for x in (3, 4, 8, 9, 14, 15)] == ["low", "medium", "medium", "high", "high", "critical"]
    with pytest.raises(ValueError, match="RISK_THRESHOLDS"):
        Settings(risk_thresholds=(9, 4, 15))


def test_role_scales_are_complete() -> None:
    from app.services.risks import scales

    for role in ("student", "entrepreneur", "expert"):
        sc = scales.load(role)
        assert sorted(sc["probability"]) == sorted(sc["severity"]) == [1, 2, 3, 4, 5] and sc["measure"]
    assert "экзамен" in scales.load("student")["severity"][5] and "вывод" in scales.load("expert")["measure"]
