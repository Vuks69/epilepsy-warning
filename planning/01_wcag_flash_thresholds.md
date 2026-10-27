# WCAG Flash Thresholds (Key for Detection)

From WCAG 2.1 Success Criterion 2.3.1 "Three Flashes or Below Threshold":

A page/web content is acceptable if:
- No more than 3 general flashes and/or no more than 3 red flashes within any one-second period; OR
- The combined area of flashes occurring concurrently occupies no more than a total of ~0.006 steradians within any 10 degree visual field on the screen (25% of any 10 degree visual field) at typical viewing distance

## Definitions
- **Flash**: A pair of opposing changes in relative luminance that can cause seizures if large/bright enough in right frequency range
- **General flash**: Pair of opposing changes in relative luminance of 10% or more of max relative luminance (1.0) where darker image is below 0.80. "Pair of opposing changes" = increase followed by decrease or vice versa.
- **Red flash**: Any pair of opposing transitions involving a saturated red
- **Blinking**: Switches between visual states to draw attention (distraction) - different from flashing
- **Relative luminance (sRGB)**: L = 0.2126*R + 0.7152*G + 0.0722*B with gamma correction as per spec

## Practical implications for detection
- We need to detect rapid changes in luminance (and red saturation) across frames
- Count flashes per second (transitions) - if > 3 per second in any window, likely problematic
- If 3 or fewer flashes, need to check area - small flashing areas may be ok even if fast? Or combined area matters
- Both time-based and spatial-based rules apply
- Need to consider the full frame or regions? "combined area of flashes occurring concurrently" - so localized large flashes vs full screen flashes matter
- For full-screen uniform color changes like in the example MP4 (colors changing randomly), almost entire frame is flashing rapidly - definitely over threshold

## Notes from spec
- 10 degree visual field reference ~ 341 x 256 CSS pixels at 1024x768 (historical) - but modern approach: use consistent size relative to visual field; effectively large areas are more dangerous
- For GIFs that loop, analyze while looping
- Color space matters (sRGB assumed by default)
- Red flashes have special stricter consideration
