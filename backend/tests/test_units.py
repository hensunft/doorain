"""Чистая логика: шкалы, бонус P, проверка блоков ответа, чанкинг, RRF."""

from __future__ import annotations

import pytest

from app.services.ingestion import chunker
from app.services.rag import verify
from app.services.risks.scoring import final_p, level, score


@pytest.mark.parametrize("sc,lv", [(1, "low"), (4, "low"), (5, "medium"), (9, "medium"), (10, "high"), (15, "high"), (16, "critical"), (25, "critical")])
def test_level_boundaries(sc: int, lv: str) -> None:
    assert level(sc) == lv


def test_score_range() -> None:
    assert score(5, 5) == 25 and score(1, 1) == 1
    for bad in ((0, 3), (3, 6), (6, 1)):
        with pytest.raises(ValueError):
            score(*bad)
    with pytest.raises(ValueError):
        level(26)


def test_bonus_rules() -> None:
    assert final_p(3, 1, False) == 4
    assert final_p(4, 1, True) == 5
    assert final_p(4, 1, False) == 4  # P5 без факта продолжающейся ситуации недопустим
    assert final_p(5, 1, True) == 5  # максимум 5
    assert final_p(2, 0, False) == 2


SRC = {"C1": "Оператор обязан опубликовать политику в отношении обработки данных на своём сайте."}


def test_verify_unknown_marker_and_missing_citation() -> None:
    assert verify.check_paragraph("Нужна политика [C9]", SRC).state == "unsupported"
    assert verify.check_paragraph("Нужна политика на сайте.", SRC).state == "unsupported"
    ok = verify.check_paragraph("Оператор обязан публиковать политику [C1]", SRC)
    assert ok.state == "verified" and ok.markers == ["C1"] and ok.kind == "claim"


def test_verify_kinds_and_quotes() -> None:
    assert verify.check_paragraph("Допущение: сайт работает в РФ.", SRC).kind == "assumption"
    assert verify.check_paragraph("Со слов пользователя: сервер за рубежом.", SRC).kind == "fact"
    good = verify.check_paragraph("Норма: «Оператор обязан опубликовать политику в отношении обработки данных» [C1]", SRC)
    assert good.state == "verified" and good.quote_checked is True
    bad = verify.check_paragraph("Норма: «Оператор вправе не публиковать никакую политику вообще» [C1]", SRC)
    assert bad.state == "unsupported" and bad.reason == "quote_not_in_source"


def test_quote_normalization_is_limited_to_whitespace() -> None:
    ok = verify.check_paragraph("«Оператор  обязан\nопубликовать политику» [C1]", SRC)
    assert ok.state == "verified"


def test_lexical_support() -> None:
    assert verify.lexical_support("Оператор обязан опубликовать политику обработки данных на сайте", ["C1"], SRC)
    assert not verify.lexical_support("Космические корабли бороздят просторы вселенной вблизи Юпитера", ["C1"], SRC)


ACT = """ДЕМО-ЗАКОН
Глава 1. Общие положения
Статья 5. Согласие
1. Оператор обязан получить согласие.
2. Сбор e-mail через форму требует согласия.
Статья 6. Хранение
Хранение осуществляется на серверах на территории юрисдикции.
"""


def test_chunk_npa_articles() -> None:
    ch = chunker.chunk_npa(ACT)
    locs = [c.locator for c in ch]
    assert locs == ["ст. 5", "ст. 6"]
    assert ch[0].article == "5" and "Общие положения" in ch[0].heading_path


def test_chunk_npa_splits_long_article_by_parts_and_keeps_numbering() -> None:
    body = "\n".join(f"{i}. " + ("Обязанность оператора состоит в выполнении требований. " * 12) for i in range(1, 6))
    ch = chunker.chunk_npa(f"Статья 7. Длинная\n{body}", target=300, cpt=2.6)
    assert len(ch) == 5 and ch[0].locator == "ст. 7 ч. 1" and ch[4].part == "5"
    assert all(c.article == "7" for c in ch)


def test_chunk_never_mixes_articles() -> None:
    ch = chunker.chunk_npa(ACT)
    assert not any("Статья 6" in c.text for c in ch if c.article == "5")


def test_textbook_chunks_keep_page() -> None:
    ch = chunker.chunk_textbook(["Глава 1 Введение\nТекст первой страницы.", "Продолжение текста на второй странице.\nГлава 2 Право\nТекст."])
    assert ch and all(c.page for c in ch) and ch[0].kind == "section"


def test_normalize_keeps_numbers_and_negations() -> None:
    t = chunker.normalize("1) не вправе передавать  \r\n2) обязан")
    assert "не вправе передавать" in t and "2) обязан" in t
