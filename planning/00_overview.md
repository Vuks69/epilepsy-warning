# Project Overview: Epilepsy Warning Library

## Problem statement

Applications that display user-supplied GIFs and short videos have no cheap, reliable way to
screen them for photosensitive epilepsy triggers. Reimplementing WCAG flash analysis in every
project is error-prone, slow to validate, and easy to get dangerously wrong.

## Scope

Build a **reusable media analysis library**, consumable from Python and Go projects. The
library takes media in, runs standards-based flash detection (WCAG 2.2 by default), and returns
a structured result.

In scope:
- Local files (GIF, MP4, WebM, and other formats supported by the decoder)
- Raw bytes / in-memory buffers
- Caller-supplied decoded frames with explicit timestamps
- Standards profiles (WCAG, ISO, ITU-R, Ofcom, NHK/JBA Japan)
- Display/viewing assumptions for area normalization
- Configurable thresholds, color space, HDR/reference luminance, and resource limits
- Structured result with reasons, measurements, working values, and assumptions
- Thin CLI for manual checks and scripting
- Example consumer showing how a moderation bot would use the library

Out of scope:
- Discord bot, MESSAGE_CONTENT intent, event handling
- Downloading URLs or handling redirects
- Moderation actions (warn/delete/react)
- Persistent storage, caching services, hosted APIs
- LLM/ML classification
- Editing or transcoding media
- Static bold-pattern analysis in v1 (separate detector later)
- Display-induced flicker (CRT refresh, PWM backlights)
- Real-time stream analysis or frame modification

The original Discord bot is downgraded to a **reference consumer**. If one is built later, it
lives in a separate repo or an `examples/` directory and depends on this library.

## Requirements

- **Fast**: seconds or faster for small/short media; no network calls in the analysis path
- **Deterministic**: same input + options + library version => same result
- **Offline**: no telemetry, no remote model, no API keys
- **Safe on untrusted input**: byte/duration/pixel caps, timeouts, no shell interpolation
- **Portable**: Python package and Go module, no cgo required
- **Stable API**: versioned result schema and semantic versioning
- **Actionable**: report *why* content was flagged (transition rate, area, red flashes), plus the
  standards profile and assumptions used, not just a boolean
- **Standards-explicit**: default to WCAG 2.2 SC 2.3.1; make profile/version/display assumptions
  visible and never imply universal compliance

## Example use

Python:
```python
from epilepsy_warning import analyze_file

result = analyze_file("clip.mp4")
if result.is_triggering:
    print(result.reasons)
```

Go:
```go
result, err := epilepsy.AnalyzeFile(ctx, "clip.mp4", epilepsy.DefaultOptions())
if err != nil {
    return err
}
if result.IsTriggering {
    log.Println(result.Reasons)
}
```

## Examples

- `./examples/triggering/4882.mp4` - frames are uniform colors changing at random intervals (obviously flashing)
- `./examples/triggering.lst` - direct GIF links considered seizure-inducing
- `./examples/triggering/*.gif` - local copies used as triggering regression fixtures
- `./examples/not-triggering.lst` / `./examples/not-triggering/*.gif` - benign controls that must stay safe

## References

- https://www.epilepsy.com/what-is-epilepsy/seizure-triggers/photosensitivity
- https://en.wikipedia.org/wiki/Photosensitive_epilepsy
- https://www.w3.org/TR/WCAG22/#seizures-and-physical-reactions
- ISO 9241-391, ITU-R BT.1702 (2023), Ofcom PSE guidance (2017), NHK/JBA guidance (2020)
- `planning/guidelines_photo_epilepsy.txt` - *International Guidelines for Photosensitive
  Epilepsy: Gap Analysis and Recommendations* (DOI `10.1145/3694790`)
- `planning/07_source_review.md` - how that paper changes this plan
