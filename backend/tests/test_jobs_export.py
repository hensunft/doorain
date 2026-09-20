from __future__ import annotations

import io
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.core.errors import ApiError
from app.core.util import now
from app.db import models as m
from app.db.session import SessionLocal
from app.services import jobs
from tests.conftest import Api, ask, new_session, run_jobs

NO_POLICY = "У нас нет политики обработки персональных данных на сайте."


def _pdf_text(data: bytes) -> tuple[str, int]:
    r = PdfReader(io.BytesIO(data))
    return " ".join(" ".join((p.extract_text() or "").split()) for p in r.pages), len(r.pages)


def test_lease_expiry_requeues_then_fails_after_max_attempts(env: Path) -> None:
    db = SessionLocal()
    j = jobs.enqueue(db, "parse_document", {"draft_id": str(uuid.uuid4())})
    db.commit()
    for attempt in (1, 2, 3):
        claimed = jobs.claim_next(db)
        assert claimed and claimed.id == j.id and claimed.attempts == attempt and claimed.status == "running"
        claimed.lease_until = now() - timedelta(seconds=1)  # worker «умер»: lease истёк
        db.commit()
        jobs.reap_expired(db)
        db.refresh(j)
    assert j.status == "failed" and "попытки" in (j.error or "")
    assert jobs.claim_next(db) is None
    db.close()


def test_heartbeat_extends_lease_and_reports_cancel(env: Path) -> None:
    db = SessionLocal()
    j = jobs.enqueue(db, "build_generation", {})
    db.commit()
    claimed = jobs.claim_next(db)
    assert claimed
    first = claimed.lease_until
    assert jobs.heartbeat(db, claimed, {"stage": "x"}) is False and claimed.lease_until >= first and claimed.progress == {"stage": "x"}
    jobs.request_cancel(db, claimed)
    assert jobs.heartbeat(db, claimed) is True
    db.close()
    _ = j


