"""Performance budget: a relative per-frame-cost guard across frame rates.

This is not a hard absolute wall (which would fork on machine/CI speed) but a
*relative* regression guard: the per-frame cost at the busiest frame rate must
not regress relative to the cheapest. Machine speed largely cancels in a ratio
of two same-machine timings, so the guard is machine-independent by design.

Why a ratio at all. The engine keeps an ``_history`` sliding window keyed on the
66 ms transition cutoff (``AnalysisOptions.sample_fps``). That window accumulates
more entries per window as the frame rate rises, so the per-frame cost of the
transition machinery legitimately grows with ``fps`` -- 120 fps does more history
work per frame than 24 fps. The guard therefore does *not* expect constant
per-frame cost across rates; it expects the growth to stay within the band the
detector legitimately requires, and fails only if a change pushes it past that.

Empirical basis. On the dev machine, ``min`` per-frame ``analyze_frames`` cost
over a deterministic two-tone 2 s clip is ~327 µs at 24 fps and ~599 µs at 120
fps, so the observed worst-case ``max/min`` ratio across the 24/30/60/120 sweep
is ~1.85× and stable between runs. ``PER_FRAME_COST_GUARD_FACTOR`` is set to
3.0×, leaving ~60% of headroom above that ceiling to absorb hardware/CI variance
while still failing on a pathological per-frame blowup (e.g. unbounded history
work) that more than 3× the best rate.

Synthetic and deterministic (no media cache, no ffmpeg), so it runs anywhere and
stays fast: one short clip per rate, ``min`` (best case) per frame over a handful
of repeats, comparing the busiest against the cheapest rate.
"""

from __future__ import annotations

import time
import unittest

import numpy as np

from epilepsy_warning import AnalysisOptions, analyze_frames

# Two-tone alternating clip: every frame is a full-solid bright or full-solid
# dark frame, so the whole tile grid is a single transition mask per frame. This
# exercises the area + transition machinery the way real flashing media do,
# without any media cache.
CLIP_SECONDS = 2.0
SIZE = 64

# Per-frame work grows with fps, so sweep the full 24/30/60/120 range; the guard
# compares the busiest against the cheapest.
FRAME_RATES = (24, 30, 60, 120)

# Best-of-this-many timings per rate: `min` is the steady-state lower bound and
# cancels warmup noise.
REPEATS = 7

# Relative guard (see module docstring): worst-rate per-frame cost must stay
# within this multiple of the best-rate per-frame cost.
PER_FRAME_COST_GUARD_FACTOR = 3.0

_OPTIONS = AnalysisOptions(area_model="screen_fraction", tile_grid_max=64)


def _clip(fps: int) -> tuple[list, list]:
    count = int(fps * CLIP_SECONDS)
    timestamps = [i / fps for i in range(count)]
    frames = [
        np.full((SIZE, SIZE, 3), 255 if i % 2 == 0 else 0, dtype=np.uint8) for i in range(count)
    ]
    return frames, timestamps


def _per_frame_seconds(fps: int) -> float:
    frames, timestamps = _clip(fps)
    best = float("inf")
    for _ in range(REPEATS):
        start = time.perf_counter()
        analyze_frames(frames, timestamps, options=_OPTIONS)
        best = min(best, time.perf_counter() - start)
    return best / (fps * CLIP_SECONDS)


class PerFrameCostGuardTests(unittest.TestCase):
    """Worst-rate per-frame cost must not regress beyond the guard band."""

    def test_per_frame_cost_ratio_within_guard(self) -> None:
        per_frame = {fps: _per_frame_seconds(fps) for fps in FRAME_RATES}
        cheapest = min(per_frame.values())
        busiest = max(per_frame.values())
        ratio = busiest / cheapest

        self.assertLess(
            ratio,
            PER_FRAME_COST_GUARD_FACTOR,
            (
                f"per-frame cost regressed {ratio:.2f}x (guard {PER_FRAME_COST_GUARD_FACTOR}x): "
                f"{per_frame!r} µs/frame"
            ),
        )


if __name__ == "__main__":
    unittest.main()
