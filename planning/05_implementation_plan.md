# Implementation Plan

Goal: ship a reusable, standards-explicit library (Python first, Go second) that classifies GIFs
and short videos for photosensitive epilepsy triggers. The Discord bot is not a deliverable.

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
- [ ] Decode video via `imageio`/`imageio-ffmpeg` with real presentation timestamps
  - current: constant container frame rate, warned in results
- [x] Build per-tile luminance/color state tracking
- [x] Implement the **66 ms** qualifying-transition rule
- [x] Implement opposing-transition pairing and **6-transition / 1-second** counting
- [x] Implement saturated-red + CIE 1976 UCS difference (>= 0.2)
- [x] Implement **20 ms** same-direction area synchronization
- [x] Implement the 10-degree/416x416 CSS-px area model
- [x] Add display geometry options and explicit assumptions
- [x] Add a standards-profile layer (WCAG first; ISO/ITU/Ofcom/Japan stubs or partial)
- [x] Add resource limits, timeouts, typed errors, and warnings
- [x] Fill in the result model and version metadata
- [x] Add full type annotations and `py.typed`
- [x] Replace the CLI with a thin wrapper and add `--standard`/display flags

## Phase 3: Python verification and packaging
- [x] Build synthetic timing fixtures for every boundary in `04_architecture.md`
- [x] Build negative fixtures (slow fades, small areas, pans, running feet, cuts)
  - covered: slow fades, small areas, GIF transparency/disposal, camera/object motion;
    synthetic pans/cuts still open
- [x] Add unit tests for color, transitions, pairing, synchronization, windowing, area
- [ ] Add automated golden media tests (`examples/triggering/*`, `examples/not-triggering/*`)
- [ ] Add property tests for determinism, monotonicity, and frame-rate invariance
- [ ] Add benchmarks at 24/30/60/120 fps and a performance budget
- [ ] Configure ruff, mypy, pytest, coverage in CI
- [ ] Publish to PyPI (`epilepsy-warning`) with docs and changelog
- [x] Rewrite README usage for the stable library API

## Phase 4: Modern-content features (P1)
- [ ] HDR/reference-luminance mode (PQ/HLG, 200 cd/m² default, theater 48 cd/m²)
- [ ] Color-space metadata detection via ffprobe/ffmpeg; explicit warnings when missing
- [x] **65 Hz** fast-flash merge and mixed-rate guard
- [x] ISO/ITU-R/Ofcom profiles; Japan profile after that
- [ ] Scene-change/inversion classification for broadcast profiles
- [ ] Analyze at the largest expected display size; VR/FOV geometry support
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
- [ ] Prototype motion compensation; measure false-positive reduction on real pans/trains
- [ ] Investigate static pattern analysis as a separate detector
- [ ] Evaluate real-time/generated-content support
- [ ] Document approximation limits and medical/safety disclaimers
- [ ] Tag `v1.0.0` for Python and Go once results agree on the corpus
- [ ] Add an optional sample consumer (Discord/Matrix) in `examples/`

## Immediate next steps
1. Add automated golden media tests and a CI workflow.
2. Decode real video presentation timestamps and color metadata; keep HDR warnings explicit.
3. Add property tests (determinism, frame-rate invariance) and benchmarks.
4. Validate the area/grid approximation against larger synthetic fixtures and pans/cuts.
5. Port the engine to Go once the Python schema and fixtures are stable.
