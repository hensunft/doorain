"""Локальные команды владельца: создание учётной записи, сброс пароля, OpenAPI, демо-корпус. Пароль — только интерактивно."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Any

from .core.errors import ApiError


def _password(confirm: bool = True) -> str:
    pw = getpass.getpass("Пароль (не короче 12 символов): ")
    if confirm and getpass.getpass("Повторите пароль: ") != pw:
        sys.exit("Пароли не совпадают")
    return pw


def _kb_parser(sub: argparse._SubParsersAction) -> None:
    kb = sub.add_parser("kb", help="база знаний: загрузка, редакции, переиндексация, поиск, диагностика, оценка").add_subparsers(dest="kb_cmd", required=True)
    add = kb.add_parser("add", help="загрузить документ из файла или по URL (скачивание — только этой ручной командой)")
    add.add_argument("source", help="путь к файлу или http(s)-адрес")
    add.add_argument("--type", dest="doc_type", choices=["law", "bylaw", "practice", "doctrine"], help="вид источника (по умолчанию — из манифеста)")
    add.add_argument("--title")
    add.add_argument("--edition", help="издание (обязательно для учебника)")
    add.add_argument("--act-number")
    add.add_argument("--revision-date", help="дата редакции ГГГГ-ММ-ДД — проверьте по официальному источнику")
    add.add_argument("--verified-at", help="дата, на которую редакция сверена с официальным источником")
    add.add_argument("--manifest-id", help="идентификатор записи knowledge_base/manifest.yaml")
    add.add_argument("--license", choices=["public_domain_official", "open_license", "owned_copy"])
    add.add_argument("--source-url")
    add.add_argument("--no-index", action="store_true", help="не строить индекс сразу")
    kb.add_parser("list", help="что загружено: документы, редакции, число чанков, даты")
    up = kb.add_parser("update", help="загрузить новую редакцию документа (старая остаётся, поиск идёт по действующей)")
    up.add_argument("doc_id", help="document_id из kb list или id записи манифеста")
    up.add_argument("source")
    up.add_argument("--revision-date", required=True)
    up.add_argument("--verified-at")
    ri = kb.add_parser("reindex", help="перестроить индекс (эмбеддинги неизменённых фрагментов переиспользуются)")
    ri.add_argument("--only", help="пометка в примечании generation")
    se = kb.add_parser("search", help="«голый» поиск в обход агента")
    se.add_argument("query")
    se.add_argument("--debug", action="store_true", help="показать скоры, источники и метаданные")
    se.add_argument("--limit", type=int, default=10)
    kb.add_parser("doctor", help="чек-лист исправности поиска")
    ev = kb.add_parser("eval", help="прогон эталонного набора вопросов")
    ev.add_argument("--set", dest="golden", default="tests/eval/golden_set.yaml")
    ev.add_argument("--out", default="evals/reports")


def _kb_run(db: Any, a: argparse.Namespace) -> None:
    from .core.config import get_settings  # noqa: PLC0415
    from .providers.registry import get_providers  # noqa: PLC0415
    from .services.ingestion import doctor, kb  # noqa: PLC0415

    s, p = get_settings(), get_providers()
    out: Any
    if a.kb_cmd == "add":
        meta = {k: getattr(a, k) for k in ("title", "edition", "act_number", "revision_date", "verified_at", "manifest_id", "license", "source_url")}
        meta["doc_type"] = {"law": "npa", "bylaw": "npa", "practice": "soft_law", "doctrine": "textbook"}.get(a.doc_type or "", None)
        out = kb.add(db, s, p, a.source, {k: v for k, v in meta.items() if v}, build=not a.no_index)
    elif a.kb_cmd == "list":
        out = kb.documents(db)
    elif a.kb_cmd == "update":
        out = kb.update_revision(db, s, p, a.doc_id, a.source, a.revision_date, a.verified_at)
    elif a.kb_cmd == "reindex":
        out = kb.reindex(db, s, p, a.only)
    elif a.kb_cmd == "search":
        out = kb.search(db, s, p, a.query, limit=a.limit)
        if not a.debug:
            out = {"query": out["query"], "sufficient": out["sufficient"], "hits": [{k: h[k] for k in ("act", "locator", "rerank")} for h in out["hits"]]}
    elif a.kb_cmd == "doctor":
        out = doctor.summary(db, p, s)
        for c in out["checks"]:
            print(f"[{'OK ' if c['ok'] else 'FAIL'}] {c['title']}: {c['detail']}")
        if not out["ok"]:
            sys.exit(f"Критичные проверки не пройдены: {', '.join(out['critical_failed'])}")
        return
    else:
        from .services.ingestion import golden  # noqa: PLC0415

        out = golden.run(db, s, p, Path(a.golden), Path(a.out))
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


def main() -> None:
    ap = argparse.ArgumentParser(prog="doorain", description="DoorAIn: управление владельцем и данными")
    sub = ap.add_subparsers(dest="cmd", required=True)
    co = sub.add_parser("create-owner", help="создать единственного владельца (интерактивный ввод пароля)")
    co.add_argument("--username", required=True)
    rp = sub.add_parser("reset-password", help="сбросить пароль пользователя и отозвать все сессии входа")
    rp.add_argument("--username", required=True)
    iv = sub.add_parser("invite", help="выпустить код приглашения (регистрация возможна только по нему)")
    iv.add_argument("--note", help="для кого код: подпись в списке приглашений")
    sub.add_parser("list-users", help="учётные записи и уровни доступа")
    eo = sub.add_parser("export-openapi", help="записать OpenAPI в JSON-файл")
    eo.add_argument("--out", required=True)
    dm = sub.add_parser("load-demo-corpus", help="загрузить ДЕМОНСТРАЦИОННЫЕ данные (не нормативная база)")
    dm.add_argument("--dir", default=str(next((p for p in (Path(__file__).resolve().parents[1] / "fixtures" / "demo", Path(__file__).resolve().parents[2] / "fixtures" / "demo") if p.is_dir()), Path("fixtures/demo"))))
    _kb_parser(sub)
    a = ap.parse_args()

    if a.cmd == "export-openapi":
        from .main import create_app  # noqa: PLC0415

        Path(a.out).write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=1), encoding="utf-8")
        return

    from .auth import service  # noqa: PLC0415
    from .db.session import SessionLocal  # noqa: PLC0415

    db = SessionLocal()
    try:
        if a.cmd == "kb":
            _kb_run(db, a)
            return
        if a.cmd == "create-owner":
            u = service.create_owner(db, a.username, _password())
            print(f"Владелец «{u.username}» создан. Публичной регистрации нет.")
        elif a.cmd == "reset-password":
            service.reset_password(db, a.username, _password())
            print("Пароль изменён; все прежние сессии входа отозваны.")
        elif a.cmd == "invite":
            from sqlalchemy import select  # noqa: PLC0415

            from .core.config import get_settings  # noqa: PLC0415
            from .db.models import User  # noqa: PLC0415

            owner_user = db.scalar(select(User).where(User.access_level == "owner"))
            if not owner_user:
                sys.exit("Владелец ещё не создан: выполните create-owner")
            code, inv = service.create_invite(db, get_settings(), owner_user.id, a.note)
            print(f"Код приглашения: {code}\nДействует до {inv.expires_at:%d.%m.%Y %H:%M} UTC. Код показывается один раз — в базе хранится только его хеш.")
        elif a.cmd == "list-users":
            from sqlalchemy import select  # noqa: PLC0415

            from .db.models import User  # noqa: PLC0415

            for u in db.scalars(select(User).order_by(User.created_at)):
                state = "отключён" if u.disabled_at else "активен"
                print(f"{u.username:<20} {u.access_level:<6} {state:<9} последний вход: {u.last_login_at or '—'}")
        elif a.cmd == "load-demo-corpus":
            from .demo import load_demo  # noqa: PLC0415

            print(json.dumps(load_demo(Path(a.dir)), ensure_ascii=False))
    except ApiError as e:
        sys.exit(f"Ошибка: {e.message}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
