# Status

## Dataset (data/items.jsonl)

**145 active items** (149 total, 4 rejected in spot-check), Python plus a few SQL.

| | count |
|---|---|
| mined (24 permissive repos, real fix commits) | 93 |
| synthetic, test-verified in the Docker sandbox | 14 |
| synthetic, checked by the blind critic | 27 |
| hand-written seed | 11 |
| "It depends" trade-offs | 10 |

By category: correctness 67, edge-case 34, security 11, api-design 9, performance 10, sql-and-schema 9, readability 5. Licenses: MIT, BSD-3-Clause, Apache-2.0. Every commit link was checked against the GitHub API.

**Shape bias:** "always pick the longer version" scores 53% on the full set, so length gives nothing away. Mined fixes alone would score 65% (fixes add guards), and synthetic items lean the other way (32%).

**Cost:** 272 paid LLM calls in total (140 judge/sonnet, 58 generator/opus, 73 critic/DeepSeek, 1 smoke test). The Team plan's 5-hour window went from 3% to 9% and the weekly window from 10% to 11%. No extra usage was spent.

### Spot-check

- An automated audit (`scratchpad/audit.py` during the fill) looked at every item for: answer words in prompts or context, comments in only one version, hint-y identifiers that differ between versions, very long items, and duplicate prompts.
- It found two leak classes in mined items: comments added by the fix, and reworded docstrings. The scrubber now removes both, and `sommelier rescrub` re-applied it to stored items. One synthetic identifier (`_SAFE_PATH`) was renamed.
- About 30 items were read by hand. Rejected: 4 near-duplicates, each the same lesson as another item (ids in the dataset with `status=rejected`).
- Kept on purpose:
  - `safe_url_string` (scrapy): the real library call the fix introduced.
  - A few long (45–59 line) mined functions where the fix is one line: needle-in-a-haystack items are realistic review practice.

## Works

- Core loop: blind side-by-side, choice/confidence/reason, server-side grading, reveal with diff, explanation, tell and attribution, and flagging. Keyboard driven, light/dark.
- Stats: by category, confidence (calibration), source and difficulty; hedge rate; the longer-version baseline; history. Review mode and filters.
- Mining: license gate → BugsInPy + regex candidates → AST single-function extraction → filters → leak scrub (keywords, one-sided comments, differing docstrings) → Sonnet judge.
- Synthetic: Opus generator, Docker sandbox (`--network none`, resource-limited, read-only) and a blind DeepSeek critic.
- `just test` (pytest + Vitest), `just lint`, `just e2e` (Playwright) and `docker compose up --build` all pass or work.

## Known gaps / caveats

- **Mined items are mostly correctness/edge-case.** Real single-function fixes rarely sit in the other categories. Security, performance, schema, API design and readability come mainly from synthetic items.
- **Source style is a weak tell.** Mined code looks like real-repo code: `self`, older idioms, long docstrings. A user who learns to spot it could partly recover the "fixes are longer" bias. The source is hidden until reveal, but the style isn't.
- **The judge accepts generously** (~85% of candidates that survive the filters), so mined items vary more in sharpness than synthetic ones. Use the flag button: flagged items leave rotation, and `export`/`import` makes cleanup easy.
- **Readability is the thinnest category (5).** The critic rejects most generated readability items as matters of taste, which is the conservative outcome.
- All topic lists are now attempted once. Add new topics to `TOPICS`/`TRADEOFF_TOPICS` in `synth.py` to generate more.

## Suggested next steps

1. Use the app for a week, flag weak items, then `export` and commit the cleaned dataset.
2. Mine more repos for difficulty variety. Add repos to `repos.toml` and run `uv run python -m sommelier mine --repo X --limit 5`.
3. A stricter judge pass for mined items, e.g. a second blind critic pick as for synthetic items, if mined items feel easy.

## Adding a language (C#/.NET, Rust, C)

Nothing outside the extractors assumes Python. Per language:
1. **Extractor:** an equivalent of `mine.extract` and `mine.scrub_pair` (functions by name, changed-function diff, comment scrub), e.g. tree-sitter. Gate candidate files by extension in `single_source_file` instead of `.py`.
2. **Sandbox:** a toolchain image beside `sandbox.Dockerfile` (dotnet SDK / rust / gcc) and a test runner in `synth.run_pytest`'s place (xunit, `cargo test`, a C test harness).
3. **Generator:** language-specific `TEST_RULES` and topics.
4. **UI:** add the CodeMirror language to `LANGUAGES` in `frontend/src/Code.tsx` (`@codemirror/lang-rust`, `lang-cpp`, a C# legacy mode).
5. **Repos:** permissive repos in `repos.toml`. The license gate is language-agnostic.
