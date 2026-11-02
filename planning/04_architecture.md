# Architecture

## Design principles

1. **Library-first**: the public API is the product; the CLI and any bot are thin adapters.
2. **Standards-explicit**: every scan names a standard/profile, version, and display assumptions.
3. **Content-only**: analysis never opens network connections, writes files, or touches a display.
   Display-induced flicker is out of scope.
4. **Decoder boundary is explicit**: callers can pass a path, bytes, or already-decoded frames.
5. **Timestamps are first-class**: flash rates and transition durations depend on real timing.
6. **Transition-based**: a flash is a pair of qualifying opposing transitions, not a frame diff.
7. **Evidence over verdicts**: return the measurements, working values, and assumptions.
8. **Fail safely**: malformed, oversized, or unsupported input yields a typed error or an explicit
   `inconclusive` result, never a silent "safe".

## Layers

```
public API (Python / Go)
  -> options validation + standards profile + display context
  -> input source (path | bytes | frames)
  -> decoder / frame iterator (GIF, video via ffmpeg, caller frames)
  -> temporal analysis engine
       -> tile luminance/color state
       -> 66 ms transition detection
       -> opposing-pair / red-transition classification
       -> 20 ms area synchronization
       -> sliding 1-second transition windows
       -> 65 Hz fast-flash merge
       -> area normalization (10-degree field / profile)
  -> result model (classification + evidence + assumptions + metadata)
```

## Public API

Python:
```python
from epilepsy_warning import (
    analyze_file, analyze_bytes, analyze_frames,
    AnalysisOptions, DisplayGeometry, AnalysisResult, EpilepsyWarningError,
)

options = AnalysisOptions(
    standard="wcag22",
    display=DisplayGeometry(screen_diagonal_in=23.0, viewing_distance_cm=71.1),
)
result: AnalysisResult = analyze_file("clip.mp4", options=options)
```

Go:
```go
import epilepsy "github.com/<owner>/epilepsy-warning"

opts := epilepsy.DefaultOptions()
opts.Standard = epilepsy.WCAG22
opts.Display = &epilepsy.DisplayGeometry{ScreenDiagonalIn: 23, ViewingDistanceCM: 71.1}

result, err := epilepsy.AnalyzeFile(ctx, "clip.mp4", opts)
result, err = epilepsy.AnalyzeBytes(ctx, data, opts)
result, err = epilepsy.AnalyzeFrames(ctx, frames, opts)
```

Common rules:
- Options are immutable/value types with defaults and a `default()`/`DefaultOptions()` constructor.
- Results are plain data, JSON-serializable, and identical in schema across languages.
- Errors are typed: unsupported format, decode failure, input too large, timeout/cancelled,
  invalid options, unsupported standard/profile.
- Analysis is concurrency-safe; no mutable global state.
- Go supports `context.Context`; Python supports an optional cancellation token/timeout.

## Standards profiles

One engine, profile-driven thresholds and rules:

- `wcag22` (default): WCAG 2.2 SC 2.3.1 with the 2023 ISO-harmonized red definition.
- `iso9241-391`: ISO profile, including the 65 Hz upper limit where applicable.
- `itu-r-bt1702`, `ofcom`: SDR/HDR thresholds and leading-edge pacing qualification.
- `nhk-jba`: Japan's area/contrast-dependent rates and scene-change rules.
- `custom`: explicit thresholds for research/conformance testing.

Profiles must not silently change semantics. Whether a profile is fully implemented is reported
in the result (e.g. `profile_coverage: "full" | "partial"`). Never claim compliance with multiple
standards from one default result.

## Input sources

- **Path**: read-only open by the library.
- **Bytes/buffer**: format detected from magic bytes, not the filename.
- **Frames**: caller supplies RGB(A) frames plus timestamps/durations. This is the escape hatch for
  custom decoders and the conformance test path.

The library does **not** download URLs. Consumers fetch media and pass bytes/paths in. This keeps
SSRF, redirects, MIME sniffing, and retries in the application.

## Decoder / frame iterator

- **GIF**: decode frames and delays, handle disposal modes, and analyze the loop transition from
  the last frame back to the first.
