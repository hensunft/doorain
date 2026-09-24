"""П. 3, 5, 12 задания 24.09: реквизиты оператора без выдумок, методика P×S из конфигурации, непокрытые темы в отказе."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import Api, ask, new_session


def test_legal_info_is_public_and_does_not_invent_operator_data(client: TestClient) -> None:
    r = TestClient(client.app).get("/api/v1/legal")
    assert r.status_code == 200  # без входа
    d = r.json()
    assert d["version"] and set(d["missing"]) >= {"name", "inn", "ogrn", "address", "email"}  # до заполнения оператором
    assert all(v == "" for v in d["operator"].values()) and d["owner_can_read_user_sessions"] is True and d["session_ttl_hours"] > 0


def test_risk_methodology_comes_from_backend_config(owner: Api) -> None:
    import yaml

    from app.core.config import RISK_CONFIG
    from app.services.risks import scales

    m = owner.get("/risk-methodology", params={"role": "student"}).json()
    low, mid, high = yaml.safe_load(RISK_CONFIG.read_text(encoding="utf-8"))["risk_thresholds"]
    assert [(x["level"], x["min"], x["max"]) for x in m["levels"]] == [("low", 1, low), ("medium", low + 1, mid), ("high", mid + 1, high), ("critical", high + 1, 25)]
    assert m["severity"] == {str(k): v for k, v in scales.load("student")["severity"].items()} and m["measure"] == scales.load("student")["measure"]
    assert any("не статистическая" in r for r in m["rules"]) and any("S от 3" in r for r in m["rules"])
    assert owner.get("/risk-methodology", params={"role": "hacker"}).status_code == 422
    assert TestClient(owner.c.app).get("/api/v1/risk-methodology").status_code == 401


def test_refusal_names_uncovered_topics_and_needed_acts(owner: Api) -> None:
    sid = new_session(owner)
    snap = ask(owner, sid, "Нужна ли политика обработки персональных данных на сайте?")
    assert snap["answer_status"] == "refused" and snap["refusal_reason"] == "corpus_empty"
    text = owner.get(f"/sessions/{sid}/messages").json()[-1]["text"]
    assert "Не покрыты базой знаний темы" in text and "Персональные данные" in text and "152-ФЗ" in text and "загружает администратор" in text
