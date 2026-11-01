"""The only place the pipeline talks to an LLM.

judge + generator -> Claude Code CLI (`claude -p`, runs on the user's subscription)
critic            -> OpenRouter (independent model family, e.g. DeepSeek)

Every response is cached on disk by (role, model, system, prompt), so reruns are free.
Paid calls are capped per process by SOMMELIER_MAX_LLM_CALLS and logged to a ledger.
"""

import glob
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Literal, TypeVar

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()

Role = Literal["judge", "generator", "critic"]
T = TypeVar("T", bound=BaseModel)

CACHE_DIR = Path(".cache/llm")
_DEFAULT_MODELS: dict[Role, tuple[str, str]] = {
    "judge": ("SOMMELIER_JUDGE_MODEL", "sonnet"),
    "generator": ("SOMMELIER_GEN_MODEL", "opus"),
    "critic": ("SOMMELIER_CRITIC_MODEL", "deepseek/deepseek-chat"),
}


class BudgetExceeded(RuntimeError):
    pass


class UsageLimitHit(RuntimeError):
    """The subscription or provider refused for quota reasons. Stop the whole run."""


class LLMError(RuntimeError):
    pass


def model_for(role: Role) -> str:
    env, default = _DEFAULT_MODELS[role]
    return os.environ.get(env) or default


def claude_bin() -> str:
    explicit = os.environ.get("SOMMELIER_CLAUDE_BIN")
    if explicit:
        return explicit
    found = shutil.which("claude")
    if found:
        return found
    # The Claude desktop app ships the CLI in a versioned folder.
    appdata = os.environ.get("APPDATA", "")
    candidates = glob.glob(os.path.join(appdata, "Claude", "claude-code", "*", "*", "claude.exe"))
    if candidates:
        return max(candidates, key=os.path.getmtime)
    raise LLMError("Claude Code CLI not found; set SOMMELIER_CLAUDE_BIN")


_LIMIT_MARKERS = ("usage limit", "rate limit", "limit reached", "quota", "429", "credit balance")


def _looks_like_limit(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _LIMIT_MARKERS)


def _call_claude(model: str, system: str, prompt: str, schema: dict[str, Any] | None) -> str:
    cmd = [
        claude_bin(),
        "-p",
        "--output-format",
        "json",
        "--model",
        model,
        "--tools",
        "",
        "--system-prompt",
        system,
        "--strict-mcp-config",
        "--no-session-persistence",
    ]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(schema)]
    # Neutral cwd so no project CLAUDE.md / settings leak into the prompt.
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=cwd,
            timeout=600,
        )
    raw = proc.stdout.strip()
    try:
        out = json.loads(raw.splitlines()[-1]) if raw else {}
    except json.JSONDecodeError as e:
        raise LLMError(f"claude -p returned non-JSON: {raw[:300]!r} {proc.stderr[:300]!r}") from e
    result = out.get("result") or ""
    if out.get("is_error") or proc.returncode != 0:
        detail = f"{result} {out.get('api_error_status')} {proc.stderr[:300]}"
        if _looks_like_limit(detail):
            raise UsageLimitHit(detail.strip())
        raise LLMError(f"claude -p failed: {detail.strip()[:500]}")
    structured = out.get("structured_output")
    return json.dumps(structured) if structured is not None else str(result)


def _call_openrouter(model: str, system: str, prompt: str) -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("OPENROUTER_API_KEY is not set")
    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        },
        timeout=300,
    )
    if resp.status_code in (402, 429):
        raise UsageLimitHit(f"openrouter {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()
    return str(resp.json()["choices"][0]["message"]["content"])


def extract_json(text: str) -> Any:
    """Parse the first JSON object in a model reply (tolerates ```json fences and prose)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start : end + 1])


class LLM:
    def __init__(self, max_calls: int | None = None, dry_run: bool = False) -> None:
        self.max_calls = max_calls or int(os.environ.get("SOMMELIER_MAX_LLM_CALLS", "400"))
        self.dry_run = dry_run
        self.calls = 0
        self.cache_hits = 0

    def ask(
        self,
        role: Role,
        system: str,
        prompt: str,
        schema: dict[str, Any] | None = None,
    ) -> str | None:
        """Return the reply text, or None in dry-run mode when the reply isn't cached."""
        model = model_for(role)
        key = hashlib.sha256(
            json.dumps([role, model, system, prompt, schema], sort_keys=True).encode()
        ).hexdigest()
        path = CACHE_DIR / f"{key}.json"
        if path.exists():
            self.cache_hits += 1
            return str(json.loads(path.read_text(encoding="utf-8"))["text"])
        if self.dry_run:
            return None
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"budget of {self.max_calls} LLM calls used up")
        self.calls += 1
        started = time.time()
        if role == "critic":
            text = _call_openrouter(model, system, prompt)
        else:
            text = _call_claude(model, system, prompt, schema)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"role": role, "model": model, "prompt": prompt, "text": text}),
            encoding="utf-8",
        )
        with (CACHE_DIR / "ledger.jsonl").open("a", encoding="utf-8") as ledger:
            ledger.write(
                json.dumps(
                    {"ts": started, "role": role, "model": model, "secs": time.time() - started}
                )
                + "\n"
            )
        return text

    def ask_model(self, role: Role, system: str, prompt: str, model: type[T]) -> T | None:
        """Ask for JSON matching a Pydantic model. Returns None in dry-run (uncached)."""
        schema = model.model_json_schema() if role != "critic" else None
        text = self.ask(role, system, prompt, schema)
        if text is None:
            return None
        try:
            return model.model_validate(extract_json(text))
        except (ValueError, ValidationError) as e:
            raise LLMError(f"{role} reply did not match {model.__name__}: {e}") from e