def test_idempotency_key_and_queue_limit(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOORAIN_MAX_ACTIVE_JOBS", "2")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    db = SessionLocal()
    a = jobs.enqueue(db, "export_pdf", {}, idempotency_key="k1")
    b = jobs.enqueue(db, "export_pdf", {}, idempotency_key="k1")
    assert a.id == b.id
    jobs.enqueue(db, "export_pdf", {}, idempotency_key="k2")
    with pytest.raises(ApiError) as e:
        jobs.enqueue(db, "export_pdf", {}, idempotency_key="k3")
    assert e.value.status == 429 and e.value.code == "queue_full"
    jobs.enqueue(db, "build_generation", {}, limit=False)  # служебное задание не блокируется лимитом пользователя
    db.close()


def test_worker_crash_does_not_leave_run_stuck(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.worker import main as w

    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("worker crashed")

    monkeypatch.setitem(w.HANDLERS, "chat_run", boom)
    sid = new_session(owner)
    r = owner.post(f"/sessions/{sid}/messages", json={"text": NO_POLICY, "client_request_id": "crash-" + uuid.uuid4().hex})
    run_jobs()
    snap = owner.get(f"/runs/{r.json()['run_id']}").json()
    assert snap["answer_status"] == "failed" and snap["error_code"] == "internal_error"
    assert owner.get(f"/sessions/{sid}").json()["busy"] is False  # сессия не заблокирована


def test_interrupted_run_is_restarted_without_duplicates(owner: Api, demo: dict) -> None:
    """Сбой worker в середине run: lease истёк → повтор; частичные цитаты очищаются, результат канонический."""
    sid = new_session(owner)
    r = owner.post(f"/sessions/{sid}/messages", json={"text": NO_POLICY, "client_request_id": "restart-" + uuid.uuid4().hex}).json()
    db = SessionLocal()
    job = jobs.claim_next(db)  # «worker» взял задание и упал, не завершив
    assert job and job.run_id
    run = db.get(m.GenerationRun, job.run_id)
    assert run
    run.answer_status = "running"
    db.add(m.Citation(run_id=run.id, session_id=sid and uuid.UUID(sid), marker="C1", chunk_id=None, revision_id=db.scalar(select(m.DocumentRevision.id)), document_id=db.scalar(select(m.Document.id)), snapshot={}, excerpt="частичное"))
    job.lease_until = now() - timedelta(seconds=5)
    db.commit()
    db.close()
    run_jobs()
    snap = owner.get(f"/runs/{r['run_id']}").json()
    assert snap["answer_status"] == "validated" and snap["analysis_status"] == "completed"
    db = SessionLocal()
    assert not [c for c in db.scalars(select(m.Citation)) if c.excerpt == "частичное"]
    assert len(list(db.scalars(select(m.Message).where(m.Message.role == "assistant")))) == 1
    db.close()
    evs = owner.get(f"/runs/{r['run_id']}").json()
    assert evs["blocks"]


def test_export_pdf_content_snapshot_and_auth(owner: Api, demo: dict) -> None:
    sid = new_session(owner, profile={"sphere": "онлайн-школа", "has_site_or_app": "yes", "processes_pd": "yes", "servers_location": "abroad"})
    ask(owner, sid, NO_POLICY)
    ask(owner, sid, "Нужна ли политика обработки персональных данных на сайте?")
    ex = owner.post(f"/sessions/{sid}/exports", json={"include_dialog": True}).json()
    assert ex["status"] == "queued" and ex["incomplete"] is False
    run_jobs()
    st = owner.get(f"/exports/{ex['id']}").json()
    assert st["status"] == "ready" and st["size"] > 5000 and len(st["sha256"]) == 64
    dl = owner.get(f"/exports/{ex['id']}/download")
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/pdf" and dl.content.startswith(b"%PDF") and "attachment" in dl.headers["content-disposition"]
    text, pages = _pdf_text(dl.content)
    for must in ("Цифровой портрет правового положения", "не заменяют профессиональную юридическую помощь", "Нет опубликованной политики обработки ПДн", "Демонстрационные данные — не нормативная база", "ДЕМО-1-ФЗ", "Таблица рисков", "Предприниматель", "онлайн-школа", "Приложение: диалог", "Нормативное основание", "Ограничения"):
        assert must in text, must
    assert pages >= 3
    # снимок не меняется после последующих изменений сессии и корпуса
    risk = owner.get(f"/sessions/{sid}/risks").json()["active"][0]
    owner.patch(f"/risks/{risk['id']}", json={"status": "resolved", "reason": "Опубликовали", "version": risk["version"]})
    again = owner.get(f"/exports/{ex['id']}/download")
    assert again.content == dl.content
    assert "Снят по сообщению" not in _pdf_text(again.content)[0]
    # скачивание требует действующей сессии входа при каждом обращении
    token = owner.c.cookies.get("doorain_session")
    owner.post("/auth/logout")
    from fastapi.testclient import TestClient

    anon = TestClient(owner.c.app)
    assert anon.get(f"/api/v1/exports/{ex['id']}/download").status_code == 401
    anon.cookies.set("doorain_session", token)
    assert anon.get(f"/api/v1/exports/{ex['id']}/download").status_code == 401


def test_export_incomplete_snapshot_requires_explicit_choice(owner: Api, demo: dict) -> None:
    sid = new_session(owner)
    owner.post(f"/sessions/{sid}/messages", json={"text": NO_POLICY, "client_request_id": "inc-" + uuid.uuid4().hex})  # run ещё не выполнен
    blocked = owner.post(f"/sessions/{sid}/exports", json={})
    assert blocked.status_code == 409 and blocked.json()["code"] == "analysis_pending"
    ex = owner.post(f"/sessions/{sid}/exports", json={"allow_incomplete": True}).json()
    assert ex["incomplete"] is True
    run_jobs()
    text, _ = _pdf_text(owner.get(f"/exports/{ex['id']}/download").content)
    assert "НЕПОЛНЫЙ СНИМОК" in text and "Неполный снимок" in text


def test_pdf_large_session_renders_wide_table_and_graph_pages(env: Path) -> None:
    from app.services.exports.pdf import render_pdf

    long = "Очень длинное название риска с кириллицей и цифрами 152-ФЗ, ст. 18.1 ч. 5 " * 3
    risks = [{"id": str(i), "kind": "legal", "title": f"{i}. {long}", "status": "open", "p": 4, "s": 3, "score": 12, "level": "high", "category": "Персональные данные", "scenario": "сайт школы " * 5, "conditions": "", "consequences": "Штраф " * 30, "recommendation": "Опубликовать политику " * 8, "p_reason": "", "s_reason": "", "clarification": None, "resolution_reason": None, "resolved_by": None, "norms": [f"152-ФЗ, ст. {i}"], "version": 1} for i in range(1, 61)]
    nodes = [{"id": "c", "kind": "center", "label": "Предприниматель", "weight": 1, "risk_level": None, "data": {}}]
    edges: list[dict[str, Any]] = []
    for t in range(4):
        nodes.append({"id": f"t{t}", "kind": "topic", "label": f"Тема {t}", "weight": 5, "risk_level": "high", "data": {}})
        edges.append({"id": f"e{t}", "source": f"t{t}", "target": "c", "kind": "belongs_to", "data": {}})
        for q in range(15):
            qid = f"q{t}_{q}"
            nodes.append({"id": qid, "kind": "question", "label": f"Вопрос {t}.{q} " + "длинный текст " * 6, "weight": 1, "risk_level": "medium" if q % 3 == 0 else None, "data": {"result": "answered"}})
            edges.append({"id": f"a{qid}", "source": qid, "target": f"t{t}", "kind": "asks_about", "data": {}})
    from app.services.portrait.layout import radial

    pos = {k: list(v) for k, v in radial(nodes, edges).items()}
    snap = {"schema": 1, "created_at": "2026-09-20T10:00:00+00:00", "incomplete": False, "incomplete_reason": None, "session": {"id": "s", "title": "Большая сессия " * 4, "role": "entrepreneur", "as_of_date": "2026-09-20", "version": 9}, "profile": {"sphere": "школа"}, "include_dialog": False, "model": {"name": "qwen3", "digest": "abc", "quantization": "Q4_K_M", "provider": "ollama", "reranker": "x"}, "corpus": {"generation_seq": 3, "generation_id": "g", "activated_at": "2026-09-01T00:00:00+00:00", "revisions": []}, "questions": [{"question": f"Вопрос {i} " * 10, "claims": ["Утверждение " * 20], "refused": False, "sources": ["152-ФЗ, ст. 18.1"]} for i in range(40)], "graph": {"nodes": nodes, "edges": edges, "positions": pos}, "risks": risks, "needs_clarification": [], "resolved": [], "clarifications": [], "sources": [{"act": "152-ФЗ", "short_name": "152-ФЗ", "locator": f"ст. {i}", "revision_date": "2025-01-01", "edition": None, "page": None, "verified_at": "2025-02-01", "is_demo": False, "excerpt": "Текст нормы " * 40} for i in range(30)], "dialog": [], "versions": {}, "disclaimer": "d", "demo": False}
    out = env / "big.pdf"
    render_pdf(snap, out)
    text, pages = _pdf_text(out.read_bytes())
    assert pages >= 10
    assert text.count("Нормативное основание") >= 3  # заголовок таблицы повторяется на страницах
    assert "60." in text and "Слепок: Тема 3" in text  # большой граф: страницы по темам
    assert "стр. " in text
