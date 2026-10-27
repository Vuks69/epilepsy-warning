# Tech Stack Selection

User preferences:
- Comfortable with Go (disgo) or Python (discord.py)
- If Go and ends up in ../pen-bot/ that's a bonus but not priority - build as standalone useful bot first
- Must be fast enough (seconds or faster), no LLM

## Options

### Option A: Go + disgo
Pros:
- Fast, efficient, single binary
- User knows it well, could integrate into pen-bot later
- Good for performance if processing many frames
- Libraries: `github.com/disgoorg/disgo`, `github.com/disgoorg/disgo/bot` etc
- Image/video: can use `ffmpeg` via exec or libraries like `gocv` (heavy deps) or `goav`, or easier use external ffmpeg
- GIF: `image/gif` in stdlib is possible but limited; may need to decode frames
- HTTP: stdlib/fiber etc

Cons:
- Frame decoding/video processing in pure Go can be cumbersome; often easier to shell out to ffmpeg
- Some libraries less mature

### Option B: Python + discord.py (or py-cord/nextcord)
Pros:
- Rich ecosystem for image/video processing: PIL/Pillow, opencv-python, imageio, moviepy
- Easy to prototype flash detection
- Quick to get working
- Can use `imageio` to read GIF frames directly

Cons:
- More overhead than Go, but still probably fast enough for small/short media
- Deployment different (needs Python env)

## Recommendation
Start with **Python** for rapid prototyping of the detection algorithm - easier to test against the examples and iterate on WCAG thresholds. Once algorithm is solid and working well, can port to Go if desired for integration into pen-bot or performance.

But let us look up what's available - check if there might be existing patterns. Also the user says "framework and bot language need to be selected" - we need to plan both.

Alternatively maybe use Go with ffmpeg subprocess calls - that's practical. Let us design for either but pick one to start implementing plan.

Given examples exist and we need to analyze them, Python is faster to experiment with. Let us plan for Python first as the initial implementation path.
