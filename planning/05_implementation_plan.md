# Implementation Plan

Goal: ship a reusable, standards-explicit library (Python first, Go second) that classifies GIFs
and short videos for photosensitive epilepsy triggers. The Discord bot is not a deliverable.

## Phase 0: Scope reset (done)
- [x] Rewrite planning docs around a library, not a bot
- [x] Move Discord concerns out of scope
- [x] Confirm the rule-based approach
- [x] Add the international-guidelines gap analysis (`07_source_review.md`)

## Phase 1: Lock the contract
- [ ] Choose the default standard profile: **WCAG 2.2 SC 2.3.1** (ISO-harmonized red)
- [ ] Define profile IDs and which profiles are fully/partially supported
- [ ] Finalize `AnalysisOptions`: thresholds, working values, display geometry, limits
- [ ] Finalize result schema v2: transitions, assumptions, profile, warnings
- [ ] Define typed errors, `inconclusive`, and truncated-scan behavior
- [ ] Define API surface for Python and Go
- [ ] Define synthetic conformance fixture format (frames + exact timestamps)
- [ ] Document supported formats, color spaces, and decoder requirements

## Phase 2: Correctness-first Python engine
- [ ] Refactor the prototype out of bot-oriented code into a standalone package
- [ ] Remove `discord.py`, `PyNaCl`, `aiohttp`, `python-dotenv` from core dependencies
- [ ] Implement path, bytes, and caller-supplied-frame entry points
- [ ] Decode GIF with correct delays/disposal and loop wrap-around
- [ ] Decode video via `imageio`/`imageio-ffmpeg` with real presentation timestamps
- [ ] Build per-tile luminance/color state tracking
- [ ] Implement the **66 ms** qualifying-transition rule
- [ ] Implement opposing-transition pairing and **6-transition / 1-second** counting
- [ ] Implement saturated-red + CIE 1976 UCS difference (>= 0.2)
- [ ] Implement **20 ms** same-direction area synchronization
- [ ] Implement the 10-degree/416x416 CSS-px area model
- [ ] Add display geometry options and explicit assumptions
- [ ] Add a standards-profile layer (WCAG first; ISO/ITU/Ofcom/Japan stubs or partial)
- [ ] Add resource limits, timeouts, typed errors, and warnings
- [ ] Fill in the result model and version metadata
- [ ] Add full type annotations and `py.typed`
- [ ] Replace the CLI with a thin wrapper and add `--standard`/display flags

## Phase 3: Python verification and packaging
- [ ] Build synthetic timing fixtures for every boundary in `04_architecture.md`
- [ ] Build negative fixtures (slow fades, small areas, pans, running feet, cuts)
- [ ] Add unit tests for color, transitions, pairing, synchronization, windowing, area
- [ ] Add golden media tests (`4882.mp4`, `giphy/*.gif`)
- [ ] Add property tests for determinism, monotonicity, and frame-rate invariance
- [ ] Add benchmarks at 24/30/60/120 fps and a performance budget
- [ ] Configure ruff, mypy, pytest, coverage in CI
- [ ] Publish to PyPI (`epilepsy-warning`) with docs and changelog
- [ ] Rewrite README usage for the stable library API

## Phase 4: Modern-content features (P1)
- [ ] HDR/reference-luminance mode (PQ/HLG, 200 cd/m² default, theater 48 cd/m²)
- [ ] Color-space metadata detection via ffprobe/ffmpeg; explicit warnings when missing
- [ ] **65 Hz** fast-flash merge and mixed-rate guard
- [ ] ISO/ITU-R/Ofcom profiles; Japan profile after that
- [ ] Scene-change/inversion classification for broadcast profiles
- [ ] Analyze at the largest expected display size; VR/FOV geometry support
- [ ] Optional advisory `extended_exposure` (5+ s near-limit, no normative threshold)

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
1. Finalize schema v2 and the standards-profile contract.
2. Separate the analyzer from the bot and remove bot dependencies.
3. Replace frame-difference counting with the 66 ms transition state machine.
4. Implement the 6-transition limit and WCAG 2.2 red test.
5. Build the synthetic fixture suite before touching the Go port.
