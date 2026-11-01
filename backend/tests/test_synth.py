import json
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from sommelier import llm, synth
from sommelier.llm import LLM
from sommelier.models import Item
from sommelier.synth import docker_ready, run_pytest, verify

GOOD = "def page_count(total, size):\n    return -(-total // size)\n"
BAD = "def page_count(total, size):\n    return total // size + 1\n"
TEST = "from solution import *\n\ndef test_exact():\n    assert page_count(100, 20) == 5\n"
HANG = "def page_count(total, size):\n    while True:\n        pass\n"


@pytest.mark.parametrize("use_docker", [False, pytest.param(True, marks=pytest.mark.docker)])
def test_sandbox_pass_fail_timeout(use_docker: bool) -> None:
    if use_docker and not docker_ready():
        pytest.skip("docker not available")
    assert run_pytest(GOOD, TEST, use_docker=use_docker) == 0
    assert run_pytest(BAD, TEST, use_docker=use_docker) == 1
    assert run_pytest("def oops(:\n", TEST, use_docker=use_docker) not in (0, 1)
    assert run_pytest(HANG, TEST, use_docker=use_docker, timeout=3) is None


def test_docker_sandbox_has_no_network() -> None:
    if not docker_ready():
        pytest.skip("docker not available")
    probe = (
        "import socket\n\ndef test_net():\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=2)\n"
    )
    assert run_pytest("", probe, use_docker=True) == 1


def test_verify_requires_pass_then_fail() -> None:
    assert verify(None, GOOD, BAD, TEST, use_docker=False) == "verified"
    assert verify(None, BAD, GOOD, TEST, use_docker=False) == "failed"
    # A "bad" version that only fails because it doesn't import is not a real verification.
    assert verify(None, GOOD, "def page_count(:\n", TEST, use_docker=False) == "failed"


def _fake_llm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, critic_pick: str, test_code: str | None = TEST
) -> list[str]:
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(synth, "docker_ready", lambda: False)
    roles: list[str] = []
    generated = {
        "language": "python",
        "difficulty": "easy",
        "prompt": "Both functions count pages.",
        "context_code": None,
        "version_good": GOOD,
        "version_bad": BAD,
        "explanation": "Ceiling division.",
        "tell": "Whenever you see // n + 1, check exact multiples.",
        "test_code": test_code,
    }

    def claude(model: str, system: str, prompt: str, schema: Any) -> str:
        roles.append("generator")
        return json.dumps(generated)

    def openrouter(model: str, system: str, prompt: str) -> str:
        roles.append("critic")
        if "AUTHOR SAYS" in prompt:
            return json.dumps({"explanation_sound": True, "subtle_enough": True, "issues": ""})
        good_is_a = prompt.index(GOOD) < prompt.index(BAD)
        pick = {"right": "A" if good_is_a else "B", "wrong": "B" if good_is_a else "A"}[critic_pick]
        return json.dumps({"better": pick, "reason": "r"})

    monkeypatch.setattr(llm, "_call_claude", claude)
    monkeypatch.setattr(llm, "_call_openrouter", openrouter)
    return roles


def test_generate_tested_item(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, session: Session
) -> None:
    roles = _fake_llm(monkeypatch, tmp_path, "right")
    assert synth.generate(session, LLM(), "edge-case", 1, log=lambda _: None) == 1
    item = session.exec(select(Item)).one()
    assert item.verification_status == "verified" and item.test_code == TEST
    assert roles == ["generator"]  # verified by test: no critic needed
    # Same cached reply again is a duplicate, not a second item.
    assert synth.generate(session, LLM(), "edge-case", 1, log=lambda _: None) == 0


@pytest.mark.parametrize(("pick", "added"), [("right", 1), ("wrong", 0)])
def test_untestable_items_need_critic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, session: Session, pick: str, added: int
) -> None:
    roles = _fake_llm(monkeypatch, tmp_path, pick, test_code=None)
    assert synth.generate(session, LLM(), "readability", 1, log=lambda _: None) == added
    assert "critic" in roles
    if added:
        assert session.exec(select(Item)).one().verification_status == "unverifiable"


def test_dry_run_adds_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, session: Session
) -> None:
    roles = _fake_llm(monkeypatch, tmp_path, "right")
    assert synth.generate(session, LLM(dry_run=True), "security", 2, log=lambda _: None) == 0
    assert roles == []
