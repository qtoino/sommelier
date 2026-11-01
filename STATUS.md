# Status

## Works
- Core loop: blind side-by-side, choice/confidence/reason, server-side grading, reveal with diff, explanation, tell, attribution, flagging. Keyboard driven, light/dark.
- Stats (category, confidence/calibration, source, difficulty, hedge rate, longer-version baseline, history), review mode, filters.
- Mining pipeline end to end (dry-run verified on pallets/click: 140 commits scanned, 20 candidates).
- Synthetic generation with Docker-sandboxed test verification and a blind OpenRouter critic.
- `just test` (pytest + Vitest), `just lint`, `just e2e` (Playwright), Docker self-hosting.

## Blocked / remaining
- **Dataset fill (M7) not run yet.** It needs the Claude Code CLI to be signed in (`claude`, then `/login`) and `OPENROUTER_API_KEY` in `.env` for the critic. The DB currently holds only the 11 hand-written seed items.

## Next steps
- Run the fill under the 95% quota guard and spot-check items.
- Adding a language (C#/.NET, Rust, C): write an extractor equivalent to `mine.extract`, add a CodeMirror language to `LANGUAGES` in `frontend/src/Code.tsx`, add a sandbox image with that toolchain, and add topics. Nothing else assumes Python.
