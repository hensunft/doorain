from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pytest
import yaml

from app.core.config import get_settings
from app.services.ingestion import parsers
from tests.conftest import DEMO_DIR, Api, run_jobs

_ACT = "ФЕДЕРАЛЬНЫЙ ЗАКОН\nСтатья 1. Предмет\n{first}\nСтатья 2. Термины\n{second}"
META = {"doc_type": "npa", "title": "ДЕМО-ЗАКОН О защите условных данных", "short_name": "ДЕМО-1-ФЗ", "act_number": "ДЕМО-1-ФЗ", "act_date": "2025-03-01", "revision_date": "2025-03-01", "verified_at": "2025-03-05", "topics": ["personal_data"]}


def _upload(api: Api, name: str, data: bytes) -> dict:
    r = api.post("/corpus/uploads", files={"file": (name, data, "application/octet-stream")})
    assert r.status_code == 201, r.text
    run_jobs()
    return api.get(f"/corpus/uploads/{r.json()['id']}").json()


def test_parsers_txt_html_docx_pdf(env: Path) -> None:
    s = get_settings()
    d = env / "x"
    d.mkdir()
    (d / "a.txt").write_text("Статья 1. Определения\nТекст статьи, достаточно длинный для проверки извлечения. " * 6, encoding="cp1251")
    assert "Статья 1" in parsers.parse(d / "a.txt", "a.txt", s).pages[0]
    (d / "a.html").write_text("<html><head><script>alert(1)</script><style>x{}</style></head><body><p>Статья 2.</p><img src='http://evil/x.png'><script>steal()</script><p>Обычный текст закона, длинный текст для проверки. " + "слово " * 60 + "</p></body></html>", encoding="utf-8")
    text = parsers.parse(d / "a.html", "a.html", s).pages[0]
    assert "alert" not in text and "steal" not in text and "evil" not in text and "Статья 2." in text
    from docx import Document

    doc = Document()
    doc.add_paragraph("Статья 3. Из DOCX. " + "Обязанность оператора. " * 20)
    doc.save(str(d / "a.docx"))
    assert "Статья 3" in parsers.parse(d / "a.docx", "a.docx", s).pages[0]
    from pypdf import PdfWriter
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(TTFont("T", str(Path(__file__).resolve().parents[1] / "app/assets/fonts/DejaVuSans.ttf")))
    c = canvas.Canvas(str(d / "a.pdf"), pagesize=A4)
    c.setFont("T", 11)
    c.drawString(50, 800, "Статья 4. Из PDF с текстовым слоем. " + "слово " * 30)
    c.showPage()
    c.drawString(50, 800, "Вторая страница документа. " + "текст " * 30)
    c.save()
    pr = parsers.parse(d / "a.pdf", "a.pdf", s)
    assert pr.paginated and len(pr.pages) == 2 and "Статья 4" in pr.pages[0]
    blank = PdfWriter()
    blank.add_blank_page(width=200, height=200)
    with (d / "scan.pdf").open("wb") as fh:
        blank.write(fh)
    with pytest.raises(parsers.UnsupportedDocument, match="текстов"):
        parsers.parse(d / "scan.pdf", "scan.pdf", s)


def test_docx_zip_bomb_rejected(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import zipfile

    monkeypatch.setenv("DOORAIN_MAX_DOCX_UNPACKED_MB", "1")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    p = env / "bomb.docx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<w/>")
        z.writestr("word/big.bin", b"\0" * 5_000_000)
    with pytest.raises(parsers.UnsupportedDocument):
        parsers.parse(p, "bomb.docx", get_settings())


