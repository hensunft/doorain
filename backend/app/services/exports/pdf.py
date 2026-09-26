"""PDF «Правовой слепок сессии» из согласованного снимка (снимок хранится в Export и не меняется после обновления корпуса).

Состав: титул, сводка, три содержательных блока (граф-слепок, риск-менеджмент, нормативные основания) и приложение
с методикой. Реплик диалога в документе нет ни целиком, ни в пересказе: вопросы обозначаются номерами. Нормы берутся
только из цитат ответов сессии, цвета — из app/config/print.yaml (те же значения, что в tokens.css)."""

from __future__ import annotations

import math
import re
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from reportlab.graphics.shapes import Circle, Drawing, Group, Line, Polygon, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
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

from ...core.config import get_settings
from ...core.util import now
from ...db.models import Citation, ConsultationSession, CorpusGeneration, GenerationRun, Risk, RiskEvidence
from ..portrait import graph
from ..risks import scales as risk_scales
from ..risks.methodology import DISCLAIMER
from ..risks.scoring import LEVEL_RU, LEVELS

APP = Path(__file__).resolve().parents[2]
FONTS = APP / "assets" / "fonts"
PAL: dict[str, str] = yaml.safe_load((APP / "config" / "print.yaml").read_text(encoding="utf-8"))
TOKEN: dict[str | None, str] = {"low": "risk-low", "medium": "risk-mid", "high": "risk-high", "critical": "risk-critical", None: "risk-none"}
DOC_TITLE = "Правовой слепок сессии"
ROLE_RU = {"student": "Студент", "entrepreneur": "Предприниматель", "expert": "Эксперт"}
STATUS_RU = {"open": "открыт", "in_progress": "в работе", "resolved": "закрыт", "not_applicable": "неприменим", "needs_clarification": "нужно уточнение"}
CLOSED = ("resolved", "not_applicable")
GROUPS = (("law", "Федеральные законы"), ("code", "Кодексы"), ("bylaw", "Подзаконные акты"), ("soft_law", "Разъяснения"), ("textbook", "Учебная литература — пояснения, не основание рисков"))
LABEL_PT = 9  # минимальный кегль подписей графа
_registered = False


def col(name: str, alpha: float = 1.0) -> colors.Color:
    c = colors.HexColor(PAL[name])
    return c if alpha == 1.0 else colors.Color(c.red, c.green, c.blue, alpha=alpha)


def lv_fill(lv: str | None) -> colors.Color:
    return col(TOKEN[lv])


def lv_tint(lv: str | None) -> colors.Color:
    return col(TOKEN[lv] + "-tint")


def lv_ink_hex(lv: str | None) -> str:
    """Цвет подписи уровня на белом: у среднего — тёмный вариант (контраст ≥ 4.5:1)."""
    return PAL["risk-mid-ink"] if lv == "medium" else PAL[TOKEN[lv]]


def lv_on(lv: str | None) -> colors.Color:
    return col("on-risk-mid") if lv == "medium" else col("on-risk")


