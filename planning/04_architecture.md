# Architecture

## Design principles

1. **Library-first**: the public API is the product; the CLI and any bot are thin adapters.
2. **No I/O surprises**: core analysis never opens network connections or writes files.
3. **Decoder boundary is explicit**: callers can pass a path, bytes, or already-decoded frames.
4. **Timestamps are first-class**: flash rates depend on real timing, not an assumed frame rate.
5. **Evidence over verdicts**: always return the measurements behind a classification.
6. **Fail safely**: malformed or oversized input yields a typed error, never a partial "safe" verdict.

## Layers

```
public API (Python / Go)
  -> options validation + resource limits
  -> input source (path | bytes | frames)
  -> decoder / frame iterator (GIF, video via ffmpeg)
  -> analysis engine (luminance, red, flashes, windows, area)
  -> result model (classification + evidence + metadata)
```

### Public API

Python:
```python
from epilepsy_warning import (
    analyze_file, analyze_bytes, analyze_frames,
    AnalysisOptions, AnalysisResult, EpilepsyWarningError,
)

result: AnalysisResult = analyze_file("clip.mp4", options=AnalysisOptions())
```

Go:
```go
import epilepsy "github.com/<owner>/epilepsy-warning"

result, err := epilepsy.AnalyzeFile(ctx, "clip.mp4", epilepsy.DefaultOptions())
result, err = epilepsy.AnalyzeBytes(ctx, data, epilepsy.DefaultOptions())
result, err = epilepsy.AnalyzeFrames(ctx, frames, epilepsy.DefaultOptions())
```

Common API rules:
- Options are immutable/value types with sane defaults and a `Default`/`default()` constructor.
- Results are plain data, JSON-serializable, and comparable across languages.
- Errors are typed: unsupported format, decode failure, input too large, timeout/cancelled,
  invalid options.
- Analysis is safe to call concurrently; no mutable global state.
- Context/cancellation support in Go; an optional cancellation token or timeout in Python.

### Input sources

- **Path**: library opens the file read-only.
- **Bytes/buffer**: format detected from magic bytes, not the filename.
- **Frames**: caller provides RGB(A) frames plus per-frame timestamps or durations. This is the
  escape hatch for custom decoders and the conformance test path.

The library does **not** download URLs. Consumers fetch media and pass bytes/paths in. This keeps
SSRF, redirects, MIME sniffing, and retries in the application where they belong.

### Decoder / frame iterator

- **GIF**: decode frames and frame delays (disposal modes handled by the decoder library).
- **Video**: stream frames through ffmpeg at a sampling rate; preserve presentation timestamps.
  Never assume 30 fps; variable frame rate content is common.
- **Sampling**: default to native frame rate for short clips, with a configurable max frames and
  max duration. If sampling is required, sample fast enough to catch flash pairs (target >= 60 Hz
  or native fps, whichever is lower) and document the limitation.
- **Resolution**: downsample for the area map, but keep enough resolution to estimate flashing
  area. The scale factor and its effect on area measurements are part of the result metadata.

### Analysis engine (core)

1. Convert frames to sRGB and compute relative luminance per pixel.
2. Classify pixel transitions beyond the luminance threshold (default 10% of max luminance),
   using the darker-state rule from WCAG.
3. Detect opposing transition pairs (flash events), not just any frame difference.
4. Track saturated-red flashes separately with the stricter red rule.
5. Group flashes into sliding one-second windows using real timestamps.
6. Estimate the flashing area and evaluate it against the 25%-of-10-degree-field rule.
7. Emit reasons and measurements.

Important correctness notes:
- A flash is a *pair* of opposing changes; a single fade or cut is not automatically a flash.
- The area rule is spatial, not "25% of the frame". The implementation needs a documented,
  conservative approximation (e.g. per-cell area map and a 10-degree field reference) rather
  than the current whole-frame average.
- Red flashes require a saturation/red-dominance test in a perceptual color space; the current
  RGB-ratio heuristic is a placeholder.
- GIF loops should be analyzed as continuous playback where the final frame meets the first.
- Report `is_triggering` plus a severity/risk level so consumers can choose warn vs block.

### Result model

Proposed cross-language shape (v1):

```json
{
  "schema_version": 1,
  "is_triggering": true,
  "risk": "high",
  "reasons": ["flash_rate_exceeded", "large_flashing_area"],
  "measurements": {
    "max_flashes_per_second": 7,
    "max_red_flashes_per_second": 0,
    "max_flashing_area_ratio": 0.82,
    "duration_seconds": 4.2,
    "frames_analyzed": 126,
    "sampled_fps": 30.0
  },
  "media": {
    "format": "mp4",
    "width": 640,
    "height": 360,
    "bytes": 812345
  },
  "analyzer": {
    "name": "epilepsy-warning",
    "version": "0.2.0",
    "options_hash": "..."
  }
}
```

Design rules:
- Unknown fields are ignored by consumers; additive changes are minor versions.
- Reasons are stable enum-like strings, not human sentences.
- Optional human-readable messages are derived by the consumer, not baked into the core.
- Timings/measurements include units in the field name.

### Configuration

```python
AnalysisOptions(
    luminance_threshold=0.10,      # WCAG general flash threshold
    max_flashes_per_second=3,
    area_threshold=0.25,
    red_flash_enabled=True,
    max_bytes=25 * 1024 * 1024,
    max_duration_seconds=30,
    max_frames=2000,
    max_pixels=1920 * 1080,
    decode_timeout_seconds=10,
    sample_fps=None,               # None = native frame rate
)
```

Defaults prioritize safety and predictable latency. Every limit that can cause a scan to stop
early must be reflected in the result (e.g. `truncated: true`), so consumers do not mistake an
incomplete scan for a clean one.

### Error and limit handling

- Input over `max_bytes` / `max_duration` / `max_frames` => typed error or explicit
  `inconclusive` result, depending on API mode (strict vs permissive).
- Decoder failure => typed error; never "not triggering".
- Cancellation/timeout => typed error.
- Unsupported format => typed error listing supported decoders.
- No temp files in the core path; decoding should stream or use caller-provided buffers.

### Adapters

- **CLI** (`epilepsy-scan`): parses arguments, calls the library, prints human-readable output,
  exits non-zero on triggering content. Useful in scripts and CI.
- **Discord bot**: separate example/project. It handles intents, attachments, URL fetching,
  size checks, actions, and cleanup; it calls the library only after it has bytes on disk.
- **HTTP service**: not in scope, but the library's stateless API makes one easy to wrap.

### Testing strategy

- Unit tests for luminance conversion, transition pairing, windowing, and area math.
- Golden tests on `examples/4882.mp4` and `examples/giphy/*.gif` (must flag).
- Negative fixtures (static images, slow fades, small localized flashes, benign animation).
- Property tests: monotonic thresholds, frame-rate invariance, deterministic output.
- Cross-language conformance: same fixtures, same schema, tolerances for numeric drift.
- Performance budget tests (e.g. 10 s 720p clip analyzed under N seconds on CI hardware).
