# WCAG Flash Thresholds (Key for Detection)

From WCAG 2.1 Success Criterion 2.3.1 "Three Flashes or Below Threshold":

Content is acceptable if **either**:
- no more than 3 general flashes and no more than 3 red flashes occur within any one-second
  period; **or**
- the combined area of flashes occurring concurrently occupies no more than ~0.006 steradians
  within any 10-degree visual field (about 25% of that field) at typical viewing distance.

These thresholds are the library's contract. Every threshold that is user-configurable must
default to the WCAG values, and any deviation must be visible in the options.

## Definitions

- **Flash**: a pair of opposing changes in relative luminance that can cause seizures if large
  and bright enough in the right frequency range.
- **General flash**: a pair of opposing changes in relative luminance of 10% or more of maximum
  relative luminance (1.0), where the darker image is below 0.80. "Pair of opposing changes"
  means increase followed by decrease, or decrease followed by increase.
- **Red flash**: any pair of opposing transitions involving a saturated red.
- **Blinking**: switching between visual states to draw attention; a distraction, not the same
  as flashing. The library targets flashes, not generic motion.
- **Relative luminance (sRGB)**: `L = 0.2126*R + 0.7152*G + 0.0722*B`, after gamma correction
  per the sRGB specification.

## Practical implications for detection

- Detect rapid changes in luminance and red saturation across frames.
- Count **flash pairs**, not frame-to-frame differences. A single cut or fade is not a flash.
- Use real timestamps. A 30 fps assumption breaks on variable-frame-rate video and GIF delays.
- Evaluate sliding one-second windows so a burst anywhere in the clip is caught.
- Evaluate flashing **area**; small localized flashes can be acceptable at low rates while
  full-screen flashes are not.
- Analyze GIF loops as continuous playback, including the transition from the last frame back
  to the first.
- Treat red flashes separately and conservatively.

## Area rule: avoid the "25% of frame" mistake

The 25% figure refers to the area of a **10-degree visual field**, not 25% of the whole video
frame. A correct or conservative implementation needs:

- a reference field size derived from assumed viewing distance and display size
- an area map (e.g. a coarse grid of cells) rather than one whole-frame average
- a documented approximation for how cell area maps to the 10-degree field
- result metadata that records the approximation and the effective area ratio

The current prototype uses a whole-frame average of changed pixels. That is a useful first
signal but is not a faithful area measurement, and it can under-report small bright flashes or
over-report large dim ones. This is a known correctness gap to close before a stable release.

## Red flashes

A red flash requires both a luminance/opposing-change component and a saturated-red component.
Implementation notes:

- Determine saturation in a perceptual space (e.g. HSV/HSL or a red-dominance test), not just
  `R / (R+G+B)`.
- Follow WCAG's definition of saturated red and the stricter red-flash rate.
- Default the red threshold to WCAG values; expose it as an option but do not disable it silently.

## Notes from the spec

- The historical 10-degree reference is roughly 341 x 256 CSS pixels at 1024x768; modern
  content should use a consistent relative field rather than a fixed pixel box.
- sRGB is assumed; other color spaces must be converted before luminance is computed.
- Alpha must be composited against a defined background before analysis (default: black).
- Frame sampling below native frame rate can miss short flashes; if sampling is used, record it
  in the result and prefer at least 60 Hz sampling or native fps.

## Why this matters for a library

Consumers will trust the result for moderation and safety decisions. The library must therefore:

- default to **conservative** thresholds (flag borderline content rather than miss it)
- expose the evidence (`max_flashes_per_second`, `max_flashing_area_ratio`, reasons) so callers
  can audit decisions
- version any change that alters classifications
- document the gap between its approximation and the formal WCAG test procedure
