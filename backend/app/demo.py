"""Синтетические акты ТОЛЬКО для тестов и e2e (provider_mode=test). В рабочую базу не загружаются и в production не попадают."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .core.config import get_settings
from .db.session import SessionLocal
from .providers.registry import get_providers
from .services.ingestion import importer
from .services.ingestion.indexer import build_generation

DEMO_META: dict[str, dict[str, Any]] = {
    "demo-data-act-2025.txt": {"doc_type": "npa", "title": "ДЕМО-ЗАКОН О защите условных данных", "short_name": "ДЕМО-1-ФЗ", "act_number": "ДЕМО-1-ФЗ", "act_date": "2025-03-01", "revision_date": "2025-03-01", "verified_at": "2025-03-05", "topics": ["personal_data"]},
    "demo-data-act-2026.txt": {"doc_type": "npa", "title": "ДЕМО-ЗАКОН О защите условных данных", "short_name": "ДЕМО-1-ФЗ", "act_number": "ДЕМО-1-ФЗ", "act_date": "2025-03-01", "revision_date": "2026-03-01", "verified_at": "2026-03-05", "topics": ["personal_data"]},
    "demo-ads-act.txt": {"doc_type": "npa", "title": "ДЕМО-ЗАКОН О маркировке условной рекламы", "short_name": "ДЕМО-2-ФЗ", "act_number": "ДЕМО-2-ФЗ", "act_date": "2025-06-15", "revision_date": "2025-06-15", "verified_at": "2025-06-20", "topics": ["internet_business"]},
    "demo-software-code.txt": {"doc_type": "npa", "title": "ДЕМО-КОДЕКС О программах для ЭВМ", "short_name": "ДЕМО-3-К", "act_number": "ДЕМО-3-К", "act_date": "2025-01-20", "revision_date": "2025-01-20", "verified_at": None, "topics": ["ip_it"]},
}


def load_demo(folder: Path, only: list[str] | None = None, build: bool = True) -> dict[str, Any]:
    s = get_settings()
    if s.provider_mode != "test":
        raise RuntimeError("Синтетические данные допускаются только в тестовом окружении (DOORAIN_PROVIDER_MODE=test)")
    p = get_providers()
    db = SessionLocal()
    out: dict[str, Any] = {"revisions": [], "note": "Демонстрационные данные — не нормативная база"}
    try:
        for name, meta in DEMO_META.items():
            if only and name not in only:
                continue
            f = folder / name
            if not f.is_file():
                continue
            draft = importer.receive_upload(db, s, name, f.read_bytes(), enqueue=False)
            importer.run_parse(db, s, draft.id)
            rev, created = importer.confirm_import(db, s, draft.id, {**meta, "license_note": "Вымышленный демонстрационный текст"}, is_demo=True)
            out["revisions"].append({"name": name, "revision_id": str(rev.id), "created": created})
        if build:
            gen = build_generation(db, p, s, None, "demo")
            out["generation"] = {"id": str(gen.id), "seq": gen.seq, "control_search": gen.control_search}
    finally:
        db.close()
    return out
