# AGENTS.md

## Project state

- Target scope is a reusable Python/Go media-analysis library, documented in `README.md` and `planning/`. The Python library (`0.2.0`) and CLI are implemented; the Discord bot and prototype analyzer have been removed. The Go port is still planned.
- `planning/01_wcag_flash_thresholds.md` is the standards contract: WCAG 2.2 default, profiles, thresholds, and working values. `planning/04_architecture.md` defines the intended API and schema v2; `planning/05_implementation_plan.md` tracks the refactor.
- `planning/07_source_review.md` is the gap analysis from the scientific paper in `planning/guidelines_photo_epilepsy.txt`; read it before changing detector semantics.
- `planning/08_optimization_plan.md` tracks performance work. Phases 1-2 are implemented (sRGB LUT, `tile_frame_uint8`, numpy GIF compositing, exact numpy BOX fallback, fused `linear_rgb_features`). Phase 3 (incremental suffix state, engine short-circuiting) is documented but not started. A separate opt-in `--quick` early-verdict mode was added per request; it stops on a triggering prefix and marks the result `quick` — intentionally distinct from Phase 3, which skips irrelevant work but never stops early.
- `pyproject.toml` describes the library, not the legacy bot. Core dependencies are `numpy`, `Pillow`, `imageio`, and `imageio-ffmpeg`.
- There is no CI. `tests/` contains stdlib `unittest` tests; run them locally before claiming a change works. `hypothesis` is a dev dependency (see `pyproject.toml`) driving `tests/test_property.py`, which covers determinism, directed monotonicity, and frame-rate invariance.

## Setup and verification

- Use the existing `.venv` (Python 3.14); the package is editable-installed. If dependencies or packaging change, run `uv pip install -e . --python .venv/bin/python` (the venv has no `pip`).
- `pyproject.toml` declares Python `>=3.9`; avoid 3.10+ runtime syntax unless the floor is raised. The modules use `from __future__ import annotations`.
- Run the unit tests:
  - `.venv/bin/python -m unittest discover -s tests -v`
- Verify known triggering media:
  - `.venv/bin/epilepsy-scan examples/triggering/30.mp4`
  - `.venv/bin/epilepsy-scan examples/triggering/1.gif`
- Both fixtures must print `TRIGGERING`. `epilepsy-scan` exits `1` when media is flagged: that is success for these checks, not a command failure. A full `30.mp4` scan takes roughly 20 seconds with the default grid.
- Check benign controls stay safe: `.venv/bin/epilepsy-scan examples/not-triggering/*.gif` (all must exit `0`).
- Golden-media regression automates all of the above: `.venv/bin/python -m unittest tests.test_golden_media` asserts every fixture in `examples/triggering.lst` reports `TRIGGERING` and every fixture in `examples/not-triggering.lst` stays safe, over the cached media (downloaded once, reused across runs). Set `EPILEPSY_GOLDEN_EQUIP=1` to also run the Phase-3 short-circuit equivalence check (toggling `TransitionEngine._enable_short_circuit`) over the real decode path.
- Property regression is synthetic and needs no media cache: `.venv/bin/python -m unittest tests.test_property`. Hypothesis properties assert byte-stable `to_json()`/`to_dict()` output, directed monotonicity (critical-difference step, uniform area scaling, transition-count), and densification invariance of the verdict and transition-level measurements — `max_transition_duration_ms` is intentionally exempt, as a coarse single-frame step resolves to a real duration once more samples bracket it.
- Performance regression is synthetic and needs no media cache: `.venv/bin/python -m unittest tests.test_performance`. It times `analyze_frames` over a deterministic two-tone clip at 24/30/60/120 fps and asserts the busiest rate stays within `PER_FRAME_COST_GUARD_FACTOR` (3.0×) of the cheapest per-frame cost. This is a machine-independent relative guard (machine speed cancels in the ratio) that tolerates the legitimate per-frame growth from the `_history` 66 ms window while failing on a pathological per-frame blowup. It adds ~1.6 s to the suite.
- These are smoke tests; the unit tests cover synthetic timing and area boundaries, but neither proves standards compliance.
- `ruff` is configured in `pyproject.toml` (`E4`, `E7`, `E9`, `F`, `I`, `B` with `target-version = "py39"`). Run `.venv/bin/ruff check src/epilepsy_warning tests` and `.venv/bin/ruff format <paths>`.
- `mypy` is configured in `pyproject.toml` (`warn_redundant_casts`, `ignore_missing_imports`; `mypy>=1.13` is a dev dependency). Run `.venv/bin/mypy src/epilepsy_warning` to type-check the library (the public API ships `py.typed`). CI runs ruff + mypy across Python 3.9/3.12/3.14; `tests/test_golden_media.py` is intentionally not part of CI.

## Architecture