def _fonts() -> None:
    global _registered  # noqa: PLW0603
    if _registered:
        return
    for name, f in (("Sans", "IBMPlexSans_400Regular.ttf"), ("Sans-Bold", "IBMPlexSans_600SemiBold.ttf"), ("Display", "PlayfairDisplay_700Bold.ttf"), ("Mono", "IBMPlexMono_400Regular.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(FONTS / f)))
    pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans", boldItalic="Sans-Bold")
    _registered = True


def _esc(t: Any) -> str:
    return str(t if t is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _d(iso: str | None) -> str:
    """ISO-дата → ДД.ММ.ГГГГ."""
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if iso and len(iso) >= 10 else ""


def _plural(n: int, one: str, few: str, many: str) -> str:
    k = n % 100
    w = many if 11 <= k <= 14 else one if k % 10 == 1 else few if 2 <= k % 10 <= 4 else many
    return f"{n} {w}"


def _level(sc: int, t: list[int]) -> str:
    return "low" if sc <= t[0] else "medium" if sc <= t[1] else "high" if sc <= t[2] else "critical"


def _rank(lv: str | None) -> int:
    return LEVELS.index(lv) + 1 if lv in LEVELS else 0


# ───────────── снимок ─────────────
def _group(sn: dict[str, Any]) -> str:
    if sn.get("doc_type") in ("soft_law", "textbook"):
        return str(sn["doc_type"])
    name = f"{sn.get('act_title') or ''} {sn.get('short_name') or ''} {sn.get('act_number') or ''}".lower()
    if "кодекс" in name or re.search(r"\bкоап\b|\bгк рф\b|\bук рф\b|\bнк рф\b|\bтк рф\b", name):
        return "code"
    if "федеральный закон" in name or re.search(r"\d+-фз", name):
        return "law"
    return "bylaw"


def _requisites(sn: dict[str, Any]) -> tuple[str, str]:
    title = sn.get("act_title") or sn.get("short_name") or "Документ"
    bits = []
    if sn.get("act_number") and sn["act_number"] not in title:
        bits.append(f"№ {sn['act_number']}")
    if sn.get("act_date") and _d(sn["act_date"]) not in title:
        bits.append(f"от {_d(sn['act_date'])}")
    bits.append(f"ред. от {_d(sn['revision_date'])}" if sn.get("revision_date") else f"изд. {sn['edition']}" if sn.get("edition") else "редакция не указана")
    if sn.get("verified_at"):
        bits.append(f"сверена {_d(sn['verified_at'])}")
    return title, " · ".join(bits)


def _norm_label(sn: dict[str, Any]) -> str:
    return f"{sn.get('short_name') or sn.get('act_title')}, {sn.get('locator')} (ред. {_d(sn.get('revision_date')) or sn.get('edition') or 'н/д'})"


def build_snapshot(db: Session, s: ConsultationSession, options: dict[str, Any], incomplete_reason: str | None) -> dict[str, Any]:
    g = graph.view(db, s)
    qs = sorted((n for n in g["nodes"] if n["kind"] == "question"), key=lambda n: (n["data"].get("seq") or 0, n["id"]))
    qnum = {n["id"]: i for i, n in enumerate(qs, 1)}
    by_msg = {str(n["data"].get("message_id")): qnum[n["id"]] for n in qs}
    nodes = []
    for n in g["nodes"]:
        d = {k: n[k] for k in ("id", "kind", "label", "weight", "risk_level", "resolved_level", "risk_count")}
        if n["kind"] == "question":
            d["label"], d["num"] = f"Вопрос №{qnum[n['id']]}", qnum[n["id"]]  # текст вопроса — реплика: в документ не попадает
        if n["kind"] == "risk":
            d["status"] = n["data"].get("status")
        nodes.append(d)
    edges = [{"source": e["source"], "target": e["target"], "kind": e["kind"]} for e in g["edges"]]

    cites = list(db.scalars(select(Citation).where(Citation.session_id == s.id).order_by(Citation.created_at, Citation.id)))
    cmap = {c.id: c for c in cites}
    runs = list(db.scalars(select(GenerationRun).where(GenerationRun.session_id == s.id).order_by(GenerationRun.created_at)))
    run_q = {r.id: by_msg.get(str(r.user_message_id)) for r in runs}
    risks = list(db.scalars(select(Risk).where(Risk.session_id == s.id).order_by(Risk.created_at, Risk.id)))
    evidence: dict[uuid.UUID, list[RiskEvidence]] = defaultdict(list)
    if risks:
        for e in db.scalars(select(RiskEvidence).where(RiskEvidence.risk_id.in_([r.id for r in risks]), RiskEvidence.kind.in_(("obligation", "consequence"))).order_by(RiskEvidence.created_at, RiskEvidence.id)):
            evidence[e.risk_id].append(e)

    bases: dict[str, dict[str, Any]] = {}

    def article(c: Citation) -> dict[str, Any]:
        sn = c.snapshot
        title, req = _requisites(sn)
        act = bases.setdefault(f"{c.document_id}:{c.revision_id}", {"group": _group(sn), "title": title, "requisites": req, "archived": bool(sn.get("archived")), "articles": {}})
        return act["articles"].setdefault(sn.get("locator") or "без локатора", {"locator": sn.get("locator") or "без локатора", "questions": set(), "risks": []})

    for c in cites:  # перечень оснований — только из цитат ответов (answer traces), ничего сверх
        q = run_q.get(c.run_id)
        a = article(c)
        if q:
            a["questions"].add(q)
    rows: list[dict[str, Any]] = []
    for r in risks:
        norms = []
        for e in evidence[r.id]:
            cit = cmap.get(e.ref_id)
            if not cit:  # основание вне цитат этой сессии в документ не попадает
                continue
            if e.kind == "obligation":
                norms.append(_norm_label(cit.snapshot))
            a = article(cit)
            if r.title not in a["risks"]:
                a["risks"].append(r.title)
        rows.append({
            "id": str(r.id), "kind": r.kind, "origin": r.origin, "title": r.title, "status": r.status, "p": r.p, "s": r.s, "score": r.score, "level": r.level,
            "norms": list(dict.fromkeys(norms)), "consequences": r.consequences, "recommendation": r.recommendation, "clarification": r.clarification,
            "resolution_reason": r.resolution_reason, "closed_at": r.closed_at.isoformat() if r.closed_at else None,
        })
    for act in bases.values():
        act["articles"] = [{**a, "questions": sorted(a["questions"])} for a in act["articles"].values()]
    acts = sorted(bases.values(), key=lambda a: (next(i for i, (k, _) in enumerate(GROUPS) if k == a["group"]), a["title"], a["requisites"]))

    active = sorted((r for r in rows if r["status"] in ("open", "in_progress") and r["level"]), key=lambda r: (-_rank(r["level"]), -(r["score"] or 0), r["title"]))
    topics = [n["label"] for n in g["nodes"] if n["kind"] == "topic"]
    normative = [a for a in acts if a["group"] != "textbook"]
    n_art = sum(len(a["articles"]) for a in normative)
    by_level = {lv: sum(1 for r in active if r["level"] == lv) for lv in LEVELS}
    role_ru = ROLE_RU.get(s.role, s.role)
    task = f"Консультация в роли «{role_ru}»" + (f" по {'теме' if len(topics) == 1 else 'темам'}: {', '.join(t.lower() for t in topics)}." if topics else ".")
    if qs:
        task += f" Задано {_plural(len(qs), 'вопрос', 'вопроса', 'вопросов')}; ответы опирались на {_plural(len(normative), 'акт', 'акта', 'актов')}" + (f" ({_plural(n_art, 'статья', 'статьи', 'статей')})." if normative else ".")
        hi = by_level["high"] + by_level["critical"]
        task += f" Открытых рисков: {len(active)}" + (f", из них высоких и критических: {hi}." if hi else ".")
    gen = None
    gid = next((r.corpus_generation_id for r in reversed(runs) if r.corpus_generation_id), None)
    if gid:
        gen = db.get(CorpusGeneration, gid)
    settings = get_settings()
    return {
        "schema": 2, "created_at": now().isoformat(), "incomplete": incomplete_reason is not None, "incomplete_reason": incomplete_reason,
        "session": {"id": str(s.id), "title": s.title, "role": s.role, "as_of_date": s.as_of_date.isoformat(), "version": s.version},
        "summary": {
            "task": task, "by_level": by_level, "top": active[:3],
            "acts_line": f"Задействовано нормативных актов: {len(normative)}, статей и пунктов: {n_art}." + (f" Пояснения из учебной литературы: {len(acts) - len(normative)}." if len(acts) > len(normative) else ""),
        },
        "graph": {"nodes": nodes, "edges": edges},
        "risks": active,
        "closed": [r for r in rows if r["status"] in CLOSED],
        "needs_clarification": [r for r in rows if r["status"] == "needs_clarification"],
        "bases": acts,
        "scales": risk_scales.load(s.role), "thresholds": list(settings.risk_thresholds),
        "corpus": {"generation_seq": gen.seq if gen else None},
        "test_mode": settings.provider_mode == "test" or any((r.model_info or {}).get("provider") == "test" for r in runs),
        "versions": {"session_version": s.version, "risks": {str(r.id): r.version for r in risks}, "citation_ids": [str(c.id) for c in cites]},
        "disclaimer": DISCLAIMER,
        "archived": any(a["archived"] for a in acts),
    }


# ───────────── оформление ─────────────
def _st() -> dict[str, ParagraphStyle]:
    base: dict[str, Any] = {"fontName": "Sans", "fontSize": 9.75, "leading": 15.1, "textColor": col("ink"), "alignment": TA_LEFT}  # 13 px / 1,55

    def ps(name: str, **kw: Any) -> ParagraphStyle:
        return ParagraphStyle(name, **{**base, **kw})

    return {
        "body": ps("body"),
        "small": ps("small", fontSize=9, leading=13.5, textColor=col("ink-2")),
        "muted": ps("muted", fontSize=9, leading=13.5, textColor=col("muted")),
        "mono": ps("mono", fontName="Mono", fontSize=8.5, leading=12.5, textColor=col("ink-2")),
        "cardt": ps("cardt", fontName="Sans-Bold", fontSize=10.5, leading=14.5),
        "cell": ps("cell", fontSize=9, leading=12.5),
        "cellb": ps("cellb", fontName="Sans-Bold", fontSize=9, leading=12.5),
        "h1": ps("h1", fontName="Display", fontSize=16.5, leading=21, spaceAfter=8),  # 22 px
        "h2": ps("h2", fontName="Display", fontSize=12.75, leading=17, spaceBefore=12, spaceAfter=5),  # 17 px
        "title": ps("title", fontName="Display", fontSize=26, leading=32, spaceAfter=8),
        "theme": ps("theme", fontSize=14, leading=19, textColor=col("ink-2")),
        "banner": ps("banner", fontName="Sans-Bold", fontSize=9.5, leading=13, textColor=col("risk-critical"), backColor=col("risk-critical-tint"), borderPadding=6, spaceBefore=6, spaceAfter=10),
    }


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    """Перенос по словам; слишком длинное слово переносится по символам — подписи не обрезаются."""
    lines: list[str] = []
    cur = ""
    for w in text.split():
        cand = f"{cur} {w}".strip()
        if pdfmetrics.stringWidth(cand, font, size) <= width:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        while pdfmetrics.stringWidth(w, font, size) > width and len(w) > 1:
            k = max(1, int(len(w) * width / pdfmetrics.stringWidth(w, font, size)))
            lines.append(w[:k])
            w = w[k:]
        cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _hatch(d: Drawing, x: float, y: float, w: float, h: float, lv: str | None, on_fill: bool) -> None:
    """Штриховка уровня (как в интерфейсе): низкий — без неё, средний — редкая, высокий — частая, критический — сетка."""
    step = {"medium": 7.0, "high": 3.5, "critical": 3.5}.get(lv or "")
    if not step:
        return
    stroke = col("surface", 0.38) if on_fill else col("ink", 0.2)
    k = -h + step
    while k < w:  # линии x − y = k
        x1, y1, x2, y2 = max(0.0, k), max(0.0, -k), min(w, h + k), min(h, w - k)
        if x2 > x1:
            d.add(Line(x + x1, y + y1, x + x2, y + y2, strokeColor=stroke, strokeWidth=0.6))
        k += step
    if lv == "critical":
        k = step
        while k < w + h:  # линии x + y = k
            x1, y1, x2, y2 = max(0.0, k - h), min(h, k), min(w, k), max(0.0, k - w)
            if x2 > x1:
                d.add(Line(x + x1, y + y1, x + x2, y + y2, strokeColor=stroke, strokeWidth=0.6))
            k += step


def _swatch(d: Drawing, x: float, y: float, size: float, lv: str | None) -> None:
    d.add(Rect(x, y, size, size, fillColor=lv_tint(lv), strokeColor=lv_fill(lv), strokeWidth=0.8))
    _hatch(d, x, y, size, size, lv, False)


def _hexagon(cx: float, cy: float, r: float) -> list[float]:
    return [v for i in range(6) for v in (cx + r * math.cos(math.pi / 3 * i), cy + 0.9 * r * math.sin(math.pi / 3 * i))]


def _diamond(cx: float, cy: float, r: float) -> list[float]:
    return [cx, cy + r, cx + r, cy, cx, cy - r, cx - r, cy]


def _arrow(d: Drawing, x: float, y: float, dx: float, dy: float, color: colors.Color) -> None:
    """Наконечник в точке (x, y) по направлению (dx, dy)."""
    n = max(1e-6, math.hypot(dx, dy))
    ux, uy = dx / n, dy / n
    d.add(Polygon([x, y, x - 6 * ux - 3 * uy, y - 6 * uy + 3 * ux, x - 6 * ux + 3 * uy, y - 6 * uy - 3 * ux], fillColor=color, strokeColor=color, strokeWidth=0.3))


# ───────────── граф-слепок ─────────────
# Раскладка по колонкам «тема → вопрос → норма → риск»: детерминирована (порядок — номер вопроса), подписи не
# перекрываются, текст остаётся текстом. Колонки и промежутки в сумме = полоса набора A4 (170 мм ≈ 482 pt).
# Связи разведены «шинами»: в промежутке между колонками у каждой темы (вопросы по теме), каждого вопроса (нормы в ответе)
# и каждого основания риска своя вертикальная дорожка; к узлам линии подходят горизонтально, каждая в свою точку.
# Ответвление от дорожки отмечено точкой, пересечение — без точки и под прямым углом: связи различимы и при десятках линий.
WIDTHS = {"topic": 104.0, "question": 56.0, "norm": 124.0}
RISK_MIN_W = 108.0
LANE, LANE_PAD, LOOP = 4.5, 5.0, 10.0  # шаг дорожек, поля промежутка, место под петли уточнений слева от вопросов
Link = tuple[str, str, str]  # левый узел, правый узел, ключ дорожки
Pos = dict[str, tuple[float, float, float, float, list[str]]]


def _links(ns: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, list[Link]]:
    """Связи по промежуткам: tq — тема → вопрос, qn — вопрос → норма (общая дорожка у узла той стороны, где узлов меньше:
    меньше дорожек — шире шаг), nr — норма → риск (своя дорожка и цвет уровня у каждого основания)."""
    kind = {n["id"]: n["kind"] for n in ns}
    out: dict[str, list[Link]] = {"tq": [], "qn": [], "nr": []}
    for e in edges:
        a, b = e["source"], e["target"]
        ka, kb = kind.get(a), kind.get(b)
        if e["kind"] == "asks_about" and ka == "question" and kb == "topic":
            out["tq"].append((b, a, ""))
        elif e["kind"] == "cites" and ka == "question" and kb == "norm":
            out["qn"].append((a, b, ""))
        elif e["kind"] == "grounded_in" and ka == "risk" and kb == "norm":
            out["nr"].append((b, a, f"{a}>{b}"))
    for g in ("tq", "qn"):
        left = len({a for a, _, _ in out[g]}) <= len({b for _, b, _ in out[g]})
        out[g] = [(a, b, a if left else b) for a, b, _ in out[g]]
    return {g: list(dict.fromkeys(v)) for g, v in out.items()}


def _cols(ns: list[dict[str, Any]], edges: list[dict[str, Any]], width: float) -> tuple[dict[str, tuple[float, float]], dict[str, float], float]:
    """Колонки (x, ширина), левые края промежутков и шаг дорожек: промежуток растёт с числом дорожек, риски берут остаток."""
    lanes = {g: len({k for *_, k in v}) for g, v in _links(ns, edges).items()}
    extra = sum(max(0, n - 1) for n in lanes.values())
    room = width - sum(WIDTHS.values()) - 6 * LANE_PAD - LOOP - RISK_MIN_W
    step = min(LANE, max(2.0, room / extra)) if extra else LANE
    cols: dict[str, tuple[float, float]] = {}
    gaps: dict[str, float] = {}
    x = 0.0
    for kind, gap in (("topic", "tq"), ("question", "qn"), ("norm", "nr")):
        cols[kind] = (x, WIDTHS[kind])
        x += WIDTHS[kind]
        gaps[gap] = x
        x += 2 * LANE_PAD + step * max(0, lanes[gap] - 1) + (LOOP if gap == "tq" else 0)
    cols["risk"] = (x, width - x)
    return cols, gaps, step


def _scale(n: dict[str, Any]) -> float:
    return 1 + min(0.4, max(0, (n.get("weight") or 1) - 1) * 0.1)  # размер — число связей


def _risk_label(n: dict[str, Any]) -> str:
    closed = n.get("status") in CLOSED
    lv = n.get("resolved_level") if closed else n.get("risk_level")
    tail = f" · закрыт ({LEVEL_RU.get(lv or '', '').lower()})" if closed else f" · {LEVEL_RU[lv].lower()}" if lv else ""
    return f"{n['label']}{tail}"


def _layout(ns: list[dict[str, Any]], edges: list[dict[str, Any]], width: float = 482.0) -> tuple[Pos, float, dict[str, float], float]:
    """Позиции (x, y сверху, ширина, высота, строки подписи), общая высота схемы, промежутки и шаг дорожек."""
    cols, gaps, step = _cols(ns, edges, width)
    ids = {n["id"] for n in ns}
    qs = sorted((n for n in ns if n["kind"] == "question"), key=lambda n: n.get("num") or 0)
    num = {n["id"]: n.get("num") or 0 for n in qs}
    first: dict[str, int] = {}
    anchor: dict[str, list[str]] = defaultdict(list)  # узел ставится не выше строки, от которой он «вырос»
    for q in qs:
        for e in edges:
            if e["source"] == q["id"] and e["target"] in ids and e["kind"] in ("cites", "evidences", "asks_about"):
                first.setdefault(e["target"], num[q["id"]])
                anchor[e["target"]] = anchor[e["target"]] or [q["id"]]
    for e in edges:  # риск выравнивается по своей норме-основанию
        if e["kind"] == "grounded_in" and e["source"] in ids and e["target"] in ids:
            anchor[e["source"]] = [x for x in anchor[e["source"]] if x not in num] + [e["target"]]
    order = {"question": qs, **{k: sorted((n for n in ns if n["kind"] == k), key=lambda n: (first.get(n["id"], 10**6), n["label"])) for k in ("topic", "norm")}}
    nidx = {n["id"]: i for i, n in enumerate(order["norm"])}
    rnorm: dict[str, list[int]] = defaultdict(list)
    for e in edges:
        if e["kind"] == "grounded_in" and e["target"] in nidx:
            rnorm[e["source"]].append(nidx[e["target"]])
    # риски — в порядке своих норм-оснований: дорожки норма → риск идут вниз, почти не пересекаясь
    order["risk"] = sorted((n for n in ns if n["kind"] == "risk"), key=lambda n: (min(rnorm[n["id"]], default=10**6), first.get(n["id"], 10**6), n["label"]))
    counts: dict[str, int] = defaultdict(int)
    for e in edges:
        if e["kind"] == "asks_about" and e["source"] in num and e["target"] in ids:
            counts[e["target"]] += 1
    pos: Pos = {}
    height = 0.0
    for kind, items in order.items():
        x, w = cols[kind]
        y = 6.0
        for n in items:
            if kind == "topic":
                lines = _wrap(n["label"], "Sans-Bold", LABEL_PT, w - 16) + _wrap(_plural(counts[n["id"]], "вопрос", "вопроса", "вопросов"), "Sans", LABEL_PT, w - 16)
                h = 10 + 11.0 * len(lines)
            elif kind == "question":
                lines, h = [n["label"]], 22.0
            elif kind == "norm":
                lines = _wrap(n["label"], "Mono", LABEL_PT, w - 28)
                h = max(22.0, 11.0 * len(lines) + 6)
            else:
                lines = _wrap(_risk_label(n), "Sans", LABEL_PT, w - 24)
                h = max(20.0, 11.0 * len(lines) + 6)
            refs = [pos[a][1] for a in anchor.get(n["id"], []) if a in pos]
            y = max(y, min(refs)) if refs else y
            pos[n["id"]] = (x, y, w, h, lines)
            y += h + 8
        height = max(height, y)
    return pos, height + 2, gaps, step


def _route(d: Drawing, pos: Pos, height: float, links: list[Link], x0: float, step: float, style: Any) -> None:
    """Связи одного промежутка «шинами»: общая вертикальная дорожка на ключ, горизонтальные подходы к узлам.
    Порты разнесены по высоте узла (по порядку другого конца), ответвления от дорожки — точки. style(link) → (цвет, толщина, пунктир)."""
    if not links:
        return

    def mid(n: str) -> float:  # y сверху
        return pos[n][1] + pos[n][3] / 2

    keys = sorted({k for *_, k in links}, key=lambda k: min(min(mid(a), mid(b)) for a, b, kk in links if kk == k))
    lane = {k: x0 + LANE_PAD + i * step for i, k in enumerate(keys)}
    ends: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)  # (узел, сторона) → ключ дорожки → y другого конца
    for a, b, k in links:
        ends[(a, "r")][k] = min(ends[(a, "r")].get(k, 1e9), mid(b))
        ends[(b, "l")][k] = min(ends[(b, "l")].get(k, 1e9), mid(a))
    port: dict[tuple[str, str, str], float] = {}
    for (n, side), others in ends.items():
        ks = sorted(others, key=lambda k: (others[k], lane[k]))
        gap = min(5.0, (pos[n][3] - 6) / max(1, len(ks) - 1))
        for i, k in enumerate(ks):
            port[(n, side, k)] = mid(n) + (i - (len(ks) - 1) / 2) * gap
    on_lane: dict[str, set[float]] = defaultdict(set)
    for link in links:
        a, b, k = link
        c, w, dash = style(link)
        ya, yb, lx = port[(a, "r", k)], port[(b, "l", k)], lane[k]
        pts = [pos[a][0] + pos[a][2], ya, lx, ya, lx, yb, pos[b][0] + 2, yb]
        d.add(PolyLine([v if i % 2 == 0 else height - v for i, v in enumerate(pts)], strokeColor=c, strokeWidth=w, strokeDashArray=dash))
        on_lane[k] |= {ya, yb}
    for k, ys in on_lane.items():  # ответвление (не крайняя точка дорожки) — точка того же цвета
        c = style(next(link for link in links if link[2] == k))[0]
        for y in sorted(ys)[1:-1]:
            d.add(Circle(lane[k], height - y, 1.5, fillColor=c, strokeColor=None))


def _graph_drawing(ns: list[dict[str, Any]], edges: list[dict[str, Any]], width: float) -> Drawing:
    pos, height, gaps, step = _layout(ns, edges, width)
    d = Drawing(width, height)
    by = {n["id"]: n for n in ns}

    def bottom(nid: str) -> float:  # нижняя граница узла в координатах PDF (ось y вверх)
        return height - pos[nid][1] - pos[nid][3]

    def mid(nid: str) -> float:
        return bottom(nid) + pos[nid][3] / 2

    def risk_style(link: Link) -> tuple[colors.Color, float, list[float] | None]:
        r = by[link[1]]
        closed = r.get("status") in CLOSED
        return lv_fill(r.get("resolved_level") if closed else r.get("risk_level")), 1.1, [3, 2] if closed else None

    links = _links(ns, edges)  # связи — под узлами
    _route(d, pos, height, links["tq"], gaps["tq"], step, lambda _: (col("line-strong"), 0.9, None))
    _route(d, pos, height, links["qn"], gaps["qn"], step, lambda _: (col("faint"), 0.7, None))
    _route(d, pos, height, links["nr"], gaps["nr"], step, risk_style)
    for e in edges:  # уточнение: петля слева от колонки вопросов
        a, b = e["source"], e["target"]
        if e["kind"] == "follow_up_of" and a in pos and b in pos and by[a]["kind"] == by[b]["kind"] == "question":
            x = pos[a][0]
            d.add(PolyLine([x, mid(a), x - 9, mid(a), x - 9, mid(b), x, mid(b)], strokeColor=col("ink-2"), strokeWidth=0.9, strokeDashArray=[3, 2]))
            _arrow(d, x, mid(b), 1, 0, col("ink-2"))
    qs = sorted((n for n in ns if n["kind"] == "question"), key=lambda n: n.get("num") or 0)
    for q1, q2 in zip(qs, qs[1:], strict=False):  # asked_next: следующий вопрос диалога
        if (q2.get("num") or 0) == (q1.get("num") or 0) + 1:
            cx = pos[q1["id"]][0] + pos[q1["id"]][2] / 2
            d.add(Line(cx, bottom(q1["id"]), cx, bottom(q2["id"]) + pos[q2["id"]][3] + 1.5, strokeColor=col("gold"), strokeWidth=1.4, strokeDashArray=[3, 2]))
            _arrow(d, cx, bottom(q2["id"]) + pos[q2["id"]][3], 0, -1, col("gold"))
    for nid, (x, _, w, h, lines) in pos.items():  # узлы
        n, y = by[nid], bottom(nid)
        lv, past = n.get("risk_level"), n.get("resolved_level")
        if n["kind"] == "topic":
            d.add(Rect(x, y, w, h, rx=10, ry=10, fillColor=lv_tint(lv) if lv else col("surface-2"), strokeColor=lv_fill(lv) if lv else col("line-strong"), strokeWidth=1.2))
            for i, s in enumerate(lines):
                last = i == len(lines) - 1
                d.add(String(x + 8, y + h - 16 - 11 * i, s, fontName="Sans" if last else "Sans-Bold", fontSize=LABEL_PT, fillColor=col("muted") if last else col("ink")))
        elif n["kind"] == "question":
            stroke, dash = (lv_fill(lv), None) if lv else (lv_fill(past), [3, 2]) if past else (col("line-strong"), None)
            d.add(Rect(x, y, w, h, rx=6, ry=6, fillColor=col("surface"), strokeColor=stroke, strokeWidth=1.6 if lv else 1.0, strokeDashArray=dash))
            d.add(String(x + w / 2, y + h / 2 - 3, lines[0], fontName="Sans-Bold", fontSize=LABEL_PT, fillColor=col("ink"), textAnchor="middle"))
        elif n["kind"] == "norm":
            d.add(Polygon(_hexagon(x + 12, y + h / 2, 9 * _scale(n)), fillColor=col("surface"), strokeColor=col("gold"), strokeWidth=1.5))
            for i, s in enumerate(lines):
                d.add(String(x + 26, y + h - 12 - 11 * i, s, fontName="Mono", fontSize=LABEL_PT, fillColor=col("ink-2")))
        else:
            closed = n.get("status") in CLOSED
            level_c = lv_fill(past if closed else lv)
            d.add(Polygon(_diamond(x + 9, y + h / 2, 7 * _scale(n)), fillColor=col("surface") if closed else level_c, strokeColor=level_c, strokeWidth=1.2, strokeDashArray=[2, 1.5] if closed else None))
            for i, s in enumerate(lines):
                d.add(String(x + 22, y + h - 12 - 11 * i, s, fontName="Sans", fontSize=LABEL_PT, fillColor=col("muted") if closed else col("ink")))
    return d


def _legend(width: float) -> Drawing:
    d = Drawing(width, 86)
    y1, y2, y3 = 66, 38, 10

    def label(x: float, y: float, text: str) -> float:
        d.add(String(x, y, text, fontName="Sans", fontSize=LABEL_PT, fillColor=col("ink")))
        return x + pdfmetrics.stringWidth(text, "Sans", LABEL_PT)

    d.add(Rect(0, y1 - 4, 30, 16, rx=8, ry=8, fillColor=col("surface-2"), strokeColor=col("line-strong"), strokeWidth=1))
    x = label(36, y1, "тема") + 14
    d.add(Rect(x, y1 - 4, 30, 16, rx=6, ry=6, fillColor=col("surface"), strokeColor=col("line-strong"), strokeWidth=1))
    x = label(x + 36, y1, "вопрос (номер)") + 18
    d.add(Polygon(_hexagon(x, y1 + 4, 8), fillColor=col("surface"), strokeColor=col("gold"), strokeWidth=1.5))
    x = label(x + 12, y1, "норма") + 18
    d.add(Polygon(_diamond(x, y1 + 4, 7), fillColor=lv_fill("high"), strokeColor=lv_fill("high")))
    label(x + 12, y1, "риск · размер нормы и риска — число связей")
    x = 0.0
    for text, c, dash, sw in (("вопрос по теме", col("line-strong"), None, 0.8), ("норма в ответе", col("faint"), None, 0.7), ("основание риска", lv_fill("high"), None, 1.1),
                              ("уточнение", col("ink-2"), [3, 2], 0.9), ("следующий вопрос", col("gold"), [3, 2], 1.4)):
        d.add(Line(x, y2 + 3, x + 22, y2 + 3, strokeColor=c, strokeWidth=sw, strokeDashArray=dash))
        x = label(x + 26, y2, text) + 12
    x = 0.0
    for lv in (*LEVELS, None):
        _swatch(d, x, y3 - 2, 11, lv)
        x = label(x + 15, y3, LEVEL_RU[lv].lower() if lv else "нет открытых рисков (не значит «безопасно»)") + 12
    return d


def _neighbourhood(qids: set[str], edges: list[dict[str, Any]], by: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    keep = set(qids)
    keep |= {e["target"] for e in edges if e["source"] in qids and e["kind"] in ("cites", "evidences") and e["target"] in by}
    keep |= {e["target"] for e in edges if e["source"] in keep and by.get(e["source"], {}).get("kind") == "risk" and e["kind"] == "grounded_in" and e["target"] in by}
    return [n for i, n in by.items() if i in keep]


def _parts(snap: dict[str, Any]) -> list[tuple[str | None, list[dict[str, Any]]]]:
    """До 40 узлов — одна схема; больше — врезки по темам, каждая со своим подзаголовком."""
    g = snap["graph"]
    ns = [n for n in g["nodes"] if n["kind"] != "center"]
    if len(g["nodes"]) <= 40:
        return [(None, ns)]
    by = {n["id"]: n for n in ns}
    out: list[tuple[str | None, list[dict[str, Any]]]] = []
    seen: set[str] = set()
    for t in (n for n in ns if n["kind"] == "topic"):
        qids = {e["source"] for e in g["edges"] if e["kind"] == "asks_about" and e["target"] == t["id"] and by.get(e["source"], {}).get("kind") == "question"}
        seen |= qids
        out.append((t["label"], [t, *_neighbourhood(qids, g["edges"], by)]))
    rest = {n["id"] for n in ns if n["kind"] == "question"} - seen
    if rest:
        out.append(("вопросы без темы", _neighbourhood(rest, g["edges"], by)))
    return out


def _graph_flowables(snap: dict[str, Any], st: dict[str, ParagraphStyle], width: float, max_h: float) -> list[Any]:
    edges = snap["graph"]["edges"]
    out: list[Any] = []
    for title, ns in _parts(snap):
        by = {n["id"]: n for n in ns}
        head = [n for n in ns if n["kind"] == "topic"]
        qs = sorted((n for n in ns if n["kind"] == "question"), key=lambda n: n.get("num") or 0)
        chunks: list[list[dict[str, Any]]] = []
        chunk: list[dict[str, Any]] = []
        for q in qs:  # схема выше полосы делится по вопросам на продолжения — кегль подписей не уменьшается
            trial = [*chunk, q]
            part = head + _neighbourhood({x["id"] for x in trial}, edges, by)
            if chunk and (_layout(part, edges, width)[1] > max_h or _cols(part, edges, width)[2] < 2.5):  # дорожки уже 2.5 pt — продолжение
                chunks.append(chunk)
                chunk = [q]
            else:
                chunk = trial
        chunks += [chunk] if chunk else []
        for i, ch in enumerate(chunks):
            d = _graph_drawing(head + _neighbourhood({x["id"] for x in ch}, edges, by), edges, width)
            label = f"Тема: {title}" if title else ("Слепок" if len(chunks) > 1 else None)
            if label and i:
                label += " (продолжение)"
            out.append(KeepTogether([Paragraph(_esc(label), st["h2"]), d]) if label else d)
    return out


# ───────────── матрица ─────────────
def _matrix(snap: dict[str, Any]) -> Drawing:
    t = snap["thresholds"]
    count: dict[tuple[int, int], int] = defaultdict(int)
    for r in snap["risks"]:
        if r["p"] and r["s"]:
            count[(r["p"], r["s"])] += 1
    c, left, low = 36.0, 34.0, 32.0
    d = Drawing(left + 5 * c + 4, low + 5 * c + 4)
    for p in range(1, 6):
        for s in range(1, 6):
            x, y, lv, n = left + (s - 1) * c, low + (p - 1) * c, _level(p * s, t), count[(p, s)]
            d.add(Rect(x, y, c, c, fillColor=lv_fill(lv) if n else lv_tint(lv), strokeColor=col("line"), strokeWidth=0.6))
            _hatch(d, x, y, c, c, lv, bool(n))
            if n:  # в ячейке только число открытых рисков; ноль не рисуется
                tw = pdfmetrics.stringWidth(str(n), "Mono", 11)
                d.add(Rect(x + c / 2 - tw / 2 - 4, y + c / 2 - 7, tw + 8, 15, rx=6, ry=6, fillColor=lv_fill(lv), strokeColor=None))
                d.add(String(x + c / 2, y + c / 2 - 3.5, str(n), fontName="Mono", fontSize=11, fillColor=lv_on(lv), textAnchor="middle"))
        d.add(String(left - 6, low + (p - 1) * c + c / 2 - 3, str(p), fontName="Mono", fontSize=9, fillColor=col("muted"), textAnchor="end"))
        d.add(String(left + (p - 1) * c + c / 2, low - 12, str(p), fontName="Mono", fontSize=9, fillColor=col("muted"), textAnchor="middle"))
    d.add(String(left + 2.5 * c, 4, "последствия (S)", fontName="Sans", fontSize=9, fillColor=col("muted"), textAnchor="middle"))
    g = Group(String(0, 0, "вероятность (P)", fontName="Sans", fontSize=9, fillColor=col("muted"), textAnchor="middle"))
    g.transform = (0, 1, -1, 0, 12, low + 2.5 * c)  # подпись оси, повёрнутая на 90°
    d.add(g)
    return d


def _ranges(t: list[int]) -> dict[str, str]:
    return {"low": f"1–{t[0]}", "medium": f"{t[0] + 1}–{t[1]}", "high": f"{t[1] + 1}–{t[2]}", "critical": f"{t[2] + 1}–25"}


def _level_legend(snap: dict[str, Any], width: float) -> Drawing:
    rg = _ranges(snap["thresholds"])
    d = Drawing(width, 18)
    x = 0.0
    for lv in LEVELS:
        _swatch(d, x, 3, 12, lv)
        text = f"{LEVEL_RU[lv]} {rg[lv]}"
        d.add(String(x + 17, 5, text, fontName="Sans", fontSize=9, fillColor=col("ink")))
        x += 30 + pdfmetrics.stringWidth(text, "Sans", 9)
    return d


def _table(rows: list[list[Any]], widths: list[float], header: bool = True, **kw: Any) -> Table:
    t = Table(rows, colWidths=widths, **kw)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, col("line")), ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4), *([("BACKGROUND", (0, 0), (-1, 0), col("surface-2"))] if header else []),
    ]))
    return t


