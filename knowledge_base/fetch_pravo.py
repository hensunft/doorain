"""Ручная офлайн-загрузка текстов НПА с официального портала pravo.gov.ru (ИПС «Законодательство России»).

Приложение в рантайме в сеть не ходит: это отдельная команда, которую владелец запускает сам.
Скрипт НЕ подтверждает юридическую актуальность: он берёт последнюю редакцию, указанную порталом,
и записывает её реквизиты в <id>.meta.json. Сверка редакции и вступления в силу — за владельцем.

    python knowledge_base/fetch_pravo.py --list
    python knowledge_base/fetch_pravo.py --tier start
    python knowledge_base/fetch_pravo.py --id fz-152 --id fz-149

Дальше документы загружаются в базу знаний:
    doorain kb add knowledge_base/sources/fz-152.txt --manifest-id fz-152 --revision-date <из meta.json>
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

HERE = Path(__file__).resolve().parent
BASE = "http://pravo.gov.ru/proxy/ips/"
UA = {"User-Agent": "DoorAIn/kb-fetch (ручная загрузка владельцем)"}
EDITION = re.compile(r"(\d{1,4})\s*-\s*от\s*(\d{2}\.\d{2}\.\d{4})\s*N?\s*№?\s*([\d\-]+\s*-?\s*[А-Яа-яЁё]{2})")
ART = re.compile(r"Стать[яи]\s+(\d+(?:\.\d+)?)")
START = re.compile(r"(ФЕДЕРАЛЬНЫЙ ЗАКОН|КОДЕКС РОССИЙСКОЙ|УКАЗ ПРЕЗИДЕНТА|ПОСТАНОВЛЕНИЕ)")


def _get(params: str) -> str:
    for attempt in range(3):
        try:
            r = httpx.get(BASE + params, timeout=120, follow_redirects=True, headers=UA)
            r.raise_for_status()
            return r.content.decode("cp1251", "replace")
        except Exception:  # noqa: BLE001 — портал отвечает нестабильно, повторяем
            if attempt == 2:
                raise
            time.sleep(3)
    return ""


def to_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", page)
    page = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|h\d|li)>", "\n", page)
    page = re.sub(r"<[^>]+>", " ", page)
    page = html.unescape(page).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in page.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def editions(nd: str) -> list[tuple[int, str, str]]:
    """Список редакций документа: (номер, дата изменяющего акта, его номер)."""
    text = to_text(_get(f"?docbody=&nd={nd}"))
    seen: dict[int, tuple[int, str, str]] = {}
    for idx, dt, num in EDITION.findall(text):
        seen[int(idx)] = (int(idx), dt, re.sub(r"\s+", "", num))
    return [seen[k] for k in sorted(seen)]


def fetch_document(nd: str, rdk: int, max_pages: int = 60) -> str:
    """Текст выбранной редакции; длинные кодексы портал отдаёт постранично."""
    parts: list[str] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        body = to_text(_get(f"?doc_itself=&nd={nd}&page={page}&rdk={rdk}"))
        core = body[body.find("\n") :].strip()
        digest = hashlib.sha256(core.encode()).hexdigest()
        if not core or digest in seen:
            break
        seen.add(digest)
        parts.append(core)
        if len(core) < 2000:  # последняя страница короче остальных
            break
    return "\n".join(parts)


def trim(text: str) -> str:
    """Отбросить навигацию портала до заголовка акта; хвост обрезать по последней статье."""
    m = START.search(text)
    if m:
        text = text[m.start() :]
    last = None
    for m2 in ART.finditer(text):
        last = m2
    if last:
        tail = text.find("\n", last.end())
        rest = text[tail:] if tail > 0 else ""
        keep = rest.find("Документ предоставлен")
        if keep > 0:
            text = text[:tail] + rest[:keep]
    return text.strip()


def run(items: list[dict[str, Any]], out: Path) -> list[dict[str, Any]]:
    out.mkdir(parents=True, exist_ok=True)
    report = []
    for it in items:
        nd = str(it.get("pravo_nd") or "")
        if not nd:
            report.append({"id": it["id"], "status": "skipped", "reason": "в манифесте нет pravo_nd"})
            continue
        eds = editions(nd)
        rdk = eds[-1][0] if eds else 0
        raw = fetch_document(nd, rdk)
        text = trim(raw)
        arts = sorted({a for a in ART.findall(text)}, key=lambda x: [int(p) for p in x.split(".")])
        expect = [str(x) for x in (it.get("match") or {}).get("act_numbers", [])]
        confirmed = all(any(e.replace("-", "").upper() in text.replace("-", "").replace(" ", "").upper() for e in [x]) for x in expect) if expect else None
        status = "ok" if (len(text) > 3000 and arts) else "failed"
        path = out / f"{it['id']}.txt"
        if status == "ok":
            path.write_text(text, encoding="utf-8")
            (out / f"{it['id']}.meta.json").write_text(
                json.dumps(
                    {
                        "manifest_id": it["id"], "title": it["title"], "pravo_nd": nd, "rdk": rdk,
                        "source_url": f"{BASE}?doc_itself=&nd={nd}&page=1&rdk={rdk}",
                        "last_amendment": {"date": eds[-1][1], "act": eds[-1][2]} if eds else None,
                        "editions_listed": len(eds), "articles": len(arts), "chars": len(text),
                        "sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                        "act_number_confirmed_in_text": confirmed,
                        "note": "Последняя редакция по данным портала. Вступление в силу и полноту текста проверяет владелец.",
                    },
                    ensure_ascii=False,
                    indent=1,
                ),
                encoding="utf-8",
            )
        report.append({"id": it["id"], "status": status, "nd": nd, "rdk": rdk, "articles": len(arts), "chars": len(text), "last_amendment": eds[-1][1] if eds else None, "act_number_in_text": confirmed})
        print(json.dumps(report[-1], ensure_ascii=False), flush=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Загрузка текстов НПА с pravo.gov.ru по манифесту (ручная операция)")
    ap.add_argument("--manifest", default=str(HERE / "manifest.yaml"))
    ap.add_argument("--out", default=str(HERE / "sources"))
    ap.add_argument("--id", action="append", default=[])
    ap.add_argument("--tier", choices=["start", "extended"])
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    items = (yaml.safe_load(Path(a.manifest).read_text(encoding="utf-8")) or {}).get("items", [])
    if a.list:
        for it in items:
            print(f"{it['id']:<24} layer={it['layer']} tier={it['tier']:<8} nd={it.get('pravo_nd') or '—':<10} {it['title'][:70]}")
        return
    sel = [it for it in items if (not a.id or it["id"] in a.id) and (not a.tier or it["tier"] == a.tier) and it.get("layer") == 1]
    if not sel:
        sys.exit("Нечего загружать: уточните --id или --tier (скачиваются только акты слоя 1)")
    rep = run(sel, Path(a.out))
    ok = [r for r in rep if r["status"] == "ok"]
    print(f"\nЗагружено {len(ok)} из {len(rep)}. Реквизиты и редакцию сверьте по официальному источнику перед импортом.")


if __name__ == "__main__":
    main()
