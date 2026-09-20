"""Локальные команды владельца: создание учётной записи, сброс пароля, OpenAPI, демо-корпус. Пароль — только интерактивно."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from .core.errors import ApiError


def _password(confirm: bool = True) -> str:
    pw = getpass.getpass("Пароль (не короче 12 символов): ")
    if confirm and getpass.getpass("Повторите пароль: ") != pw:
        sys.exit("Пароли не совпадают")
    return pw


def main() -> None:
    ap = argparse.ArgumentParser(prog="doorain", description="DoorAIn: управление владельцем и данными")
    sub = ap.add_subparsers(dest="cmd", required=True)
    co = sub.add_parser("create-owner", help="создать единственного владельца (интерактивный ввод пароля)")
    co.add_argument("--username", required=True)
    rp = sub.add_parser("reset-password", help="сбросить пароль владельца и отозвать все сессии входа")
    rp.add_argument("--username", required=True)
    eo = sub.add_parser("export-openapi", help="записать OpenAPI в JSON-файл")
    eo.add_argument("--out", required=True)
    dm = sub.add_parser("load-demo-corpus", help="загрузить ДЕМОНСТРАЦИОННЫЕ данные (не нормативная база)")
    dm.add_argument("--dir", default=str(next((p for p in (Path(__file__).resolve().parents[1] / "fixtures" / "demo", Path(__file__).resolve().parents[2] / "fixtures" / "demo") if p.is_dir()), Path("fixtures/demo"))))
    a = ap.parse_args()

    if a.cmd == "export-openapi":
        from .main import create_app  # noqa: PLC0415

        Path(a.out).write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=1), encoding="utf-8")
        return

    from .auth import service  # noqa: PLC0415
    from .db.session import SessionLocal  # noqa: PLC0415

    db = SessionLocal()
    try:
        if a.cmd == "create-owner":
            u = service.create_owner(db, a.username, _password())
            print(f"Владелец «{u.username}» создан. Публичной регистрации нет.")
        elif a.cmd == "reset-password":
            service.reset_password(db, a.username, _password())
            print("Пароль изменён; все прежние сессии входа отозваны.")
        elif a.cmd == "load-demo-corpus":
            from .demo import load_demo  # noqa: PLC0415

            print(json.dumps(load_demo(Path(a.dir)), ensure_ascii=False))
    except ApiError as e:
        sys.exit(f"Ошибка: {e.message}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