# ───────────── блоки документа ─────────────
def _title_page(snap: dict[str, Any], st: dict[str, ParagraphStyle], fw: float) -> list[Any]:
    se = snap["session"]
    mark = Drawing(fw, 40)

    def pt(x: float, y: float) -> tuple[float, float]:  # знак как в favicon.svg (32 × 32, ось y вниз)
        return 1.15 * x, 2 + 1.15 * (32 - y)

    mark.add(PolyLine([*pt(8, 28), *pt(8, 6.5), *pt(21, 4.4), *pt(21, 28)], strokeColor=col("ink"), strokeWidth=1.8))
    mark.add(Line(*pt(4, 28), *pt(28, 28), strokeColor=col("ink"), strokeWidth=1.8))
    mark.add(Circle(*pt(17.3, 17), 1.5, fillColor=col("brand"), strokeColor=col("brand")))
    mark.add(String(44, 13, "DoorAIn", fontName="Display", fontSize=20, fillColor=col("ink")))
    rows = [["Роль", ROLE_RU.get(se["role"], se["role"])], ["Дата формирования", _d(snap["created_at"])], ["Дата правового среза", _d(se["as_of_date"])]]
    info = [[Paragraph(a, st["muted"]), Paragraph(_esc(b), st["body"])] for a, b in rows] + [[Paragraph("Идентификатор сессии", st["muted"]), Paragraph(se["id"], st["mono"])]]
    out: list[Any] = [mark, Spacer(1, 64 * mm), Paragraph(DOC_TITLE, st["title"]), Paragraph(_esc(se["title"]), st["theme"]), Spacer(1, 10 * mm),
                      _table(info, [46 * mm, fw - 46 * mm], header=False), Spacer(1, 8 * mm)]
    if snap["incomplete"]:
        out.append(Paragraph(f"Неполный снимок: {_esc(snap['incomplete_reason'])}", st["banner"]))
    if snap["archived"]:
        out.append(Paragraph("Часть оснований выведена из базы знаний: соответствующие нормы помечены как архивные и не подтверждают риски.", st["banner"]))
    if snap["test_mode"]:
        out.append(Paragraph("Тестовый режим: ответы сформированы без языковой модели (TEST-провайдеры) — документ не отражает качество анализа.", st["banner"]))
    out.append(Paragraph(f"{_esc(snap['disclaimer'])}. Документ носит справочный характер и не является юридическим заключением.", st["muted"]))
    return out


