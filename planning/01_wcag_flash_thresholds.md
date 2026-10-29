# Flash Thresholds and Standards Profiles

The library's defaults target **WCAG 2.2 Success Criterion 2.3.1** (the 2023 update to WCAG 2.1
uses the same red-flash semantics). ISO 9241-391, ITU-R BT.1702, Ofcom, and NHK/JBA Japan are
similar but not interchangeable; see `07_source_review.md`.

Do not describe a result as compliant with "the PSE guidelines" in general. Every result must
name the standard/profile, version, and assumptions used.

## Core rule: all dimensions must be met

A sequence is potentially hazardous only when **all** of these hold simultaneously:

1. Transitions alternate in direction.
2. The luminance or red critical difference is met.
3. The transition occurs within the qualifying duration.
4. The affected area (including synchronized nearby areas) meets the area threshold.
5. The transition count exceeds the rate limit within a 1-second window.

A single cut, fade, or localized flicker is not automatically a flash. The current prototype's
"any significant frame difference is a flash" model is wrong and must be replaced.

## Transition counts, not flash counts

- A **flash** is a pair of opposing transitions.
- Standards phrase the limit as **3 flashes per second**, which is equivalent to **no more than
  6 qualifying transitions in any 1-second window**.
- Seven alternating transitions (3.5 flashes) is a potential failure.
- Luminance transitions and red transitions are counted **separately**.
- One transition can count as both a luminance and a red transition.
- **Fast flashes** (ISO / paper working value): when leading edges are 15 ms or less apart
  (>= 65 flashes/s), merge same-direction transitions into one and count the sequence as **two
  transitions total** (one per direction). Do not let a mixed-rate burst (e.g. 50 Hz plus a faster
  burst) pass merely because the total exceeds 65 in a second.

Implementation: store transitions with `start_time`, `direction`, `kind` (luminance/red),
`area_cells`, and `duration`. Derive flash counts from opposing pairs and expose both counts.

## Qualifying transition duration (paper working value: 66 ms)

No standard specifies this. Use **66 ms** as the maximum time for a transition to reach or
exceed the critical difference:

- A transition that takes longer than 66 ms is not a flash transition.
- At 24-30 fps this is 1-2 frames; at 60 fps up to 4; at 120 fps up to 8.
- This avoids counting slow fades while catching multi-frame transitions at high frame rates.

The value is a working value, not a WCAG requirement. Keep it configurable and record it.

## Synchronization of areas (paper working value: 20 ms)

When adjacent or nearby areas transition in the same direction within **20 ms**, sum them for the
area test. At 24-30 fps this is effectively frame-by-frame; at 50+ fps it may combine multiple
frames. Record the window and whether any areas were merged.

## Luminance thresholds

### Default (WCAG, sRGB)

A general flash is a pair of opposing changes of **>= 0.1 relative luminance** where the darker
state is **< 0.8 relative luminance**. Relative luminance is computed from linearized sRGB:

`L = 0.2126*R + 0.7152*G + 0.0722*B`.

### SDR broadcast (ISO / ITU-R / Ofcom / NHK-JBA)

**>= 20 cd/m²** difference when the darker state is **< 160 cd/m²**, assuming a **200 cd/m²**
reference white. This is numerically equivalent to the WCAG rule under that reference white.

### HDR (ITU-R, NHK-JBA)

When the darker state is **>= 160 cd/m²**, use **Michelson contrast >= 1/17**:

`(L_high - L_low) / (L_high + L_low) >= 1/17`.

Japan adds rate bands for 1/8-1/4 and > 1/4 brightness changes; these require a Japan profile.

### Reference luminance

- Indoor SDR default: 200 cd/m².
- Theater: 48 cd/m², giving a 4.8 cd/m² critical difference when the darker state is < 38.4 cd/m².
- PQ/HLG HDR: use the transfer functions in ITU-R BT.2100 and a 200 cd/m² reference unless the
  display is known.
- The file alone cannot tell you the display or ambient conditions. Return the assumptions.

## Red flashes

### Saturated red (WCAG 2.2 / ISO)

Using linear, gamma-expanded channels:

`R / (R + G + B) >= 0.8`.

This is a saturation test only. Borderline colors include reddish orange, magenta, pink, and very
dark red; that is expected and conservative for dark reds.

### Red transition difference (WCAG 2.2 / ISO)

A red flash requires a color difference of **>= 0.2 on the CIE 1976 UCS chromaticity diagram**
between a saturated-red state and another state, in either direction, regardless of luminance.
Convert linear sRGB -> XYZ -> `u', v'` and compare Euclidean distance.

