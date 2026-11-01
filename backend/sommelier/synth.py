"""Synthetic pairs: generate with Claude, verify by running a test in a sandbox, or have an
independent critic (different model family) re-judge blind when no test is possible."""

import random
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from sqlmodel import Session, select

from sommelier.llm import LLM, LLMError, model_for
from sommelier.models import Difficulty, Item, line_count, validate_item

Log = Callable[[str], None]

TOPICS: dict[str, list[str]] = {
    "correctness": [
        "mutable default argument shared across calls",
        "late-binding closures created in a loop",
        "dict/set mutated while iterating",
        "integer vs float division in an average or percentage",
        "shallow copy of nested structures before modification",
        "`is` vs `==` for strings or numbers",
        "generator exhausted after first use",
        "exception swallowed so a partial result looks complete",
        "sorting stability or key function subtly wrong",
        "rounding money or percentages",
        "merging dicts where later keys should or should not win",
        "bool is a subclass of int in validation",
    ],
    "edge-case": [
        "pagination off-by-one at exact multiples or empty input",
        "timezone-naive datetimes compared or converted",
        "DST transitions when adding days",
        "empty string vs None vs missing key",
        "unicode case-insensitive comparison (casefold, ß, Turkish i)",
        "splitting CSV or text where the separator appears in fields",
        "chunking a list where the last chunk is short",
        "negative numbers with modulo or floor division",
        "float comparison for equality or thresholds",
        "parsing durations or ranges with open ends",
        "retry loop that never runs or runs once too many",
    ],
    "security": [
        "SQL injection via f-string or format into a query",
        "path traversal when joining user input to a base dir",
        "non-constant-time comparison of tokens",
        "predictable tokens from `random` instead of `secrets`",
        "unsafe deserialization (pickle, yaml.load) of request data",
        "shell injection via subprocess with shell=True",
        "open redirect from a `next` parameter",
        "XML external entities or zip-slip on archive extraction",
        "logging secrets or tokens",
        "JWT decoded without verifying algorithm or signature",
    ],
    "performance": [
        "N+1 queries in an ORM loop",
        "list membership test inside a loop instead of a set",
        "repeated string concatenation building a large output",
        "loading a whole file or query result into memory instead of streaming",
        "regex recompiled or catastrophic backtracking",
        "quadratic dedupe or list.pop(0) queue",
        "pandas row-wise apply where vectorized ops exist",
        "unbounded cache or memoization keyed by user input",
        "sorting to get the top k items",
        "sync HTTP calls in a loop that could be batched",
    ],
    "readability": [
        "over-abstracted class hierarchy vs a plain function",
        "boolean flag parameters that switch behaviour",
        "deeply nested conditionals vs early returns",
        "clever one-liner comprehension vs a clear loop",
        "magic numbers and stringly-typed status values",
        "a function doing parsing, validation and I/O at once",
        "misleading names that disagree with behaviour",
        "needless indirection through config or registries",
    ],
    "api-design": [
        "leaking library exceptions across an API boundary",
        "returning None for both not-found and error",
        "retry without backoff or jitter in a client",
        "functions with many positional booleans",
        "mutating an argument the caller passed in",
        "inconsistent return types depending on input",
        "missing timeouts on network calls in a client library",
        "public API that exposes internal data structures",
        "idempotency of a POST handler that may be retried",
    ],
    "sql-and-schema": [
        "missing or wrongly ordered composite index for a common query",
        "NULL semantics in NOT IN or comparisons",
        "COUNT(*) vs COUNT(column) with outer joins",
        "storing money as FLOAT",
        "unique constraint missing so a race creates duplicates",
        "OFFSET pagination on a large table vs keyset pagination",
        "timestamp without time zone for event times",
        "check-then-insert race vs INSERT ... ON CONFLICT",
        "SELECT * in an API query that later breaks or leaks columns",
    ],
}

