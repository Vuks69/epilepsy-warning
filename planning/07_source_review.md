# Source Review: International PSE Guidelines Gap Analysis

Source: Gregg C. Vanderheiden et al., *International Guidelines for Photosensitive Epilepsy:
Gap Analysis and Recommendations*, ACM, DOI `10.1145/3694790`
(local copy: `planning/guidelines_photo_epilepsy.txt`).

This is a comparison of the five major PSE standards (WCAG, ISO 9241-391, ITU-R BT.1702,
Ofcom, and NHK/JBA Japan) plus proposed updates. It is **not itself a standard**. Normative
thresholds and the paper's "working values" must be kept distinct in the implementation.

## Why it matters

The plan before this review was WCAG-2.1-flavored, counted frame differences as flashes, assumed
sRGB at a fixed 0.1 luminance threshold, and approximated area per frame. The paper shows that
several of those choices are ambiguous or wrong for modern content.

## Highest-impact corrections

### 1. Count transitions, not "flashes" or frame differences

- A flash is a **pair** of opposing transitions. The standards limit flashes to **3 per second**,
  which means **no more than 6 qualifying transitions in any 1-second window**.
- Seven alternating transitions in a second (3.5 flashes) is a potential failure.
- Luminance transitions and red transitions are counted **separately**, and one transition can
  count as both.
- The current prototype appends every significant frame change and compares that count to 3,
  which is a factor-of-two error.

Plan change: make transitions the internal primitive; derive flash counts from them; expose both
`transition_counts` and `max_flashes_per_second`.

### 2. Qualifying transition duration (66 ms working value)

- No current standard defines how long a transition may take.
- At high frame rates a real flash transition can span multiple frames. Adjacent-frame
  differencing misses it; conversely, a 750 ms fade followed by three quick flashes should not
  count the fade as a flash.
- The paper proposes **66 ms** as the maximum time for a transition to reach/exceed the critical
  difference. At 24-30 fps that is 1-2 frames; at 60 fps up to 4; at 120 fps up to 8.

Plan change: track luminance/color state per cell over time and accept transitions that cross the
threshold within 66 ms. Reject slower changes. Record the working value in options/result.

### 3. Synchronized areas (20 ms working value)

- At high frame rates a large flashing area may transition over two or more frames.
- Areas transitioning in the same direction within **20 ms** should be summed for the area test.
- At 24-30 fps this degenerates to frame-by-frame analysis; it matters at 50+ fps.

Plan change: add a 20 ms synchronization window when accumulating area, and record it in the
result.

### 4. Fast-flash exception (65 Hz)

- ISO treats flashing at **65 flashes/s or faster** as low risk; the paper proposes merging fast
  flashes whose leading edges are 15 ms or less apart. Merge all transitions in the same direction
  into one, so the fast sequence counts as **two transitions total** (one per direction).
- Naive counting would flag very high frame-rate content incorrectly.
- The paper warns against mixed-rate content where a 50 Hz burst plus a faster burst totals 65+
  flashes in a second.

Plan change: implement the merge rule as an option, enabled for high-frame-rate content; count a
merged fast sequence as two transitions total (one per direction). Add synthetic tests for mixed
rates. Do not use it to bypass the rate check at lower frequencies.

### 5. Red-flash definition changed in 2023

- Current ISO and WCAG 2.2 (and the 2023 update to WCAG 2.1) define saturated red as
  `R_lin / (R_lin + G_lin + B_lin) >= 0.8` using linear, gamma-expanded channels.
- A red transition requires a color difference of **>= 0.2 in CIE 1976 UCS** between a saturated
  red state and another state, regardless of luminance.
- The older WCAG 2.0/2.1 color-difference equation is not equivalent and is more conservative in
  some cases. The previous plan's RGB-ratio heuristic is only the saturation half of the test.

Plan change: implement both the saturated-red test and the CIE 1976 UCS color-difference test.
State the WCAG version in the result.

### 6. Luminance thresholds depend on reference luminance and HDR

- WCAG: >= 0.1 relative luminance change when the darker state is < 0.8 relative luminance.
- ISO/ITU/Ofcom SDR: >= 20 cd/m² change when the darker state is < 160 cd/m², assuming a
  200 cd/m² reference white.
- HDR: when the darker state is >= 160 cd/m², use Michelson contrast >= 1/17.
- The paper notes theater viewing at 48 cd/m² reference white implies a 4.8 cd/m² threshold.
- A library cannot know the display or ambient conditions from the file alone.

Plan change: keep sRGB relative luminance as the default, but model `reference_luminance` and
`color_space`/`transfer` explicitly. Add an HDR-aware mode. Return the assumptions used.

### 7. Area must be normalized to a 10-degree field, not a frame fraction

- WCAG: 0.006 steradians within **any** 10-degree field (25% of that field).
- For unknown screen type/size, the paper proposes 25% of any **416 x 416 CSS px** subarea,
  where one CSS px subtends 0.0213 degrees. A 10-degree circle is ~470 CSS px in diameter.