- **Video**: stream frames through `imageio`/`imageio-ffmpeg`; timestamps come from the constant
  container frame rate. Per-frame presentation timestamps are not exposed by the decoder, so the
  analysis never assumes 30 fps but does not recover true per-frame PTS; the rate is recorded and
  a fallback rate is assumed (and warned) only when the container reports none.
- **Color metadata**: color space, transfer function, and HDR metadata are **not** read. Color is
  always treated as sRGB and reported with `color_space_assumed_srgb`.
- **Sampling**: native frame rate by default for short clips; configurable cap. If sampling is
  required, sample fast enough to catch 66 ms transitions (target >= 60 Hz) and record it.
- **Resolution**: tile the frame for area analysis. Keep enough resolution to approximate the
  10-degree field; record the tile grid and CSS-pixel mapping.
- **Display size**: analyze at the largest expected display size. If unknown, use the 416x416
  CSS-px subarea model and mark assumptions.

## Temporal analysis engine

1. Resolve the profile, thresholds, and display/area model. Reject unsupported combinations.
2. Convert frames to sRGB (or the declared color space) and compute relative luminance per tile.
   Convert to CIE XYZ/1976 UCS when red analysis is active.
3. Maintain per-tile state with the timestamp when the current state began.
4. Detect a transition when luminance/color crosses the critical difference within **66 ms**
   (working value). Slower changes do not qualify.
5. Classify transitions as luminance, red, or both. A red transition needs a saturated-red state
   and a CIE 1976 UCS color difference >= 0.2.
6. Pair opposing transitions into flashes. Count luminance and red transitions separately.
7. Sum same-direction areas that occur within **20 ms** (working value).
8. Count qualifying transitions in sliding 1-second windows. Default limit: **6 transitions**
   (3 flashes). Apply profile-specific pacing qualifications if configured.
9. Merge fast flashes whose leading edges are <= 15 ms apart (>= 65 Hz) per the profile; guard
   against mixed-rate bursts.
10. Evaluate the area threshold against the relevant model:
    - WCAG/ISO: 0.006 sr within any 10-degree field, normalized to 416x416 CSS-px subareas by
      default.
    - Broadcast profiles: 25% of the displayed screen, explicitly selected.
11. Emit reasons and measurements, including which rules fired and which assumptions were used.

Correctness notes:
- Seven alternating transitions in 1 s fail; six pass. Do not compare a raw frame-diff count to 3.
- A single cut/fade is not a flash unless it forms an opposing pair within the duration.
- Motion compensation is experimental and off by default; pans/running feet/trains can create
  false positives.
- Scene changes/inversions are profile-specific; WCAG does not add a separate rule.
- Extended-exposure (5+ s near-limit flashing) has no normative thresholds; optional advisory.

## Result model

Proposed cross-language shape (schema v2):

```json
{
  "schema_version": 2,
  "standard": {
    "id": "wcag22",
    "version": "2.2",
    "profile_coverage": "full"
  },
  "is_triggering": true,
  "risk": "high",
  "reasons": ["transition_rate_exceeded", "large_flashing_area"],
  "measurements": {
    "max_luminance_transitions_per_second": 14,
    "max_red_transitions_per_second": 0,
    "max_flashes_per_second": 7,
    "max_flashing_area_ratio": 0.82,
    "max_transition_duration_ms": 33,
    "synchronized_area_merges": 2,
    "fast_flash_sequences": 0,
    "duration_seconds": 4.2,
    "frames_analyzed": 126,
    "sampled_fps": 30.0
  },
  "assumptions": {
    "color_space": "srgb",
    "reference_luminance_cd_m2": 200,
    "max_transition_duration_ms": 66,
    "synchronicity_window_ms": 20,
    "fast_flash_hz": 65,
    "area_model": "wcag_solid_angle",
    "area_subarea_css_px": [416, 416],
    "area_base_threshold_px2": 43264,
    "area_source_scaled": false,
    "display_assumed": true
  },
  "media": {
    "format": "mp4",
    "width": 640,
    "height": 360,
    "bytes": 812345,
    "color_space": "bt709",
    "transfer": "srgb"
  },
  "warnings": ["color_metadata_missing"],
  "analyzer": {
    "name": "epilepsy-warning",
    "version": "1.0.0",
    "options_hash": "..."
  }
}
```

