"""Цифровой слепок: узлы/связи в PostgreSQL, идемпотентные upsert по стабильным ключам, цвет = max активных рисков."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import Citation, ConsultationSession, GraphEdge, GraphNode, Message, Risk
from ..risks.methodology import TOPIC_TITLES
from ..risks.scoring import LEVELS, level_rank

ROLE_TITLE = {"student": "Студент", "entrepreneur": "Предприниматель", "expert": "Эксперт"}
ACTIVE = ("open", "in_progress")


def node(db: Session, session_id: uuid.UUID, kind: str, key: str, label: str, data: dict[str, Any] | None = None) -> GraphNode:
    n = db.scalar(select(GraphNode).where(GraphNode.session_id == session_id, GraphNode.stable_key == key))
    if n:
        return n
    n = GraphNode(session_id=session_id, kind=kind, stable_key=key, label=label[:400], data=data or {})
    db.add(n)
    db.flush()
    return n


def link(db: Session, session_id: uuid.UUID, src: GraphNode, dst: GraphNode, kind: str, data: dict[str, Any] | None = None) -> GraphEdge:
    e = db.scalar(select(GraphEdge).where(GraphEdge.session_id == session_id, GraphEdge.src_id == src.id, GraphEdge.dst_id == dst.id, GraphEdge.kind == kind))
    if e:
        return e
    e = GraphEdge(session_id=session_id, src_id=src.id, dst_id=dst.id, kind=kind, data=data or {})
    db.add(e)
    db.flush()
    return e


def center(db: Session, s: ConsultationSession) -> GraphNode:
    return node(db, s.id, "center", "center", f"{ROLE_TITLE.get(s.role, s.role)}: {s.title}", {"role": s.role})


def topic(db: Session, s: ConsultationSession, topic_id: str) -> GraphNode:
    t = node(db, s.id, "topic", f"topic:{topic_id}", TOPIC_TITLES.get(topic_id, topic_id), {"topic_id": topic_id})
    link(db, s.id, t, center(db, s), "belongs_to")
    return t


def question(db: Session, s: ConsultationSession, msg: Message, result: str, topic_ids: list[str]) -> GraphNode:
    q = node(db, s.id, "question", f"q:{msg.id}", msg.content[:140], {"message_id": str(msg.id), "result": result, "seq": msg.seq})
    q.data = {**q.data, "result": result}  # результат может уточниться (answered/refused/cancelled/failed)
    for t in topic_ids:
        link(db, s.id, q, topic(db, s, t), "asks_about")
    if not topic_ids:
        link(db, s.id, q, center(db, s), "asks_about")
    return q


def norm(db: Session, s: ConsultationSession, c: Citation) -> GraphNode:
    snap = c.snapshot
    key = f"norm:{c.revision_id}:{snap.get('locator', '')}"
    label = f"{snap.get('short_name') or snap.get('act_title', '')[:40]}, {snap.get('locator', '')}"
    return node(db, s.id, "norm", key, label, {"citation_id": str(c.id), "revision_id": str(c.revision_id), "document_id": str(c.document_id), "locator": snap.get("locator")})


def risk_node(db: Session, s: ConsultationSession, r: Risk) -> GraphNode:
    return node(db, s.id, "risk", f"risk:{r.id}", r.title, {"risk_id": str(r.id)})


def view(db: Session, s: ConsultationSession) -> dict[str, Any]:
    nodes = list(db.scalars(select(GraphNode).where(GraphNode.session_id == s.id).order_by(GraphNode.created_at, GraphNode.id)))
    edges = list(db.scalars(select(GraphEdge).where(GraphEdge.session_id == s.id).order_by(GraphEdge.created_at, GraphEdge.id)))
    risks = {r.id: r for r in db.scalars(select(Risk).where(Risk.session_id == s.id))}
    by_id = {n.id: n for n in nodes}

    def rid(n: GraphNode) -> uuid.UUID | None:
        return uuid.UUID(n.data["risk_id"]) if n.kind == "risk" and n.data.get("risk_id") else None

    lvl: dict[uuid.UUID, int] = {}  # node.id -> rank активных рисков
    past: dict[uuid.UUID, int] = {}  # node.id -> rank снятых рисков: узел светлеет, но след в истории остаётся
    counts: dict[uuid.UUID, int] = {}  # node.id -> сколько активных рисков связано (бейдж вместо отдельных узлов)

    def bump(acc: dict[uuid.UUID, int], nid: uuid.UUID, rank: int) -> None:
        acc[nid] = max(acc.get(nid, 0), rank)

    q_topics: dict[uuid.UUID, list[uuid.UUID]] = {}
    for e in edges:
        a, b = by_id.get(e.src_id), by_id.get(e.dst_id)
        if not a or not b:
            continue
        if e.kind == "asks_about" and b.kind == "topic":
            q_topics.setdefault(a.id, []).append(b.id)
        for x, y in ((a, b), (b, a)):
            if y.kind == "risk" and x.kind in ("question", "norm"):
                ry = rid(y)
                r = risks.get(ry) if ry else None
                if not r:
                    continue
                if r.status in ACTIVE:
                    bump(lvl, x.id, level_rank(r.level))
                    counts[x.id] = counts.get(x.id, 0) + 1
                else:
                    bump(past, x.id, level_rank(r.level))
    for qid, tids in q_topics.items():
        for t in tids:
            if lvl.get(qid):
                bump(lvl, t, lvl[qid])
            if past.get(qid):
                bump(past, t, past[qid])
            if counts.get(qid):
                counts[t] = counts.get(t, 0) + counts[qid]
    degree: dict[uuid.UUID, set[uuid.UUID]] = {}
    for e in edges:
        if e.kind in ("cites", "asks_about"):
            degree.setdefault(e.dst_id, set()).add(e.src_id)
    out_nodes = []
    for n in nodes:
        rn = rid(n)
        r = risks.get(rn) if rn else None
        rl = (r.level if r and r.status in ACTIVE else None) if n.kind == "risk" else (LEVELS[lvl[n.id] - 1] if lvl.get(n.id) else None)
        d = dict(n.data)
        if r:
            d.update(status=r.status, score=r.score)
        prev = (r.level if r and r.status not in ACTIVE else None) if n.kind == "risk" else (LEVELS[past[n.id] - 1] if past.get(n.id) and not lvl.get(n.id) else None)
        out_nodes.append({"id": str(n.id), "kind": n.kind, "label": n.label, "weight": len(degree.get(n.id, ())) or 1, "risk_level": rl, "resolved_level": prev, "risk_count": counts.get(n.id, 0), "data": d})
    lay = s.layout or {}
    return {
        "nodes": out_nodes,
        "edges": [{"id": str(e.id), "source": str(e.src_id), "target": str(e.dst_id), "kind": e.kind, "data": e.data} for e in edges],
        "positions": lay.get("positions", {}),
        "filters": lay.get("filters", {}),
        "topics": [{"id": k, "title": v} for k, v in TOPIC_TITLES.items()],
    }


def timeline(db: Session, s: ConsultationSession) -> list[dict[str, Any]]:
    """Хронология: вопросы по порядку, их основания, риски (с уровнем и статусом) и ветвления-уточнения."""
    qs = list(db.scalars(select(GraphNode).where(GraphNode.session_id == s.id, GraphNode.kind == "question").order_by(GraphNode.created_at, GraphNode.id)))
    edges = list(db.scalars(select(GraphEdge).where(GraphEdge.session_id == s.id)))
    nodes = {n.id: n for n in db.scalars(select(GraphNode).where(GraphNode.session_id == s.id))}
    risks = {r.id: r for r in db.scalars(select(Risk).where(Risk.session_id == s.id))}
    out = []
    for i, q in enumerate(qs, 1):
        topics, norms, rlist, follow, cond = [], [], [], None, None
        for e in edges:
            if e.src_id == q.id:
                d = nodes.get(e.dst_id)
                if not d:
                    continue
                if e.kind == "asks_about" and d.kind == "topic":
                    topics.append(d.label)
                elif e.kind == "cites":
                    norms.append(d.label)
                elif e.kind == "evidences":
                    r = risks.get(uuid.UUID(d.data["risk_id"])) if d.data.get("risk_id") else None
                    rlist.append({
                        "node_id": str(d.id), "label": d.label, "risk_id": str(r.id) if r else None,
                        "level": r.level if r else None, "score": r.score if r else None, "p": r.p if r else None, "s": r.s if r else None,
                        "status": r.status if r else None, "recommendation": r.recommendation if r else "", "closed_at": r.closed_at.isoformat() if r and r.closed_at else None,
                    })
                elif e.kind == "follow_up_of":
                    follow, cond = d.data.get("message_id"), e.data.get("condition")
        out.append({
            "node_id": str(q.id), "message_id": q.data.get("message_id"), "seq": i, "at": q.created_at, "text": q.label, "result": q.data.get("result"),
            "topics": topics, "norms": norms, "risks": rlist, "follow_up_of": follow, "condition": cond,
        })
    return out