- `api.py` contains the public entry points: `analyze_file`, `analyze_bytes`, and `analyze_frames`.
- `engine.py` owns the transition state machine, synchronization, flash pairing, sliding-window counting, and fast-flash merge.
- `decode.py` isolates format decoding; `area.py` owns tiling and area qualification; `color.py` owns sRGB/linear/CIE UCS math.
- Performance paths: `area.tile_frame_uint8` returns uint8 tile averages and is what `api.py` feeds the engine; public `tile_frame` wraps it as float32. Pillow's BOX resize is the normal path; the bit-exact numpy `_box_downsample` is a tested fallback. `color.linear_rgb_features` computes luminance, redness, the saturated-red mask, and CIE UCS in one pass. `decode._alpha_composite_rgba` vectorizes Pillow's `AlphaComposite.c` formula. Keep these equivalent to their reference helpers (tests cover this).
- `standards.py` is the profile registry; `options.py` holds analysis and display assumptions; `result.py` is schema v2.
- `cli.py` is a thin wrapper. Keep the core free of platform I/O, downloads, moderation actions, and temp-file side effects.

## Gotchas

- A triggering result is evidence that the configured working values were exceeded, not a compliance or medical determination. Keep `profile_coverage="partial"` for partially implemented profiles and keep the warning in results.
- The WCAG area model assumes a 416 x 416 CSS-pixel 10-degree field and treats source pixels as CSS pixels when display geometry is unknown. Do not silently claim a more precise area calculation.
- The analysis grid is capped by `AnalysisOptions.tile_grid_max` (default 192). Fine high-frequency patterns can be averaged away; the result always warns `tile_averaging_approximation`.
- Opposing transitions are paired into flashes before the area test; area qualifies a flash for rate counting and is not an independent trigger. The changed area is the pair mask union, but the pair must also overlap (`flash_area_overlap_ratio`, default 0.30) unless the union is large (`flash_area_union_scale`, default 1.50). Those tolerances are heuristics, not normative thresholds.
- GIF frames are composited over white; Pillow does not apply disposal when converting a single frame, so `decode.py` tracks disposal explicitly. Do not switch back to `image.convert("RGB")` per frame: transparent pixels become a dark palette color and fabricate full-screen flashes.
- The decoder keeps an RGBA numpy canvas and replaces it per frame rather than mutating it; yielded `frame` arrays are views into that canvas. Do not mutate them, and do not switch to in-place canvas updates: disposal-3 snapshots and the retained first frame depend on the replace-only invariant.
- Do not replace the Pillow BOX resize normal path with the numpy fallback without benchmarking. The numpy implementation is bit-exact but roughly 5-8x slower for real downscales in this pipeline; it exists for portability and as a tested reference.
- Keep `linear_rgb_features` in sync with `linear_rgb_to_luminance`, `red_ratio`, `is_saturated_red`, and `linear_rgb_to_ucs`, and keep the sRGB LUT built with the same float32 ops as the float path. Tests assert uint8 and `value / 255` inputs agree exactly.
- A single-frame step sampled at an interval longer than the 66 ms cutoff is treated as an unresolved hard cut (`duration_ms=0`). This is deliberate recall insurance for low-frame-rate GIFs, not a measured transition duration; it can over-count a real fade that spans one coarse sample interval.
- Looping GIFs shorter than one second are repeated through enough cycles to cover roughly one second plus one cycle (`gif_loop_repeated_analysis`); longer looping GIFs get a synthetic loop-seam frame (`gif_loop_wrap_analyzed`). Synthetic frames are analysis-only and do not change the reported media duration.
- Video timestamps come from constant container frame rate, not per-frame presentation timestamps. Color management assumes sRGB; motion compensation and scene-change classification are not implemented.
- Media files are gitignored (`*.mp4`, `*.gif`); only the two list files (`examples/triggering.lst`, `examples/not-triggering.lst`) are tracked. `30.mp4` and the numbered GIFs exist locally only. Recreate them with `cd examples && ../util/download_gifs.sh triggering.lst` and `../util/download_gifs.sh not-triggering.lst` (uses `wget`, waits 5 seconds between downloads). Add media with `git add -f` only deliberately.
- CLI exit codes are `0` safe, `1` triggering, and `2` error/inconclusive. Truncated analyses set `inconclusive=True` and warn.

## Conventions

- Before changing detector thresholds or counting, read `planning/01_wcag_flash_thresholds.md` and `planning/07_source_review.md`. Default to WCAG 2.2; make profiles, display assumptions, and result schema explicit.
- Keep normative thresholds separate from the paper's working values (66 ms transition, 20 ms synchronization, 65 Hz fast-flash). Record which assumptions a result used.
- Stick to rule-based flash detection; LLM/ML and static-pattern analysis are explicitly out of scope for v1.
- Use the src layout (`src/epilepsy_warning`) and the `epilepsy-warning` / `epilepsy_warning` naming when adding packages or modules.