TRADEOFF_TOPICS: list[tuple[str, str]] = [
    ("sql-and-schema", "denormalized counter column vs COUNT(*) at read time"),
    ("performance", "caching a computed value vs recomputing it on every call"),
    ("api-design", "raising an exception vs returning a result object for expected failures"),
    ("readability", "explicit loop vs a functional pipeline (map/filter/itertools)"),
    ("performance", "eager loading related rows vs lazy loading"),
    ("api-design", "strict input validation that rejects vs lenient coercion"),
    ("correctness", "failing fast on a bad record vs skipping and reporting it"),
    ("sql-and-schema", "UUID vs auto-increment integer primary keys"),
    ("performance", "precomputing a lookup dict vs a linear scan for small inputs"),
    ("api-design", "returning a list vs a generator from a public function"),
    ("edge-case", "rejecting ambiguous input vs guessing a sensible default"),
    ("security", "per-request DB permission checks vs a cached permission set"),
]

TESTED = {"correctness", "edge-case"}  # must ship a passing/failing test
MAYBE_TESTED = {"security", "performance"}


class Generated(BaseModel):
    language: Literal["python", "sql"]
    difficulty: Difficulty
    prompt: str
    context_code: str | None = None
    version_good: str
    version_bad: str
    explanation: str
    tell: str
    test_code: str | None = None


class BlindPick(BaseModel):
    better: Literal["A", "B", "depends"]
    reason: str


class Review(BaseModel):
    explanation_sound: bool
    subtle_enough: bool
    issues: str


GEN_SYSTEM = """\
You write items for Sommelier, a trainer where experienced engineers see two versions of the \
same code side by side (unlabelled, random order), pick the better one, then read an \
explanation. The worse version must be the kind of mistake an AI coding assistant plausibly \
makes: clean, confident, idiomatic-looking code that is subtly wrong or worse in production.

Hard rules:
- No obvious planted bugs, no suspicious names, no comments or docstrings hinting at the \
problem, no TODOs. Comments should be rare and identical in both versions.
- Both versions solve the same task with the same signature, similar style and naming, and \
look equally professional. Only the substance differs.
- Keep each version 4-30 lines. Code must be complete and runnable given context_code.
- prompt: one or two neutral sentences of context, e.g. "Both functions paginate search \
results." Never hint at the answer or name the pitfall.
- context_code: only what is needed to judge (constants, imports, a class header), or null.
- explanation: 3-6 sentences: what concrete input/situation separates them and why. Teach a \
reusable lesson. Refer to "the better version"/"the other version", never A/B.
- tell: one sentence a reviewer carries into real reviews: "Whenever you see X, check Y."
- A great item makes an experienced engineer hesitate for a few seconds. Prefer subtle and \
realistic over clever.

Reply with JSON only, matching the requested schema.
"""

TEST_RULES = """\
test_code: a pytest module. The code under test (context_code followed by ONE version) is \
saved as `solution.py`; start the test with `from solution import *`. It must PASS against \
version_good and FAIL (an assertion failure, not an ImportError or SyntaxError) against \
version_bad. Use only the standard library and pytest, no network, no timing assertions, \
finish in under 2 seconds."""


def gen_prompt(
    category: str, topic: str, *, shorter_good: bool, tradeoff: bool, avoid: list[str]
) -> str:
    shape = (
        "The BETTER version must have FEWER lines than the worse one."
        if shorter_good
        else "The two versions must be within 2 lines of each other in length."
    )
    if tradeoff:
        kind = (
            "This is a TRADE-OFF item: neither version is simply better. version_good and "
            "version_bad are just the two sides. Each must win clearly in a realistic situation, "
            "and the explanation must say when each wins. The correct answer is 'It depends'. "
            "Set test_code to null."
        )
    elif category in TESTED:
        kind = TEST_RULES + " test_code is REQUIRED."
    elif category in MAYBE_TESTED:
        kind = (
            TEST_RULES
            + " Include test_code only if such a deterministic test is natural; else null."
        )
    else:
        kind = "Set test_code to null."
    lang = (
        "Use SQL DDL/queries (language 'sql'), or Python with sqlite3/SQLAlchemy where natural."
        if category == "sql-and-schema"
        else "Use Python (language 'python')."
    )
    avoid_txt = "\n".join(f"- {p}" for p in avoid[-30:]) or "- (none yet)"
    return (
        f"Category: {category}\nTopic: {topic}\n{lang}\n{shape}\n{kind}\n\n"
        f"Do not repeat these existing items in this category:\n{avoid_txt}\n"
    )


