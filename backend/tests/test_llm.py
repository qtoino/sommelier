import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from sommelier import llm
from sommelier.llm import LLM, BudgetExceeded, UsageLimitHit, extract_json


class Answer(BaseModel):
    ok: bool


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    calls: list[str] = []

    def call(model: str, system: str, prompt: str, schema: Any) -> str:
        calls.append(prompt)
        return json.dumps({"ok": True})

    monkeypatch.setattr(llm, "_call_claude", call)
    return calls


def test_cache_makes_reruns_free(fake: list[str]) -> None:
    a = LLM(max_calls=5)
    assert a.ask_model("judge", "sys", "p1", Answer) == Answer(ok=True)
    b = LLM(max_calls=5)
    assert b.ask_model("judge", "sys", "p1", Answer) == Answer(ok=True)
    assert len(fake) == 1 and b.calls == 0 and b.cache_hits == 1


def test_budget_cap(fake: list[str]) -> None:
    client = LLM(max_calls=2)
    client.ask("judge", "s", "a")
    client.ask("judge", "s", "b")
    with pytest.raises(BudgetExceeded):
        client.ask("judge", "s", "c")
    client.ask("judge", "s", "a")  # cached: still allowed
    assert len(fake) == 2


def test_dry_run_never_calls(fake: list[str]) -> None:
    assert LLM(dry_run=True).ask_model("judge", "s", "new", Answer) is None
    assert fake == []


def test_usage_limit_detection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class Proc:
        returncode = 1
        stdout = json.dumps({"is_error": True, "result": "Claude usage limit reached"})
        stderr = ""

    monkeypatch.setattr(llm, "claude_bin", lambda: "claude")
    monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(UsageLimitHit):
        llm._call_claude("sonnet", "s", "p", None)


def test_extract_json_tolerates_fences() -> None:
    assert extract_json('Sure:\n```json\n{"ok": true}\n```') == {"ok": True}