- Broadcast standards use 25% of the screen, which is less conservative and is not equivalent.
- Content should be analyzed at the largest expected display size.

Plan change: implement a tiled area model with configurable display assumptions
(`screen_size`, `viewing_distance`, `fov`, or the 416x416 CSS-px default). Keep
`screen_fraction` as an explicit broadcast-profile option, never as the WCAG default.

## Standards profiles

The five standards are similar but not interchangeable:

- WCAG/ISO: 20 cd/m² or 0.1 relative luminance; 0.006 sr area; 3 flashes/s.
- ITU-R/Ofcom: same core, but allow a leading-edge spacing qualification of 334-360 ms.
- NHK/JBA Japan: area- and contrast-dependent rates; 5 flashes/s for moderate 10-20% changes for
  up to 2 s, 3 flashes/s above that, stricter rules for scene changes/inversions.
- ISO: also specifies a 65 Hz upper safe limit.

Plan change: add a `standard`/`profile` option. Default to **WCAG 2.2 SC 2.3.1**, with ISO
alignment for red, and treat other profiles as explicit opt-ins. Never claim a single result is
compliant with all standards.

## Other gaps worth planning for

- **Scene changes/inversions**: treated as flashes by ISO/ITU/Ofcom and more strictly by Japan;
  WCAG does not add a separate rule. Broadcast profiles need this; WCAG default should document
  that it is not separately classified.
- **Motion compensation**: ITU-R and HardingFPA compensate for pans, running feet, trains, etc.
  before flash analysis. No public thresholds exist. Add as an experimental pre-filter, not a
  default, and collect fixtures that trigger false positives.
- **Extended exposure**: ISO/Ofcom/ITU-R acknowledge that near-threshold flashing over 5+ seconds
  can be cumulative; HardingFPA flags near-limit flashing in >80% of frames over the last 5 s.
  No standard thresholds exist. Add an optional advisory flag, off by default.
- **Static patterns**: bold patterns are a PSE risk independent of flashing. This library is
  flash-only in v1; state that limitation and consider a separate pattern analyzer later.
- **Display-induced flicker**: CRT/PWM/backlight flicker is a display property, not media content.
  Out of scope; document it.
- **VR/AR**: use the WCAG solid-angle rule rather than 25% of the headset FOV; make FOV/display
  assumptions explicit.
- **HDR/color metadata**: PQ/HLG and wide-gamut content require transfer-function and gamut
  handling. Read metadata when available; otherwise assume sRGB and mark the result as assumed.
- **Fine patterns**: highly unbalanced fine checkerboards can flash under WCAG while balanced
  white noise is exempt. Not a priority for user-generated GIF/video, but document the gap.

## Test fixtures this source implies

Add synthetic fixtures with exact timing, independent of the existing GIFs/MP4:

1. Six transitions in 1 s (3 flashes) passes; seven transitions fails.
2. A 750 ms fade followed by three quick flashes does not count the fade.
3. A 20 cd/m² transition spread over 4 frames at 60 fps counts; over 5 frames does not (66 ms).
4. Two adjacent areas, each below the area threshold but above it when summed within 20 ms,
   fails; the same areas 40 ms apart do not sum.
5. A 65 Hz+ sequence is merged/treated per the fast-flash rule; a 50 Hz burst plus a faster burst
   is not automatically safe.
6. `#FF0000` to `#FF3636` (small UCS difference) is not a red flash under WCAG 2.2; a larger
   red-to-blue transition is.
7. SDR 20 cd/m² and HDR Michelson 1/17 boundary cases.
8. 416x416 CSS-px area boundary cases, plus a legacy 25%-of-screen profile comparison.
9. Near-limit flashing sustained for 5+ s (advisory path only).

## Recommended priority

**P0 (correctness, before v1)**
- Transition-based counting (6 transitions = limit).
- 66 ms transition duration.
- WCAG 2.2/2023 red definition with CIE 1976 UCS difference.
- 416x416 CSS-px area model with explicit display assumptions.
- Result metadata for all assumptions and working values.

**P1 (modern content)**
- HDR/reference-luminance mode and color-space metadata.
- 20 ms synchronicity window.
- 65 Hz fast-flash merge.
- Standards profiles (ISO, ITU-R, Ofcom; Japan later).

**P2 (research/optional)**
- Motion compensation.
- Extended-exposure advisory.
- Static pattern analysis.
- Real-time/generated content support.

## Bottom line

The plan's core approach remains valid; the updated plan moves from "frame differences -> flashes"
to "timed transitions -> synchronized areas -> standards profile". Default to WCAG 2.2/ISO red
semantics, make display assumptions explicit, and treat the paper's 66 ms/20 ms/65 Hz values as
configurable working values with their provenance recorded.
