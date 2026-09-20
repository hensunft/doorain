"""Нормализация и чанкинг. НПА: статья → часть → пункт; учебник: разделы. Один чанк = один акт и одна редакция.

Нумерация, отрицания и пункты сохраняются дословно; нормализация — только пробелы/переносы/мягкие дефисы.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ...core.util import est_tokens


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFC", text).replace("­", "").replace(" ", " ").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" ?\n ?", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


@dataclass
class ChunkDraft:
    kind: str
    heading_path: str
    locator: str
    text: str
    article: str | None = None
    part: str | None = None
    point: str | None = None
    page: int | None = None


_ART = re.compile(r"^\s*Статья\s+(\d+(?:\.\d+)*)\.?\s*(.*)$", re.I)
_CHAPTER = re.compile(r"^\s*(Глава|Раздел)\s+([\dIVXLCА-Я]+(?:\.\d+)?)\.?\s*(.*)$", re.I)
_PART = re.compile(r"^\s*(\d+(?:\.\d+)?)\.\s+\S")
_POINT = re.compile(r"^\s*(\d+)\)\s+\S")
_MD_HEAD = re.compile(r"^\s{0,3}#{1,4}\s+(.+)$")
_TB_HEAD = re.compile(r"^\s*(Глава|Раздел|Тема|§)\s*[\dIVXLC.]*\s*\S.*$", re.I)
_SENT = re.compile(r"(?<=[.;!?])\s+")


def _split_long(text: str, target: int, overlap: int, cpt: float) -> list[str]:
    """Деление длинного текста по границам предложений; overlap только здесь."""
    if est_tokens(text, cpt) <= target:
        return [text]
    sents, out, cur = _SENT.split(text), [], ""
    for sent in sents:
        if cur and est_tokens(cur + " " + sent, cpt) > target:
            out.append(cur)
            tail = cur[-int(overlap * cpt) :] if overlap else ""
            tail = tail[tail.find(" ") + 1 :] if " " in tail else ""
            cur = (tail + " " + sent).strip()
        else:
            cur = (cur + " " + sent).strip()
    if cur:
        out.append(cur)
    return out


def _group(blocks: list[tuple[str, str]], head: str, target: int, cpt: float) -> list[tuple[str, list[str]]]:
    """Группирует пункты (номер, текст) до целевого размера, перенося заголовок части в каждый чанк."""
    groups: list[tuple[str, list[str]]] = []
    cur_nums: list[str] = []
    cur_txt: list[str] = []
    for num, txt in blocks:
        if cur_txt and est_tokens(head + "\n" + "\n".join(cur_txt + [txt]), cpt) > target:
            groups.append((",".join(cur_nums), cur_txt))
            cur_nums, cur_txt = [], []
        cur_nums.append(num)
        cur_txt.append(txt)
    if cur_txt:
        groups.append((",".join(cur_nums), cur_txt))
    return groups


def chunk_npa(text: str, target: int = 700, overlap: int = 60, cpt: float = 2.6) -> list[ChunkDraft]:
    lines = text.split("\n")
    chapter = ""
    arts: list[tuple[str, str, list[str], str]] = []  # (номер, заголовок, строки, глава)
    pre: list[str] = []
    for ln in lines:
        m = _ART.match(ln)
        if m and len(ln) < 400:
            arts.append((m.group(1), ln.strip(), [], chapter))
            continue
        c = _CHAPTER.match(ln)
        if c and len(ln) < 300:
            chapter = ln.strip()
            continue
        (arts[-1][2] if arts else pre).append(ln)
    out: list[ChunkDraft] = []
    pre_text = "\n".join(pre).strip()
    if len(pre_text) > 200:
        for i, piece in enumerate(_split_long(pre_text, target, overlap, cpt), 1):
            out.append(ChunkDraft("text", "Преамбула", f"преамбула ({i})" if i > 1 else "преамбула", piece))
    for num, title, body_lines, chap in arts:
        body = "\n".join(body_lines).strip()
        full = f"{title}\n{body}".strip()
        hp = f"{chap} / {title}" if chap else title
        base_loc = f"ст. {num}"
        if est_tokens(full, cpt) <= target:
            out.append(ChunkDraft("article", hp, base_loc, full, article=num))
            continue
        parts: list[tuple[str, list[str]]] = []
        for ln in body_lines:
            m = _PART.match(ln)
            if m and (not parts or True):
                parts.append((m.group(1), [ln]))
            elif parts:
                parts[-1][1].append(ln)
            else:
                parts.append(("", [ln]))
        for pnum, plines in parts:
            ptxt = "\n".join(plines).strip()
            if not ptxt:
                continue
            ploc = f"{base_loc} ч. {pnum}" if pnum else base_loc
            ptext = f"{title}\n{ptxt}"
            if est_tokens(ptext, cpt) <= target:
                out.append(ChunkDraft("part", hp, ploc, ptext, article=num, part=pnum or None))
                continue
            intro, points = [], []
            for ln in plines:
                if _POINT.match(ln):
                    points.append((_POINT.match(ln).group(0).strip().split(")")[0], [ln]))  # type: ignore[union-attr]
                elif points:
                    points[-1][1].append(ln)
                else:
                    intro.append(ln)
            head = f"{title}\n" + "\n".join(intro).strip()
            if points:
                for nums, txts in _group([(n, "\n".join(t)) for n, t in points], head, target, cpt):
                    loc = f"{ploc} п. {nums}"
                    out.append(ChunkDraft("point", hp, loc, head + "\n" + "\n".join(txts), article=num, part=pnum or None, point=nums))
            else:
                for i, piece in enumerate(_split_long(ptext, target, overlap, cpt), 1):
                    out.append(ChunkDraft("part", hp, f"{ploc} (фрагмент {i})", piece, article=num, part=pnum or None))
    return out


def chunk_textbook(pages: list[str], target: int = 700, overlap: int = 60, cpt: float = 2.6) -> list[ChunkDraft]:
    """Учебник: разбиение по разделам/заголовкам, страница сохраняется для цитаты."""
    sections: list[tuple[str, list[tuple[str, int]]]] = [("Введение", [])]
    for pno, page in enumerate(pages, 1):
        for ln in page.split("\n"):
            if not ln.strip():
                continue
            h = _MD_HEAD.match(ln)
            if h or (_TB_HEAD.match(ln) and len(ln) < 160):
                sections.append(((h.group(1) if h else ln).strip(), []))
            else:
                sections[-1][1].append((ln.strip(), pno))
    out: list[ChunkDraft] = []
    for title, items in sections:
        if not items:
            continue
        # абзацы -> группы до target
        cur: list[str] = []
        first_page = items[0][1]
        for ln, pno in items:
            if cur and est_tokens("\n".join(cur + [ln]), cpt) > target:
                out.append(_tb(title, cur, first_page))
                cur, first_page = [], pno
            cur.append(ln)
        if cur:
            out.append(_tb(title, cur, first_page))
    res: list[ChunkDraft] = []
    for c in out:  # одиночная слишком длинная строка — режем по предложениям
        for i, piece in enumerate(_split_long(c.text, target, overlap, cpt), 1):
            res.append(ChunkDraft("section", c.heading_path, c.locator + (f" (фрагмент {i})" if i > 1 else ""), piece, page=c.page))
    return res


def _tb(title: str, lines: list[str], page: int) -> ChunkDraft:
    return ChunkDraft("section", title, f"{title[:80]}, с. {page}", "\n".join(lines), page=page)


def guess_kind(text: str) -> str:
    """Подсказка типа источника для формы импорта (не доверяем полностью)."""
    n_art = len(re.findall(r"^\s*Статья\s+\d", text, flags=re.M | re.I))
    return "npa" if n_art >= 2 else "textbook"