def _summary(snap: dict[str, Any], st: dict[str, ParagraphStyle], fw: float) -> list[Any]:
    sm = snap["summary"]
    dist = Drawing(fw, 40)
    for i, lv in enumerate(reversed(LEVELS)):
        x = i * fw / 4
        _swatch(dist, x, 14, 18, lv)
        dist.add(String(x + 26, 17, str(sm["by_level"].get(lv, 0)), fontName="Mono", fontSize=18, fillColor=col("ink")))
        dist.add(String(x + 26, 3, LEVEL_RU[lv], fontName="Sans", fontSize=9, fillColor=col("muted")))
    top = [
        Paragraph(f"{i}. <b>{_esc(r['title'])}</b> — <font color='{lv_ink_hex(r['level'])}'>{LEVEL_RU[r['level']].lower()}</font>, P × S = {r['score']}"
                  + (f" · <font name='Mono'>{_esc(r['norms'][0])}</font>" if r["norms"] else ""), st["body"])
        for i, r in enumerate(sm["top"], 1)
    ] or [Paragraph("Открытых рисков нет. Это не доказывает безопасность: риск создаётся только при нормативном основании в ответах.", st["body"])]
    return [KeepTogether([
        Paragraph("Сводка", st["h1"]), Paragraph(_esc(sm["task"]), st["body"]),
        Paragraph("Открытые риски по уровням", st["h2"]), dist,
        Paragraph("Наиболее значимые открытые риски", st["h2"]), *top,
        Spacer(1, 8), Paragraph(_esc(sm["acts_line"]), st["body"]),
    ])]


