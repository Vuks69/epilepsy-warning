# Implementation Plan

Goal: ship a reusable, well-tested library (Python first, Go second) that classifies GIFs and
short videos for photosensitive epilepsy triggers. The Discord bot is no longer a deliverable.

## Phase 0: Scope reset (done)
- [x] Rewrite planning docs around a library, not a bot
- [x] Move Discord concerns (intents, downloads, moderation actions) out of scope
- [x] Define consumers and non-goals
- [x] Confirm the rule-based WCAG approach

## Phase 1: Lock the contract
- [ ] Finalize `AnalysisOptions` fields, defaults, and limits
- [ ] Finalize the v1 result schema (classification, risk, reasons, measurements, metadata)
- [ ] Define typed errors and the incomplete-scan behavior
- [ ] Decide the public API surface for Python and Go
- [ ] Write the cross-language conformance fixture format
- [ ] Document supported formats and decoder requirements

## Phase 2: Python reference library
- [ ] Refactor the prototype out of `bot.py`-oriented code into a standalone package
- [ ] Remove `discord.py`, `PyNaCl`, `aiohttp`, `python-dotenv` from core dependencies
- [ ] Implement path, bytes, and caller-supplied-frame entry points
- [ ] Decode GIF with correct delays/disposal and loop wrap-around
- [ ] Decode video via `imageio`/`imageio-ffmpeg` with real timestamps
- [ ] Implement opposing-transition pairing (not frame-difference counting)
- [ ] Implement sliding one-second windows using timestamps
- [ ] Implement per-cell flashing-area estimation with a documented field approximation
- [ ] Implement perceptual saturated-red detection
- [ ] Add resource limits, timeouts, and typed errors
- [ ] Fill in the result model and version metadata
- [ ] Add full type annotations and `py.typed`
- [ ] Replace the current CLI with a thin wrapper over the library

## Phase 3: Python quality and packaging
- [ ] Build the regression corpus: `4882.mp4`, `giphy/*.gif`, and negative fixtures
- [ ] Add unit tests for luminance, pairing, windowing, area, red detection, and limits
- [ ] Add golden/conformance tests with expected classifications
- [ ] Add property tests for determinism, monotonic thresholds, and frame-rate invariance
- [ ] Add benchmark/performance budget tests
- [ ] Configure ruff, mypy, pytest, and coverage in CI
- [ ] Publish to PyPI (`epilepsy-warning`) with docs and changelog
- [ ] Document library usage (not bot usage) in the README

## Phase 4: Go port
- [ ] Create the Go module with the same public API shape
- [ ] Implement luminance, pairing, windowing, area, and red detection
- [ ] Use stdlib GIF decoding; stream video frames from ffmpeg via `os/exec`
- [ ] Support caller-supplied frames (`AnalyzeFrames`) and context cancellation
- [ ] Run the same conformance fixtures and assert schema parity
- [ ] Add benchmarks and a small usage example (`examples/`)
- [ ] Publish a tagged module version

## Phase 5: Release hardening
- [ ] Fuzz decoders and API inputs
- [ ] Verify behavior on malformed, truncated, oversized, and high-resolution media
- [ ] Confirm no network access in the core path
- [ ] Document approximation limits and medical/safety disclaimers
- [ ] Tag `v1.0.0` for Python and Go once results agree on the corpus
- [ ] Add a sample consumer (optional): a Discord/Matrix bot in `examples/`, depending on the
      library and owning all platform-specific logic

## Immediate next steps
1. Finalize the result schema and options (Phase 1) - everything else depends on it.
2. Split the analyzer from the bot code and strip bot dependencies.
3. Fix the two highest-risk correctness gaps: real timestamps and flash-pair detection.
4. Build the golden fixture suite before starting the Go port.
