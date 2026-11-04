"""Property tests: determinism, directed monotonicity, and frame-rate invariance.

Exemplar tests (``test_engine``/``test_area``, ``test_media``) assert a
known-correct output for a specific input, and the golden-media module
(``test_golden_media``) asserts verdicts over the real media cache. Those all
prove the detector gets *these* cases right. Property tests instead encode
invariants that must hold for *arbitrarily many* inputs and let Hypothesis throw
random timelines at them, catching regressions in the structure of the detector
(ordering, hashing, threshold direction) that a handful of fixtures cannot, and
documenting the intended semantics as executable spec.

Three invariants are covered here.

- **Determinism.** The same input under the same options is byte-stable: two
  fresh analyses produce identical ``to_json()`` and ``to_dict()``. The result
  is a frozen dataclass with no global RNG, so this is expected; the property is
  the guard against a change that reintroduced order- or nondeterminism (a
  dict/set leak into output, float rounding, shared mutable state).

- **Directed monotonicity.** Pushing an input "more flashing" never un-triggers
  it. This is one-directional and all-else-equal: (1) a qualifying transition's
  critical difference only grows as the step grows, (2) a qualifying flash's
  area only grows as *both* transition masks scale up together, and (3) a
  triggering clip stays triggering as more valid alternating transitions are
  added. None of these claim "bigger -> safe": a safe clip may become
  triggering, never the reverse. The all-else-equal framing matters -- the area
  guard rejects lopsided changes, so only uniform scaling is asserted.

- **Frame-rate invariance.** The detector keys on transitions in time, not on
  how densely the timeline is sampled. Densifying a clip by repeating each frame
  an integer number of times with interpolated timestamps preserves the verdict
  and the transition-level measurements. The reported
  ``max_transition_duration_ms`` is *not* invariant: a coarse single-frame step
  measured as 0 ms at low density resolves to a genuine duration at high
  density.

These are synthetic, so no media cache is needed. Hypothesis properties live
inside ``unittest.TestCase`` subclasses so the stdlib test runner discovers
them.

"""

from __future__ import annotations

import unittest

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from epilepsy_warning import AnalysisOptions, analyze_frames


def _alternating(lo: int, hi: int, count: int, dt: float, size: int) -> tuple[list, list]:
    """A solid-frame clip alternating between two luminance levels."""
    frames = [
        np.full((size, size, 3), lo if i % 2 == 0 else hi, dtype=np.uint8) for i in range(count)
    ]
    timestamps = [i * dt for i in range(count)]
    return frames, timestamps


def _patch_clip(bg: int, fg: int, patch: int, count: int, dt: float, size: int):
    """Alternate a centered ``fg`` patch over a ``bg`` background (both frames)."""
    origin = (size - patch) // 2
    frames, timestamps = [], []
    for index in range(count):
        frame = np.full((size, size, 3), bg, dtype=np.uint8)
        if index % 2 == 1:
            frame[origin : origin + patch, origin : origin + patch] = fg
        frames.append(frame)
        timestamps.append(index * dt)
    return frames, timestamps


def _densify(frames: list, timestamps: list, repeat: int) -> tuple[list, list]:
    """Repeat each frame ``repeat`` times, inserting duplicates at interpolated
    timestamps so the original transition times are preserved."""
    out_frames, out_times = [], []
    gaps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
    gaps.append(gaps[-1] if timestamps else 1.0)
    for index, value in enumerate(frames):
        gap = gaps[index]
        for offset in range(repeat):
            out_frames.append(value)
            out_times.append(timestamps[index] + offset * gap / repeat)
    return out_frames, out_times


class DeterminismTests(unittest.TestCase):
    @settings(max_examples=60)
    @given(
        lo=st.integers(0, 128),
        hi=st.integers(129, 255),
        count=st.integers(3, 16),
        dt=st.sampled_from([0.02, 0.03, 0.04, 0.05]),
        size=st.sampled_from([16, 24]),
        area_model=st.sampled_from(["screen_fraction", "wcag_solid_angle", None]),
    )
    def test_analysis_is_byte_stable(self, lo, hi, count, dt, size, area_model) -> None:
        # Same input under the same options must serialize identically, every time.
        options = AnalysisOptions(area_model=area_model, tile_grid_max=64)
        frames, timestamps = _alternating(lo, hi, count, dt, size)
        first = analyze_frames(frames, timestamps, options=options)
        second = analyze_frames(frames, timestamps, options=options)
        assert first.to_json() == second.to_json()
        assert first.to_dict() == second.to_dict()


class RateMonotonicityTests(unittest.TestCase):
    @settings(max_examples=40)
    @given(
        lo=st.integers(0, 120),
        hi=st.integers(150, 255),
        dt=st.sampled_from([0.03, 0.04, 0.05]),
        size=st.sampled_from([16, 24]),
    )
    def test_rate_is_monotone_as_transitions_increase(self, lo, hi, dt, size) -> None:
        # All-else-equal: the spacing and levels are fixed, only the transition count
        # grows, so a triggering clip must never un-trigger.
        options = AnalysisOptions(area_model="screen_fraction", tile_grid_max=64)
        previous = None
        for transitions in range(3, 17):
            frames, timestamps = _alternating(lo, hi, transitions, dt, size)
            result = analyze_frames(frames, timestamps, options=options)
            current = result.is_triggering
            if previous is not None:
                assert previous <= current, (
                    f"un-triggered going {transitions - 1} -> {transitions} transitions"
                )
            previous = current