def _graph_block(snap: dict[str, Any], st: dict[str, ParagraphStyle], fw: float, max_h: float) -> list[Any]:
    out: list[Any] = [Paragraph("1. Граф-слепок", st["h1"]), _legend(fw), Spacer(1, 8)]
    if not [n for n in snap["graph"]["nodes"] if n["kind"] == "question"]:
        return [*out, Paragraph("В сессии нет вопросов — слепок пуст.", st["body"])]
    flows = _graph_flowables(snap, st, fw, max_h - 70)
    note = Paragraph(
        "Как читать слепок. Слева — темы, правее — вопросы по порядку их появления (текст вопросов в документ не включается), "
        "затем нормы, на которые опирались ответы, и риски с их основаниями. Рамка темы и вопроса окрашена наивысшим уровнем "
        "связанных открытых рисков: чем темнее и насыщеннее узел, тем серьёзнее риск; серый — открытых рисков нет. Закрытый риск "
        "оставляет пунктирный след прежнего цвета — портрет высветляется по мере закрытия рисков. Связи идут по дорожкам между "
        "колонками: точка на дорожке — ответвление к узлу, пересечение без точки — просто перекрёсток линий.", st["small"])
    return [*out, *flows[:-1], KeepTogether([flows[-1], Spacer(1, 8), note])]  # комментарий — под схемой, без отрыва на пустую страницу


