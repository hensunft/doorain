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
    jobs.enqueue(db, "build_generation", {})
    db.commit()
    claimed = jobs.claim_next(db)
    assert claimed
    first = claimed.lease_until
    assert jobs.heartbeat(db, claimed, {"stage": "x"}) is False and claimed.lease_until >= first and claimed.progress == {"stage": "x"}
    jobs.request_cancel(db, claimed)
    assert jobs.heartbeat(db, claimed) is True
    db.close()


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
    """Короткая сессия с одним риском: три блока + сводка + приложение, ни одной реплики диалога."""
    sid = new_session(owner, profile={"sphere": "онлайн-школа", "has_site_or_app": "yes", "processes_pd": "yes", "servers_location": "abroad"})
    ask(owner, sid, NO_POLICY)
    ask(owner, sid, "Нужна ли политика обработки персональных данных на сайте?")
    ex = owner.post(f"/sessions/{sid}/exports", json={}).json()
    assert ex["status"] == "queued" and ex["incomplete"] is False
    run_jobs()
    st = owner.get(f"/exports/{ex['id']}").json()
    assert st["status"] == "ready" and st["size"] > 5000 and len(st["sha256"]) == 64
    dl = owner.get(f"/exports/{ex['id']}/download")
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/pdf" and dl.content.startswith(b"%PDF") and "attachment" in dl.headers["content-disposition"]
    assert "DoorAIn_" in dl.headers["content-disposition"] and ".pdf" in dl.headers["content-disposition"]
    text, pages = _pdf_text(dl.content)
    for must in ("Правовой слепок сессии", "Сводка", "1. Граф-слепок", "2. Риск-менеджмент", "3. Нормативные основания", "Приложение. Методика оценки",
                 "не заменяют профессиональную юридическую помощь", "Нет опубликованной политики обработки ПДн", "ДЕМО-1-ФЗ", "Предприниматель", "Вопрос №1", "Вопрос №2", "Матрица рисков 5 × 5", "Тестовый режим", sid):
        assert must in text, must
    # реплики диалога не попадают в документ ни целиком, ни частично; заголовка о диалоге нет
    for replica in ("У нас нет политики обработки", "Нужна ли политика", "диалог", "онлайн-школа"):
        assert replica not in text, replica
    assert pages >= 5
    # печатная тема: Playfair в заголовках, IBM Plex в тексте и реквизитах (встроенные подмножества шрифтов)
    fonts = {str(f["/BaseFont"]) for p in PdfReader(io.BytesIO(dl.content)).pages for f in p["/Resources"]["/Font"].values()}
    assert {"PlayfairDisplay", "IBMPlexSans", "IBMPlexMono"} <= {f.split("+")[-1].split("-")[0] for f in fonts}, fonts
    # снимок не меняется после последующих изменений сессии и корпуса
    risk = owner.get(f"/sessions/{sid}/risks").json()["active"][0]
    owner.patch(f"/risks/{risk['id']}", json={"status": "resolved", "reason": "Опубликовали", "version": risk["version"], "override": True})
    again = owner.get(f"/exports/{ex['id']}/download")
    assert again.content == dl.content
    assert "Закрытые риски" not in _pdf_text(again.content)[0]
    # скачивание требует действующей сессии входа при каждом обращении
    token = owner.c.cookies.get("doorain_session")
    owner.post("/auth/logout")
    from fastapi.testclient import TestClient

    anon = TestClient(owner.c.app)
    assert anon.get(f"/api/v1/exports/{ex['id']}/download").status_code == 401
    anon.cookies.set("doorain_session", token)
    assert anon.get(f"/api/v1/exports/{ex['id']}/download").status_code == 401


def test_export_empty_session_says_no_risks(owner: Api, demo: dict) -> None:
    """Пустая сессия: честная строка вместо пустой матрицы и пустого графа."""
    sid = new_session(owner)
    ex = owner.post(f"/sessions/{sid}/exports", json={}).json()
    run_jobs()
    text, pages = _pdf_text(owner.get(f"/exports/{ex['id']}/download").content)
    assert "Рисков не выявлено" in text and "слепок пуст" in text and "не опирались на документы" in text
    assert "Матрица рисков" not in text and pages >= 5