Design rules:
- Unknown fields are ignored by consumers; additive changes are minor versions.
- Reasons are stable enum-like strings, not human sentences.
- Human-readable messages are derived by the consumer.
- Working values (66 ms, 20 ms, 65 Hz) are reported in `assumptions` with their provenance.
- Timings/measurements include units in the field name.
- `inconclusive`/`truncated` results must be explicit, never coerced to `is_triggering: false`.

## Configuration

```python
AnalysisOptions(
    standard="wcag22",
    luminance_threshold=0.10,           # relative luminance
    red_saturation=0.80,                # linear R/(R+G+B)
    red_color_difference=0.20,          # CIE 1976 UCS distance
    max_flashes_per_second=3,           # = 6 qualifying transitions
    max_transition_duration_ms=66,      # paper working value
    synchronicity_window_ms=20,         # paper working value
    fast_flash_hz=65,                   # merge <= 15 ms leading edges
    area_model="wcag_solid_angle",      # or "screen_fraction" for broadcast profiles
    area_subarea_css_px=(416, 416),
    flash_area_overlap_ratio=0.30,      # implementation heuristic
    flash_area_union_scale=1.50,        # implementation heuristic
    flash_area_scaled_overlap_ratio=0.40,  # small sources below the base threshold
    flash_area_frame_fraction=0.50,     # small sources below the base threshold
    display=None,                       # DisplayGeometry(...)
    reference_luminance_cd_m2=200,
    color_space="auto",
    motion_compensation=False,          # experimental
    extended_exposure=False,            # advisory only
    max_bytes=25 * 1024 * 1024,
    max_duration_seconds=30,
    max_frames=2000,
    max_pixels=1920 * 1080,
    decode_timeout_seconds=10,
    sample_fps=None,                    # None = native frame rate
)
```

Defaults prioritize safety and predictable latency. Limits that stop a scan early must be
reflected in `warnings`/`inconclusive`.

## Error and limit handling

- Input over `max_bytes` / `max_duration` / `max_frames` => typed error or explicit `inconclusive`,
  depending on strict/permissive mode.
- Decoder failure => typed error; never "not triggering".
- Cancellation/timeout => typed error.
- Unsupported format/profile => typed error listing what is supported.
- No temp files in the core path; decoding streams or uses caller-provided buffers.

## Adapters

- **CLI** (`epilepsy-scan`): parses arguments, calls the library, prints human-readable output,
  exits non-zero on triggering content. Add `--standard`, `--screen`, `--viewing-distance`.
- **Discord bot**: separate example/project. It handles intents, attachments, URL fetching, size
  checks, actions, and cleanup; it calls the library only after it has bytes on disk. It should
  pass its best display assumptions (desktop/mobile) rather than relying on defaults silently.
- **HTTP service**: out of scope, but the stateless API makes one easy to wrap.

## Testing strategy

- Unit tests: sRGB/linear conversion, relative luminance, CIE XYZ/UCS, red difference, transition
  state machine, pairing, windowing, area tiles, fast-flash merge.
- Synthetic timing fixtures:
  - 6 transitions/s passes; 7 fails.
  - 750 ms fade + 3 quick flashes does not count the fade.
  - 66 ms transition boundary at 24/30/50/60/120 fps.
  - 20 ms area synchronization boundary.
  - 65 Hz fast-flash and mixed-rate cases.
  - 20 cd/m² SDR and Michelson 1/17 HDR boundaries.
  - 416x416 CSS-px area boundary; legacy 25%-of-screen profile comparison.
- Golden media tests on `examples/triggering/4882.mp4` and `examples/triggering/*.gif`.
- Negative fixtures under `examples/not-triggering/`: static images, slow fades, small localized
  flashes, pans/running feet, scene cuts, benign animation, and GIF transparency/disposal.
- Property tests: deterministic output, monotonic thresholds, frame-rate invariance.
- Cross-language conformance: same fixtures and schema, with numeric tolerances.
- Performance budget tests at 24/30/60/120 fps with a bounded tile grid.

Current coverage: `tests/` (stdlib `unittest`, 48 tests) has color, area, engine, media, and CLI
tests, and they pass. Unit tests cover sRGB/linear conversion, relative luminance, CIE UCS, red
saturation, the transition/area/fast-flash state machine, GIF transparency/disposal, and the CLI.
Golden-media, property, benchmark, and cross-language conformance tests are planned but not yet
added; there is no CI.
