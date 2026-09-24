"""П. 7 задания 24.09: синтетические акты выводятся из рабочей базы, основания в истории помечаются, пустая БЗ честно отказывает."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import Api, ask, new_session

NO_POLICY = "У нас нет политики обработки персональных данных на сайте."


def _retire(tmp: Path) -> dict[str, Any]:
    from app.core.config import get_settings
    from app.db.session import SessionLocal
    from app.providers.registry import get_providers
    from app.services.ingestion import kb

    db = SessionLocal()
    try:
        return kb.retire_demo(db, get_settings(), get_providers(), tmp / "retired-demo")
    finally:
        db.close()


def test_retire_demo_archives_history_and_empties_corpus(owner: Api, demo: dict, env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    risk = owner.get(f"/sessions/{sid}/risks").json()["active"][0]
    msgs_before = owner.get(f"/sessions/{sid}/messages").json()
    cid = msgs_before[-1]["citations"][0]["id"]

    out = _retire(env)
    report = json.loads(Path(out["report"]).read_text(encoding="utf-8"))
    assert len(report["documents"]) == 3 and len(report["revisions"]) == 4 and report["citations"] and report["sessions"] == [sid] and report["risks"][0]["id"] == risk["id"]  # отчёт: затронутые ID
    assert report["chunks"] and all(c["text"] for c in report["chunks"])  # резервная копия текстов
    actions = {i["action"] for i in out["items"]}
    assert actions == {"excluded", "removed"} and out["generation"] is None and "Корпус пуст" in out["note"]

    # рабочая БЗ пуста: документов в списке нет, статус — «корпус пуст», правовой вопрос честно отклоняется
    assert all(d["excluded"] for d in owner.get("/corpus/documents").json())  # в тестовом стенде видны как исключённые
    from app.core.config import reset_settings_cache

    monkeypatch.setenv("DOORAIN_PROVIDER_MODE", "ollama")
    reset_settings_cache()
    assert owner.get("/corpus/documents").json() == []  # в рабочем режиме выведенные тестовые акты не показываются вовсе
    monkeypatch.setenv("DOORAIN_PROVIDER_MODE", "test")
    reset_settings_cache()
    assert owner.get("/system/status").json()["corpus_empty"] is True
    snap = ask(owner, new_session(owner), "Нужно ли маркировать рекламу в интернете?")
    assert snap["answer_status"] == "refused" and snap["refusal_reason"] == "corpus_empty"

    # история: сообщения целы, основание помечено архивным, цитата открывается, риск больше не считается подтверждённым
    msgs = owner.get(f"/sessions/{sid}/messages").json()
    assert [m["role"] for m in msgs] == [m["role"] for m in msgs_before] and msgs[0]["text"] == msgs_before[0]["text"]
    blocks = msgs[-1]["blocks"]
    assert blocks[-1]["kind"] == "notice" and blocks[-1]["reason"] == "source_archived" and blocks[0]["text"] == msgs_before[-1]["blocks"][0]["text"]
    assert all(c["archived"] for c in msgs[-1]["citations"])
    assert owner.get(f"/citations/{cid}").json()["snapshot"]["archived"] is True
    data = owner.get(f"/sessions/{sid}/risks").json()
    assert data["active"] == [] and data["needs_clarification"][0]["id"] == risk["id"] and "выведено из базы знаний" in data["needs_clarification"][0]["clarification"]
    events = owner.get(f"/risks/{risk['id']}").json()["events"]
    assert any(e["kind"] == "evidence" and "Основание выведено" in e["reason"] for e in events)
    assert any(e["action"] == "corpus.demo_retired" for e in owner.get("/admin/audit").json())

    # повторный запуск ничего не меняет
    again = _retire(env)
    assert again["items"] == [] and again["report"] is None
    assert len(owner.get(f"/sessions/{sid}/messages").json()[-1]["blocks"]) == len(blocks)
    assert len(owner.get(f"/risks/{risk['id']}").json()["events"]) == len(events)


def test_retire_demo_keeps_real_documents_and_rebuilds_index(owner: Api, demo: dict, env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.models import Document
    from app.db.session import SessionLocal

    db = SessionLocal()
    real = db.query(Document).filter(Document.short_name == "ДЕМО-2-ФЗ").one()
    real.is_demo = False  # представим, что это подлинный документ администратора
    db.commit()
    db.close()
    out = _retire(env)
    assert out["generation"] and out["generation"]["control_search"]["passed"] == out["generation"]["control_search"]["checked"]
    docs = owner.get("/corpus/documents").json()
    assert [d["short_name"] for d in docs] == ["ДЕМО-2-ФЗ"] and owner.get("/system/status").json()["corpus_empty"] is False
    assert ask(owner, new_session(owner), "Нужно ли маркировать рекламу в интернете?")["answer_status"] == "validated"


def test_demo_cannot_be_imported_outside_test_mode(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import reset_settings_cache
    from app.demo import load_demo
    from tests.conftest import DEMO_DIR

    monkeypatch.setenv("DOORAIN_PROVIDER_MODE", "ollama")
    reset_settings_cache()
    with pytest.raises(RuntimeError, match="только в тестовом окружении"):
        load_demo(DEMO_DIR)


def test_demo_revisions_are_ignored_by_search_in_production_mode(owner: Api, demo: dict, env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Даже если синтетический акт остался в БД, вне тестового режима он не участвует в ответах."""
    from datetime import date

    from app.core.config import reset_settings_cache
    from app.db.session import SessionLocal
    from app.services.ingestion.indexer import active_generation, applicable_revisions

    db = SessionLocal()
    gen = active_generation(db)
    assert gen and applicable_revisions(db, gen, date(2026, 9, 20))
    monkeypatch.setenv("DOORAIN_PROVIDER_MODE", "ollama")
    reset_settings_cache()
    assert applicable_revisions(db, gen, date(2026, 9, 20)) == []
    db.close()
