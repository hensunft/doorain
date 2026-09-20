"""Живая сквозная проверка стека с реальными моделями: вопрос → SSE → ответ → аналитика → риски (тайминги и результаты).

Запуск внутри контейнера api (там есть httpx и внутренняя сеть):
  docker compose cp evals/live_check.py api:/tmp/live_check.py
  docker compose exec -T -e DOORAIN_EVAL_PASSWORD=... api python /tmp/live_check.py --user owner --role entrepreneur "вопрос 1" "вопрос 2"
Ничего не отправляется наружу. Пароль — из окружения.
"""

from __future__ import annotations

import argparse
import json
import os
import time

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://web:80")
    ap.add_argument("--user", required=True)
    ap.add_argument("--role", default="entrepreneur")
    ap.add_argument("--as-of", default="2026-09-20")
    ap.add_argument("--rebuild", action="store_true", help="перед вопросами построить новую generation (реальные embeddings) и дождаться её")
    ap.add_argument("--brief", action="store_true", help="одна строка JSON на вопрос")
    ap.add_argument("questions", nargs="*")
    a = ap.parse_args()
    c = httpx.Client(base_url=a.base, timeout=httpx.Timeout(900, connect=10), headers={"Host": os.environ.get("EVAL_HOST", "localhost")})
    r = c.post("/api/v1/auth/login", json={"username": a.user, "password": os.environ["DOORAIN_EVAL_PASSWORD"]})
    r.raise_for_status()
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    if a.rebuild:
        t0 = time.monotonic()
        job = c.post("/api/v1/corpus/generations/build", headers=h).json()
        while True:
            j = c.get(f"/api/v1/corpus/jobs/{job['id']}", headers=h).json()
            if j["status"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(1)
        print(json.dumps({"build": j["status"], "seconds": round(time.monotonic() - t0, 1), "result": j["result"], "error": j["error"]}, ensure_ascii=False))
    sid = c.post("/api/v1/sessions", json={"role": a.role, "as_of_date": a.as_of}, headers=h).json()["id"]
    for q in a.questions:
        t0 = time.monotonic()
        acc = c.post(f"/api/v1/sessions/{sid}/messages", json={"text": q, "client_request_id": os.urandom(8).hex()}, headers=h)
        if acc.status_code != 202:
            print(json.dumps({"question": q, "http": acc.status_code, "body": acc.text[:200]}, ensure_ascii=False))
            continue
        run = acc.json()["run_id"]
        first, events = None, []
        with c.stream("GET", f"/api/v1/runs/{run}/events", headers=h) as st:
            for line in st.iter_lines():
                if line.startswith("event:"):
                    ev = line[6:].strip()
                    events.append((ev, round(time.monotonic() - t0, 2)))
                    if ev == "answer_delta" and first is None:
                        first = round(time.monotonic() - t0, 2)
        total = round(time.monotonic() - t0, 2)
        snap = c.get(f"/api/v1/runs/{run}", headers=h).json()
        tr = c.get(f"/api/v1/runs/{run}/trace", headers=h).json()
        msgs = c.get(f"/api/v1/sessions/{sid}/messages", headers=h).json()
        ans = next((m for m in reversed(msgs) if m["role"] == "assistant"), {})
        risks = c.get(f"/api/v1/sessions/{sid}/risks", headers=h).json()
        t = tr["trace"] or {}
        if a.brief:
            tm = (t.get("retrieval") or {}).get("timings_ms") or {}
            print(json.dumps({
                "q": q[:70], "answer": snap["answer_status"], "analysis": snap["analysis_status"], "refusal": snap["refusal_reason"], "ttft_s": first, "total_s": total,
                "gen_ms": (t.get("stages_ms") or {}).get("generation"), "embed_ms": tm.get("embed_ms"), "rerank_ms": tm.get("rerank_ms"), "prompt_tok": (t.get("budget") or {}).get("est_prompt_tokens"),
                "top": [s["rerank"] for s in (t.get("retrieval") or {}).get("scores", [])[:2]], "unsupported": t.get("unsupported_blocks"), "topics": (t.get("classification") or {}).get("topics"),
                "blocks": [b["kind"] + ":" + b["state"][:3] for b in (ans.get("blocks") or [])],
                "risks": [f"{x['title'][:40]} P{x['p']}xS{x['s']}={x['score']} {x['level']}" for x in risks["active"]], "clarify": [x["title"][:40] for x in risks["needs_clarification"]],
                "analysis_err": (t.get("analysis") or {}).get("error"),
            }, ensure_ascii=False))
            continue
        print(json.dumps({
            "question": q, "answer_status": snap["answer_status"], "analysis_status": snap["analysis_status"], "refusal": snap["refusal_reason"], "first_text_s": first, "total_s": total,
            "events": {e: t_ for e, t_ in events if e in ("answer_completed", "analysis_started", "risk_updated", "completed")},
            "stages_ms": t.get("stages_ms"), "retrieval_ms": (t.get("retrieval") or {}).get("timings_ms"), "top_rerank": [s["rerank"] for s in (t.get("retrieval") or {}).get("scores", [])[:4]],
            "budget": t.get("budget"), "unsupported_blocks": t.get("unsupported_blocks"), "classification": t.get("classification"), "analysis": t.get("analysis"),
            "blocks": [{"kind": b["kind"], "state": b["state"], "markers": b["markers"], "text": b["text"][:400]} for b in (ans.get("blocks") or [])],
            "citations": [f"{x['label']}, {x['locator']}" for x in ans.get("citations", [])], "warnings": ans.get("warnings"),
            "risks": [{"title": x["title"], "p": x["p"], "s": x["s"], "score": x["score"], "level": x["level"], "status": x["status"]} for x in risks["active"]], "needs_clarification": [x["title"] for x in risks["needs_clarification"]],
            "raw_answer": (t.get("raw_answer") or "")[:1800], "raw_analysis": ((t.get("analysis") or {}).get("raw") or "")[:1500], "retrieval_reason": (t.get("retrieval") or {}).get("reason"),
            "model": tr["model_info"].get("name"), "digest": tr["model_info"].get("digest"),
        }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