def _card(r: dict[str, Any], st: dict[str, ParagraphStyle], fw: float) -> Table:
    closed = r["status"] in CLOSED
    lv = r["level"]
    text = st["muted"] if closed else st["small"]
    status = STATUS_RU.get(r["status"], r["status"])
    head = f"<font color='{lv_ink_hex(lv)}'><b>{LEVEL_RU[lv]}</b></font> · P {r['p']} × S {r['s']} = {r['score']} · статус: {status}" if lv else f"Не оценён · статус: {status}"
    body: list[Any] = [Paragraph(_esc(r["title"]), st["cardt"]), Paragraph(head, text)]
    if r["norms"]:
        body.append(Paragraph("Основание: " + "; ".join(f"<font name='Mono'>{_esc(n)}</font>" for n in r["norms"]), text))
    elif r["origin"] == "user":
        body.append(Paragraph("Основание не указано — риск добавлен пользователем.", text))
    if r["consequences"]:
        body.append(Paragraph(f"Последствия: {_esc(r['consequences'])}", text))
    if r["recommendation"]:
        body.append(Paragraph(f"<b>Что сделать:</b> {_esc(r['recommendation'])}", text))
    if r["clarification"] and r["status"] == "needs_clarification":
        body.append(Paragraph(f"Нужно уточнить: {_esc(r['clarification'])}", text))
    if closed:
        body.append(Paragraph(f"Закрыт {_d(r['closed_at'])}" + (f": {_esc(r['resolution_reason'])}" if r["resolution_reason"] else ""), text))
    bar = 2.0 if closed else 5.0
    t = Table([["", body]], colWidths=[bar, fw - bar])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), lv_fill(lv)), ("BACKGROUND", (1, 0), (1, 0), col("surface")), ("BOX", (0, 0), (-1, -1), 0.5, lv_fill(lv) if closed else col("line")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 0), ("LEFTPADDING", (1, 0), (1, 0), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _scale_table(snap: dict[str, Any], st: dict[str, ParagraphStyle], width: float, order: tuple[int, ...]) -> Table:
    pr, sv = ({int(k): v for k, v in snap["scales"][axis].items()} for axis in ("probability", "severity"))  # после JSON ключи — строки
    rows = [[Paragraph("", st["cellb"]), Paragraph("Вероятность P", st["cellb"]), Paragraph("Последствия S", st["cellb"])]]
    rows += [[Paragraph(str(k), st["cellb"]), Paragraph(_esc(pr[k]), st["cell"]), Paragraph(_esc(sv[k]), st["cell"])] for k in order]
    return _table(rows, [16, (width - 16) / 2, (width - 16) / 2])


def _risk_block(snap: dict[str, Any], st: dict[str, ParagraphStyle], fw: float) -> list[Any]:
    out: list[Any] = [Paragraph("2. Риск-менеджмент", st["h1"])]
    if not snap["risks"]:
        out.append(Paragraph("<b>Рисков не выявлено.</b> Открытых оценённых рисков в сессии нет. Риск создаётся только при нормативном основании "
                             "из фрагментов ответа и подтверждённых фактах, поэтому отсутствие рисков не доказывает безопасность ситуации.", st["body"]))
    else:
        side = Table([[_matrix(snap), _scale_table(snap, st, fw - 222, (5, 4, 3, 2, 1))]], colWidths=[222, fw - 222])
        side.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        out += [KeepTogether([Paragraph("Матрица рисков 5 × 5", st["h2"]), side, Spacer(1, 6), _level_legend(snap, fw), Paragraph(
            "Число в ячейке — открытые риски сессии; цвет ячейки — уровень её координат P × S. Уровень дублируется штриховкой: "
            "низкий — без штриховки, средний — редкая, высокий — частая, критический — сетка.", st["muted"])]), Paragraph("Открытые риски", st["h2"])]
        out += [KeepTogether([_card(r, st, fw), Spacer(1, 6)]) for r in snap["risks"]]
    for title, key in (("Ожидают уточнения фактов (не оценены)", "needs_clarification"), ("Закрытые риски", "closed")):
        if snap[key]:
            out.append(Paragraph(title, st["h2"]))
            out += [KeepTogether([_card(r, st, fw), Spacer(1, 6)]) for r in snap[key]]
    return out


def _bases_block(snap: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Any]:
    out: list[Any] = [Paragraph("3. Нормативные основания", st["h1"]), Paragraph(
        "Перечень составлен только из фрагментов, на которые фактически опирались ответы сессии. Реквизиты указаны по редакции, "
        "применённой к дате правового среза; актуальность редакций на дату использования документа подлежит проверке.", st["muted"])]
    if not snap["bases"]:
        return [*out, Paragraph("Ответы сессии не опирались на документы базы знаний.", st["body"])]
    for gid, gtitle in GROUPS:
        acts = [a for a in snap["bases"] if a["group"] == gid]
        if not acts:
            continue
        out.append(Paragraph(gtitle, st["h2"]))
        for a in acts:
            items: list[Any] = [Paragraph(f"<b>{_esc(a['title'])}</b>" + (" · источник выведен из базы знаний" if a["archived"] else ""), st["body"]), Paragraph(_esc(a["requisites"]), st["mono"])]
            for art in a["articles"]:
                why = []
                if art["questions"]:
                    why.append(("вопрос " if len(art["questions"]) == 1 else "вопросы ") + ", ".join(f"№{n}" for n in art["questions"]))
                if art["risks"]:
                    why.append(("риск " if len(art["risks"]) == 1 else "риски ") + "; ".join(f"«{t}»" for t in art["risks"]))
                items.append(Paragraph(f"<font name='Mono'>{_esc(art['locator'])}</font> — {_esc('; '.join(why)) or 'в ответах сессии'}", st["small"]))
            out.append(KeepTogether([*items, Spacer(1, 8)]))
    return out


def _appendix(snap: dict[str, Any], st: dict[str, ParagraphStyle], fw: float) -> list[Any]:
    sc, rg = snap["scales"], _ranges(snap["thresholds"])
    role = ROLE_RU.get(snap["session"]["role"], snap["session"]["role"])
    levels = _table([[Paragraph("Уровень", st["cellb"]), Paragraph("P × S", st["cellb"])]]
                    + [[Paragraph(f"<font color='{lv_ink_hex(lv)}'><b>{LEVEL_RU[lv]}</b></font>", st["cell"]), Paragraph(rg[lv], st["cell"])] for lv in LEVELS],
                    [50 * mm, 30 * mm], hAlign="LEFT")
    corpus = f" Корпус: generation №{snap['corpus']['generation_seq']}." if snap["corpus"]["generation_seq"] else ""
    return [
        Paragraph("Приложение. Методика оценки", st["h1"]),
        Paragraph("Риск оценивается по двум шкалам — вероятность P и последствия S, каждая от 1 до 5. Уровень = P × S (1–25) и рассчитывается "
                  "приложением по порогам ниже; модель предлагает только P, S и обоснование. Риск создаётся лишь при нормативном основании из "
                  "фрагментов, на которые опирался ответ; учебная литература основанием риска не является. Методика экспериментальная и юристом не проверена.", st["body"]),
        Paragraph("Пороги уровней", st["h2"]), levels,
        Paragraph(f"Шкалы для роли «{_esc(role)}» — {_esc(sc['measure'])}", st["h2"]), _scale_table(snap, st, fw, (1, 2, 3, 4, 5)),
        Paragraph("Дисклеймер", st["h2"]),
        Paragraph(f"{_esc(snap['disclaimer'])}. Документ носит справочный характер, не является юридическим заключением; актуальность редакций "
                  f"нормативных актов подлежит проверке.{corpus}", st["body"]),
    ]


def _deco(snap: dict[str, Any], footer: bool):  # noqa: ANN202
    def deco(canv: Any, doc: Any) -> None:
        canv.saveState()
        w, h = canv._pagesize
        if footer:  # колонтитул: название документа слева, номер страницы справа, тонкая линия над ним
            canv.setStrokeColor(col("line"))
            canv.setLineWidth(0.5)
            canv.line(20 * mm, 15.5 * mm, w - 20 * mm, 15.5 * mm)
            canv.setFont("Sans", 8)
            canv.setFillColor(col("muted"))
            canv.drawString(20 * mm, 11 * mm, f"{DOC_TITLE} · {snap['session']['title'][:70]}")
            canv.drawRightString(w - 20 * mm, 11 * mm, f"стр. {doc.page}")
        if snap["incomplete"]:
            canv.setFont("Sans-Bold", 8)
            canv.setFillColor(col("risk-critical"))
            canv.drawString(20 * mm, h - 11 * mm, "НЕПОЛНЫЙ СНИМОК: анализ сессии не завершён на момент выгрузки")
        canv.restoreState()

    return deco


def render_pdf(snap: dict[str, Any], out: Path) -> None:
    _fonts()
    st = _st()
    w, h = A4
    ml, mr, mt, mb = 20 * mm, 20 * mm, 18 * mm, 22 * mm
    fw, fh = w - ml - mr, h - mt - mb
    se = snap["session"]
    # invariant: без случайного ID и времени сборки — повторный рендер того же снимка даёт те же байты
    doc = BaseDocTemplate(str(out), pagesize=A4, leftMargin=ml, rightMargin=mr, topMargin=mt, bottomMargin=mb, title=f"{DOC_TITLE} — {se['title']}", author="DoorAIn", invariant=1)
    frame = Frame(ml, mb, fw, fh, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="T", frames=[frame], onPage=_deco(snap, False)), PageTemplate(id="P", frames=[frame], onPage=_deco(snap, True))])
    story: list[Any] = [*_title_page(snap, st, fw), NextPageTemplate("P"), PageBreak()]
    story += [*_summary(snap, st, fw), PageBreak()]
    story += [*_graph_block(snap, st, fw, fh - 60), PageBreak()]
    story += [*_risk_block(snap, st, fw), PageBreak()]
    story += [*_bases_block(snap, st), PageBreak()]
    story += _appendix(snap, st, fw)
    doc.build(story)
