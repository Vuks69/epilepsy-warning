# AGENTS.md

## Project state

- Target scope is a reusable Python/Go media-analysis library, documented in `README.md` and `planning/`. The implementation still contains the legacy Discord bot (`bot.py`) and a prototype analyzer.
- `planning/01_wcag_flash_thresholds.md` is the standards contract: WCAG 2.2 default, profiles, thresholds, and working values. `planning/04_architecture.md` defines the intended API and schema v2; `planning/05_implementation_plan.md` tracks the refactor. Code lags all of them.
- `planning/07_source_review.md` is the gap analysis from the scientific paper in `planning/guidelines_photo_epilepsy.txt`; read it before changing detector semantics.
- `pyproject.toml` is stale scope-wise: its description and dependencies still describe the Discord bot. Do not treat it as the source of truth for project scope.
- There is no CI and `tests/` is empty. Do not claim the test suite passes.

## Setup and verification

- Use the existing `.venv` (Python 3.14); the package is editable-installed. If dependencies or packaging change, run `.venv/bin/pip install -e .`.
- `pyproject.toml` declares Python `>=3.9`; avoid 3.10+ syntax unless the floor is raised.
- Verify detection with:
  - `.venv/bin/epilepsy-scan examples/4882.mp4`
  - `.venv/bin/epilepsy-scan examples/giphy/1.gif`
- Both known fixtures must print `TRIGGERING`. `epilepsy-scan` exits `1` when media is flagged: that is success for these checks, not a command failure.
- These are smoke tests only: they prove the prototype flags known-bad media, not that its transition counting, area model, or red detection follow the standards.
- `ruff` is available but has no configured rule set; `ruff check .` currently reports pre-existing errors in the prototype. Lint/format only the files you touch: `.venv/bin/ruff format <paths>`.

## Gotchas

- `src/epilepsy_warning/__init__.py` is empty, so the README's `from epilepsy_warning import FlashDetector` fails. Import from `epilepsy_warning.analyzer` until public exports are added.
- `FlashDetector.analyze(path)` returns a plain dict. It counts raw frame differences as flashes, assumes 30 fps, uses a whole-frame area average, and applies an RGB-ratio red heuristic. See `planning/02_analysis_approaches.md` and `planning/07_source_review.md`. Do not use it as a standards reference or claim WCAG/ISO compliance from its output.
- Media files are gitignored (`*.mp4`, `*.gif`), and only `examples/giphy.lst` is tracked. `4882.mp4` and `examples/giphy/*.gif` exist locally only. Recreate them with `cd examples && ../util/download_gifs.sh giphy.lst` (uses `wget`, waits 5 seconds between downloads). Add media with `git add -f` only deliberately.
- `util/run_bot.sh` is stale: it hardcodes an absolute path and points to the non-existent `src/bot.py`. Do not use it as the run command.
- The `epilepsy-bot` entry point is legacy and requires `DISCORD_TOKEN`; the `.env.example` settings are bot-only. Keep new library code independent of env vars, network access, and Discord.

## Conventions

- Core analysis lives in `src/epilepsy_warning/analyzer.py`; `cli.py` is a thin wrapper. Keep the core free of platform I/O, downloads, moderation actions, and temp-file side effects.
- Before changing detector thresholds or counting, read `planning/01_wcag_flash_thresholds.md` and `planning/07_source_review.md`. Default to WCAG 2.2; make profiles, display assumptions, and result schema explicit.
- Keep normative thresholds separate from the paper's working values (66 ms transition, 20 ms synchronization, 65 Hz fast-flash). Record which assumptions a result used.
- Stick to rule-based flash detection; LLM/ML and static-pattern analysis are explicitly out of scope for v1.
- Use the src layout (`src/epilepsy_warning`) and the `epilepsy-warning` / `epilepsy_warning` naming when adding packages or modules.
