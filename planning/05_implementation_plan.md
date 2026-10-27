# Implementation Plan

## Phase 1: Research & Setup (immediate)
- [x] Read idea.md and understand requirements
- [x] Look at examples (4882.mp4, giphy.lst)
- [x] Review WCAG flash thresholds
- [x] Create planning docs
- [ ] Examine 4882.mp4 more closely (frame rate, duration) to understand test case
- [ ] Try to understand a sample gif from giphy.lst behavior if possible

## Phase 2: Prototype flash detection (Python)
Goal: Build a standalone analyzer that can classify the example MP4 correctly.

Tasks:
- [ ] Create Python project structure
- [ ] Add dependencies (imageio, numpy, opencv-python or Pillow, ffmpeg)
- [ ] Frame extraction for MP4 and GIF
- [ ] Implement relative luminance calculation
- [ ] Implement flash detection per WCAG rules
- [ ] Test on `examples/4882.mp4` - should detect as triggering
- [ ] Test on a few GIFs from giphy.lst (download or analyze URLs)
- [ ] Tune thresholds if needed

## Phase 3: Discord bot (Python)
- [ ] Set up discord.py/py-cord bot skeleton
- [ ] MESSAGE_CONTENT intent handling
- [ ] Extract attachments/embeds/URLs
- [ ] Integrate analyzer
- [ ] Add size/duration limits
- [ ] Add configuration (.env)
- [ ] Basic actions (log/warn/delete)
- [ ] Error handling, cleanup

## Phase 4: Testing & refinement
- [ ] Test with more examples
- [ ] Performance testing (speed)
- [ ] False positive/negative consideration
- [ ] Documentation

## Phase 5: (Optional) Go port/integration
- [ ] If time/resources allow, consider Go implementation for pen-bot integration

## Immediate next steps
1. Analyze the example MP4 in detail (duration, fps, see if we can peek at frames)
2. Start Python prototype
