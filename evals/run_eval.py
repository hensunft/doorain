"""Оценка RAG на запущенном стеке DoorAIn через HTTP API (владелец). Ничего не отправляется во внешние сервисы.

Запуск:  DOORAIN_EVAL_PASSWORD=... uv run --project backend python evals/run_eval.py --user owner --split holdout
Пароль — только из переменной окружения. Отчёты: evals/reports/*.json|md; шаблон экспертной разметки: *.csv.

Честные оговорки, которые попадают в отчёт:
* expected_* в датасете — гипотезы автора, не экспертная разметка (status=hypothesis);
* автоматические метрики (тема, отказ, целостность ссылок, act-hit) НЕ заменяют юридическую экспертизу;
* пороги подбираются только на calibration; holdout — только для итоговой оценки.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
LEVEL = {"calibration": "calibration", "holdout": "holdout"}


class Sampler(threading.Thread):
    """Пики VRAM/загрузки/температуры GPU и RAM контейнеров (best effort)."""

    def __init__(self, project: str) -> None:
        super().__init__(daemon=True)
        self.stop, self.project, self.gpu, self.mem = threading.Event(), project, [], {}

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu,temperature.gpu,clocks.sm", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout.strip()
                self.gpu.append([float(x) for x in o.split(",")]) if o else None
                d = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.MemUsage}}"], capture_output=True, text=True, timeout=15).stdout
                for line in d.splitlines():
                    name, usage = line.split("|")
                    if name.startswith(self.project):
                        v, u = usage.split("/")[0].strip()[:-3], usage.split("/")[0].strip()[-3:]
                        mb = float(v) * (1024 if u == "GiB" else 1 if u == "MiB" else 0.001)
                        self.mem[name] = max(self.mem.get(name, 0.0), mb)
            except Exception:  # noqa: BLE001, S110 — измерения ресурсов не должны ломать прогон
                pass
            self.stop.wait(4)

    def summary(self) -> dict[str, Any]:
        g = list(zip(*self.gpu, strict=False)) if self.gpu else []
        return {"gpu_vram_peak_mib": max(g[0]) if g else None, "gpu_util_peak_pct": max(g[1]) if g else None, "gpu_temp_peak_c": max(g[2]) if g else None, "gpu_sm_clock_min_mhz": min(g[3]) if g else None, "gpu_sm_clock_max_mhz": max(g[3]) if g else None, "container_ram_peak_mib": {k: round(v) for k, v in self.mem.items()}}


class Api:
    def __init__(self, base: str, user: str, password: str) -> None:
        self.c = httpx.Client(base_url=base, timeout=httpx.Timeout(900, connect=10), headers={"Host": os.environ.get("EVAL_HOST", "localhost")})
        r = self.c.post("/api/v1/auth/login", json={"username": user, "password": password})
        r.raise_for_status()
        self.h = {"X-CSRF-Token": r.json()["csrf_token"]}

    def req(self, m: str, url: str, **kw: Any) -> Any:
        r = self.c.request(m, "/api/v1" + url, headers=self.h, **kw)
        r.raise_for_status()
        return r.json() if r.content else None

    def ask(self, sid: str, text: str) -> dict[str, Any]:
        t0 = time.monotonic()
        acc = self.req("POST", f"/sessions/{sid}/messages", json={"text": text, "client_request_id": os.urandom(8).hex()})
        first_text = None
        with self.c.stream("GET", f"/api/v1/runs/{acc['run_id']}/events", headers=self.h) as st:
            for line in st.iter_lines():
                if line.startswith("event: answer_delta") and first_text is None:
                    first_text = time.monotonic() - t0
        total = time.monotonic() - t0
        snap = self.req("GET", f"/runs/{acc['run_id']}")
        trace = self.req("GET", f"/runs/{acc['run_id']}/trace")
        msgs = self.req("GET", f"/sessions/{sid}/messages")
        ans = next((m for m in reversed(msgs) if m["role"] == "assistant"), None)
        return {"run_id": acc["run_id"], "snapshot": snap, "trace": trace, "answer": ans, "client_first_text_ms": int(first_text * 1000) if first_text else None, "client_total_ms": int(total * 1000)}


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def run_case(api: Api, case: dict[str, Any], as_of: str, first: bool) -> dict[str, Any]:
    sid = api.req("POST", "/sessions", json={"role": case["role"], "as_of_date": as_of})["id"]
    try:
        for h in case.get("history", []):
            api.ask(sid, h)
        r = api.ask(sid, case["question"])
        snap, trace, ans = r["snapshot"], r["trace"], r["answer"]
        cls = (trace["trace"] or {}).get("classification", {})
        retr = (trace["trace"] or {}).get("retrieval", {})
        cites = ans["citations"] if ans else []
        integrity = all(api.c.get(f"/api/v1/citations/{c['id']}", headers=api.h).status_code == 200 for c in cites)
        acts = sorted({c["label"] for c in cites})
        top = (retr.get("scores") or [{}])[0].get("rerank")
        return {
            "id": case["id"], "split": case["split"], "kind": case["kind"], "role": case["role"], "question": case["question"], "cold": first,
            "answer_status": snap["answer_status"], "analysis_status": snap["analysis_status"], "refusal_reason": snap["refusal_reason"],
            "predicted_topics": cls.get("topics", []), "expected_topics": case["expected_topics"], "expected_refusal": case["expected_refusal"], "expected_acts": case["expected_acts"], "cited_acts": acts,
            "citations": len(cites), "citation_integrity": integrity, "top_rerank": top, "retrieval_timings_ms": retr.get("timings_ms"),
            "ttft_ms_server": (trace["trace"] or {}).get("ttft_ms"), "ttft_ms_client": r["client_first_text_ms"], "total_ms": r["client_total_ms"], "stages_ms": (trace["trace"] or {}).get("stages_ms"),
            "unsupported_blocks": (trace["trace"] or {}).get("unsupported_blocks"), "answer_text": (ans or {}).get("text", "")[:4000], "model": trace["model_info"].get("name"), "digest": trace["model_info"].get("digest"),
        }
    finally:
        api.req("DELETE", f"/sessions/{sid}", params={"confirm": api.req("GET", f"/sessions/{sid}")["title"]})


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ans = [r for r in rows if not r["expected_refusal"]]
    ref = [r for r in rows if r["expected_refusal"]]
    validated = [r for r in rows if r["answer_status"] == "validated"]
    with_topics = [r for r in rows if r["expected_topics"]]
    ttft = [r["ttft_ms_client"] for r in validated if r["ttft_ms_client"]]
    tot = [r["total_ms"] for r in validated]
    warm = [r for r in validated if not r["cold"]]
    def rate(n: int, d: int) -> float | None:
        return round(n / d, 3) if d else None
    return {
        "n_cases": len(rows), "n_answerable": len(ans), "n_expected_refusal": len(ref),
        "topic_recall_pct": rate(sum(set(r["expected_topics"]) <= set(r["predicted_topics"]) for r in with_topics), len(with_topics)),
        "honest_refusals": {"correct": sum(r["answer_status"] == "refused" for r in ref), "of": len(ref), "rate": rate(sum(r["answer_status"] == "refused" for r in ref), len(ref)), "target": 1.0},
        "false_refusals_on_answerable": {"count": sum(r["answer_status"] == "refused" for r in ans), "of": len(ans)},
        "citation_technical_integrity": {"ok": sum(r["citation_integrity"] for r in validated), "of": len(validated), "target": 1.0},
        "act_hit_rate_hypothesis": rate(sum(bool(set(r["expected_acts"]) & set(r["cited_acts"])) for r in validated if r["expected_acts"]), sum(1 for r in validated if r["expected_acts"])),
        "failed_or_unavailable": sum(r["answer_status"] == "failed" for r in rows),
        "latency_ms": {"ttft_p50": pct(ttft, 0.5), "ttft_p95": pct(ttft, 0.95), "total_p50": pct(tot, 0.5), "total_p95": pct(tot, 0.95), "warm_n": len(warm), "cold_ttft": next((r["ttft_ms_client"] for r in rows if r["cold"]), None), "targets": {"ttft_s": 5, "total_s": 40}},
    }


def calibrate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    pos = [r["top_rerank"] for r in rows if not r["expected_refusal"] and r["top_rerank"] is not None]
    neg = [r["top_rerank"] for r in rows if r["expected_refusal"] and r["top_rerank"] is not None]
    if not pos or not neg:
        return None
    best = max(sorted(set(pos + neg)), key=lambda t: (sum(x >= t for x in pos) / len(pos) + sum(x < t for x in neg) / len(neg)) / 2)
    return {"min_rerank_score": round(best, 4), "n_answerable": len(pos), "n_refusal_with_retrieval": len(neg), "balanced_accuracy": round((sum(x >= best for x in pos) / len(pos) + sum(x < best for x in neg) / len(neg)) / 2, 3)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--user", required=True)
    ap.add_argument("--split", choices=["calibration", "holdout", "all"], default="holdout")
    ap.add_argument("--profile", default="laptop-16gb-6gb")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--as-of", default=datetime.now(UTC).date().isoformat())
    ap.add_argument("--project", default="doorain")
    ap.add_argument("--sample-resources", action="store_true")
    ap.add_argument("--write-thresholds", action="store_true")
    a = ap.parse_args()
    if a.write_thresholds and a.split != "calibration":
        sys.exit("Пороги подбираются только на split=calibration (holdout не подстраивается)")
    password = os.environ.get("DOORAIN_EVAL_PASSWORD") or sys.exit("Задайте DOORAIN_EVAL_PASSWORD")
    ds = (HERE / "datasets" / "cases.jsonl").read_text(encoding="utf-8")
    cases = [json.loads(x) for x in ds.splitlines() if x.strip()]
    if a.split != "all":
        cases = [c for c in cases if c["split"] == a.split]
    if a.limit:
        cases = cases[: a.limit]
    api = Api(a.base, a.user, password)
    diag = api.req("GET", "/system/diagnostics")
    corpus = api.req("GET", "/corpus/overview")
    sampler = Sampler(a.project) if a.sample_resources else None
    if sampler:
        sampler.start()
    rows: list[dict[str, Any]] = []
    for i, c in enumerate(cases):
        try:
            rows.append(run_case(api, c, a.as_of, i == 0))
            print(f"[{i + 1}/{len(cases)}] {c['id']} {rows[-1]['answer_status']:9} {rows[-1]['total_ms']:>6} мс  {c['question'][:60]}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[{i + 1}/{len(cases)}] {c['id']} ОШИБКА {type(e).__name__}: {e}", flush=True)
    if sampler:
        sampler.stop.set()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report = {
        "created_at": datetime.now(UTC).isoformat(), "profile": a.profile, "split": a.split, "as_of": a.as_of, "dataset_sha256": hashlib.sha256(ds.encode()).hexdigest()[:16],
        "hardware": {"platform": platform.platform(), "gpu": subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"], capture_output=True, text=True).stdout.strip() if shutil_which("nvidia-smi") else None},
        "model": diag["llm"], "thresholds": diag["thresholds"], "provider_mode": diag["provider_mode"], "corpus": {"revisions": corpus["revisions"], "chunks": corpus["chunks"], "has_demo": corpus["has_demo"], "generation": (corpus["active_generation"] or {}).get("seq")},
        "resources": sampler.summary() if sampler else None, "aggregate": aggregate(rows), "calibration_suggestion": calibrate(rows) if a.split == "calibration" else None,
        "caveats": ["expected_* — гипотезы автора набора, не экспертная разметка", "автоматические метрики не заменяют юридическую экспертизу; LLM-as-judge не использовался", "при provider_mode=test или корпусе с демо-данными результаты не характеризуют качество реальной модели/права"],
        "cases": rows,
    }
    if diag["provider_mode"] == "test" or corpus["has_demo"]:
        report["caveats"].insert(0, "ВНИМАНИЕ: прогон на тестовых провайдерах и/или демонстрационных данных — это проверка стенда, не оценка качества")
    out = HERE / "reports"
    out.mkdir(exist_ok=True)
    (out / f"{stamp}-{a.profile}-{a.split}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    with (out / f"{stamp}-{a.profile}-{a.split}-expert.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["case_id", "role", "question", "answer", "cited_sources", "predicted_topics", "topic_correct_0_1", "citation_content_correct_0_1", "risk_agreement_0_1", "portrait_complete_0_1", "usability_1_5", "comment"])
        for r in rows:
            w.writerow([r["id"], r["role"], r["question"], r["answer_text"], "; ".join(r["cited_acts"]), ", ".join(r["predicted_topics"]), "", "", "", "", "", ""])
    if a.write_thresholds and report["calibration_suggestion"]:
        cfg = {**report["calibration_suggestion"], "source": f"calibrated:{datetime.now(UTC).date()}:{a.split}", "model": (diag["llm"] or {}).get("name")}
        (HERE / "configs" / "thresholds.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Порог записан: DOORAIN_MIN_RERANK_SCORE={cfg['min_rerank_score']} DOORAIN_THRESHOLD_SOURCE={cfg['source']}")
    print(json.dumps(report["aggregate"], ensure_ascii=False, indent=1))


def shutil_which(x: str) -> str | None:
    import shutil  # noqa: PLC0415

    return shutil.which(x)


if __name__ == "__main__":
    main()
    _ = statistics