class AreaMonotonicityTests(unittest.TestCase):
    @settings(max_examples=40)
    @given(
        bg=st.integers(0, 80),
        fg=st.integers(175, 255),
        base=st.integers(6, 16),
        dt=st.sampled_from([0.03, 0.04, 0.05]),
        size=st.just(32),
    )
    def test_flash_area_is_monotone_as_uniform_patch_grows(self, bg, fg, base, dt, size) -> None:
        # Both transition frames carry the same centered patch, so scaling the patch
        # scales *both* masks uniformly -- the invariant the area guard preserves.
        options = AnalysisOptions(area_model="screen_fraction", tile_grid_max=64)
        previous = None
        for patch in range(base, size + 1, 2):
            frames, timestamps = _patch_clip(bg, fg, patch, 8, dt, size)
            result = analyze_frames(frames, timestamps, options=options)
            current = result.is_triggering
            if previous is not None:
                assert previous <= current, f"un-triggered going patch {patch - 2} -> {patch}"
            previous = current


class CriticalDifferenceMonotonicityTests(unittest.TestCase):
    @settings(max_examples=40)
    @given(
        hi=st.integers(175, 255),
        lo0=st.integers(120, 160),
        dt=st.sampled_from([0.03, 0.04, 0.05]),
        size=st.just(32),
    )
    def test_critical_difference_is_monotone_as_step_grows(self, hi, lo0, dt, size) -> None:
        # wcag_relative qualifies when (high - low) >= threshold and low < 0.8.
        # Lowering the dark level only widens the step and keeps low < 0.8, so a
        # clip that qualifies can never fall back out as the step grows.
        options = AnalysisOptions(area_model="screen_fraction", tile_grid_max=64)
        previous = None
        for low in range(lo0, lo0 - 24, -3):
            frames, timestamps = _alternating(low, hi, 8, dt, size)
            result = analyze_frames(frames, timestamps, options=options)
            current = result.is_triggering
            if previous is not None:
                assert previous <= current, (
                    f"un-triggered going step {hi - (low + 3)} -> {hi - low}"
                )
            previous = current


class DensificationTests(unittest.TestCase):
    @settings(max_examples=60)
    @given(
        lo=st.integers(0, 128),
        hi=st.integers(129, 255),
        dt=st.floats(
            min_value=0.04,
            max_value=0.10,
            allow_nan=False,
            allow_infinity=False,
            allow_subnormal=False,
        ),
        base_count=st.integers(4, 10),
        repeat=st.integers(2, 4),
        size=st.just(32),
    )
    def test_densification_preserves_verdict_and_measurements(
        self, lo, hi, dt, base_count, repeat, size
    ) -> None:
        # Duplicating frames changes sampling density, not the transitions, so the
        # verdict and every transition-level measurement is preserved.
        options = AnalysisOptions(area_model="screen_fraction", tile_grid_max=64)
        timestamps = [i * dt for i in range(base_count)]
        frames = [
            np.full((size, size, 3), lo if i % 2 == 0 else hi, dtype=np.uint8)
            for i in range(base_count)
        ]
        base = analyze_frames(frames, timestamps, options=options)

        densified_frames, densified_times = _densify(frames, timestamps, repeat)
        assert len(densified_times) > len(timestamps)
        dens = analyze_frames(densified_frames, densified_times, options=options)

        assert dens.is_triggering == base.is_triggering
        assert dens.measurements.luminance_transitions == base.measurements.luminance_transitions
        assert dens.measurements.red_transitions == base.measurements.red_transitions
        assert dens.measurements.max_flashes_per_second == base.measurements.max_flashes_per_second
        assert (
            dens.measurements.max_luminance_transitions_per_second
            == base.measurements.max_luminance_transitions_per_second
        )


class DensificationSmokeTests(unittest.TestCase):
    """A couple of fixed cases pin the canonical steady-rate invariant."""

    def _options(self) -> AnalysisOptions:
        return AnalysisOptions(area_model="screen_fraction", tile_grid_max=64)

    def test_steady_alternation_preserved_on_densify(self) -> None:
        options = self._options()
        frames, timestamps = _alternating(0, 255, 8, 0.04, 48)
        base = analyze_frames(frames, timestamps, options=options)
        densified_frames, densified_times = _densify(frames, timestamps, 3)
        dens = analyze_frames(densified_frames, densified_times, options=options)
        self.assertEqual(dens.is_triggering, base.is_triggering)
        self.assertEqual(
            dens.measurements.max_luminance_transitions_per_second,
            base.measurements.max_luminance_transitions_per_second,
        )


if __name__ == "__main__":
    unittest.main()
