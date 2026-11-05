# Implementation Plan

Goal: ship a reusable, standards-explicit library (Python first, Go second) that classifies GIFs
and short videos for photosensitive epilepsy triggers. The Discord bot is not a deliverable.

Checkbox legend: `[x]` done, `[ ]` not started, `[~]` partially implemented (some pieces done,
noted in-line).

## Phase 0: Scope reset (done)
- [x] Rewrite planning docs around a library, not a bot
- [x] Move Discord concerns out of scope
- [x] Confirm the rule-based approach
- [x] Add the international-guidelines gap analysis (`07_source_review.md`)

## Phase 1: Lock the contract
- [x] Choose the default standard profile: **WCAG 2.2 SC 2.3.1** (ISO-harmonized red)
- [x] Define profile IDs and which profiles are fully/partially supported
- [x] Finalize `AnalysisOptions`: thresholds, working values, display geometry, limits
- [x] Finalize result schema v2: transitions, assumptions, profile, warnings
- [x] Define typed errors, `inconclusive`, and truncated-scan behavior
- [x] Define API surface for Python and Go
- [x] Define synthetic conformance fixture format (frames + exact timestamps)
- [x] Document supported formats, color spaces, and decoder requirements

## Phase 2: Correctness-first Python engine
- [x] Refactor the prototype out of bot-oriented code into a standalone package
- [x] Remove `discord.py`, `PyNaCl`, `aiohttp`, `python-dotenv` from core dependencies
- [x] Implement path, bytes, and caller-supplied-frame entry points
- [x] Decode GIF with correct delays/disposal and loop wrap-around
  - short looping GIFs repeat enough cycles to cover the one-second window; longer clips get a
    loop-seam frame; both are marked synthetic and warned about
- [x] Decode video via `imageio`/`imageio-ffmpeg`
  - uses the constant container frame rate; per-frame presentation timestamps are not exposed by
    the decoder and are reported with `video_timestamps_from_constant_fps`. A fallback rate is
    assumed (and warned) only when the container reports none. This is the only open item here.
- [x] Build per-tile luminance/color state tracking
- [x] Implement the **66 ms** qualifying-transition rule
- [x] Implement opposing-transition pairing and **6-transition / 1-second** counting
- [x] Implement saturated-red + CIE 1976 UCS difference (>= 0.2)
- [x] Implement **20 ms** same-direction area synchronization
- [x] Implement the 10-degree/416x416 CSS-px area model
  - small unknown-display sources clamp the assumed field to the source and use stronger
    overlap/frame-coverage guards below the base threshold (heuristic, recorded in assumptions)
- [x] Add display geometry options and explicit assumptions
- [x] Add a standards-profile layer (WCAG first; ISO/ITU/Ofcom/Japan stubs or partial)
- [x] Add resource limits, timeouts, typed errors, and warnings
- [x] Fill in the result model and version metadata
- [x] Add full type annotations and `py.typed`
- [x] Replace the CLI with a thin wrapper and add `--standard`/display flags

## Phase 3: Python verification and packaging
- [x] Build synthetic timing fixtures for the transition/area/red/fast-flash boundaries
  - covered by `tests/test_engine.py`: 6 vs 7 transitions, slow fade not counted, 66 ms counted,
    coarse-step -> `duration_ms=0`, small vs large area, saturated-red counted separately,
    65 Hz merge, disjoint vs overlapping motion edges, and small-source clamping. Not every
    boundary in `04_architecture.md` has a fixture (e.g. 20 ms sync boundary, 65 Hz mixed-rate,
    SDR/HDR luminance boundaries, display-geometry area).
- [x] Build negative fixtures for the decoder path
  - covered by `tests/test_media.py`: GIF loop repeat, transparent GIF composited over white,
    disposal-3 canvas restore, static image safe, video bytes rejected, byte limit enforced.
    Synthetic pans/cuts and scene-cut negatives are still open.
