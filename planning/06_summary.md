# Summary

## Scope change

The project was originally planned as a Discord bot. The reusable value is the detection engine,
so the scope is now a **code library for Python and Go projects**. The bot is optional example
code and owns all platform-specific concerns (intents, downloads, moderation actions, cleanup).

## What we know

1. Photosensitive epilepsy detection maps cleanly to WCAG 2.1 SC 2.3.1: opposing luminance
   changes, flash rate per second, red flashes, and flashing area.
2. Rule-based analysis is fast, deterministic, offline, and explainable. LLM/ML is out of scope.
3. The existing Python prototype already flags the known examples (`4882.mp4`, `giphy/*.gif`),
   proving the approach.
4. A native Python library plus a native Go port, kept aligned by a shared result schema and
   conformance fixtures, is simpler to distribute than FFI or a subprocess bridge.

## Current state

- Planning docs now describe a library, its public API, result schema, packaging, and a
  Python-first / Go-second delivery plan.
- The prototype in `src/` still contains the original bot and a rough analyzer. It needs a
  refactor into a standalone package.

## Known correctness gaps to close before v1

- Real frame timestamps instead of an assumed 30 fps
- Opposing flash pairs instead of raw frame differences
- Spatial flashing-area estimation instead of a whole-frame average
- Perceptual saturated-red detection instead of an RGB ratio heuristic
- GIF loop wrap-around handling
- Typed errors, resource limits, and timeouts for untrusted input

## Deliverables

- Python package `epilepsy-warning` (PyPI), importable as `epilepsy_warning`
- Go module with the same API shape and result schema
- Thin `epilepsy-scan` CLI
- Shared fixture corpus and conformance tests
- Documentation: usage, supported formats, thresholds, approximations, and limitations
- Optional example consumer (e.g. a Discord bot) that depends on the library

## Next steps

1. Finalize options and the v1 result schema.
2. Refactor the analyzer into a standalone Python library and remove bot dependencies.
3. Fix timing, flash-pair, area, and red-detection correctness.
4. Build the golden corpus, then port to Go and verify parity.
5. Publish v1 for both languages.
