# Epilepsy Warning Discord Bot

A Discord bot that scans GIFs and short videos for potential photosensitive epilepsy triggers (rapid flashing, high-contrast color changes) based on WCAG 2.1 guidelines.

## Features
- Scans message attachments, embeds, and URLs for GIFs/videos
- Uses WCAG-aligned flash detection (luminance changes, flash rate, area)
- Fast analysis (no LLM) - returns results within seconds
- Configurable actions (warn, delete, react)

## Setup
1. Install dependencies: `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and add your Discord bot token
3. Enable MESSAGE_CONTENT intent in Discord Developer Portal
4. Run: `python src/bot.py`

## Testing
Test the analyzer on examples:
```bash
python src/analyzer_optimized.py examples/4882.mp4
```

## How it works
Based on WCAG 2.1 Success Criterion 2.3.1, detects content with > 3 flashes per second or large flashing areas.
