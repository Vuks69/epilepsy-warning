# Epilepsy Warning

An offline, rule-based library for detecting flashing and saturated-red content in GIFs,
images, and short videos. The default profile implements WCAG 2.2 Success Criterion 2.3.1
(Three Flashes or Below Threshold) with the ISO-harmonized red definition.

The library is intended for upload pipelines, chat/moderation tools, CMS/forum software, CI
checks, and anything else that displays user-supplied media. It is not a medical device and
does not certify compliance.

> Status: the Python library and CLI are implemented (`0.2.0`). The native Go port is still
> planned. See `planning/` for the standards contract and architecture.

## Features

- Counts **transitions**, not raw frame differences, and pairs opposing transitions into flashes.
- Accepts a file path, in-memory image/GIF bytes, or caller-supplied frames with timestamps.
- Separates luminance flashes from saturated-red flashes.
- Applies the paper's working values explicitly: 66 ms transition duration, 20 ms area
  synchronization, and 65 Hz fast-flash merging.
- Evaluates flashing area against the WCAG 10-degree / 0.006 sr rule, normalized to a
  416 x 416 CSS-pixel field when display geometry is unknown.
- Reports the standard profile, thresholds, assumptions, warnings, and measurements with every
  verdict.
- Runs fully offline and deterministically; no platform, Discord, network, or temp-file
  dependencies in the core.

## Install

From a checkout:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

Video decoding uses `imageio-ffmpeg`, which bundles an ffmpeg binary; a system ffmpeg is not
required.

## Python API

```python
from epilepsy_warning import AnalysisOptions, analyze_file

result = analyze_file("examples/triggering/4882.mp4")

print(result.is_triggering)              # True
print(result.risk)                       # "triggering" | "none" | "inconclusive"
print(result.standard.id)                # "wcag22"
print(result.standard.profile_coverage)  # "partial"
print(result.measurements.max_flashes_per_second)
print(result.reasons)
print(result.warnings)
```

The stable entry points are:

- `analyze_file(path, options=None)`
- `analyze_bytes(data, options=None)` for still images and GIFs; video bytes are rejected
  because the decoder needs a seekable file.
- `analyze_frames(frames, timestamps, durations=None, options=None)` for exact synthetic or
  already-decoded frame sequences. Timestamps and durations are seconds.

`AnalysisResult.to_dict()` returns JSON-serializable schema v2. `AnalysisResult.to_json()`
serializes it directly. Results include `measurements`, `assumptions`, `media`, `warnings`,
`analyzer`, and the `standard` profile, so consumers can distinguish "no flash found" from
"only part of the media was checked".

### Options and profile selection

```python
from epilepsy_warning import AnalysisOptions, DisplayGeometry

options = AnalysisOptions(
    standard="wcag22",                    # default
    display=DisplayGeometry(              # optional; improves the area estimate
        screen_diagonal_in=23.0,
        viewing_distance_cm=71.1,
        aspect_ratio=16 / 9,
    ),
    max_duration_seconds=60.0,
    max_frames=5000,
    max_bytes=64 * 1024 * 1024,
    analysis_timeout_seconds=60.0,
)
result = analyze_file("clip.mp4", options)
```

If display geometry is not supplied, the WCAG area model is normalized to a 416 x 416 CSS-pixel
field and the result carries `display_assumed: true` plus an
`area_normalized_to_416_css_px` warning. Source pixels are treated as CSS pixels; that is an
explicit approximation.

### Standards profiles

| ID | Coverage | Notes |
| --- | --- | --- |
| `wcag22` (default) | partial | WCAG 2.2 SC 2.3.1; ISO-harmonized red; 10-degree area rule |
| `iso9241-391` | partial | SDR/HDR luminance model; scene-change classification absent |
| `itu-r-bt1702` | partial | SDR/HDR model; leading-edge pacing qualification absent |
| `ofcom` | partial | SDR model; leading-edge pacing qualification absent |
| `nhk-jba` | not implemented | Rejected rather than silently approximated |
| `custom` | custom | Explicit caller-supplied thresholds |

One engine serves every profile. "Partial" means the implemented rate and area rules are
checked, not that the profile as a whole is certified. `available_profiles()` lists the
implemented IDs.

## CLI