def test_upload_limits_and_safe_names(owner: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    r = owner.post("/corpus/uploads", files={"file": ("evil.exe", b"MZ" + b"\0" * 100, "application/octet-stream")})
    assert r.status_code == 415
    r = owner.post("/corpus/uploads", files={"file": ("a.txt", b"", "text/plain")})
    assert r.status_code == 422
    r = owner.post("/corpus/uploads", files={"file": ("a.docx", b"PK\x03\x04junk", "application/zip")})
    assert r.status_code in (201, 415)
    monkeypatch.setenv("DOORAIN_MAX_UPLOAD_MB", "1")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    assert owner.post("/corpus/uploads", files={"file": ("big.txt", b"a" * (1024 * 1024 + 10), "text/plain")}).status_code == 413
    reset_settings_cache()
    d = _upload(owner, "../../etc/passwd.txt", ("Статья 1. Тест\nТекст " * 40).encode())
    stored = Path(get_settings().uploads_dir)
    assert d["filename"] == "passwd.txt" and all(stored in p.parents for p in stored.rglob("*") if p.is_file())


def test_import_flow_revisions_generation_and_compare(owner: Api) -> None:
    d1 = _upload(owner, "act2025.txt", (DEMO_DIR / "demo-data-act-2025.txt").read_bytes())
    assert d1["status"] == "ready" and d1["preview"]["guess"]["act_number"] == "ДЕМО-1-ФЗ" and d1["preview"]["stats"]["articles"] == 6
    assert d1["preview"]["guess"]["revision_date"] == "2025-03-01"
    bad = owner.post(f"/corpus/uploads/{d1['id']}/confirm", json={**META, "doc_type": "textbook"})
    assert bad.status_code == 422 and bad.json()["code"] == "edition_required"
    ok = owner.post(f"/corpus/uploads/{d1['id']}/confirm", json=META)
    assert ok.status_code == 200 and ok.json()["created"] is True
    rev1 = ok.json()["revision_id"]
    again = owner.post(f"/corpus/uploads/{d1['id']}/confirm", json=META)  # идемпотентно
    assert again.json()["created"] is False and again.json()["revision_id"] == rev1
    d1b = _upload(owner, "act2025-copy.txt", (DEMO_DIR / "demo-data-act-2025.txt").read_bytes())  # тот же материал, новый файл
    same = owner.post(f"/corpus/uploads/{d1b['id']}/confirm", json=META)
    assert same.json()["created"] is False and same.json()["revision_id"] == rev1
    run_jobs()
    ov = owner.get("/corpus/overview").json()
    assert ov["revisions"] == 1 and ov["active_generation"]["status"] == "ready" and ov["active_generation"]["control_search"]["passed"] == ov["active_generation"]["control_search"]["checked"] >= 1
    # вторая редакция
    d2 = _upload(owner, "act2026.txt", (DEMO_DIR / "demo-data-act-2026.txt").read_bytes())
    r2 = owner.post(f"/corpus/uploads/{d2['id']}/confirm", json={**META, "revision_date": "2026-03-01", "verified_at": None})
    assert r2.json()["created"] is True
    rev2 = r2.json()["revision_id"]
    # та же дата редакции, другое содержимое → конфликт (редакции неизменяемы)
    d3 = _upload(owner, "fake.txt", (DEMO_DIR / "demo-data-act-2026.txt").read_text(encoding="utf-8").replace("ответственного лица", "иного лица").encode())
    conflict = owner.post(f"/corpus/uploads/{d3['id']}/confirm", json={**META, "revision_date": "2026-03-01"})
    assert conflict.status_code == 409 and conflict.json()["code"] == "revision_exists"
    run_jobs()
    ov = owner.get("/corpus/overview").json()
    assert ov["revisions"] == 2 and len(ov["generations"]) == 2 and ov["active_generation"]["seq"] == 2
    docs = owner.get("/corpus/documents").json()
    assert len(docs) == 1 and len(docs[0]["revisions"]) == 2
    diff = owner.get("/corpus/compare", params={"left": rev1, "right": rev2}).json()
    assert diff["summary"]["changed"] == 1 and diff["items"][0]["locator"] == "ст. 7"
    ins = " ".join(o["text"] for o in diff["items"][0]["ops"] if o["op"] == "insert")
    dele = " ".join(o["text"] for o in diff["items"][0]["ops"] if o["op"] == "delete")
    assert "Публикация" in ins and "не допускается" in ins and "либо обеспечить" in dele
    # сравнивать можно только реально загруженные редакции
    import uuid

    assert owner.get("/corpus/compare", params={"left": rev1, "right": str(uuid.uuid4())}).status_code == 404
    hits = owner.get("/corpus/search", params={"q": "ст. 7"}).json()
    assert hits and all("ст. 7" in h["locator"] for h in hits)


def test_applicable_revisions_by_date(owner: Api, demo: dict) -> None:
    from app.db.session import SessionLocal
    from app.services.ingestion.indexer import active_generation, applicable_revisions

    db = SessionLocal()
    gen = active_generation(db)
    assert gen is not None
    def dates(d: date) -> set[str]:
        return {str(r.revision_date) for r in applicable_revisions(db, gen, d) if r.revision_date and r.revision_date.year >= 2025 and "ДЕМО-1" in (db.get(__import__("app.db.models", fromlist=["Document"]).Document, r.document_id).act_number or "")}
    assert dates(date(2025, 6, 1)) == {"2025-03-01"}
    assert dates(date(2026, 9, 20)) == {"2026-03-01"}  # действует последняя редакция
    assert dates(date(2024, 1, 1)) == set()
    db.close()


def test_generation_is_idempotent_and_reuses_embeddings(owner: Api, demo: dict) -> None:
    from sqlalchemy import func, select

    from app.db.models import ChunkIndex, CorpusGeneration
    from app.db.session import SessionLocal
    from app.providers.registry import get_providers
    from app.services.ingestion.indexer import build_generation

    db = SessionLocal()
    n_idx = db.scalar(select(func.count()).select_from(ChunkIndex))
    g1 = build_generation(db, get_providers(), get_settings())
    assert db.scalar(select(func.count()).select_from(CorpusGeneration)) == 1 and db.scalar(select(func.count()).select_from(ChunkIndex)) == n_idx
    assert g1.status == "ready"
    db.close()


def test_textbook_requires_license_and_edition(owner: Api) -> None:
    body = ("Глава 1 Введение\n" + "Учебный текст об информационном праве. " * 20).encode()
    d = _upload(owner, "book.txt", body)
    assert d["status"] == "ready"
    m = {"doc_type": "textbook", "title": "Учебник по IT-праву"}
    assert owner.post(f"/corpus/uploads/{d['id']}/confirm", json={**m, "edition": "2-е изд."}).json()["code"] == "license_required"
    ok = owner.post(f"/corpus/uploads/{d['id']}/confirm", json={**m, "edition": "2-е изд., 2024", "license_note": "Открытая лицензия автора", "build_index": False})
    assert ok.status_code == 200
    ch = owner.get(f"/corpus/revisions/{ok.json()['revision_id']}/chunks").json()
    assert ch and ch[0]["kind"] == "section"


def test_manifest_statuses(owner: Api) -> None:
    items = owner.get("/corpus/manifest").json()
    assert {i["status"] for i in items} == {"missing"} and any(i["tier"] == "start" for i in items) and len(items) >= 16
    d = _upload(owner, "fz152.txt", ("О персональных данных\n№ 152-ФЗ\nСтатья 1. Тест\nТекст статьи. " + "слово " * 60 + "\nСтатья 2. Второй\n" + "текст статьи. " * 20).encode())
    owner.post(f"/corpus/uploads/{d['id']}/confirm", json={"doc_type": "npa", "title": "О персональных данных", "act_number": "152-ФЗ", "revision_date": "2024-01-01", "build_index": False})
    st = {i["id"]: i["status"] for i in owner.get("/corpus/manifest").json()}
    assert st["fz-152"] == "imported" and st["fz-149"] == "missing"


def test_original_file_served_as_attachment(owner: Api, demo: dict) -> None:
    rid = demo["revisions"][0]["revision_id"]
    r = owner.get(f"/revisions/{rid}/file")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment") and r.headers["x-content-type-options"] == "nosniff"
    assert io.BytesIO(r.content).getbuffer().nbytes > 100


def test_retrieval_smoke(owner: Api, demo: dict) -> None:
    """Чек-лист исправности поиска: падает, если коллекция пуста или контрольный запрос ничего не находит."""
    from app.db.session import SessionLocal
    from app.providers.registry import get_providers
    from app.services.ingestion import doctor
    from app.services.ingestion.indexer import active_generation

    db, p, s = SessionLocal(), get_providers(), get_settings()
    rep = doctor.summary(db, p, s, date(2026, 9, 20))
    assert rep["ok"] and not rep["critical_failed"], rep["checks"]
    by_id = {c["id"]: c for c in rep["checks"]}
    assert by_id["collection"]["data"]["points"] > 0
    assert by_id["dim"]["ok"] and by_id["metric"]["ok"] and by_id["same_model"]["ok"]
    assert by_id["raw_search"]["ok"] and by_id["guardrail_order"]["ok"]
    assert by_id["chunks"]["data"]["short"] == 0

    p.vs.drop(active_generation(db).collection_name)  # пустая коллекция обязана валить чек-лист
    broken = doctor.summary(db, p, s, date(2026, 9, 20))
    assert not broken["ok"] and "collection" in broken["critical_failed"] and "raw_search" in broken["critical_failed"]
    db.close()


def test_kb_requires_license_and_reports_summary(owner: Api, env: Path) -> None:
    """Документ без основания включения не индексируется; после импорта печатается сводка."""
    from app.core.errors import ApiError
    from app.db.session import SessionLocal
    from app.providers.registry import get_providers
    from app.services.ingestion import kb

    db, s, p = SessionLocal(), get_settings(), get_providers()
    src = env / "act.txt"
    src.write_text(_ACT.format(first="Текст первой статьи закона. " * 12, second="Текст второй статьи закона. " * 12), encoding="utf-8")
    with pytest.raises(ApiError) as e:
        kb.add(db, s, p, str(src), {"title": "Тестовый акт", "act_number": "999-ФЗ"}, build=False)
    assert e.value.code == "license_required"

    out = kb.add(db, s, p, str(src), {"title": "Тестовый акт", "act_number": "999-ФЗ", "license": "public_domain_official", "revision_date": "2026-01-01"}, build=False)
    assert out["created"] and out["chunks"] >= 2 and out["avg_chars"] > 0 and out["sample"]
    assert [d for d in kb.documents(db) if d["act_number"] == "999-ФЗ"][0]["license_note"].endswith("[public_domain_official]")

    src2 = env / "act2.txt"
    src2.write_text(_ACT.format(first="Изменённый текст первой статьи. " * 12, second="Текст второй статьи закона. " * 12), encoding="utf-8")
    doc_id = [d for d in kb.documents(db) if d["act_number"] == "999-ФЗ"][0]["document_id"]
    upd = kb.update_revision(db, s, p, doc_id, str(src2), "2026-06-01")
    assert upd["superseded"] == 1 and len([d for d in kb.documents(db) if d["act_number"] == "999-ФЗ"][0]["revisions"]) == 2
    db.close()


def test_manifest_yaml_declares_license_for_every_item() -> None:
    from app.services.ingestion import kb

    items = kb.load_manifest(get_settings())
    assert len(items) >= 16
    assert all(i["license"] in kb.LICENSES for i in items)
    assert {i["layer"] for i in items} == {1, 2, 3}
    assert all(i.get("pravo_nd") for i in items if i["tier"] == "start")


def test_golden_set_covers_roles_and_traps(owner: Api, demo: dict) -> None:
    from app.db.session import SessionLocal
    from app.providers.registry import get_providers
    from app.services.ingestion import golden

    path = Path(__file__).resolve().parent / "eval" / "golden_set.yaml"
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 40
    assert {r: sum(1 for c in cases if c["role"] == r and c["expect"] == "answer") for r in ("student", "entrepreneur", "expert")} == {"student": 10, "entrepreneur": 10, "expert": 10}
    assert sum(1 for c in cases if c["expect"] == "refusal") == 10
    assert all(c.get("expect_acts") for c in cases if c["expect"] == "answer")

    db, p, s = SessionLocal(), get_providers(), get_settings()
    rep = golden.run(db, s, p, path, env_out := (Path(str(get_settings().data_dir)) / "eval"))
    assert rep["metrics"]["answerable"] == 30 and rep["metrics"]["honest_refusals"]["of"] == 10
    assert any("демонстрационные" in c for c in rep["caveats"])  # демо-корпус помечается
    assert Path(rep["report_path"]).is_file() and env_out.is_dir()
    db.close()
