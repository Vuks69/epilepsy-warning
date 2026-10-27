# Architecture

## Bot flow
1. **Listen for messages** with MESSAGE_CONTENT intent (Discord bot needs privileged intent)
2. **Extract media** from message: attachments (images/gifs/videos), embeds, URLs in content
3. **Filter** to supported types: GIF, MP4, WebM, short videos; also direct gif links
4. **Download** media to temp storage (with size limits - "small/short" mentioned)
5. **Analyze** using flash detection algorithm
6. **Take action**: flag/warn/delete based on config (plan should be flexible). At minimum return classification result.
7. **Cleanup** temp files

## Components

### Discord client
- Handle events (on_message)
- Parse attachments/embeds/URLs
- Permissions/ratelimits

### Media fetcher
- Download from URLs (giphy links in examples are direct gif URLs)
- Handle redirects
- Size/duration limits
- MIME type detection

### Frame extractor
- **GIF**: Extract all frames + frame durations
- **Video (MP4/WebM)**: Extract frames at sampling rate (e.g., every frame or downsampled; need to catch flashes so may need decent sampling). Or decode at native framerate.
- Tools: `imageio`, `Pillow`, `opencv`, `ffmpeg-python`, or call `ffmpeg` directly

### Flash detector (core)
Input: list of frames with timestamps/durations
Steps:
1. Convert each frame to RGB/sRGB
2. Compute relative luminance for each pixel: L = 0.2126*R + 0.7152*G + 0.0722*B (gamma corrected)
3. For analysis, can work on full frame or downsampled for speed; need to consider area threshold
4. Detect luminance changes between consecutive frames
5. Find flash pairs (opposing transitions) - increase then decrease or decrease then increase exceeding threshold
6. Track red flashes separately (saturated red transitions)
7. Count flashes per 1-second sliding window
8. Check area: if > 3 flashes/sec, bad. If <= 3 flashes/sec, check if combined flashing area exceeds 25% of 10° visual field (~25% of frame in normalized terms?)
9. Return (is_triggering: bool, confidence/reasons, details)

### Configuration
- Thresholds (maybe configurable)
- Max file size / max duration
- Action: warn, delete message, add reaction, log
- Whitelist/blacklist
- Channels to monitor

## Storage/temp
- Use temp directory, clean up after analysis
- Don't store media long-term
