# Summary

## Scope change

The project was originally planned as a Discord bot. The reusable value is the detection engine,
so the scope is now a **code library for Python and Go projects**. The bot is optional example
code and owns all platform-specific concerns (intents, downloads, moderation actions, cleanup).

## What we know

1. Detection maps to the PSE standards' common structure: alternating transitions, critical
   luminance/color difference, qualifying duration, synchronized area, and rate limits.
2. Rule-based analysis is fast, deterministic, offline, and explainable. LLM/ML is out of scope.
3. The Python library flags the known examples and implements the standards-correct approach
   (timed transitions, opposing pairs, 20 ms area synchronization, 416x416 CSS-px area model,
   WCAG 2.2 red). It is not the frame-difference prototype any more.
4. A native Python library plus a native Go port, aligned by schema v2 and shared fixtures, is
   simpler to distribute than FFI or a subprocess bridge.
5. The five major standards are similar but not interchangeable; the library must name its
   standard profile and assumptions. See `07_source_review.md`.

## Correctness changes from the gap-analysis paper

- Count **qualifying transitions**, not frame differences. Limit is 6 transitions (3 flashes) per
  second; 7 transitions fail.
- A transition must cross the threshold within **66 ms** (working value); slow fades do not count.
- Sum same-direction areas within **20 ms** (working value), especially at 50+ fps.
- Use the **WCAG 2.2 / ISO 2023 red definition**: linear `R/(R+G+B) >= 0.8` plus a CIE 1976 UCS
  difference >= 0.2.
- Normalize area to a **10-degree field**: 0.006 sr, or 25% of any 416x416 CSS-px subarea by
  default. "25% of the frame" is not the WCAG rule.
- Make reference luminance and display geometry explicit; support HDR/Michelson 1/17 in P1.
- Merge fast flashes at **65 Hz** (leading edges <= 15 ms) and guard against mixed-rate bursts.
- Default to WCAG 2.2; add ISO/ITU-R/Ofcom/Japan as explicit profiles, never a single universal
  compliance claim.

## Current state

- Planning docs describe a standards-explicit library, API, schema v2, packaging, and a
  Python-first / Go-second plan. That is now what the code is.
- The reusable library is implemented in `src/epilepsy_warning/` at version `0.2.0`: `api.py`
  (entry points), `engine.py` (transition state machine, pairing, synchronization, windowing,
  fast-flash merge), `decode.py` (GIF/video/caller-frame decoding), `area.py` (tiling + area
  model), `color.py` (sRGB/linear/CIE UCS, fused features), `standards.py` (profile registry),
  `options.py`, `result.py` (schema v2), `cli.py`, typed `errors.py`. The original Discord bot
  and the frame-difference prototype are gone.
- The default profile is `wcag22`; `iso9241-391`, `itu-r-bt1702`, `ofcom` are partial,
  `nhk-jba` is rejected, and `custom` is available.
- The Go port is still planned and not started.

## Known gaps closed in the library

- Transition-based counting (6 transitions = 3 flashes) instead of frame differences.
- Real per-frame timestamps from GIF delays / the container frame rate, not an assumed 30 fps.
- 66 ms qualifying-transition rule with per-tile state tracking.
- 20 ms same-direction area synchronization.
- Spatial 10-degree-field area model (0.006 sr), not a whole-frame average.
- WCAG 2.2 red test with CIE 1976 UCS.
- Standards profiles, display assumptions, and a relative-luminance `cd_m2` model (SDR +
  Michelson 1/17 HDR branches).
- GIF loop wrap-around (repeat for <1 s clips, loop-seam frame).
- Typed errors, resource limits, timeouts, and explicit truncation for untrusted input.

## Known gaps not yet closed

- PQ/HLG transfer functions and wide-gamut handling; color metadata is not read (assumed sRGB).
- Scene-change/inversion classification for broadcast profiles.
- Motion compensation (experimental, opt-in, no public thresholds).
- Static bold-pattern analysis (separate detector, later).
- Automated testing: benchmarks and CI remain; golden-media and property tests are done.
- The Go port.

## Deliverables

- Python package `epilepsy-warning` (importable as `epilepsy_warning`); implemented at
  `0.2.0`, not yet published to PyPI.
- Go module with the same API shape and schema v2 — planned, not started.
- Thin `epilepsy-scan` CLI with standard/display options.
- Synthetic + media fixture corpus with `unittest` coverage; golden-media regression tests and
  property tests are done.
- Documentation: usage, standards profiles, thresholds, assumptions, limitations.
- Optional example consumer (e.g. a Discord bot) that depends on the library — not yet shipped.

## Next steps

1. Finalize schema v2 and the standards-profile contract.
2. Refactor the analyzer into a standalone Python library.
3. Replace frame-difference counting with timed transitions and the 6-transition limit.
4. Implement WCAG 2.2 red and the 416x416 CSS-px area model.
5. Build the synthetic corpus, then add HDR/profiles, then port to Go.
