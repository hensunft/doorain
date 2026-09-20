"""PDF-экспорт портрета из согласованного снимка (snapshot хранится в Export и не меняется после обновления корпуса)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from reportlab.graphics.shapes import Circle, Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    LongTable,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.util import now
from ...db.models import (
    BusinessProfile,
    Citation,
    ConsultationSession,
    CorpusGeneration,
    DocumentRevision,
    GenerationRun,
    Message,
    Risk,
    RiskEvidence,
    SessionFact,
)
from ..portrait import graph, layout
from ..risks.methodology import DEMO_NOTICE, DISCLAIMER, TOPIC_TITLES
from ..risks.scoring import LEVEL_RU

FONTS = Path(__file__).resolve().parents[2] / "assets" / "fonts"
LEVEL_COLOR = {"low": "#3F6B55", "medium": "#8A641F", "high": "#B4473E", "critical": "#70263A", None: "#9A9A94"}
ROLE_RU = {"student": "Студент", "entrepreneur": "Предприниматель", "expert": "Эксперт"}
STATUS_RU = {"open": "Открыт", "in_progress": "В работе", "resolved": "Снят", "needs_clarification": "Нужно уточнение", "not_applicable": "Неприменим"}
_registered = False


def _fonts() -> None:
    global _registered  # noqa: PLW0603
    if _registered:
        return
    for name, f in (("Sans", "DejaVuSans.ttf"), ("Sans-Bold", "DejaVuSans-Bold.ttf"), ("Serif-Bold", "DejaVuSerif-Bold.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(FONTS / f)))
    pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans", boldItalic="Sans-Bold")
    _registered = True


# ───────────── снимок ─────────────
def build_snapshot(db: Session, s: ConsultationSession, options: dict[str, Any], incomplete_reason: str | None) -> dict[str, Any]:
    g = graph.view(db, s)
    pos = layout.radial(g["nodes"], g["edges"])
    risks = list(db.scalars(select(Risk).where(Risk.session_id == s.id)))
    cites = list(db.scalars(select(Citation).where(Citation.session_id == s.id).order_by(Citation.created_at)))
    runs = list(db.scalars(select(GenerationRun).where(GenerationRun.session_id == s.id).order_by(GenerationRun.created_at)))
    msgs = list(db.scalars(select(Message).where(Message.session_id == s.id).order_by(Message.seq)))
    cmap = {c.id: c for c in cites}

    def norms_for(r: Risk) -> list[str]:
        ids = [e.ref_id for e in db.scalars(select(RiskEvidence).where(RiskEvidence.risk_id == r.id, RiskEvidence.kind == "obligation"))]
        out = []
        for i in ids:
            c = cmap.get(i)
            if c:
                sn = c.snapshot
                out.append(f"{sn['short_name'] or sn['act_title']}, {sn['locator']} (ред. {sn['revision_date'] or sn['edition'] or 'н/д'})")
        return list(dict.fromkeys(out))

    def rdict(r: Risk) -> dict[str, Any]:
        return {"id": str(r.id), "kind": r.kind, "title": r.title, "status": r.status, "p": r.p, "s": r.s, "score": r.score, "level": r.level, "category": TOPIC_TITLES.get(r.category or "", r.category), "scenario": r.scenario, "conditions": r.conditions, "consequences": r.consequences, "recommendation": r.recommendation, "p_reason": r.p_reason, "s_reason": r.s_reason, "clarification": r.clarification, "resolution_reason": r.resolution_reason, "resolved_by": r.resolved_by, "norms": norms_for(r), "version": r.version}

    ranked = sorted([r for r in risks if r.status in ("open", "in_progress")], key=lambda r: (-(r.score or 0), -(r.s or 0)))
    qsum = []
    for m in msgs:
        if m.role == "user":
            ans = next((a for a in msgs if a.role == "assistant" and a.seq == m.seq + 1), None)
            claims = [b["text"] for b in (ans.blocks or []) if b["kind"] == "claim" and b["state"] == "verified"][:2] if ans else []
            refused = bool(ans and ans.blocks and ans.blocks[0]["kind"] == "refusal")
            srcs = set()
            for b in (ans.blocks or []) if ans else []:
                for cid in b.get("citation_ids", []):
                    c = cmap.get(uuid.UUID(cid))
                    if c:
                        srcs.add(f"{c.snapshot['short_name'] or c.snapshot['act_title']}, {c.snapshot['locator']}")
            qsum.append({"question": m.content, "claims": claims, "refused": refused, "sources": sorted(srcs)})
    gen = None
    gid = next((r.corpus_generation_id for r in reversed(runs) if r.corpus_generation_id), None)
    if gid:
        gen = db.get(CorpusGeneration, gid)
    revs = []
    seen = set()
    for c in cites:
        if c.revision_id in seen:
            continue
        seen.add(c.revision_id)
        rv = db.get(DocumentRevision, c.revision_id)
        revs.append({"title": c.snapshot["act_title"], "short_name": c.snapshot["short_name"], "revision_date": c.snapshot["revision_date"], "edition": c.snapshot["edition"], "verified_at": c.snapshot["verified_at"], "is_demo": c.snapshot["is_demo"], "doc_type": c.snapshot["doc_type"], "checksum": (rv.checksum if rv else "")[:12]})
    prof = None
    if options.get("include_profile") and s.role == "entrepreneur":
        bp = db.scalar(select(BusinessProfile).where(BusinessProfile.session_id == s.id).order_by(BusinessProfile.created_at.desc()))
        prof = bp.data if bp else None
    last_model = next((r.model_info for r in reversed(runs) if r.model_info), {})
    seen_src: dict[tuple, dict[str, Any]] = {}
    for c in cites:
        sn = c.snapshot
        seen_src.setdefault((str(c.revision_id), sn["locator"]), {"act": sn["act_title"], "short_name": sn["short_name"], "locator": sn["locator"], "revision_date": sn["revision_date"], "edition": sn["edition"], "page": sn["page"], "verified_at": sn["verified_at"], "is_demo": sn["is_demo"], "excerpt": c.excerpt[:700]})
    return {
        "schema": 1, "created_at": now().isoformat(), "incomplete": incomplete_reason is not None, "incomplete_reason": incomplete_reason,
        "session": {"id": str(s.id), "title": s.title, "role": s.role, "as_of_date": s.as_of_date.isoformat(), "version": s.version},
        "profile": prof, "include_dialog": bool(options.get("include_dialog")),
        "model": {"name": last_model.get("name"), "digest": last_model.get("digest"), "quantization": last_model.get("quantization"), "provider": last_model.get("provider"), "reranker": last_model.get("reranker")},
        "corpus": {"generation_seq": gen.seq if gen else None, "generation_id": str(gen.id) if gen else None, "activated_at": gen.activated_at.isoformat() if gen and gen.activated_at else None, "revisions": revs},
        "questions": qsum,
        "graph": {"nodes": g["nodes"], "edges": g["edges"], "positions": {k: list(v) for k, v in pos.items()}},
        "risks": [rdict(r) for r in ranked], "needs_clarification": [rdict(r) for r in risks if r.status == "needs_clarification"], "resolved": [rdict(r) for r in risks if r.status in ("resolved", "not_applicable")],
        "clarifications": [f.statement for f in db.scalars(select(SessionFact).where(SessionFact.session_id == s.id, SessionFact.kind == "clarification", SessionFact.status == "active"))],
        "sources": list(seen_src.values()),
        "dialog": [{"role": m.role, "text": "\n".join(b["text"] for b in (m.blocks or [])) if m.role == "assistant" else m.content} for m in msgs] if options.get("include_dialog") else [],
        "versions": {"session_version": s.version, "risks": {str(r.id): r.version for r in risks}, "message_ids": [str(m.id) for m in msgs], "citation_ids": [str(c.id) for c in cites]},
        "disclaimer": DISCLAIMER,
        "demo": any(r["is_demo"] for r in revs),
    }


# ───────────── рендер ─────────────
def _st() -> dict[str, ParagraphStyle]:
    base = dict(fontName="Sans", fontSize=9.5, leading=13.5, textColor=colors.HexColor("#37352F"), alignment=TA_LEFT)
    return {
        "body": ParagraphStyle("body", **base),
        "small": ParagraphStyle("small", **{**base, "fontSize": 8, "leading": 10.5}),
        "cell": ParagraphStyle("cell", **{**base, "fontSize": 8, "leading": 10.2}),
        "cellb": ParagraphStyle("cellb", **{**base, "fontName": "Sans-Bold", "fontSize": 8, "leading": 10.2}),
        "h1": ParagraphStyle("h1", **{**base, "fontName": "Serif-Bold", "fontSize": 20, "leading": 25, "spaceAfter": 6}),
        "h2": ParagraphStyle("h2", **{**base, "fontName": "Serif-Bold", "fontSize": 13.5, "leading": 18, "spaceBefore": 12, "spaceAfter": 5}),
        "muted": ParagraphStyle("muted", **{**base, "textColor": colors.HexColor("#6B6B66"), "fontSize": 8.5}),
        "banner": ParagraphStyle("banner", **{**base, "textColor": colors.HexColor("#70263A"), "fontName": "Sans-Bold", "backColor": colors.HexColor("#F7EDEF"), "borderPadding": 6, "spaceBefore": 6, "spaceAfter": 8}),
    }


def _esc(t: Any) -> str:
    return str(t if t is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _draw_graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], pos: dict[str, list[float]], w: float, h: float) -> Drawing:
    d = Drawing(w, h)
    if not nodes:
        return d
    xs, ys = [pos[n["id"]][0] for n in nodes if n["id"] in pos], [pos[n["id"]][1] for n in nodes if n["id"] in pos]
    if not xs:
        return d
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    sc = min((w - 120) / max(1, maxx - minx), (h - 60) / max(1, maxy - miny), 1.6)
    ox, oy = w / 2 - (minx + maxx) / 2 * sc, h / 2 - (miny + maxy) / 2 * sc
    P = {n["id"]: (pos[n["id"]][0] * sc + ox, pos[n["id"]][1] * sc + oy) for n in nodes if n["id"] in pos}
    for e in edges:
        if e["source"] in P and e["target"] in P:
            a, b = P[e["source"]], P[e["target"]]
            d.add(Line(a[0], a[1], b[0], b[1], strokeColor=colors.HexColor("#C9C9C5"), strokeWidth=0.6))
    for n in nodes:
        if n["id"] not in P:
            continue
        x, y = P[n["id"]]
        r = {"center": 12, "topic": 9, "question": 6, "norm": 5, "risk": 7}.get(n["kind"], 5) + min(3, n["weight"] - 1)
        fill = colors.HexColor("#37352F") if n["kind"] == "center" else colors.HexColor(LEVEL_COLOR[n["risk_level"]])
        d.add(Circle(x, y, r, fillColor=fill if n["kind"] != "norm" else colors.white, strokeColor=fill, strokeWidth=1.2 if n["kind"] == "norm" else 0.5))
        lab = n["label"][:26] + ("…" if len(n["label"]) > 26 else "")
        d.add(String(x + r + 2, y - 2.5, lab, fontName="Sans", fontSize=6.5, fillColor=colors.HexColor("#37352F")))
    return d


def _page_deco(snap: dict[str, Any]):
    def deco(canv: Any, doc: Any) -> None:
        canv.saveState()
        canv.setFont("Sans", 7)
        canv.setFillColor(colors.HexColor("#6B6B66"))
        w, h = canv._pagesize
        canv.drawString(15 * mm, 9 * mm, f"DoorAIn · {snap['session']['title'][:60]} · {DISCLAIMER}")
        canv.drawRightString(w - 15 * mm, 9 * mm, f"стр. {doc.page}")
        if snap["incomplete"]:
            canv.setFillColor(colors.HexColor("#70263A"))
            canv.drawString(15 * mm, h - 9 * mm, "НЕПОЛНЫЙ СНИМОК: анализ сессии не завершён на момент выгрузки")
        canv.restoreState()

    return deco


def render_pdf(snap: dict[str, Any], out: Path) -> None:
    _fonts()
    st = _st()
    pw, ph = A4
    lw, lh = landscape(A4)
    m = 15 * mm
    doc = BaseDocTemplate(str(out), pagesize=A4, title=f"DoorAIn — {snap['session']['title']}", author="DoorAIn", leftMargin=m, rightMargin=m, topMargin=m, bottomMargin=m)
    deco = _page_deco(snap)
    doc.addPageTemplates([
        PageTemplate(id="P", frames=[Frame(m, m + 4 * mm, pw - 2 * m, ph - 2 * m - 4 * mm, id="fp")], onPage=deco, pagesize=A4),
        PageTemplate(id="L", frames=[Frame(m, m + 4 * mm, lw - 2 * m, lh - 2 * m - 4 * mm, id="fl")], onPage=deco, pagesize=landscape(A4)),
    ])
    se = snap["session"]
    story: list[Any] = [Paragraph("DoorAIn · «Дориан»", st["muted"]), Paragraph("Цифровой портрет правового положения", st["h1"])]
    if snap["incomplete"]:
        story.append(Paragraph(f"Неполный снимок: {_esc(snap['incomplete_reason'])}", st["banner"]))
    if snap["demo"]:
        story.append(Paragraph(DEMO_NOTICE, st["banner"]))
    corpus = snap["corpus"]
    info = [
        ["Сессия", se["title"]], ["Роль", ROLE_RU.get(se["role"], se["role"])], ["Дата правового среза", se["as_of_date"]],
        ["Дата выгрузки", snap["created_at"][:19].replace("T", " ") + " UTC"],
        ["Корпус", f"generation №{corpus['generation_seq']} (активирована {(corpus['activated_at'] or '')[:10]})" if corpus["generation_seq"] else "не использовался"],
        ["Модель", f"{snap['model'].get('name') or 'не указана'}; digest {(snap['model'].get('digest') or 'н/д')[:16]}; {snap['model'].get('quantization') or ''}".strip("; ")],
    ]
    if snap["profile"]:
        info.append(["Профиль бизнеса", "; ".join(f"{k}: {v}" for k, v in snap["profile"].items() if v not in (None, ""))])
    t = Table([[Paragraph(_esc(a), st["cellb"]), Paragraph(_esc(b), st["cell"])] for a, b in info], colWidths=[42 * mm, pw - 2 * m - 42 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#E9E9E7")), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story += [t, Spacer(1, 6), Paragraph(f"<b>Важно.</b> {DISCLAIMER}.", st["body"])]
    story.append(Paragraph("Краткий итог по вопросам сессии", st["h2"]))
    if not snap["questions"]:
        story.append(Paragraph("В сессии пока нет вопросов.", st["body"]))
    for i, q in enumerate(snap["questions"], 1):
        parts = [Paragraph(f"<b>{i}. {_esc(q['question'])}</b>", st["body"])]
        if q["refused"]:
            parts.append(Paragraph("Ответ: отказ — в базе знаний недостаточно оснований или вопрос вне области.", st["small"]))
        for cl in q["claims"]:
            parts.append(Paragraph("• " + _esc(cl), st["small"]))
        if q["sources"]:
            parts.append(Paragraph("Источники: " + _esc("; ".join(q["sources"])), st["muted"]))
        story.append(KeepTogether(parts + [Spacer(1, 4)]))
    # граф + таблица рисков — на альбомных страницах
    story += [NextPageTemplate("L"), PageBreak(), Paragraph("Цифровой слепок (граф)", st["h2"])]
    g = snap["graph"]
    gw, gh = lw - 2 * m, lh - 2 * m - 40
    if len(g["nodes"]) <= 40:
        story.append(_draw_graph(g["nodes"], g["edges"], g["positions"], gw, gh))
    else:  # общий обзор (темы и риски) + страницы по темам
        ov = [n for n in g["nodes"] if n["kind"] in ("center", "topic", "risk")]
        story.append(_draw_graph(ov, g["edges"], g["positions"], gw, gh))
        for t_ in [n for n in g["nodes"] if n["kind"] == "topic"]:
            ids = {t_["id"]} | {e["source"] for e in g["edges"] if e["target"] == t_["id"]}
            ids |= {e["target"] if e["source"] in ids else e["source"] for e in g["edges"] if e["source"] in ids or e["target"] in ids}
            story += [PageBreak(), Paragraph(f"Слепок: {_esc(t_['label'])}", st["h2"]), _draw_graph([n for n in g["nodes"] if n["id"] in ids], g["edges"], g["positions"], gw, gh)]
    story.append(Paragraph("Цвет узла — максимальный уровень связанных активных рисков; серый — риски не выявлены или сведений недостаточно (это не доказательство безопасности).", st["muted"]))
    story += [PageBreak(), Paragraph("Таблица рисков", st["h2"]), Paragraph("Методика P×S экспериментальная и качественная: это не вероятность штрафа. Основание последствий указывается отдельно.", st["muted"])]
    head = ["№", "Риск и сценарий", "P×S, уровень", "Нормативное основание", "Последствия", "Рекомендация", "Статус"]
    cw = [8 * mm, 58 * mm, 24 * mm, 56 * mm, 46 * mm, 50 * mm, 22 * mm]
    rows: list[list[Any]] = [[Paragraph(h, st["cellb"]) for h in head]]
    styles = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F7F7F5")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#E9E9E7")), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for i, r in enumerate(snap["risks"], 1):
        col = LEVEL_COLOR[r["level"]]
        lvl = f"<font color='{col}'><b>{r['p']}×{r['s']}={r['score']}<br/>{LEVEL_RU.get(r['level'], '')}</b></font>"
        rows.append([Paragraph(str(i), st["cell"]), Paragraph(f"<b>{_esc(r['title'])}</b><br/>{_esc(r['scenario'])}", st["cell"]), Paragraph(lvl, st["cell"]), Paragraph(_esc("; ".join(r["norms"]) or "—"), st["cell"]), Paragraph(_esc(r["consequences"] or "—"), st["cell"]), Paragraph(_esc(r["recommendation"] or "—"), st["cell"]), Paragraph(STATUS_RU.get(r["status"], r["status"]), st["cell"])])
    if len(rows) == 1:
        rows.append([Paragraph("—", st["cell"])] + [Paragraph("Активных оценённых рисков нет", st["cell"])] + [Paragraph("", st["cell"])] * 5)
    tb = LongTable(rows, colWidths=cw, repeatRows=1)
    tb.setStyle(TableStyle(styles))
    story.append(tb)
    for title, key in (("Ожидают уточнения (не ранжируются)", "needs_clarification"), ("Снятые риски (история)", "resolved")):
        items = snap[key]
        if items:
            story.append(Paragraph(title, st["h2"]))
            for r in items:
                extra = r["clarification"] if key == "needs_clarification" else f"{r['resolution_reason'] or ''} ({'по сообщению пользователя' if r['resolved_by'] == 'user_message' else 'вручную'})"
                story.append(Paragraph(f"• <b>{_esc(r['title'])}</b> — {_esc(extra)}", st["small"]))
    if snap["clarifications"]:
        story.append(Paragraph("Вопросы для уточнения", st["h2"]))
        story += [Paragraph("• " + _esc(c), st["small"]) for c in snap["clarifications"]]
    story += [NextPageTemplate("P"), PageBreak(), Paragraph("Источники и редакции", st["h2"])]
    for src in snap["sources"]:
        when = f"редакция от {src['revision_date']}" if src["revision_date"] else (f"издание {src['edition']}" + (f", с. {src['page']}" if src["page"] else "") if src["edition"] else "дата не указана")
        ver = f"проверена {src['verified_at']}" if src["verified_at"] else "актуальность не подтверждена"
        story.append(KeepTogether([Paragraph(f"<b>{_esc(src['short_name'] or src['act'])}</b>, {_esc(src['locator'])} — {when}; {ver}", st["small"]), Paragraph("«" + _esc(src["excerpt"]) + "»", st["muted"]), Spacer(1, 4)]))
    if not snap["sources"]:
        story.append(Paragraph("Источники не использовались.", st["body"]))
    story.append(Paragraph("Ограничения", st["h2"]))
    story.append(Paragraph(f"{DISCLAIMER}. Оценки рисков получены по экспериментальной методике и не проверены юристом. Тексты норм приведены по загруженным редакциям корпуса; актуальность на дату выгрузки определяется владельцем корпуса.", st["small"]))
    if snap["include_dialog"] and snap["dialog"]:
        story += [PageBreak(), Paragraph("Приложение: диалог", st["h2"])]
        story += [Paragraph(f"<b>{'Вопрос' if d['role'] == 'user' else 'Ответ'}:</b> {_esc(d['text'])}", st["small"]) for d in snap["dialog"]]
    doc.build(story)