- [x] Add unit tests for color, transitions, pairing, synchronization, windowing, area
- [x] Add automated golden media tests (`examples/triggering/*`, `examples/not-triggering/*`)
  - covered by `tests/test_golden_media.py`: verdict + schema/annotation regression over the real
    media cache. The `.lst` files are the tracked source of truth and the media is gitignored, so
    this module downloads any missing files (throttled, like `util/download_gifs.sh`) and reuses
    them across runs. It asserts every `triggering.lst` fixture reports `TRIGGERING` and every
    `not-triggering.lst` fixture stays safe, and that results are not `inconclusive` and carry the
    standing warnings. An opt-in short-circuit equivalence check (`EPILEPSY_GOLDEN_EQUIP=1`)
    toggles `TransitionEngine._enable_short_circuit` over the real decode path and asserts an
    identical measured surface.
- [x] Add property tests for determinism, monotonicity, and frame-rate invariance
  - covered by `tests/test_property.py`: property (Hypothesis) tests over synthetic clips rather
    than exemplar fixtures. Determinism asserts `analyze_frames` produces byte-identical
    `to_json()`/`to_dict()` across two fresh analyses (the result is a frozen dataclass with no
    global RNG, so this guards against dict/set/float nondeterminism). Monotonicity encodes three
    directed, all-else-equal invariants that never claim "bigger -> safe": a qualifying transition
    stays qualifying as its critical-difference step grows, a qualifying flash stays qualifying as
    both masks scale up uniformly (the area guard rejects lopsided changes), and a triggering clip
    stays triggering as more valid alternating transitions are added. Frame-rate invariance
    asserts densifying a clip by repeating frames at interpolated timestamps preserves the verdict
    and `luminance_transitions` / `red_transitions` / `max_flashes_per_second` /
    `max_luminance_transitions_per_second`, while leaving `max_transition_duration_ms` free (a
    coarse single-frame step reads as 0 ms at low density, resolves to a real duration when more
    samples bracket it).
- [x] Add benchmarks at 24/30/60/120 fps and a performance budget
   - covered by `tests/test_performance.py`: a relative (regression) guard, not an absolute wall.
     Per-frame `analyze_frames` cost over a deterministic two-tone 2 s clip is measured (`min` over
     7 repeats) at each rate and asserted that the busiest rate stays within
     `PER_FRAME_COST_GUARD_FACTOR` (3.0×) of the cheapest. This is machine-independent: machine
     speed cancels in a ratio of two same-machine timings, and the 3.0× band leaves ~60% of
     headroom above the observed worst-case ~1.85× (120 fps vs 24 fps per-frame), which is the
     legitimate per-frame growth from the `_history` 66 ms window holding more entries at higher
     fps. Synthetic and no media cache, so it runs anywhere (~1.6 s, no network).
- [ ] Configure ruff, mypy, pytest, coverage in CI
- [ ] Publish to PyPI (`epilepsy-warning`) with docs and changelog
- [x] Rewrite README usage for the stable library API

Current test posture: stdlib `unittest`, 75 test methods in `tests/` (color, area, engine, media,
cli, golden-media, property, performance); no pytest, no CI, no benchmarks. `ruff` is configured
and the package is editable-installed in `.venv`. `hypothesis>=6.0` is a dev dependency driving the
property module. The golden-media module (3 methods) is network-backed: it runs from the cached
`examples/triggering/*` / `examples/not-triggering/*` media and skips the short-circuit equivalence
check unless `EPILEPSY_GOLDEN_EQUIP=1`. The property module is fully synthetic, so it needs no
media cache and stays fast (6 methods, ~3-4 s); the performance guard is synthetic too and adds
~1.6 s.

## Phase 4: Modern-content features (P1)
- [~] Relative-luminance `cd_m2` mode is implemented for the broadcast profiles (SDR: >=20 cd/m²
  change when darker state <160 cd/m²; HDR: Michelson contrast >= 1/17 when darker state
  >=160 cd/m²), with a configurable `reference_luminance_cd_m2` (default 200). PQ/HLG transfer
  functions and wide-gamut handling are not yet done (color is always assumed sRGB).
- [ ] Color-space metadata detection via ffprobe/ffmpeg; explicit warnings when missing. Color is
  always assumed sRGB and reported with `color_space_assumed_srgb`.
