# Sommelier

Blind tasting for code. Two plausible versions of the same thing, no labels: pick the better one (or "it depends"), say how sure you are, then see the answer, a diff, the explanation, and *the tell*: the signal a sharp reviewer should have noticed.

Built to train code-review judgment on AI-era code, which tends to *look* good whether or not it is.

## Quick start

Requirements: [uv](https://docs.astral.sh/uv/) and Node 20+. Everything else (Python 3.12, deps, `just`, Playwright browsers) is installed into the project, not your machine.

```bash
uv sync                 # .venv with Python 3.12, app + dev deps (incl. `just`)
cd frontend && npm install && cd ..
uv run just seed        # create the DB and load fixtures + data/items.jsonl
uv run just dev         # API on :8000 + Vite on http://localhost:5173
```

Keyboard: `1` / `2` / `3` choose A / B / it depends, `L` / `M` / `H` confidence, `Enter` submit (Ctrl+Enter inside the reason box), `N` next, `F` flag a bad item.

Tabs: **Practice** (unseen items first), **Review mistakes** (items whose last answer was wrong), **Stats** (accuracy by category, source, difficulty; calibration by confidence; hedge rate; and an "always pick the longer version" baseline you should beat). Filters: category, source (mined/synthetic), difficulty.

### Commands

| Command | What it does |
|---|---|
| `uv run just dev` | migrate + run API (reload) and Vite |
| `uv run just test` | pytest + Vitest |
| `uv run just lint` | ruff, ruff format check, mypy, oxlint, tsc |
| `uv run just seed` | migrate + import `fixtures/seed.jsonl` and `data/items.jsonl` |
| `uv run just e2e` | build frontend, install Chromium locally, Playwright smoke test |
| `docker compose up --build` | self-host on http://localhost:8000 (DB in a named volume) |

On Windows, run the CLI as `uv run python -m sommelier …` (Application Control may block the generated `sommelier.exe` shim; `python -m` always works).

## Content pipeline

A separate CLI. The web app only reads what the pipeline already stored; **no LLM calls happen while you use the app**.

```bash
uv run python -m sommelier mine --repo click --repo flask --limit 5 [--dry-run]
uv run python -m sommelier generate --category security --count 5 [--dry-run]
uv run python -m sommelier generate --tradeoff --count 3
uv run python -m sommelier verify          # re-run every synthetic item's test in the sandbox
uv run python -m sommelier stats           # counts by category / source / status
uv run python -m sommelier export data/items.jsonl --status active
uv run python -m sommelier import data/items.jsonl
```

### LLM backends (no API key needed)

| Role | Backend | Default model (env) |
|---|---|---|
| judge (mined items) | Claude Code CLI `claude -p` on your Claude subscription | `sonnet` (`SOMMELIER_JUDGE_MODEL`) |
| generator (synthetic) | Claude Code CLI `claude -p` | `opus` (`SOMMELIER_GEN_MODEL`) |
| critic (independent check) | OpenRouter | `deepseek/deepseek-chat` (`SOMMELIER_CRITIC_MODEL`, `OPENROUTER_API_KEY`) |

The CLI must be signed in once (`claude`, then `/login`). It is found on `PATH`, via `SOMMELIER_CLAUDE_BIN`, or in the Claude desktop app's folder. Calls run in a temp dir with tools disabled and a custom system prompt, so no project context leaks in.

Every reply is cached in `.cache/llm/` keyed by (role, model, system, prompt), so reruns cost nothing. Paid calls per command are capped by `SOMMELIER_MAX_LLM_CALLS` (default 400) and logged to `.cache/llm/ledger.jsonl`. The run stops at the first usage-limit or rate-limit error. All LLM commands support `--dry-run`.

### Mined pairs (real bugs from real history)

1. **Allowlist**: `repos.toml`.
2. **License gate**: the GitHub API's `license.spdx_id`, falling back to the LICENSE file. Only MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0 and ISC pass. GPL/AGPL/LGPL/MPL, non-SPDX and unknown licenses are skipped. Every item stores its SPDX id, repo, commit URL, path, commit message and linked issue.
3. **Candidates**: BugsInPy's confirmed fix commits (commit ids only) come first. Then non-merge commits whose subject matches fix-like words. The commit must modify exactly one non-test `.py` file.
4. **Extraction (Python `ast`)**: exactly one function or method changed (comparing ASTs, so comments, docstrings and layout don't count), and nothing else at module level changed apart from imports.
5. **Filters**: function ≤ 60 lines, 1–15 changed lines. Rejected: rename-only, type-annotation-only, string/message-only, deprecation or version changes.
6. **Leak scrubbing**: comments like `# fix for #123`, `# workaround` and `# was wrong` are removed using `tokenize`, along with `.. versionchanged::` notes. Code is otherwise untouched.
7. **Judge**: Claude decides whether this is a real improvement that can be judged from the function plus a small `context_code`. If so, it writes the neutral prompt, category, difficulty, explanation and tell. The reply is validated with Pydantic. Decisions are logged in `.cache/mine/*.jsonl`.

The "after" version is better, not necessarily perfect. The reveal screen says so.

### Synthetic pairs

Seed topics per category live in `backend/sommelier/synth.py`. The generator is told to write the kind of mistake an AI assistant plausibly makes: clean, idiomatic and subtly wrong, with no hinting names or comments, and similar length and style in both versions.

- **correctness / edge-case** (and security/performance where natural) ship a pytest that must **pass on the good version and fail with an assertion (or time out) on the bad one**. It runs in Docker with `--network none --memory 256m --cpus 1 --pids-limit 64 --read-only --cap-drop ALL`, as `nobody`, with code mounted read-only. Without Docker it falls back to an isolated subprocess with a timeout and logs a warning.
- **Untestable items** (readability, API design, schema, trade-offs) go to a critic from a different model family. The critic first picks A/B/depends **blind**, in random order. Only if it agrees does it review the explanation. Any disagreement discards the item.

### Shape bias

Bug fixes usually add guards, so "pick the longer, more defensive version" would score well without any skill. Countermeasures:
- Generation alternates between items where the better version is shorter and items where the two are equal length.
- The miner tries fixes that don't grow the function first.
- Stats show the accuracy of the "always pick the longer one" strategy, so you can check that you beat it.

## Data model

`Item` (with `language`, `kind`, source attribution, verification fields and `status`), `Attempt`, and `ItemFlag`. See `backend/sommelier/models.py`.

When an item is served, a pending `Attempt` stores which version is on the left. The client only ever receives `left` and `right`. Grading happens server-side, and `/reveal` refuses until the item is answered. Item ids are random.

## Layout

```
backend/sommelier/  app.py (API), models.py, db.py, io.py (JSONL), cli.py,
                    llm.py, mine.py, synth.py, sandbox.Dockerfile
backend/alembic/    migrations
backend/tests/      pytest (+ e2e Playwright, docker sandbox tests)
frontend/src/       React + CodeMirror 6 (@codemirror/merge for the diff)
fixtures/seed.jsonl hand-written starter items
data/items.jsonl    the versioned dataset
```

See `DECISIONS.md` for why things are the way they are and `STATUS.md` for what's left.
