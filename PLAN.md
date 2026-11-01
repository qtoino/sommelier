# Plan

Status legend: [x] done, [ ] todo, [~] partial (see STATUS.md)

## M1 Scaffold
- [x] uv project (`backend/sommelier`), FastAPI app, health endpoint + test
- [x] Vite + React + TS + Tailwind v4 + CodeMirror deps, Vitest
- [x] justfile: dev / test / lint / fmt / seed / e2e
- [x] ruff, mypy, pytest, oxlint + tsc

## M2 Data model + seed
- [x] SQLModel models: Item, Attempt, ItemFlag (+ lines_good/lines_bad)
- [x] Alembic initial migration
- [x] JSONL import/export + `fixtures/seed.jsonl` (~10 items, ≥1 tradeoff)
- [x] API: GET /api/items/next, POST /api/attempts, GET /api/items/{id}/reveal, POST /api/items/{id}/flag, GET /api/stats
- [x] Tests: randomization, server-side grading (incl. tradeoff rules), no-leak, reveal gating

## M3 Core loop UI
- [x] Side-by-side read-only panes, choice/confidence/reason, keyboard 1/2/3/Enter/N
- [x] Reveal: merge diff, explanation, tell, category, attribution, flag
- [x] Light/dark mode

## M4 Stats, review, filters
- [x] Stats page: overall, by category, by confidence, hedge rate, longer-baseline, history
- [x] Review mode (items last answered wrong)
- [x] Filters: category, source type, difficulty

## M5 Mining
- [x] Repo allowlist + license gate (GitHub API → LICENSE file fallback)
- [x] Candidates: BugsInPy commit list + fix-pattern regex
- [x] AST single-function extraction + filters
- [x] Leak scrubbing
- [x] LLM judge (claude -p, Pydantic-validated JSON), cache, budget cap, dry-run
- [x] Run on 2–3 repos, then broaden (click pilot, then 24 repos)

## M6 Synthetic
- [x] Seed topics per category
- [x] Generator (claude -p opus) with shape-balance instruction
- [x] Docker sandbox (subprocess fallback) for pytest verification
- [x] Critic (OpenRouter DeepSeek) for unverifiable items

## M7 Dataset
- [x] 100+ active items (145), all 7 categories, 10 tradeoffs, under quota guard (peak 9% of 5h window)
- [x] Spot-check, reject weak items (audit + ~30 read by hand, 4 rejected)

## M8 Polish
- [x] Dockerfile + docker-compose
- [x] README
- [x] Playwright smoke test
- [x] STATUS.md