def mostly_clean(code: str) -> bool:
    """Reject versions that literally comment on their own problem."""
    low = code.lower()
    return not any(
        w in low for w in ("# bug", "# fix", "todo", "fixme", "# wrong", "# unsafe", "vulnerab")
    )


# ---------------------------------------------------------------- sandbox

SANDBOX_IMAGE = "sommelier-sandbox"
SANDBOX_DOCKERFILE = Path(__file__).resolve().parent / "sandbox.Dockerfile"


def docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        return False
    inspect = subprocess.run(["docker", "image", "inspect", SANDBOX_IMAGE], capture_output=True)
    if inspect.returncode != 0:
        build = subprocess.run(
            [
                "docker",
                "build",
                "-t",
                SANDBOX_IMAGE,
                "-f",
                str(SANDBOX_DOCKERFILE),
                str(SANDBOX_DOCKERFILE.parent),
            ],
            capture_output=True,
        )
        return build.returncode == 0
    return True


def run_pytest(solution: str, test_code: str, *, use_docker: bool, timeout: int = 20) -> int | None:
    """Pytest exit code (0 pass, 1 test failure, >1 errors), or None on timeout."""
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "solution.py").write_text(solution, encoding="utf-8")
        Path(tmp, "test_solution.py").write_text(test_code, encoding="utf-8")
        pytest_args = ["-m", "pytest", "-q", "-p", "no:cacheprovider", "test_solution.py"]
        if use_docker:
            name = f"sommelier-{uuid.uuid4().hex[:12]}"
            cmd = [
                "docker", "run", "--rm", "--name", name, "--network", "none",
                "--memory", "256m", "--cpus", "1", "--pids-limit", "64",
                "--read-only", "--tmpfs", "/tmp", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "-e", "PYTHONDONTWRITEBYTECODE=1",
                "-v", f"{tmp}:/work:ro", "-w", "/work", SANDBOX_IMAGE, "python", *pytest_args,
            ]  # fmt: skip
            cwd = None
        else:
            cmd, cwd = [sys.executable, "-I", *pytest_args], tmp
        try:
            proc = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            if use_docker:  # killing the client leaves the container running
                subprocess.run(["docker", "rm", "-f", name], capture_output=True)
            return None
        return proc.returncode


def verify(context_code: str | None, good: str, bad: str, test_code: str, use_docker: bool) -> str:
    """'verified' if the test passes on good and fails (assertion or timeout) on bad."""
    prefix = (context_code or "").rstrip() + "\n\n\n" if context_code else ""
    on_good = run_pytest(prefix + good, test_code, use_docker=use_docker)
    on_bad = run_pytest(prefix + bad, test_code, use_docker=use_docker)
    return "verified" if on_good == 0 and on_bad in (1, None) else "failed"


# ---------------------------------------------------------------- critic


CRITIC_SYSTEM = """\
You are a principal engineer reviewing two versions of the same code. Judge which is better \
for production use. If each clearly wins in different realistic situations, answer "depends". \
Reply with JSON only: {"better": "A" | "B" | "depends", "reason": "..."}"""

REVIEW_SYSTEM = """\
You are a principal engineer checking a teaching item. You are given two versions of some \
code, which one the author says is better (or that it is a trade-off), and the author's \
explanation. Check that the explanation is technically correct and complete enough to teach \
the lesson, and that the item is subtle enough that an experienced engineer might hesitate \
(not an obviously planted bug). Reply with JSON only: \
{"explanation_sound": bool, "subtle_enough": bool, "issues": "..."}"""


def critic_agrees(llm: LLM, g: Generated, tradeoff: bool, log: Log) -> bool | None:
    """Blind pick by an independent model, then an explanation review. None in dry-run."""
    good_is_a = random.random() < 0.5
    a, b = (g.version_good, g.version_bad) if good_is_a else (g.version_bad, g.version_good)
    shown = f"CONTEXT: {g.prompt}\n{g.context_code or ''}\n\nVERSION A:\n{a}\n\nVERSION B:\n{b}\n"
    pick = llm.ask_model("critic", CRITIC_SYSTEM, shown, BlindPick)
    if pick is None:
        return None
    expected = "depends" if tradeoff else ("A" if good_is_a else "B")
    if pick.better != expected:
        log(f"    critic disagrees ({pick.better} vs {expected}): {pick.reason[:150]}")
        return False
    claim = "a trade-off" if tradeoff else f"version {expected} is better"
    review = llm.ask_model(
        "critic",
        REVIEW_SYSTEM,
        f"{shown}\nAUTHOR SAYS: {claim}\nEXPLANATION: {g.explanation}\n",
        Review,
    )
    if review is None:
        return None
    if not (review.explanation_sound and review.subtle_enough):
        log(f"    critic review failed: {review.issues[:150]}")
        return False
    return True


