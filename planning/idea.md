## Problem/idea

Developers routinely display user-supplied GIFs and short videos without checking them for
photosensitive epilepsy triggers. A Discord bot was the original motivating use case, but the
actual reusable value is the **detection engine**, not the bot.

Build a **code library** that other Python and Go projects can embed to answer one question:

> Does this media file contain flashing content that is likely to trigger photosensitive epilepsy?

The library should:
- accept a local file, raw bytes, or caller-supplied frames
- detect general luminance flashes and red flashes using WCAG 2.2 SC 2.3.1 thresholds by default,
  with optional ISO/ITU-R/Ofcom/Japan profiles
- return a structured, stable result (classification, evidence, limits, version)
- run offline and fast enough for interactive moderation/upload flows (seconds or faster)
- avoid LLM/ML inference entirely

The library should **not** own:
- Discord (or any chat platform) event handling
- downloading media from URLs
- moderation actions (warn/delete/react)
- persistent storage
- a hosted service

Those belong to the consuming application. A Discord bot can be shipped later as an example
consumer, but it is not part of this project's scope.

## Consumers

- Chat/moderator bots (Discord, Matrix, Slack, ...)
- Social/media upload pipelines that warn or block before publishing
- CMS and forum software
- CI checks for media assets
- Desktop/mobile backends written in Python or Go

## Questions

Primary choice is the detection method. AI/LLM analysis is out of the question due to being
overkill, too slow and too costly. This needs to be able to return the result within a few
seconds, or faster. Rule-based luminance/flash analysis maps directly to WCAG and the known
examples.

Language strategy is the second question:
- one shared implementation with bindings, or
- native implementations in both Python and Go, kept consistent by a shared spec and
  conformance fixtures?

See `03_tech_stack.md` for the options and recommendation. The plan assumes a Python reference
implementation first, followed by a native Go port validated against the same fixtures.

## Sources

https://www.epilepsy.com/what-is-epilepsy/seizure-triggers/photosensitivity
https://en.wikipedia.org/wiki/Photosensitive_epilepsy
https://www.w3.org/TR/WCAG22/#seizures-and-physical-reactions
https://dl.acm.org/doi/10.1145/3694790

## Examples for testing

- `./examples/triggering/4882.mp4` is a video where the frames are one uniform color, changing
  color and brightness at random intervals.
- `./examples/triggering.lst` is a collection of direct GIF links that are considered
  seizure-inducing (they would be removed in a Discord server by a moderator).
- `./examples/triggering/*.gif` are downloaded copies of those links for offline tests.
- `./examples/not-triggering.lst` and `./examples/not-triggering/*.gif` are benign controls
  (motion, transparency, benign animation) that must not be flagged.
