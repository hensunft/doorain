"""Операционные команды внутри backend-образа: модели, режим обслуживания, backup/restore, проверки.

Хост-скрипты (scripts/doorain.ps1|sh) вызывают их через `docker compose exec/run`. Пути — Linux внутри контейнера,
поэтому бинарные дампы не проходят через текстовые pipeline PowerShell.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select, text, update

from . import __version__
from .core.config import get_settings
from .core.util import now
from .db.models import (
    AuthSession,
    Chunk,
    ChunkIndex,
    Citation,
    ConsultationSession,
    CorpusGeneration,
    Document,
    DocumentRevision,
    Job,
    LoginAttempt,
    Message,
    Risk,
)
from .db.session import SessionLocal
from .services import jobs
from .services.ingestion.indexer import active_generation, get_state, set_state

BACKUPS = Path(os.environ.get("DOORAIN_BACKUPS_DIR", "/backups"))


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _counts(db: Any) -> dict[str, int]:
    return {n: db.scalar(select(func.count()).select_from(m)) or 0 for n, m in (("documents", Document), ("revisions", DocumentRevision), ("chunks", Chunk), ("chunk_index", ChunkIndex), ("sessions", ConsultationSession), ("messages", Message), ("risks", Risk), ("citations", Citation))}


# ───────────── модели (подготовка с интернетом) ─────────────
def fetch_models(lock: Path, dest: Path, ollama: Path | None = None) -> None:
    from huggingface_hub import hf_hub_download, snapshot_download  # noqa: PLC0415

    spec = json.loads(lock.read_text(encoding="utf-8"))
    for m in spec["huggingface"]:
        target = dest / m["name"]
        print(f"→ {m['repo']}@{m['revision'][:8]} → {target}", flush=True)
        snapshot_download(repo_id=m["repo"], revision=m["revision"], local_dir=str(target), allow_patterns=m.get("allow_patterns"), ignore_patterns=m.get("ignore_patterns"))
        files = {str(p.relative_to(target)): _sha256(p) for p in sorted(target.rglob("*")) if p.is_file() and ".cache" not in p.parts}
        (target / ".doorain-lock.json").write_text(json.dumps({"repo": m["repo"], "revision": m["revision"], "license": m["license"], "files": files}, indent=1), encoding="utf-8")
        print(f"  файлов: {len(files)}", flush=True)
    # GGUF-модели кладутся прямо в хранилище Ollama под sha256: Modelfile (infra/ollama) ссылается на этот слой, второй копии нет.
    # `ollama pull hf.co/...` не подходит: Ollama 0.34 не идёт по перенаправлению Hugging Face на его CDN.
    if ollama is None:
        return
    for m in spec.get("gguf", []):
        blob = ollama / "models" / "blobs" / f"sha256-{m['sha256']}"
        if blob.exists():  # сюда файл попадает только после сверки хеша
            print(f"→ {m['file']}: уже в хранилище Ollama", flush=True)
            continue
        print(f"→ {m['repo']}@{m['revision'][:8]}/{m['file']} ({m['size'] / 1e9:.1f} ГБ) → {blob}", flush=True)
        tmp = Path(hf_hub_download(repo_id=m["repo"], filename=m["file"], revision=m["revision"], local_dir=str(ollama / "import")))
        if (got := _sha256(tmp)) != m["sha256"]:
            tmp.unlink()
            raise SystemExit(f"sha256 {m['file']} не совпал с lock: {got}")
        blob.parent.mkdir(parents=True, exist_ok=True)
        tmp.replace(blob)
        shutil.rmtree(ollama / "import", ignore_errors=True)


# ───────────── режим обслуживания ─────────────
def maintenance(on: bool, wait: bool, timeout: int) -> int:
    db = SessionLocal()
    try:
        set_state(db, "maintenance", {"on": on, "since": datetime.now(UTC).isoformat()})
        db.commit()
        if on and wait:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                active = db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(("queued", "running")))) or 0
                if not active:
                    return 0
                if time.monotonic() > deadline - timeout / 2:  # половина времени прошла — отменяем оставшиеся операции
                    for j in db.scalars(select(Job).where(Job.status.in_(("queued", "running")))):
                        jobs.request_cancel(db, j)
                time.sleep(1)
                db.expire_all()
            print("Активные задания не завершились за отведённое время", file=sys.stderr)
            return 3
        return 0
    finally:
        db.close()


def worker_alive() -> int:
    db = SessionLocal()
    try:
        hb = get_state(db, "worker").get("heartbeat")
        return 0 if hb and (datetime.now(UTC) - datetime.fromisoformat(hb)).total_seconds() < 30 else 1
    finally:
        db.close()


# ───────────── backup ─────────────
def backup_begin(bid: str, timeout: int) -> int:
    part = BACKUPS / f"{bid}.partial"
    if part.exists() or (BACKUPS / bid).exists():
        print(f"Backup {bid} уже существует", file=sys.stderr)
        return 2
    part.mkdir(parents=True)
    part.chmod(0o777)  # pg_dump выполняется в контейнере postgres (другой uid) и пишет файл в этот каталог
    rc = maintenance(True, True, timeout)
    if rc:
        shutil.rmtree(part, ignore_errors=True)
        maintenance(False, False, 0)
    return rc


def backup_finish(bid: str) -> int:
    s = get_settings()
    part = BACKUPS / f"{bid}.partial"
    dump = part / "db.dump"
    if not dump.is_file() or dump.stat().st_size < 1024:
        print("db.dump отсутствует или пуст: backup неполный", file=sys.stderr)
        return 2
    db = SessionLocal()
    try:
        gen = active_generation(db)
        rev = db.execute(text("select version_num from alembic_version")).scalar()
        # файлы (оригиналы и нормализованные документы, PDF-экспорты)
        with tarfile.open(part / "files.tar.gz", "w:gz") as tar:
            for sub in ("documents", "exports"):
                d = s.data_dir / sub
                if d.is_dir():
                    tar.add(d, arcname=sub)
        # Qdrant: snapshot каждой используемой коллекции
        collections: dict[str, Any] = {}
        used = {c for (c,) in db.execute(select(CorpusGeneration.collection_name).where(CorpusGeneration.status.in_(("ready", "retired"))))}
        for coll in sorted(used):
            snap = httpx.post(f"{s.qdrant_url}/collections/{coll}/snapshots", timeout=600).json()["result"]
            out = part / f"qdrant-{coll}.snapshot"
            with httpx.stream("GET", f"{s.qdrant_url}/collections/{coll}/snapshots/{snap['name']}", timeout=600) as r:
                r.raise_for_status()
                with out.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            info = httpx.get(f"{s.qdrant_url}/collections/{coll}", timeout=30).json()["result"]
            collections[coll] = {"file": out.name, "sha256": _sha256(out), "points": info.get("points_count"), "vectors": list(info["config"]["params"].get("vectors", {}).keys()), "sparse": list(info["config"]["params"].get("sparse_vectors", {}).keys())}
        model_digest: dict[str, Any] = {}
        try:
            r = httpx.get(f"{s.ollama_url}/api/tags", timeout=5)
            model_digest = {m["name"]: m.get("digest") for m in r.json().get("models", [])}
        except Exception:  # noqa: BLE001 — Ollama может быть остановлен; manifest назовёт нужную версию модели
            model_digest = {"unavailable": True}
        manifest = {
            "backup_id": bid, "created_at": datetime.now(UTC).isoformat(), "app_version": __version__, "schema_revision": rev,
            "image_versions": {k: os.environ.get(k, "") for k in ("DOORAIN_VERSION",)}, "required_models": {"llm": s.ollama_model, "ollama_digests": model_digest, "hf_lock": "infra/models.lock.json"},
            "corpus": {"generation_id": str(gen.id) if gen else None, "generation_seq": gen.seq if gen else None, "embedding_fingerprint": gen.fingerprint if gen else None, "fingerprint_hash": gen.fingerprint_hash if gen else None, "manifest_sha256": gen.manifest_sha256 if gen else None},
            "counts": _counts(db), "collections": collections,
            "files": {"db.dump": {"sha256": _sha256(dump), "size": dump.stat().st_size}, "files.tar.gz": {"sha256": _sha256(part / "files.tar.gz")}},
            "includes": ["postgresql dump (pg_dump -Fc)", "documents/exports files", "qdrant snapshots"], "excludes": ["ollama/hf model weights (см. required_models)", "secrets (.env)", "TLS certificates"],
            "password_hashes_included": True,
        }
        (part / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        part.rename(BACKUPS / bid)  # атомарная отметка: только полный набор считается backup
        print(json.dumps({"backup_id": bid, "counts": manifest["counts"], "collections": list(collections)}, ensure_ascii=False))
    finally:
        db.close()
        maintenance(False, False, 0)
    return 0


def backup_abort(bid: str) -> int:
    shutil.rmtree(BACKUPS / f"{bid}.partial", ignore_errors=True)
    return maintenance(False, False, 0)


def verify_backup(bid: str) -> dict[str, Any]:
    d = BACKUPS / bid
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    for name, meta in m["files"].items():
        if _sha256(d / name) != meta["sha256"]:
            raise SystemExit(f"Контрольная сумма {name} не совпадает")
    for coll, meta in m["collections"].items():
        if _sha256(d / meta["file"]) != meta["sha256"]:
            raise SystemExit(f"Контрольная сумма snapshot {coll} не совпадает")
    return m


# ───────────── restore (в НОВЫЕ volumes; дамп PostgreSQL уже восстановлен хост-скриптом) ─────────────
def restore_verify(bid: str) -> int:
    s = get_settings()
    m = verify_backup(bid)
    db = SessionLocal()
    try:
        set_state(db, "maintenance", {"on": True, "since": now().isoformat(), "reason": "restore"})
        db.commit()
        rev = db.execute(text("select version_num from alembic_version")).scalar()
        if rev != m["schema_revision"]:
            raise SystemExit(f"Ревизия схемы {rev} не совпадает с backup ({m['schema_revision']}): восстановите совместимую версию приложения")
        with tarfile.open(BACKUPS / bid / "files.tar.gz") as tar:
            tar.extractall(s.data_dir, filter="data")  # noqa: S202 — filter="data" блокирует выход за пределы каталога
        for coll, meta in m["collections"].items():
            with (BACKUPS / bid / meta["file"]).open("rb") as f:
                r = httpx.post(f"{s.qdrant_url}/collections/{coll}/snapshots/upload", params={"priority": "snapshot", "wait": "true"}, files={"snapshot": (meta["file"], f)}, timeout=900)
            r.raise_for_status()
            pts = httpx.get(f"{s.qdrant_url}/collections/{coll}", timeout=30).json()["result"].get("points_count")
            if pts != meta["points"]:
                raise SystemExit(f"Коллекция {coll}: точек {pts}, ожидалось {meta['points']}")
        counts = _counts(db)
        if counts != m["counts"]:
            raise SystemExit(f"Числа объектов не совпадают: {counts} ≠ {m['counts']}")
        problems = []
        for c in db.scalars(select(Citation)):  # старые цитаты: реквизиты, выдержка и редакция на месте
            if not c.snapshot.get("locator") or not c.excerpt or not db.get(DocumentRevision, c.revision_id):
                problems.append(str(c.id))
        for rev_row in db.scalars(select(DocumentRevision)):
            if not Path(rev_row.original_path).is_file() and not (s.data_dir / "documents" / str(rev_row.id)).exists():
                problems.append(f"file:{rev_row.id}")
        if problems:
            raise SystemExit(f"Проверка цитат/файлов не пройдена: {problems[:5]}")
        gen = active_generation(db)
        report: dict[str, Any] = {"backup_id": bid, "counts": counts, "citations_ok": True}
        if gen:
            from .providers.registry import get_providers  # noqa: PLC0415
            from .services.ingestion.indexer import control_search, fp_hash  # noqa: PLC0415

            p = get_providers()
            revs = list(db.scalars(select(DocumentRevision).where(DocumentRevision.status == "ready")))
            try:
                fp_ok = fp_hash(p.embedder.fingerprint()) == gen.fingerprint_hash
                report["embedding_compatible"] = fp_ok
                if fp_ok:
                    cs = control_search(db, p, gen, revs)
                    report["control_search"] = cs
                    if cs["passed"] != cs["checked"]:
                        raise SystemExit(f"Контрольный поиск не пройден: {cs}")
                else:
                    print("ВНИМАНИЕ: embedding fingerprint отличается — поиск заблокирован до переиндексации", file=sys.stderr)
            except SystemExit:
                raise
            except Exception as e:  # noqa: BLE001 — модели могут быть недоступны на новой машине
                report["control_search"] = f"пропущен: {type(e).__name__}"
        db.execute(update(AuthSession).values(revoked_at=now()).where(AuthSession.revoked_at.is_(None)))  # прежние web-сессии недействительны
        db.query(LoginAttempt).delete()
        set_state(db, "maintenance", {"on": False})
        db.commit()
        (BACKUPS / bid / "restore-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, default=str))
    finally:
        db.close()
    return 0


def list_backups() -> int:
    for d in sorted(BACKUPS.glob("*/manifest.json")):
        m = json.loads(d.read_text(encoding="utf-8"))
        print(f"{m['backup_id']}  {m['created_at']}  v{m['app_version']}  {m['counts']}")
    return 0


# ───────────── smoke через HTTP (проверка стека изнутри Docker, включая Caddy/SSE) ─────────────
def smoke(base: str) -> int:
    user, pw = os.environ.get("SMOKE_USER", "smoke"), os.environ["SMOKE_PASSWORD"]
    with httpx.Client(base_url=base, timeout=120, headers={"Host": os.environ.get("SMOKE_HOST", "localhost")}) as c:  # Host должен входить в allowed_hosts
        r = c.post("/api/v1/auth/login", json={"username": user, "password": pw})
        r.raise_for_status()
        h = {"X-CSRF-Token": r.json()["csrf_token"]}
        s = c.post("/api/v1/sessions", json={"role": "entrepreneur"}, headers=h).json()
        m = c.post(f"/api/v1/sessions/{s['id']}/messages", json={"text": "У нас нет политики обработки персональных данных на сайте.", "client_request_id": "smoke" + os.urandom(6).hex()}, headers=h)
        m.raise_for_status()
        run = m.json()["run_id"]
        events: list[str] = []
        with c.stream("GET", f"/api/v1/runs/{run}/events", headers=h) as st:
            for line in st.iter_lines():
                if line.startswith("event:"):
                    events.append(line[6:].strip())
        snap = c.get(f"/api/v1/runs/{run}", headers=h).json()
        risks = c.get(f"/api/v1/sessions/{s['id']}/risks", headers=h).json()
        ok = snap["answer_status"] == "validated" and snap["analysis_status"] == "completed" and events[-1] == "completed" and len(risks["active"]) >= 1
        print(json.dumps({"ok": ok, "answer": snap["answer_status"], "analysis": snap["analysis_status"], "events": len(events), "active_risks": len(risks["active"]), "csp": c.get("/").headers.get("content-security-policy", "")[:40]}, ensure_ascii=False))
        return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(prog="ops")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch-models")
    f.add_argument("--lock", required=True)
    f.add_argument("--dest", required=True)
    f.add_argument("--ollama", help="каталог данных Ollama (том ollama): сюда ложатся GGUF-модели из lock")
    mt = sub.add_parser("maintenance")
    mt.add_argument("state", choices=["on", "off"])
    mt.add_argument("--wait", action="store_true")
    mt.add_argument("--timeout", type=int, default=120)
    sub.add_parser("worker-alive")
    for n in ("backup-begin", "backup-finish", "backup-abort", "verify", "restore-verify"):
        p = sub.add_parser(n)
        p.add_argument("--id", required=True)
        if n == "backup-begin":
            p.add_argument("--timeout", type=int, default=120)
    sub.add_parser("list-backups")
    sm = sub.add_parser("smoke")
    sm.add_argument("--base", default="http://web:80")
    a = ap.parse_args()
    rc = 0
    if a.cmd == "fetch-models":
        fetch_models(Path(a.lock), Path(a.dest), Path(a.ollama) if a.ollama else None)
    elif a.cmd == "maintenance":
        rc = maintenance(a.state == "on", a.wait, a.timeout)
    elif a.cmd == "worker-alive":
        rc = worker_alive()
    elif a.cmd == "backup-begin":
        rc = backup_begin(a.id, a.timeout)
    elif a.cmd == "backup-finish":
        rc = backup_finish(a.id)
    elif a.cmd == "backup-abort":
        rc = backup_abort(a.id)
    elif a.cmd == "verify":
        print(json.dumps(verify_backup(a.id)["counts"]))
    elif a.cmd == "restore-verify":
        rc = restore_verify(a.id)
    elif a.cmd == "list-backups":
        rc = list_backups()
    elif a.cmd == "smoke":
        rc = smoke(a.base)
    sys.exit(rc)


if __name__ == "__main__":
    main()
