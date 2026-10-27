# Analysis Approaches for Detecting Photosensitive Triggers

We need fast, lightweight detection (no heavy LLM). Possible approaches:

## 1) Frame-difference / luminance threshold approach (classic PEAT-like)
This is similar to the Harding FPA/PEAT tools used in broadcasting. Core idea:
- Extract frames from GIF/video at a reasonable rate (or all frames)
- For each frame compute relative luminance for pixels (or average/region)
- Detect transitions: look for pairs (up/down) in luminance that cross threshold
- Track flashes per second and size of flashing area
- Apply WCAG-style rules

Pros:
- Fast, deterministic, well-understood for this exact problem
- Low compute cost, can run in Go/Python easily
- Matches the kind of triggers described (full-screen color changes, flashlight effects)
- Can be tuned to WCAG thresholds

Cons:
- May miss some complex patterns; need careful implementation
- Need good frame extraction (ffmpeg/gifski etc)
- Red flashes need special handling

## 2) Histogram/HSV change detection
- Look at rapid changes in brightness/value or saturation
- Detect high-frequency oscillation

Less precise than luminance transition pairs, but simpler.

## 3) ML/classification (but user said avoid heavy/slow/costly)
- Could train on examples (we have giphy.lst of known bad ones)
- But collecting/training is effort; inference might be fast with small model but still more complex than rule-based
- Maybe possible later, but rule-based is better starting point

## Recommendation: Start with WCAG-aligned rule-based luminance flash detection
This directly maps to the problem and matches examples (uniform color changes = big luminance swings). Tools like PEAT use this approach.

### Implementation details needed
- Frame extraction: for GIF use `giflib`/`image/gif` or `ffmpeg`; for MP4 use `ffmpeg`/`avcodec`
- Color space conversion to sRGB, compute relative luminance per pixel
- Downsample? Or analyze full frame - area matters. But analyzing every pixel every frame can be expensive for large videos; might need to downsample to reasonable resolution
- Find flash events: detect when luminance crosses thresholds creating opposing transitions
- Count flashes in sliding 1-second windows
- Track contiguous flashing areas
- Red flash detection: check for saturated red transitions