def test_export_bases_come_only_from_answer_traces(owner: Api, demo: dict, env: Path) -> None:
    """Норма-призрак: основание, которого не было в ответах этой сессии, в документ не попадает."""
    from app.db.session import SessionLocal
    from app.services.exports.pdf import build_snapshot, render_pdf

    other = new_session(owner)
    ask(owner, other, NO_POLICY)
    sid = new_session(owner)
    ask(owner, sid, NO_POLICY)
    db = SessionLocal()
    mine = list(db.scalars(select(m.Citation).where(m.Citation.session_id == uuid.UUID(sid))))
    cited = {x.snapshot["locator"] for x in mine}
    # цитата другой сессии на фрагмент, которого в ответах этой сессии не было
    chunk = next(c for c in db.scalars(select(m.Chunk)) if c.locator not in cited)
    rev = db.get(m.DocumentRevision, chunk.revision_id)
    run = db.scalar(select(m.GenerationRun).where(m.GenerationRun.session_id == uuid.UUID(other)))
    assert rev and run
    ghost = m.Citation(run_id=run.id, session_id=run.session_id, marker="C99", chunk_id=chunk.id, revision_id=rev.id, document_id=rev.document_id,
                       snapshot={**mine[0].snapshot, "locator": chunk.locator}, excerpt=chunk.text[:200])
    db.add(ghost)
    db.flush()
    risk = db.scalar(select(m.Risk).where(m.Risk.session_id == uuid.UUID(sid)))
    assert risk
    db.add(m.RiskEvidence(risk_id=risk.id, role="context", kind="obligation", ref_id=ghost.id))  # подложное основание
    db.commit()
    s = db.get(m.ConsultationSession, uuid.UUID(sid))
    assert s
    snap = build_snapshot(db, s, {}, None)
    db.close()
    assert {a["locator"] for b in snap["bases"] for a in b["articles"]} <= cited
    assert all(ghost.snapshot["locator"] not in n for r in snap["risks"] for n in r["norms"])
    out = env / "ghost.pdf"
    render_pdf(snap, out)
    assert f"{ghost.snapshot['short_name']}, {ghost.snapshot['locator']}" not in _pdf_text(out.read_bytes())[0]


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


