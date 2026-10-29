# Epilepsy Warning

A fast, offline library for detecting photosensitive epilepsy triggers in GIFs and short
videos. It implements WCAG 2.2 Success Criterion 2.3.1 (Three Flashes or Below Threshold) using
rule-based luminance and red-flash analysis — no LLM, no network calls, no platform
dependencies.

The library is intended for use in **Python and Go projects**: chat/moderation bots, upload
pipelines, CMS/forum software, CI checks, and anything else that displays user-supplied media.

> Status: the Python analyzer and CLI work today. The package is still mid-refactor from the
> original Discord bot; the stable `analyze_file` / `analyze_bytes` / `analyze_frames` API and
> the native Go port are planned. See `planning/` for the design.

## Features

- Detects general luminance flashes and saturated-red flashes
- Evaluates flash rate per second and flashing area
- Works on GIF, MP4, WebM, and other formats supported by the decoder
- Returns structured evidence, not just a boolean
- Fast enough for interactive moderation and upload flows
- Runs fully offline and deterministically

## Install

```bash
pip install epilepsy-warning
```

Or from a checkout:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

Video support uses `imageio-ffmpeg`, which bundles an ffmpeg binary; a system ffmpeg is not
required.

## Usage (Python)

```python
from epilepsy_warning import FlashDetector

detector = FlashDetector()
result = detector.analyze("examples/4882.mp4")

if result["is_triggering"]:
    print("Flagged:", result["reason"])
else:
    print("Acceptable:", result["reason"])
```

The result contains measurements such as `flash_count`, `max_flashes_per_second`, and
`frames_analyzed` alongside the classification.

## Usage (CLI)

```bash
epilepsy-scan examples/4882.mp4
epilepsy-scan examples/giphy/*.gif
```

The command prints a human-readable verdict per file and exits with status `1` if any media is
flagged, so it can be used in scripts and CI.

## Go

A native Go module is planned, using the same thresholds and result schema as the Python
library, with stdlib GIF decoding and ffmpeg-backed video decoding. It is not published yet;
see `planning/03_tech_stack.md` and `planning/04_architecture.md` for the API shape.

## How it works

Based on WCAG 2.2 SC 2.3.1, content is flagged when it has:

- more than 3 general flashes and/or more than 3 red flashes in any one-second period, or
- flashes below that rate whose combined area exceeds the allowed portion of a 10-degree
  visual field.

The analyzer computes relative luminance per pixel, looks for opposing luminance changes,
counts flash events in sliding one-second windows, and checks flashing area.

## Development

```bash
pip install -e .
pip install pytest ruff
ruff check .
pytest
```

Regression examples are in `examples/` (`4882.mp4` should be flagged; `giphy/*.gif` are known
triggering GIFs). Planning and design notes live in `planning/`.

## Scope

In scope: the reusable analysis engine, a thin CLI, and a stable structured result.

Out of scope: platform integrations (the original Discord bot is now only a motivating example),
downloading URLs, moderation actions, storage, and hosted services. Those belong to the
consuming application.

## Limitations

This is a heuristic safety aid, not a medical device or a guarantee. It approximates the WCAG
area rule and can miss some patterns or flag benign motion. Defaults are conservative; review
the reported reasons before taking irreversible action.