```bash
epilepsy-scan examples/triggering/4882.mp4
epilepsy-scan --json examples/triggering/1.gif
epilepsy-scan --standard wcag22 --screen-diagonal-in 23 --viewing-distance-cm 71.1 clip.mp4
epilepsy-scan --list-standards
```

Exit codes:

- `0`: no triggering content found
- `1`: triggering content found
- `2`: error, invalid input, or inconclusive/truncated analysis

`--json` emits one object for a single file and an array for multiple files. Other useful flags
include `--area-model`, `--max-flashes-per-second`, `--max-duration-seconds`, `--max-frames`,
`--sample-fps`, `--strict-limits`, `--no-fast-flash-merge`, and `--extended-exposure`.
`epilepsy-scan --help` lists the full set.

## Detection model

1. Frames are gamma-expanded from sRGB and reduced to a per-tile grid.
2. A luminance transition is accepted only when the darker level is below 0.80 relative
   luminance, the difference reaches 0.10, and the change reaches the new level within 66 ms.
   The local-extremum test rejects slow monotonic fades.
3. A saturated-red transition requires linear `R / (R + G + B) >= 0.8` and a CIE 1976 UCS
   chromaticity distance of at least 0.2.
4. Same-direction areas are synchronized only when their leading edges are within 20 ms and
   their tile masks do not overlap.
5. Simultaneous up/down inversions count as one state change. Opposing transitions within one
   second are paired into flashes; the area test uses the pair's changed-area union, but the
   two masks must overlap or the union must be large enough to avoid counting unrelated motion
   edges (`flash_area_overlap_ratio`, `flash_area_union_scale`).
6. More than six area-qualified alternating transitions in any one-second window (more than
   three flashes) is triggering. Runs at or above 65 Hz are merged to two transitions.
7. Area qualifies a flash for rate counting; it is not a separate trigger. The area test uses
   the largest portion inside any 10-degree field, not the whole frame average.

The 66 ms, 20 ms, and 65 Hz values are the paper's working values, not normative WCAG text.
They are recorded in every result under `assumptions`.

## Limitations

- The analysis grid is capped (default `tile_grid_max=192`) to bound runtime. Very fine,
  high-frequency patterns can be averaged away; `tile_averaging_approximation` is always
  reported. Raise `tile_grid_max` at the cost of speed.
- Video timestamps come from the container frame rate, not per-frame presentation timestamps.
- Color management is assumed sRGB. HDR/PQ/HLG and embedded ICC profiles are not interpreted.
- GIF transparency is composited over white and GIF disposal is applied explicitly. Other page
  backgrounds are not configurable; `transparency_composited_white` is reported when needed.
- Motion compensation is not implemented, so large pans or cuts can look like luminance
  changes. Scene-change classification is not implemented for broadcast profiles. The
  flash-area overlap guard is a heuristic for motion edges, not a motion detector.
- The 65 Hz merge cannot be observed faithfully in media sampled below that rate.
- Default limits apply (`60 s`, `5000` frames, `64 MiB`, `60 s` wall time). Truncated analyses
  are marked `inconclusive` and warned about.
- This is a safety aid. It can miss content and can flag benign motion. Do not treat it as a
  guarantee, a compliance certification, or medical advice.

## Development

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src/epilepsy_warning tests
.venv/bin/ruff format src/epilepsy_warning tests
```

Smoke fixtures (media files are local-only and gitignored):

```bash
.venv/bin/epilepsy-scan examples/triggering/4882.mp4    # TRIGGERING, exit 1
.venv/bin/epilepsy-scan examples/triggering/1.gif      # TRIGGERING, exit 1
```

Recreate the GIF fixtures with `cd examples && ../util/download_gifs.sh triggering.lst`
(known triggering) and `../util/download_gifs.sh not-triggering.lst` (benign controls). The
download script names the output directory after the list file.

Planning and standards notes live in `planning/`; `planning/01_wcag_flash_thresholds.md` is the
threshold contract and `planning/07_source_review.md` records the paper gaps.

## Scope

In scope: the reusable analysis engine, a thin CLI, and a stable structured result.

Out of scope: platform integrations, URL downloads, moderation actions, storage, hosted
services, and a Go implementation in this repository. Those belong to consuming applications
or a later port.
