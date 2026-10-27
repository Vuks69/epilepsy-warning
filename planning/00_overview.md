# Project Overview: Epilepsy Warning Discord Bot

## Problem statement recap
Discord bot that scans user messages containing gifs and (small/short) video files (or links) sent by users for potential epilepsy-inducing imagery. It needs to:
- use the MESSAGE_CONTENT intent to get the media to scan
- download the media file
- analyze the file
- declare the file as epilepsy-triggering or not

Constraints/requirements:
- Must return result within a few seconds or faster (AI/LLM is out of question - overkill, too slow, too costly)
- Analyze gifs and small/short video files (or links)
- Focus on photosensitive epilepsy triggers (fast changing colors/brightness, full-image flashes, flashlight effects)

## Examples
- `./examples/4882.mp4` - frames are uniform color changing randomly at intervals (obviously flashing)
- `./examples/giphy.lst` - collection of direct gif links considered seizure-inducing

## References
- https://www.epilepsy.com/what-is-epilepsy/seizure-triggers/photosensitivity
- https://en.wikipedia.org/wiki/Photosensitive_epilepsy
- https://www.w3.org/TR/WCAG21/#seizures-and-physical-reactions
