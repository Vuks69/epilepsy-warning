# Summary

## Scope change

The project was originally planned as a Discord bot. The reusable value is the detection engine,
so the scope is now a **code library for Python and Go projects**. The bot is optional example
code and owns all platform-specific concerns (intents, downloads, moderation actions, cleanup).

## What we know

1. Detection maps to the PSE standards' common structure: alternating transitions, critical
   luminance/color difference, qualifying duration, synchronized area, and rate limits.
2. Rule-based analysis is fast, deterministic, offline, and explainable. LLM/ML is out of scope.
3. The existing Python prototype flags the known examples, proving the approach, but its counting
   and area logic are not standards-correct.
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

- Planning docs now describe a standards-explicit library, API, schema v2, packaging, and a
  Python-first / Go-second plan.
- The prototype in `src/` still contains the original bot and a rough analyzer. It needs a
  refactor into a standalone package and a transition-based rewrite.

## Known gaps to close before v1

- Frame-difference counting (factor-of-two error against the 6-transition limit)
- Real frame timestamps instead of an assumed 30 fps
- 66 ms transition duration and per-tile state tracking
- 20 ms area synchronization
- Spatial 10-degree-field area model instead of a whole-frame average
- WCAG 2.2 red test with CIE 1976 UCS
- Standards profiles, display assumptions, and HDR/reference luminance
- GIF loop wrap-around
- Typed errors, resource limits, and timeouts for untrusted input
- Motion compensation and extended-exposure advisory (P2, not v1 blockers)

## Deliverables

- Python package `epilepsy-warning` (PyPI), importable as `epilepsy_warning`
- Go module with the same API shape and schema v2
- Thin `epilepsy-scan` CLI with standard/display options
- Shared synthetic + media fixture corpus and conformance tests
- Documentation: usage, standards profiles, thresholds, assumptions, limitations
- Optional example consumer (e.g. a Discord bot) that depends on the library

## Next steps

1. Finalize schema v2 and the standards-profile contract.
2. Refactor the analyzer into a standalone Python library.
3. Replace frame-difference counting with timed transitions and the 6-transition limit.
4. Implement WCAG 2.2 red and the 416x416 CSS-px area model.
5. Build the synthetic corpus, then add HDR/profiles, then port to Go.