def _big_snapshot(topics: int, per_topic: int, risks: int) -> dict[str, Any]:
    """Синтетический снимок большой сессии: темы × вопросы, нормы и риски разных уровней."""
    from app.services.risks import scales

    levels = ["critical", "high", "high", "medium", "medium", "low", "low", "medium"]
    ps = {"critical": (4, 5), "high": (4, 3), "medium": (3, 3), "low": (2, 2)}
    nodes: list[dict[str, Any]] = [{"id": "c", "kind": "center", "label": "Предприниматель", "weight": 1, "risk_level": None, "resolved_level": None, "risk_count": 0}]
    edges: list[dict[str, Any]] = []
    n = 0
    for t in range(topics):
        nodes.append({"id": f"t{t}", "kind": "topic", "label": f"Тема {t} персональные данные и сайт", "weight": per_topic, "risk_level": "high", "resolved_level": None, "risk_count": 2})
        edges.append({"source": f"t{t}", "target": "c", "kind": "belongs_to"})
        for q in range(per_topic):
            n += 1
            qid = f"q{n}"
            nodes.append({"id": qid, "kind": "question", "label": f"Вопрос №{n}", "num": n, "weight": 1, "risk_level": "medium" if q % 3 == 0 else None, "resolved_level": None, "risk_count": 0})
            edges.append({"source": qid, "target": f"t{t}", "kind": "asks_about"})
            if q % 2 == 0:
                nid = f"n{n}"
                nodes.append({"id": nid, "kind": "norm", "label": f"152-ФЗ, ст. {n} ч. 1 (ред. 01.03.2026)", "weight": 2, "risk_level": None, "resolved_level": None, "risk_count": 0})
                edges.append({"source": qid, "target": nid, "kind": "cites"})
            if n > 1 and q % 4 == 1:
                edges.append({"source": qid, "target": f"q{n - 1}", "kind": "follow_up_of"})
    rows = []
    for i in range(risks):
        lv = levels[i % len(levels)]
        p, s = ps[lv]
        title = f"Риск {i + 1}: штраф за обработку персональных данных без уведомления регулятора на сайте школы хвостXYZ{i}"
        rid, qn = f"r{i}", 1 + i * 2
        nodes.append({"id": rid, "kind": "risk", "label": title, "weight": 2, "risk_level": lv, "resolved_level": None, "risk_count": 0, "status": "open"})
        edges += [{"source": f"q{qn}", "target": rid, "kind": "evidences"}, {"source": rid, "target": f"n{qn}", "kind": "grounded_in"}]
        rows.append({"id": rid, "kind": "legal", "origin": "agent", "title": title, "status": "open", "p": p, "s": s, "score": p * s, "level": lv,
                     "norms": [f"152-ФЗ, ст. {qn} ч. 1 (ред. 01.03.2026)"], "consequences": "Штраф по КоАП РФ", "recommendation": "Направьте уведомление в течение 10 дней",
                     "clarification": None, "resolution_reason": None, "closed_at": None})
    rows.sort(key=lambda r: (-["low", "medium", "high", "critical"].index(r["level"]), -r["score"]))
    return {
        "schema": 2, "created_at": "2026-09-21T10:00:00+00:00", "incomplete": False, "incomplete_reason": None,
        "session": {"id": "00000000-0000-0000-0000-000000000042", "title": "Большая сессия: онлайн-школа", "role": "entrepreneur", "as_of_date": "2026-09-20", "version": 9},
        "summary": {"task": "Консультация в роли «Предприниматель».", "by_level": {"low": 2, "medium": 3, "high": 2, "critical": 1}, "top": rows[:3], "acts_line": "Задействовано нормативных актов: 1."},
        "graph": {"nodes": nodes, "edges": edges}, "risks": rows, "closed": [], "needs_clarification": [],
        "bases": [{"group": "law", "title": "Федеральный закон «О персональных данных»", "requisites": "№ 152-ФЗ · от 27.07.2006 · ред. от 01.03.2026", "archived": False,
                   "articles": [{"locator": f"ст. {i} ч. 1", "questions": [i], "risks": []} for i in range(1, 20, 2)]}],
        "scales": scales.load("entrepreneur"), "thresholds": [4, 9, 15], "corpus": {"generation_seq": 3}, "test_mode": False, "versions": {},
        "disclaimer": "Ответы носят информационный характер", "archived": False,
    }


def test_pdf_large_session_splits_graph_by_topic_and_is_reproducible(env: Path) -> None:
    """Объёмная сессия (30+ узлов, 8 рисков): граф по темам, подписи не обрезаются, повторный рендер побайтово тот же."""
    from app.services.exports.pdf import render_pdf

    snap = _big_snapshot(topics=4, per_topic=9, risks=8)
    assert len(snap["graph"]["nodes"]) > 40
    out, again = env / "big.pdf", env / "big2.pdf"
    render_pdf(snap, out)
    render_pdf(snap, again)
    assert out.read_bytes() == again.read_bytes()  # воспроизводимость (дата — часть снимка)
    text, pages = _pdf_text(out.read_bytes())
    assert pages >= 6 and "стр. " in text
    assert "Тема: Тема 3 персональные данные и сайт" in text and "Вопрос №36" in text  # граф — текстом, поиск работает
    assert all(f"хвостXYZ{i}" in text for i in range(8))  # длинные подписи переносятся, а не обрезаются
    assert "…" not in text
    small = _big_snapshot(topics=2, per_topic=8, risks=8)
    assert len(small["graph"]["nodes"]) > 30
    out3 = env / "mid.pdf"
    render_pdf(small, out3)
    assert "Тема: " not in _pdf_text(out3.read_bytes())[0]  # до 40 узлов — одна схема без врезок
