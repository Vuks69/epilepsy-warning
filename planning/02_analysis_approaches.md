# Analysis Approaches for Detecting Photosensitive Triggers

The detector must be fast, deterministic, offline, and implementable in both Python and Go.
The approach must also be precise enough to defend a moderation/safety decision.

## 1) Timed-transition analysis (recommended)

This is the approach used by broadcast tooling such as HardingFPA and PEAT. It follows the
standards' actual structure: transitions -> opposing pairs -> synchronized areas -> rate/area
checks.

Core idea:
- Decode frames with per-frame timestamps (or accept caller-supplied frames)
- Compute relative luminance and perceptual color per pixel or tile
- Track state changes per tile over time, not just adjacent-frame differences
- Form transitions that cross the critical luminance/color difference within 66 ms
- Pair opposing transitions into flashes
- Sum same-direction areas that occur within 20 ms
- Count transitions in sliding 1-second windows
- Evaluate the area rule for the active standards profile
- Apply fast-flash merging for 65 Hz+ sequences
- Return reasons, measurements, profile, and assumptions

Pros:
- Matches the physical structure of WCAG/ISO/ITU/Ofcom/Japan rules
- Deterministic, explainable, and cheap enough for interactive use
- Handles multi-frame transitions and high-frame-rate content
- Directly maps to a standards profile and conformance tests

Cons:
- More state to track than frame differencing (per-tile timestamps and area maps)
- Sensitive to decode timing and color-space correctness
- Motion, scene cuts, and camera pans can create false positives without compensation
- Japan profile rules are substantially more complex

This is the required v1 approach; the prototype's frame-difference heuristic is not sufficient.

## 2) Histogram/HSV change detection

- Track rapid changes in brightness (value) or saturation histograms
- Detect high-frequency oscillation

Pros:
- Simple and cheap
- Robust to small spatial shifts

Cons:
- Cannot identify opposing transitions, timing, or area
- Higher false-positive rate on motion and scene cuts
- Does not produce standards-aligned evidence

Use only as a coarse pre-filter, never as the classifier.

## 3) ML/classification

Rejected for v1. Labeled data is limited, decisions are opaque for a safety feature, inference is
slower and harder to ship in two languages, and the thresholds are already specified by standards.
Revisit only as an optional supplementary signal with a proper evaluation set.

## Standards strategy

Implement one engine with a **standards profile**:

- `wcag22`: WCAG 2.2 SC 2.3.1, ISO-harmonized red (default)
- `iso9241-391`: ISO profile, including the 65 Hz upper limit if applicable
- `itu-r-bt1702` / `ofcom`: SDR/HDR thresholds, leading-edge pacing qualification
- `nhk-jba`: Japan's area/contrast-dependent rates and scene-change rules
- `custom`: explicit thresholds for research

Keep the common engine; profiles alter thresholds, counting, and area assumptions. Do not claim
cross-standard compliance.

## Required engine capabilities

### Timing and transitions

- Per-frame timestamps/durations; never assume 30 fps.
- Per-tile luminance/color state with the time the state began.
- Transitions qualify only if the critical difference is reached within 66 ms.
- Record transition start, direction, kind, duration, and area.
- Handle variable frame rate and dropped/duplicated frames.

### Area and synchronization

- Per-tile changed-area map, not a whole-frame average.
- Sum adjacent/nearby same-direction areas within 20 ms.
- Normalize to a 10-degree field using CSS pixels (416 x 416 subareas by default) or known
  display geometry.
- Keep a broadcast `screen_fraction` model behind an explicit profile.

### Luminance and color

- sRGB relative luminance by default.
- Explicit reference luminance and color space; HDR/PQ/HLG support in P1.
- Saturated red via linear `R/(R+G+B) >= 0.8`.
- Red difference via CIE 1976 UCS distance >= 0.2.
- Count red and luminance transitions independently; one transition can be both.

### High-frame-rate handling

- Merge fast flashes whose leading edges are <= 15 ms apart.
- Do not let mixed-rate bursts pass; check the 65 Hz rule over the actual sequence.
- Add synthetic tests at 24, 30, 50, 60, and 120 fps.

### Motion and scene changes

- Classify inversions/scene changes for broadcast profiles.
- Add optional motion compensation as an experimental pre-filter; collect false-positive
  fixtures (pans, running feet, trains, shaking objects).
- Candidate approach: estimate a global translation (block matching or phase correlation), warp
  the previous tile field, and require a transition to survive a residual test. Local/object
  motion may need per-region estimates later; start with a single global estimate and record
  when it fails.
- Evaluate on both triggering and benign fixtures. Compensation that hides real flashes is worse
  than the current overlap heuristic; keep the function opt-in and report the recall/precision
  trade-off explicitly.
- No public motion thresholds exist; do not make it a default.

## Out of scope for v1

- Static bold-pattern analysis (separate detector later)
- Display-induced flicker (CRT/PWM/backlight)
- Real-time stream analysis and frame modification/filtering
- Medical diagnosis or individualized risk prediction

## Implementation status (Python `0.2.0`)

The required v1 approach is implemented in the `epilepsy_warning` package:
timed transitions -> opposing pairs -> 20 ms area synchronization -> sliding 1 s window ->
fast-flash merge, with per-tile state, the 416x416 CSS-px area model, and a standards-profile
layer. The old frame-difference prototype and its Discord bot are gone.

Covered now:
- Transition-based counting (6 transitions = 3 flashes); luminance and red counted separately.
- 66 ms qualifying-transition rule, including the coarse-step (unresolved single-frame step ->
  `duration_ms=0`) rule for low-frame-rate GIFs.
- CIE 1976 UCS >= 0.2 red-difference test plus the linear `R/(R+G+B) >= 0.8` saturation test.
- 20 ms same-direction area synchronization and the local-extremum fade rejection.
- 10-degree / 0.006 sr area model, normalized to a 416x416 CSS-px field; small-source clamping
  with stronger overlap/frame-coverage guards below the base threshold (heuristics, recorded).
- 65 Hz fast-flash merge (on by default) with a mixed-rate guard.
- Standards profiles: `wcag22`, `iso9241-391`, `itu-r-bt1702`, `ofcom` (all partial),
  `nhk-jba` (not implemented/rejected), `custom`.
- Relative-luminance `cd_m2` model for the broadcast profiles (SDR 20 cd/m² change and
  Michelson >= 1/17 HDR branches); display geometry (`DisplayGeometry`) for known screens.
- GIF decoding with delays, disposal (2/3), loop-repeat for <1 s clips, and a loop-seam frame;
  RGBA composited over white so transparent pixels do not fabricate flashes.
- Typed errors, resource limits (`max_bytes`/`max_duration_seconds`/`max_frames`/`max_pixels`),
  `analysis_timeout_seconds`, and explicit `inconclusive`/truncation.
- Structured result schema v2 with profile, working values, assumptions, warnings, measurements.

Still open (tracked in `05_implementation_plan.md`):
- Scene-change/inversion classification for broadcast profiles (not implemented; WCAG default
  documents that it does not classify these).
- Motion compensation (experimental pre-filter, opt-in, no public thresholds).
- PQ/HLG transfer-function and wide-gamut color handling; color-space metadata detection is not
  done (color is always assumed sRGB and reported as such).
- Static bold-pattern analysis (separate detector, later).
- Automated golden-media tests, property tests, benchmarks, and CI.
- The native Go port.

These are tracked in `05_implementation_plan.md`; the source rationale is in
`07_source_review.md`.