The older WCAG 2.0/2.1 color-difference equation is not equivalent; do not mix it with the
current definition. The 2023 WCAG 2.1 update and WCAG 2.2 are harmonized with ISO.

## Rate and pacing

- Default: no more than 6 qualifying transitions in **any** 1-second window (sliding).
- The paper recommends this unqualified rule as the more conservative choice.
- ITU-R/Ofcom allow leading edges separated by >= 334 ms (60 Hz environment) or >= 360 ms
  (50 Hz), making two quick flashes, a pause, and two more quick flashes acceptable. Implement
  only in those profiles.
- Japan uses area- and contrast-dependent rates: up to 5 flashes/s for moderate changes for up to
  2 s, 3 flashes/s otherwise, and stricter scene-change/inversion rules.

## Area thresholds

### WCAG / ISO (default)

**0.006 steradians within any 10-degree field of view** (25% of that field) at typical viewing
distance. This is a solid-angle rule, not 25% of the whole frame.

Implementation approach:

- Normalize content to CSS pixels: one CSS px subtends **0.0213 degrees**.
- Analyze at the largest expected display size.
- For unknown screens, use **25% of any 416 x 416 CSS px subarea** (the paper's working
  normalization; a 10-degree circle is ~470 CSS px in diameter).
- For a known screen and viewing distance, compute the 10-degree field from the display geometry.
- Keep a per-tile area map so non-contiguous flashing areas can be summed.

### Broadcast profiles

ISO/ITU/Ofcom/NHK-JBA use **25% of the displayed screen area** in some contexts. This is less
conservative than the WCAG solid-angle rule and must be an explicit profile choice, never the
default.

### Display assumptions

Area depends on screen size, viewing distance, FOV, and expected display size. Expose these as
options; otherwise use the 416 x 416 CSS-px default and mark the result as using assumed display
geometry. Center-weighted risk is noted in the literature but has no normative threshold; do not
invent one.

## Scene changes and inversions

ISO/ITU/Ofcom treat inversions and scene changes as flashes; NHK/JBA applies stricter rules
(3/s, or 1.5/s for scene changes covering 80-100% of the screen). WCAG 2.3.1 does not add a
separate scene-change rule. Broadcast profiles must classify these explicitly; the WCAG default
should document that it does not.

## Related risks not covered by v1

- **Static bold patterns**: a PSE risk independent of flashing. Out of scope for v1; plan a
  separate pattern analyzer.
- **Motion**: pans, running feet, and trains can create spurious flash detections. ITU-R and
  HardingFPA use motion compensation; no public thresholds exist. Add as an experimental
  pre-filter, not a default.
- **Extended exposure**: near-limit flashing over 5+ seconds may be cumulative. Standards give no
  thresholds. Provide an optional advisory flag (off by default), inspired by HardingFPA's
  >80%-of-frames-in-5-seconds heuristic.
- **Display-induced flicker**: CRT refresh, PWM backlights, and panel flicker are display
  properties, not media content. Out of scope.
- **VR/AR**: use the solid-angle area rule, not 25% of the headset FOV; make FOV assumptions
  explicit.

## Defaults for the library

| Option | Default | Status |
|---|---|---|
| `standard` | `wcag22` (ISO-harmonized red) | normative |
| `luminance_threshold` | `0.1` relative luminance | WCAG |
| `red_saturation` | `0.8` linear RGB ratio | WCAG/ISO |
| `red_color_difference` | `0.2` CIE 1976 UCS | WCAG 2.2/ISO |
| `max_flashes_per_second` | `3` (6 transitions) | normative |
| `max_transition_duration_ms` | `66` | paper working value |
| `synchronicity_window_ms` | `20` | paper working value |
| `fast_flash_hz` | `65` (merge at <=15 ms) | ISO + paper |
| `area_model` | `wcag_solid_angle` | normative |
| `area_subarea_css_px` | `416 x 416` | paper working normalization |
| `reference_luminance` | `200 cd/m²` | standard assumption |
| `extended_exposure` | off | advisory only |
| `motion_compensation` | off | experimental |

## References

- WCAG 2.2 SC 2.3.1 and the 2023 WCAG 2.1 update
- ISO 9241-391
- ITU-R BT.1702 (2023)
- Ofcom PSE guidance (2017)
- NHK/JBA joint guidance (2020)
- `planning/guidelines_photo_epilepsy.txt` (gap analysis and proposed working values)
