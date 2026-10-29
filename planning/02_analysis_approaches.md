# Analysis Approaches for Detecting Photosensitive Triggers

The detector must be fast, deterministic, offline, and implementable in both Python and Go.
This document compares approaches independently of the original Discord bot.

## 1) Frame-difference / luminance threshold approach (recommended)

This is the approach used by broadcast tooling such as Harding FPA and PEAT, and it maps
directly to WCAG 2.3.1.

Core idea:
- Decode frames with timestamps (or use caller-supplied frames)
- Compute relative luminance per pixel (sRGB, gamma-corrected)
- Detect opposing luminance transitions that exceed the WCAG threshold
- Pair up/down transitions into flash events
- Track saturated-red transitions separately
- Count flashes in sliding one-second windows using real timestamps
- Estimate the flashing area and apply the area rule for low-rate flashes

Pros:
- Fast, deterministic, well-understood for this exact problem
- Low compute cost; easy to implement in Python and Go
- Matches the known triggers (full-screen color changes, flashlight effects)
- Directly tunable to WCAG thresholds and explainable in a result

Cons:
- Requires care: pairing transitions, timestamps, area approximation, red saturation
- Depends on reliable frame decoding (GIF disposal modes, variable frame rate video)
- Some complex patterns (localized flicker, camera motion, strobing text) are harder to model

This remains the correct starting point.

## 2) Histogram/HSV change detection

- Track rapid changes in brightness (value) or saturation histograms
- Detect high-frequency oscillation

Pros:
- Simple and cheap
- Robust to small spatial shifts

Cons:
- Does not identify opposing luminance pairs or area
- Higher false-positive rate on motion and scene cuts
- Cannot produce WCAG-aligned evidence

Useful as a **pre-filter or signal**, not as the primary classifier.

## 3) ML/classification

- Train on known-bad examples (`giphy.lst`) and negatives
- Use a small model for inference

Pros:
- Could learn patterns not captured by hand-written rules

Cons:
- Limited labeled data; hard to prove coverage
- Opaque decisions for a safety feature
- Slower and more complex to ship in two languages
- The physical thresholds are already specified by WCAG

Rejected for v1. Revisit only as an optional supplementary signal with a clear dataset and
evaluation story.

## Recommendation

Implement **WCAG-aligned rule-based luminance/red flash detection** as the core, with a clean
separation between decoding and analysis.

### Implementation details needed

- **Frame timing**: per-frame timestamps/durations; never assume 30 fps
- **Decoding**: GIF via the language's native decoder; video via ffmpeg streaming
- **Frame input**: allow callers to supply frames to bypass decoders entirely
- **Color**: convert to sRGB, composite alpha, compute luminance
- **Downsampling**: retain enough resolution for area estimation; record the scale
- **Transition pairing**: identify state changes and form opposing pairs
- **Windowing**: sliding 1-second windows over timestamps
- **Area**: per-cell changed-area map with a documented 10-degree-field approximation
- **Red**: perceptual saturation test plus opposing transition
- **Result**: classification, risk level, reasons, measurements, metadata
- **Parity**: share fixtures and expected outputs between Python and Go

## Known gaps in the current prototype

- Whole-frame average instead of a spatial area map
- Assumed 30 fps instead of real timestamps
- Counts frame differences rather than opposing flash pairs
- Red heuristic is an RGB ratio, not perceptual saturation
- No handling of GIF loop wrap-around
- No typed errors or resource limits for untrusted input

These are planned work items, not reasons to change the approach.