# ---------------------------------------------------------------- orchestration


def generate(
    session: Session,
    llm: LLM,
    category: str | None,
    count: int,
    *,
    tradeoff: bool = False,
    log: Log = print,
) -> int:
    existing = session.exec(select(Item).where(Item.source_type == "synthetic")).all()
    if tradeoff:
        topics = [(c, t) for c, t in TRADEOFF_TOPICS if category in (None, c)]
    else:
        assert category, "category is required unless --tradeoff"
        topics = [(category, t) for t in TOPICS[category]]
    offset = sum(
        1 for i in existing if i.is_tradeoff == tradeoff and category in (None, i.category)
    )
    use_docker = docker_ready()
    if not use_docker:
        log(
            "WARNING: Docker unavailable; tests run in a subprocess with a timeout"
            " (weaker isolation)"
        )
    known_good = {i.version_good.strip() for i in existing}
    added = 0
    for n in range(count):
        cat, topic = topics[(offset + n) % len(topics)]
        avoid = [i.prompt for i in existing if i.category == cat]
        shorter_good = (offset + n) % 2 == 0
        prompt = gen_prompt(cat, topic, shorter_good=shorter_good, tradeoff=tradeoff, avoid=avoid)
        log(f"  [{cat}] {topic}")
        try:
            g = llm.ask_model("generator", GEN_SYSTEM, prompt, Generated)
        except LLMError as e:
            log(f"    generator error: {e}")
            continue
        if g is None:
            log("    [dry-run] would generate")
            continue
        if g.version_good.strip() in known_good:
            log("    duplicate of an existing item; skipped")
            continue
        if not (mostly_clean(g.version_good) and mostly_clean(g.version_bad)):
            log("    rejected: hinting comments")
            continue

        status = "unverifiable"
        if not tradeoff and g.test_code and g.language == "python":
            status = verify(g.context_code, g.version_good, g.version_bad, g.test_code, use_docker)
            log(f"    test: {status}")
            if status == "failed":
                continue
        elif cat in TESTED and not tradeoff:
            log("    rejected: tested category without a test")
            continue
        if status == "unverifiable":
            try:
                agrees = critic_agrees(llm, g, tradeoff, log)
            except LLMError as e:
                log(f"    critic error: {e}")
                continue
            if agrees is None:
                log("    [dry-run] would ask critic")
                continue
            if not agrees:
                continue
        data = validate_item(
            {
                **g.model_dump(),
                "category": cat,
                "is_tradeoff": tradeoff,
                "source_type": "synthetic",
                "generator_model": model_for("generator"),
                "verification_status": status,
            }
        )
        session.add(Item(**data))
        session.commit()
        known_good.add(g.version_good.strip())
        existing = [*existing, Item(**data)]
        added += 1
        shape = line_count(g.version_good) - line_count(g.version_bad)
        log(f"    ADDED ({status}, good-bad lines {shape:+d})")
    return added


def reverify(session: Session, log: Log = print) -> dict[str, int]:
    """Re-run every stored synthetic test; demote items whose test no longer behaves."""
    use_docker = docker_ready()
    counts: dict[str, int] = {}
    items = session.exec(select(Item).where(Item.source_type == "synthetic")).all()
    for item in items:
        if not item.test_code:
            continue
        status = verify(
            item.context_code, item.version_good, item.version_bad, item.test_code, use_docker
        )
        counts[status] = counts.get(status, 0) + 1
        if status != item.verification_status:
            log(f"  {item.id}: {item.verification_status} -> {status}")
            item.verification_status = status
            if status == "failed":
                item.status = "rejected"
            session.add(item)
    session.commit()
    return counts
