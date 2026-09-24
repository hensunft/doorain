"""П. 6 задания 24.09: блок «Со слов пользователя» — только утверждение с предметом и только то, что пользователь сказал."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.services.rag import verify
from tests.conftest import Api, ask, new_session

SRC = {"C1": "Оператор обязан опубликовать политику в отношении обработки данных на своём сайте."}
Q = "Могу ли я не делать форму сбора персональных данных на сайте? Сайт не собирает персональные данные."


@pytest.mark.parametrize("para", ["Со слов пользователя: нет.", "Со слов пользователя: да", "Со слов пользователя — неизвестно.", "Со слов пользователя: не знаю"])
def test_bare_yes_no_is_clarification_not_fact(para: str) -> None:
    ck = verify.check_paragraph(para, SRC, Q)
    assert ck.kind == "clarification" and ck.reason == "fact_without_subject" and "нет" not in ck.text.lower().split()


def test_negation_with_clear_subject_is_kept_as_fact() -> None:
    ck = verify.check_paragraph("Со слов пользователя: сайт не собирает персональные данные.", SRC, Q)
    assert ck.kind == "fact" and ck.state == "verified" and ck.text == "Со слов пользователя: сайт не собирает персональные данные."


def test_fact_not_said_by_user_becomes_assumption() -> None:
    ck = verify.check_paragraph("Со слов пользователя: серверы расположены в Германии и принимают платежи.", SRC, Q)
    assert ck.kind == "assumption" and ck.text.startswith("Допущение:") and ck.reason == "fact_not_in_user_text"


def test_no_fact_paragraph_means_no_fact_block() -> None:
    assert verify.check_paragraph("Оператор обязан публиковать политику [C1]", SRC, Q).kind == "claim"


def _stream_with(extra: str) -> Any:
    from app.providers.registry import get_providers

    llm = get_providers().llm
    real = llm.stream

    def stream(messages: list[dict[str, str]], **kw: Any) -> Iterator[str]:
        yield from real(messages, **kw)
        yield "\n\n" + extra

    return llm, stream


@pytest.mark.parametrize(("extra", "kind"), [("Со слов пользователя: нет.", "clarification"), ("Со слов пользователя: сайт не собирает персональные данные.", "fact")])
def test_answer_pipeline_stores_only_meaningful_facts(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch, extra: str, kind: str) -> None:
    llm, stream = _stream_with(extra)
    monkeypatch.setattr(llm, "stream", stream)
    sid = new_session(owner)
    ask(owner, sid, Q)
    blocks = owner.get(f"/sessions/{sid}/messages").json()[-1]["blocks"]
    tail = [b for b in blocks if b["kind"] in ("fact", "clarification")]
    assert [b["kind"] for b in tail] == [kind]
    assert not any(b["kind"] == "fact" and verify.fact_body(b["text"]).strip(" .").lower() in ("нет", "да") for b in blocks)


def test_vacuous_fact_candidate_is_not_saved(owner: Api, demo: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.models import SessionFact
    from app.db.session import SessionLocal
    from app.providers.registry import get_providers

    llm = get_providers().llm
    real = llm._analyze  # type: ignore[attr-defined]
    facts = [{"key": "collects_pd", "value": "no", "statement": "нет.", "ongoing": False}, {"key": "site_collects_pd", "value": "no", "statement": "Сайт не собирает персональные данные", "ongoing": False}]
    monkeypatch.setattr(llm, "_analyze", lambda ctx: {**real(ctx), "fact_candidates": facts})
    sid = new_session(owner)
    ask(owner, sid, Q)
    db = SessionLocal()
    assert [f.key for f in db.query(SessionFact).filter(SessionFact.kind == "user_fact")] == ["site_collects_pd"]
    db.close()
