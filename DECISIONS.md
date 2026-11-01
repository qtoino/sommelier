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
