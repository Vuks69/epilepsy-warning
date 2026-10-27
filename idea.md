## Problem/idea
Discord bot that scans user messages containing gifs and (small/short) video files (or links) sent by users for potential epilepsy-inducing imagery.

The bot needs to:
- use the MESSAGE_CONTENT intent to get the media to scan
- download the media file
- analyze the file
- declare the file as epilepsy-triggering or not

## Questions
Primary choice is likely the method used to analyze the files. AI/LLM analysis is out of question due to being overkill, too slow and too costly. This needs to be able to return the result within a few seconds, or faster.
Machine learning or some sort of classification/fuzzing could work, but how would we classify gifs?
Photosensitive epilepsy in those could be fast changing colors, levels of brightness etc; could be full-image color switches every frame or be a recording of a flashlight going back and forth in front of the camera.

Once a method is chosen, the framework and bot language need to be selected.
I'm comfortable with Go (using the disgo library), and if necessary, Python (discord.py).
If the implementation is done in Go, it may end up being included in an existing Go discord bot project (../pen-bot/), but that's a secondary consideration/cherry on top, not a priority. A bot like this may well become a useful/popular moderation tool on its own.

## Sources
https://www.epilepsy.com/what-is-epilepsy/seizure-triggers/photosensitivity
https://en.wikipedia.org/wiki/Photosensitive_epilepsy
https://www.w3.org/TR/WCAG21/#seizures-and-physical-reactions

## Examples for testing
./examples/4882.mp4 is a video where the frames are one uniform color, changing color and brightness at random intervals.
./examples/giphy.lst is a collection of direct gif links that are considered as seizure-inducing (aka would be removed in a discord server by a moderator).