- [x] **65 Hz** fast-flash merge and mixed-rate guard
- [x] ISO/ITU-R/Ofcom profiles; `nhk-jba` (Japan) is registered as not implemented/rejected
- [ ] Scene-change/inversion classification for broadcast profiles
- [~] Known display geometry is supported: `DisplayGeometry` maps screen diagonal + viewing
  distance to a 10-degree field; the default remains the 416x416 CSS-px assumption.
- [x] Optional advisory `extended_exposure` (5+ s near-limit, no normative threshold)

## Phase 5: Go port
- [ ] Create the Go module with the same public API shape and schema v2
- [ ] Port color math, transition state machine, pairing, synchronization, area model
- [ ] Use stdlib GIF decoding; stream video frames from ffmpeg via `os/exec`
- [ ] Support caller-supplied frames (`AnalyzeFrames`) and context cancellation
- [ ] Run the same synthetic and media conformance fixtures
- [ ] Add benchmarks and a usage example (`examples/`)
- [ ] Publish a tagged module version

## Phase 6: Research and release hardening (P2)
- [ ] Fuzz decoders and API inputs
- [ ] Verify malformed, truncated, oversized, and high-resolution media
- [ ] Prototype motion compensation (deferred; not a v1 blocker)
  - Estimate global/local motion before the area test (e.g. block matching or phase
    correlation), warp the previous tile field, and treat luminance/color changes explained by
    the estimated motion as non-flash residuals. Keep the existing transition engine as the
    source of truth; compensation is a pre-filter, not a replacement detector.
  - Keep it opt-in (`motion_compensation=False` by default) and record the estimator, search
    range, residual threshold, and any frames the warp could not explain in assumptions/warnings.
  - Build a labelled motion fixture set (pans, trains, running feet, shaking objects, camera
    shake) from both `examples/triggering` and `examples/not-triggering`; do not tune only on the
    triggering list.
  - Measure both false-positive reduction and recall loss. A useful prototype must reduce benign
    motion flags without dropping real flashes; report the before/after matrix rather than a
    single accuracy number.
  - Do not make motion compensation a default or claim standards coverage until the public
    thresholds and evaluation corpus are defensible. ITU-R/HardingFPA-style compensation has no
    public normative thresholds.
- [ ] Investigate static pattern analysis as a separate detector
- [ ] Evaluate real-time/generated-content support
- [ ] Document approximation limits and medical/safety disclaimers
- [ ] Tag `v1.0.0` for Python and Go once results agree on the corpus
- [ ] Add an optional sample consumer (Discord/Matrix) in `examples/`

## Immediate next steps
1. ~~Configure a CI workflow (unit tests + golden-media + property tests)~~ (done; synthetic suite + ruff. Golden media deferred out of CI — see CI note.)
2. Decode real video presentation timestamps and color metadata; keep HDR warnings explicit.
3. ~~Add benchmarks at 24/30/60/120 fps and a performance budget~~ (done; `tests/test_performance.py`,
   relative per-frame-cost guard, see Phase 3).
4. Validate the area/grid approximation against larger synthetic fixtures and pans/cuts.
5. Port the engine to Go once the Python schema and fixtures are stable.

CI note (`.github/workflows/ci.yml`): runs the synthetic suite — unit tests, the Phase-3
short-circuit equivalence test, the property tests, and the per-frame-cost guard — across a Python
3.9/3.12/3.14 matrix, plus `ruff check`/`format`; intentionally network-free. The hosted-fixture
regression (`tests/test_golden_media.py`) is **deferred** out of CI and runs local-only with
`EPILEPSY_GOLDEN_EQUIP=1`: it needs the gitignored media cache plus a third-party CDN, and GitHub
runners are ephemeral (nothing persists between runs). Reintroducing golden in CI needs an
`actions/cache` step keyed on the two `.lst` file hashes so the downloaded fixtures persist (it
then only redownloads when the fixture list changes). Caveat: the giphy/tenor controls are
third-party and can expire or rate-limit, so a golden job carries a media flakiness risk
independent of caching.
