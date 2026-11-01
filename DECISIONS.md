# Decisions

One entry per decision: what, alternatives, why.

1. **LLM via Claude Code CLI (`claude -p`) instead of the Anthropic SDK.** Alt: SDK + API key. Why: no API key available and API spend would be billed to the employer; `claude -p` runs on the existing subscription.
2. **Critic via OpenRouter (DeepSeek), not Claude.** Alt: Claude critic in fresh context. Why: cheaper and a different model family is a more independent second opinion.
3. **Models: opus for synthetic generation, sonnet for the mined-item judge.** Alt: one model everywhere. Why: subtlety matters most in generation; the judge is high-volume and mostly rejects.
4. **Quota guard at 95% of the 5-hour/weekly plan window.** The account has extra usage enabled, so >100% costs money. The pipeline also aborts on the first usage-limit error.
5. **justfile instead of Makefile.** Alt: GNU make. Why: no make on this Windows box; just runs natively with PowerShell. `just` is a dev dependency (`rust-just`) so nothing is installed globally: `uv run just <recipe>`.
6. **Shape-bias countermeasure.** Bug fixes usually add guards, so "pick the longer one" would score well without skill. We store line counts, steer synthetic items so the good version is shorter ~half the time, prefer simplifying mined fixes, and show an "always pick longer" baseline in stats.
7. **"It depends" is strict and ~10–15% of items are tradeoffs.** Only "It depends" is correct on tradeoffs, and it is wrong elsewhere. Enough tradeoffs that the option stays live; hedge rate is tracked.
8. **~70 mined / ~30 synthetic, mining seeded from BugsInPy commit IDs + regex.** Alt: 60/40 regex-only. Why: real shipped bugs are the most valuable; BugsInPy commits are confirmed bug fixes. Only commit IDs are used; license gate still applies per repo.
9. **API under `/api` prefix; Vite proxies `/api` in dev; FastAPI serves `frontend/dist` in Docker.** Why: one origin, no CORS.
10. **Python package lives in `backend/sommelier`, single root `pyproject.toml`.** Why: one env for app + pipeline + tests.
11. **Serving an item creates a pending Attempt row** (choice NULL) that stores `shown_left`. Alt: signed token, or trusting the client. Why: server keeps the mapping with no extra table; `time_to_answer_ms` is computed server-side from it.
12. **Category and difficulty are hidden until reveal.** Seeing "security" before answering is a hint.
13. **Line counts are derived, not stored.** `line_count()` is computed at stats time. Why: nothing to keep in sync.
14. **Hand-written seed items are `source_type=synthetic`, `generator_model=hand-written`, `verification_status=unverifiable`.** Why: the spec only has mined/synthetic; these are not mined.
15. **Flagging an item sets `status=flagged`, removing it from rotation** until it is cleaned up via export/import.
16. **Fix-pattern regex requires a fix-like word; a bare `#123` is not enough.** Alt: spec's "issue refs" as a standalone pattern. Why: squash-merged repos put `(#123)` on every commit, so issue refs alone match everything. Issue refs are still used to fetch the linked issue for the judge.
17. **Exactly one non-test `.py` file modified, and nothing outside function bodies changed** (imports excepted). Why: cheapest reliable way to get "one function meaningfully changed" without the judge needing more of the repo. Tests/docs may change in the same commit.
18. **"Changed lines" = max(removed, added) in the function diff, 1..15.** A one-line edit counts as 1, not 2.
19. **Extra filter: string/message-only changes are rejected** (AST equal after blanking string constants). These are almost never judgeable improvements.
20. **Blobless partial clones (`--filter=blob:none`) in `.cache/repos/`.** Commit metadata is local; only the two versions of candidate files are fetched. Keeps pandas/django clones small.
21. **The CLI runs as `python -m sommelier`.** Windows Application Control on this machine blocks the generated `sommelier.exe` launcher; `python -m` works everywhere.
22. **BugsInPy contributes commit ids only** (it ships no license for its metadata; we never copy its code or tests). Each repo still goes through the license gate, which drops e.g. ansible (GPL), matplotlib (non-SPDX), tqdm (MPL), youtube-dl (Unlicense, not allowlisted).
