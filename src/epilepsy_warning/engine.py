"""Temporal transition engine.

A flash is a pair of opposing transitions.  The engine tracks per-tile
luminance and color state, accepts only changes that reach the critical
difference within the qualifying duration, synchronizes same-direction areas,
counts alternating transitions in sliding one-second windows, and merges fast
flashes.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

try:
    from line_profiler import profile  # type: ignore
except ImportError:

    def profile(func):  # type: ignore
        return func


from .area import AreaEvaluation, AreaEvaluator
from .color import (
    linear_rgb_features,
    srgb_to_linear,
    ucs_distance_squared,
)
from .options import AnalysisOptions
from .standards import StandardProfile

_LUMINANCE = "luminance"
_RED = "red"
_LOCAL_EXTREMUM_TOLERANCE = 0.002

# Quick mode confirms at most this many prefix passes before the guard stops
# tripping; dense-but-safe content then falls through to one normal finish.
_QUICK_MAX_CONFIRMATIONS = 16


@dataclass(frozen=True)
class _HistoryRecord:
    timestamp: float
    luminance: np.ndarray
    red: np.ndarray
    redness: np.ndarray
    u: np.ndarray
    v: np.ndarray


@dataclass
class _Bucket:
    kind: str
    direction: int
    start_time: float
    mask: np.ndarray
    max_duration_ms: float


@dataclass(frozen=True)
class TransitionCandidate:
    kind: str
    direction: int
    start_time: float
    duration_ms: float
    mask: np.ndarray
    area: AreaEvaluation


@dataclass(frozen=True)
class TransitionEvent:
    kind: str
    direction: int
    start_time: float
    duration_ms: float
    mask: np.ndarray
    area: AreaEvaluation
    raw_transitions: int = 1
    fast_merged: bool = False
    merged_from: int = 0


@dataclass(frozen=True)
class EngineResult:
    is_triggering: bool
    reasons: List[str]
    luminance_transitions: int
    red_transitions: int
    max_luminance_transitions_per_second: int
    max_red_transitions_per_second: int
    max_luminance_flashes_per_second: float
    max_red_flashes_per_second: float
    max_flashes_per_second: float
    max_area_px2: float
    area_threshold_px2: float
    max_flashing_area_ratio: float
    max_flashing_area_screen_fraction: float
    max_transition_duration_ms: float
    synchronized_area_merges: int
    fast_flash_sequences: int
    merged_fast_flash_transitions: int
    extended_exposure_advisory: bool = False


class TransitionEngine:
    """Stateful per-frame analyzer for one media item."""

    def __init__(
        self,
        options: AnalysisOptions,
        profile: StandardProfile,
        area_evaluator: AreaEvaluator,
    ) -> None:
        self.options = options
        self.profile = profile
        self.area = area_evaluator
        self.max_duration_s = options.max_transition_duration_ms / 1000.0
        self.sync_window_s = options.synchronicity_window_ms / 1000.0
        self.fast_gap_s = 1.0 / options.fast_flash_hz

        shape = (area_evaluator.grid.rows, area_evaluator.grid.cols)
        self._last_luminance_direction = np.zeros(shape, dtype=np.int8)
        self._last_red_direction = np.zeros(shape, dtype=np.int8)
        self._history: List[_HistoryRecord] = []
        # Whole-window saturated-red state, maintained incrementally for the
        # red detector's early-out guard.  Appending only ever adds red tiles,
        # so the pool grows as the window fills; a prune rebuilds it, until
        # which it may be a conservative superset (a false "has red" only lets
        # the detector run, never makes it misfire).
        self._red_pool = np.zeros(shape, dtype=bool)
        # The most recent tile grid, for the duplicate-frame skip.  The decoder
        # replaces (never mutates) its canvas, so a bare reference is stable.
        self._last_grid: Optional[np.ndarray] = None
        # When False, every Phase 3 short-circuit is disabled and the engine is
        # byte-for-byte the pre-optimization detector.  Kept on the instance
        # (not an AnalysisOptions field) so an equivalence test can toggle it
        # without touching public configuration or the result schema.
        self._enable_short_circuit = True
        # Did the most recently *detected* frame flip either direction state?
        # The duplicate-frame skip is only safe when this is False: processing a
        # duplicate of the previous frame is a no-op only if the previous frame
        # left both direction states unchanged, in which case the duplicate
        # (identical grid, identical history tail) makes the identical choice.
        # A duplicate following a direction change can itself complete a flash
        # pair (e.g. down then immediately up), so only the frames after such a
        # change are skippable.  The flag is left untouched when a frame is
        # skipped, so a whole static run stays gated on the first processed frame.
        self._last_frame_changed_direction = False
        self._buckets: Dict[Tuple[str, int, float], _Bucket] = {}
        # Timestamps at which new buckets are created, used by the quick-mode
        # guard to count qualifying transitions within a sliding second.
        self._bucket_created_at: Deque[float] = deque()
        # Number of quick-mode confirmations run so far; throttled so that
        # high-transition-but-safe content cannot drive unbounded work.
        self._quick_confirmations = 0

    @profile
    def add_frame(self, timestamp: float, tiles_rgb: np.ndarray) -> None:
        linear = srgb_to_linear(tiles_rgb)
        luminance, redness, red, u, v = linear_rgb_features(linear, self.options.red_saturation)
        record = _HistoryRecord(
            timestamp=float(timestamp),
            luminance=luminance,
            red=red,
            redness=redness,
            u=u,
            v=v,
        )
        self._history.append(record)

        cutoff = timestamp - self.max_duration_s
        pruned = False
        while len(self._history) >= 2 and self._history[1].timestamp < cutoff:
            self._history.pop(0)
            pruned = True

        # Keep the whole-window red pool in sync with the sliding window.  Only
        # run when the red guard is active; when disabled this is dead weight
        # avoided entirely so the disabled path matches the old code exactly.
        if self._enable_short_circuit:
            if red.any():
                self._red_pool |= red
            if pruned:
                # A pop invalidates the running OR, so rebuild it.  Until the
                # next prune the pool may be a conservative superset, which is
                # safe: the guard only ever lets the detector run, never fires
                # a false red transition.
                self._red_pool = self._history[0].red
                for previous in self._history[1:]:
                    self._red_pool |= previous.red

        if len(self._history) < 2:
            return

        # Duplicate-frame short-circuit.  Skip the per-frame detection pass when
        # the new tile grid is elementwise identical to the previous frame's
        # *and* the sliding window did not shrink this frame.  Equal pixels make
        # every (record -> now) pair identical to the (record -> previous) pair
        # already processed, and no prune means the record set is identical too
        # (the only addition is the previous frame itself, a zero-difference
        # no-op); the local-extremum suffix extrema are unchanged because the
        # appended equal frame duplicates the window tail, so the duplicate makes
        # the identical up/down choice and changes no bucket.  That reasoning
        # holds only when the previous frame changed *neither* direction state:
        # a duplicate following a direction change can itself complete a flash
        # pair (a "down then immediately up"), which would move the direction
        # state and cascade into later buckets.  ``_last_frame_changed_direction``
        # is left untouched on a skip, so an entire static run stays gated on the
        # first frame that actually ran detection.
        if (
            self._enable_short_circuit
            and not pruned
            and not self._last_frame_changed_direction
            and self._last_grid is not None
            and np.array_equal(tiles_rgb, self._last_grid)
        ):
            self._last_grid = tiles_rgb
            return
        self._last_grid = tiles_rgb

        self._detect_luminance(timestamp, cutoff)
        self._detect_red(timestamp, cutoff)

    def finish(self) -> EngineResult:
        candidates = self._candidates()
        events = self._synchronized_events(candidates)

        luminance_events = self._alternating([e for e in events if e.kind == _LUMINANCE])
        red_events = self._alternating([e for e in events if e.kind == _RED])
        luminance_events = self._qualify_by_flash_area(luminance_events)
        red_events = self._qualify_by_flash_area(red_events)
        # Dropping non-qualifying flashes can leave two same-direction events
        # adjacent; enforce alternation again before rate counting.
        luminance_events = self._alternating(luminance_events)
        red_events = self._alternating(red_events)

        fast_sequences = 0
        merged_transitions = 0
        if self.options.enable_fast_flash_merge:
            luminance_events, sequences, merged = self._merge_fast(luminance_events)
            fast_sequences += sequences
            merged_transitions += merged
            red_events, sequences, merged = self._merge_fast(red_events)
            fast_sequences += sequences
            merged_transitions += merged

        luminance_times = [e.start_time for e in luminance_events]
        red_times = [e.start_time for e in red_events]
        max_luminance_window = self._max_in_window(luminance_times, 1.0)
        max_red_window = self._max_in_window(red_times, 1.0)
        limit = self.options.max_transitions_per_second

        luminance_exceeded = max_luminance_window > limit
        red_exceeded = max_red_window > limit
        reasons: List[str] = []
        if luminance_exceeded:
            reasons.append("luminance_transition_rate_exceeded")
        if red_exceeded:
            reasons.append("red_transition_rate_exceeded")

        final_events = luminance_events + red_events
        max_area = max((e.area.area_px2 for e in final_events), default=0.0)
        max_area_ratio = max((e.area.area_ratio for e in final_events), default=0.0)
        max_area_fraction = max((e.area.screen_fraction for e in final_events), default=0.0)
        max_duration = max((e.duration_ms for e in final_events), default=0.0)

        extended_advisory = False
        if self.options.extended_exposure:
            extended_advisory = self._extended_exposure_advisory(
                [e.start_time for e in final_events],
                self.options.max_transitions_per_second,
            )

        return EngineResult(
            is_triggering=luminance_exceeded or red_exceeded,
            reasons=reasons,
            luminance_transitions=len(luminance_events),
            red_transitions=len(red_events),
            max_luminance_transitions_per_second=max_luminance_window,
            max_red_transitions_per_second=max_red_window,
            max_luminance_flashes_per_second=max_luminance_window / 2.0,
            max_red_flashes_per_second=max_red_window / 2.0,
            max_flashes_per_second=max(max_luminance_window, max_red_window) / 2.0,
            max_area_px2=max_area,
            area_threshold_px2=self.area.threshold_px2,
            max_flashing_area_ratio=max_area_ratio,
            max_flashing_area_screen_fraction=max_area_fraction,
            max_transition_duration_ms=max_duration,
            synchronized_area_merges=self._synchronized_area_merges,
            fast_flash_sequences=fast_sequences,
            merged_fast_flash_transitions=merged_transitions,
            extended_exposure_advisory=extended_advisory,
        )

    def quick_finish(self) -> EngineResult:
        """Confirm or clear a quick-mode verdict over what has been seen.

        The caller runs this from quick mode once the cheap guard trips: it is
        exactly :meth:`finish`, so its verdict uses the same logic as a full
        scan.  A triggering verdict here is evidence that the working values
        were exceeded *within the frames analyzed so far*; a later frame can
        still merge a fast sequence back to safe, so this can over-report.
        Quick mode never under-reports: it only stops on this verdict and, if
        it is not triggering, keeps scanning to completion.
        """
        self._quick_confirmations += 1
        return self.finish()

    # -- quick mode ----------------------------------------------------

    def quick_should_finish(self, now: float) -> bool:
        """Return True once a full pass is worth running to confirm a verdict.

        Counts qualifying transitions (raw buckets, measured before the
        alternating and area-qualification steps, so it over-counts and errs
        toward flagging) created within the last second and trips past the
        transition limit.  It is a recall-biased probe, not a verdict: the
        confirmation in ``quick_finish`` is what actually decides.  Confirmation
        is throttled so that dense-but-safe content cannot drive unbounded work.
        The window is trimmed before the cap check so the deque never grows past
        one second regardless of how many confirmations have run.
        """
        while self._bucket_created_at and self._bucket_created_at[0] < now - 1.0:
            self._bucket_created_at.popleft()
        if self._quick_confirmations >= _QUICK_MAX_CONFIRMATIONS:
            return False
        return len(self._bucket_created_at) > self.options.max_transitions_per_second

    # -- detection ----------------------------------------------------

    @profile
    def _detect_luminance(self, timestamp: float, cutoff: float) -> None:
        history = self._history
        count = len(history)
        now = history[-1]
        times = [record.timestamp for record in history]
        shape = now.luminance.shape

        suffix_min = [None] * count
        suffix_max = [None] * count
        running_min = now.luminance.copy()
        running_max = now.luminance.copy()
        for index in range(count - 1, -1, -1):
            running_min = np.minimum(history[index].luminance, running_min)
            running_max = np.maximum(history[index].luminance, running_max)
            suffix_min[index] = running_min
            suffix_max[index] = running_max

        up_difference = np.full(shape, -1.0, dtype=np.float32)
        down_difference = np.full(shape, -1.0, dtype=np.float32)
        up_index = np.full(shape, -1, dtype=np.int16)
        down_index = np.full(shape, -1, dtype=np.int16)

        # A hard cut sampled at a low frame rate has no start frame inside the
        # 66 ms history cutoff.  Treat an immediate single-frame step as
        # instantaneous when the sample interval itself exceeds the cutoff;
        # the source transition cannot be resolved more finely than one frame.
        # The duration is reported as 0 for these steps (see ``_record``).
        step_index = count - 2
        step_is_coarse = step_index >= 0 and times[step_index] < cutoff

        for index in range(count - 2, -1, -1):
            is_coarse_step = index == step_index and step_is_coarse
            if times[index] < cutoff and not is_coarse_step:
                continue
            record = history[index]
            # suffix_min/suffix_max were fully populated by the forward pass
            # above; mypy still reads them as None and flags None + float, so
            # silence the operator errors here.
            if index == 0:
                local_min = record.luminance <= suffix_min[index] + _LOCAL_EXTREMUM_TOLERANCE  # type: ignore[operator]
                local_max = record.luminance >= suffix_max[index] - _LOCAL_EXTREMUM_TOLERANCE  # type: ignore[operator]
            else:
                previous = history[index - 1]
                local_min = (record.luminance <= previous.luminance + _LOCAL_EXTREMUM_TOLERANCE) & (
                    record.luminance <= suffix_min[index] + _LOCAL_EXTREMUM_TOLERANCE  # type: ignore[operator]
                )
                local_max = (record.luminance >= previous.luminance - _LOCAL_EXTREMUM_TOLERANCE) & (
                    record.luminance >= suffix_max[index] - _LOCAL_EXTREMUM_TOLERANCE  # type: ignore[operator]
                )

            difference_up = now.luminance - record.luminance
            difference_down = record.luminance - now.luminance
            valid_up = (
                local_min
                & (difference_up > 0)
                & self._luminance_pair_qualifies(record.luminance, now.luminance)
            )
            valid_down = (
                local_max
                & (difference_down > 0)
                & self._luminance_pair_qualifies(now.luminance, record.luminance)
            )

            better = valid_up & (difference_up > up_difference)
            up_difference[better] = difference_up[better]
            up_index[better] = index
            better = valid_down & (difference_down > down_difference)
            down_difference[better] = difference_down[better]
            down_index[better] = index

        up_allowed = (up_index >= 0) & (self._last_luminance_direction != 1)
        down_allowed = (down_index >= 0) & (self._last_luminance_direction != -1)
        both = up_allowed & down_allowed
        choose_up = up_allowed & (~both | (up_difference >= down_difference))
        choose_down = down_allowed & (~both | (~choose_up))

        self._last_luminance_direction[choose_up] = 1
        self._last_luminance_direction[choose_down] = -1
        # choose_up/choose_down only fire where the direction actually flips, so
        # their union is exactly where the state changed this frame.
        self._last_frame_changed_direction = bool((choose_up | choose_down).any())

        instant_up = choose_up & (up_index == step_index) if step_is_coarse else None
        instant_down = choose_down & (down_index == step_index) if step_is_coarse else None

        time_array = np.asarray(times, dtype=np.float64)
        if choose_up.any():
            starts = np.zeros(shape, dtype=np.float64)
            starts[choose_up] = time_array[up_index[choose_up]]
            self._record(_LUMINANCE, 1, starts, choose_up, timestamp, instant=instant_up)
        if choose_down.any():
            starts = np.zeros(shape, dtype=np.float64)
            starts[choose_down] = time_array[down_index[choose_down]]
            self._record(_LUMINANCE, -1, starts, choose_down, timestamp, instant=instant_down)

    def _luminance_pair_qualifies(self, low: np.ndarray, high: np.ndarray) -> np.ndarray:
        threshold = self.options.luminance_threshold
        if self.profile.luminance_model == "wcag_relative":
            return ((high - low) >= threshold) & (low < 0.8)

        reference = self.options.reference_luminance_cd_m2
        low_cd = low * reference
        high_cd = high * reference
        darker_limit = 0.8 * reference
        sdr = (low_cd < darker_limit) & ((high_cd - low_cd) >= threshold * reference)
        denominator = high_cd + low_cd
        michelson = np.divide(
            high_cd - low_cd,
            denominator,
            out=np.zeros_like(denominator),
            where=denominator > 0,
        )
        hdr = (low_cd >= darker_limit) & (michelson >= (1.0 / 17.0))
        return sdr | hdr

    @profile
    def _detect_red(self, timestamp: float, cutoff: float) -> None:
        if self._enable_short_circuit and not self._red_pool.any():
            # No saturated-red tile exists anywhere in the current window, so
            # `(record.red | now.red)` is empty for every record and no red
            # transition can qualify.  This early return is semantics-preserving.
            return
        history = self._history
        count = len(history)
        now = history[-1]
        times = [record.timestamp for record in history]
        shape = now.luminance.shape
        threshold_squared = self.options.red_color_difference**2

        best_distance = np.zeros(shape, dtype=np.float32)
        best_start = np.zeros(shape, dtype=np.float64)
        best_index = np.full(shape, -1, dtype=np.int16)
        best_direction = np.zeros(shape, dtype=np.int8)

        # Mirror the luminance step rule: a single coarse sample interval is
        # treated as an instantaneous change because the 66 ms transition
        # cannot be resolved at that frame rate.
        step_index = count - 2
        step_is_coarse = step_index >= 0 and times[step_index] < cutoff

        for index in range(count - 2, -1, -1):
            is_coarse_step = index == step_index and step_is_coarse
            if times[index] < cutoff and not is_coarse_step:
                continue
            record = history[index]
            distance = ucs_distance_squared(record.u, record.v, now.u, now.v)
            valid = (record.red | now.red) & (distance >= threshold_squared)
            better = valid & (distance > best_distance)
            if not better.any():
                continue

            direction = np.zeros(shape, dtype=np.int8)
            to_red = (~record.red) & now.red
            from_red = record.red & (~now.red)
            direction[to_red] = 1
            direction[from_red] = -1

            both_red = record.red & now.red
            if both_red.any():
                redness_change = now.redness - record.redness
                direction[both_red & (redness_change > 0)] = 1
                direction[both_red & (redness_change < 0)] = -1
                tied = both_red & (redness_change == 0)
                if tied.any():
                    u_change = now.u - record.u
                    direction[tied & (u_change > 0)] = 1
                    direction[tied & (u_change < 0)] = -1
                    still_tied = tied & (direction == 0)
                    if still_tied.any():
                        v_change = now.v - record.v
                        direction[still_tied & (v_change >= 0)] = 1
                        direction[still_tied & (v_change < 0)] = -1

            best_distance[better] = distance[better]
            best_start[better] = times[index]
            best_index[better] = index
            best_direction[better] = direction[better]

        allowed = (best_direction != 0) & (best_direction != self._last_red_direction)
        self._last_red_direction[allowed] = best_direction[allowed]
        # `allowed` only flips the red direction, so OR its presence into the
        # frame-changed flag already set by the luminance detector.
        self._last_frame_changed_direction = self._last_frame_changed_direction or bool(
            allowed.any()
        )
        if allowed.any():
            instant = allowed & (best_index == step_index) if step_is_coarse else None
            self._record(
                _RED,
                None,
                best_start,
                allowed,
                timestamp,
                directions=best_direction,
                instant=instant,
            )

    def _record(
        self,
        kind: str,
        direction: Optional[int],
        start_times: np.ndarray,
        mask: np.ndarray,
        timestamp: float,
        directions: Optional[np.ndarray] = None,
        instant: Optional[np.ndarray] = None,
    ) -> None:
        if not mask.any():
            return
        rounded = np.round(start_times, 6)
        for start in np.unique(rounded[mask]):
            base = mask & (rounded == start)
            if not base.any():
                continue
            if direction is None:
                if directions is None:
                    continue
                direction_values = [
                    int(value) for value in np.unique(directions[base]) if value != 0
                ]
            else:
                direction_values = [direction]

            for event_direction in direction_values:
                selected = base
                if direction is None and directions is not None:
                    selected = base & (directions == event_direction)
                if not selected.any():
                    continue
                if instant is not None and bool(np.all(instant[selected])):
                    # Unresolved single-frame step at a coarse sample rate.
                    duration_ms = 0.0
                else:
                    duration_ms = (timestamp - float(start)) * 1000.0
                key = (kind, event_direction, float(start))
                bucket = self._buckets.get(key)
                if bucket is None:
                    self._buckets[key] = _Bucket(
                        kind=kind,
                        direction=event_direction,
                        start_time=float(start),
                        mask=selected.copy(),
                        max_duration_ms=duration_ms,
                    )
                    if self.options.quick:
                        self._bucket_created_at.append(float(start))
                else:
                    bucket.mask |= selected
                    bucket.max_duration_ms = max(bucket.max_duration_ms, duration_ms)

    # -- aggregation ---------------------------------------------------

    def _candidates(self) -> List[TransitionCandidate]:
        candidates: List[TransitionCandidate] = []
        for bucket in self._buckets.values():
            candidates.append(
                TransitionCandidate(
                    kind=bucket.kind,
                    direction=bucket.direction,
                    start_time=bucket.start_time,
                    duration_ms=bucket.max_duration_ms,
                    mask=bucket.mask.copy(),
                    area=self.area.evaluate(bucket.mask),
                )
            )
        candidates.sort(key=lambda candidate: (candidate.start_time, candidate.kind))
        return candidates

    def _synchronized_events(self, candidates: List[TransitionCandidate]) -> List[TransitionEvent]:
        grouped: Dict[Tuple[str, int], List[TransitionCandidate]] = {}
        for candidate in candidates:
            grouped.setdefault((candidate.kind, candidate.direction), []).append(candidate)

        events: List[TransitionEvent] = []
        self._synchronized_area_merges = 0
        for (kind, direction), group in grouped.items():
            group.sort(key=lambda candidate: candidate.start_time)
            current: List[TransitionCandidate] = []
            current_mask: Optional[np.ndarray] = None
            cluster_start = 0.0

            def flush(
                kind: str = kind,
                direction: int = direction,
            ) -> None:
                nonlocal current, current_mask
                if not current:
                    return
                mask = current_mask.copy() if current_mask is not None else current[0].mask
                if len(current) > 1:
                    span = current[-1].start_time - current[0].start_time
                    if span > 0:
                        self._synchronized_area_merges += 1
                events.append(
                    TransitionEvent(
                        kind=kind,
                        direction=direction,
                        start_time=current[0].start_time,
                        duration_ms=max(candidate.duration_ms for candidate in current),
                        mask=mask,
                        area=self.area.evaluate(mask),
                        raw_transitions=len(current),
                    )
                )
                current = []
                current_mask = None

            for candidate in group:
                overlaps = current_mask is not None and bool(np.any(current_mask & candidate.mask))
                outside_window = (
                    bool(current) and candidate.start_time - cluster_start > self.sync_window_s
                )
                if current and (outside_window or overlaps):
                    flush()
                if not current:
                    cluster_start = candidate.start_time
                    current_mask = candidate.mask.copy()
                else:
                    current_mask |= candidate.mask
                current.append(candidate)
            flush()

        events.sort(key=lambda event: event.start_time)
        return events

    def _alternating(self, events: List[TransitionEvent]) -> List[TransitionEvent]:
        """Order transitions and reject repeats of the previous direction.

        Simultaneous up and down transitions are one state change, not two.
        Inversions (some tiles brightening while others darken in the same
        frame) are therefore coalesced into a single event whose direction
        opposes the previous one.
        """
        ordered = sorted(events, key=lambda event: (event.start_time, event.direction))
        groups: List[List[TransitionEvent]] = []
        for event in ordered:
            if groups and abs(event.start_time - groups[-1][0].start_time) < 1e-6:
                groups[-1].append(event)
            else:
                groups.append([event])

        coalesced: List[TransitionEvent] = []
        for group in groups:
            first = group[0]
            if len(group) == 1:
                coalesced.append(first)
                continue
            mask = np.logical_or.reduce([event.mask for event in group])
            coalesced.append(
                TransitionEvent(
                    kind=first.kind,
                    direction=0,
                    start_time=first.start_time,
                    duration_ms=max(event.duration_ms for event in group),
                    mask=mask,
                    area=self.area.evaluate(mask),
                    raw_transitions=sum(event.raw_transitions for event in group),
                    fast_merged=any(event.fast_merged for event in group),
                )
            )

        result: List[TransitionEvent] = []
        last_direction = 0
        for event in coalesced:
            if event.direction == 0:
                direction = -last_direction if last_direction else 1
                event = replace(event, direction=direction)
            if event.direction != last_direction:
                result.append(event)
                last_direction = event.direction
        return result

    @profile
    def _qualify_by_flash_area(self, events: List[TransitionEvent]) -> List[TransitionEvent]:
        """Keep transitions whose opposing pair changes a qualifying area.

        The changed area is the union of the two transition masks.  A pair is
        also required to overlap in the same region: motion can produce a large
        union while the brightening and darkening edges are in different
        places.  The overlap ratio is measured in raw tile counts so it does
        not depend on the area model.  Texture and dithering fragment the
        overlap, so a pair whose changed area is well beyond the threshold is
        still accepted.

        When the source is smaller than the nominal 416 x 416 CSS-pixel field,
        the area threshold is clamped to the source size.  A flash that only
        reaches that lower threshold is held to stronger region evidence: it
        must overlap more, or cover at least half of the frame.  This keeps
        moving patterns from counting as flashes just because the source is
        small.  These tolerances are implementation choices, not normative
        thresholds, and are recorded with the result.
        """
        if not events:
            return []

        base_threshold = self.area.base_threshold_px2
        scaled_regime = self.area.source_scaled
        flash_area: List[Optional[AreaEvaluation]] = [None] * len(events)
        for index in range(1, len(events)):
            previous = events[index - 1]
            current = events[index]
            if current.start_time - previous.start_time > 1.0:
                continue

            changed = self.area.evaluate(previous.mask | current.mask)
            if not changed.qualifies:
                continue
            changed_tiles = float(np.count_nonzero(previous.mask | current.mask))
            overlap_tiles = float(np.count_nonzero(previous.mask & current.mask))
            overlap_ratio = overlap_tiles / changed_tiles if changed_tiles else 0.0

            if scaled_regime and changed.area_px2 < base_threshold:
                small_area = (
                    overlap_ratio < self.options.flash_area_scaled_overlap_ratio
                    and changed.screen_fraction < self.options.flash_area_frame_fraction
                )
                if small_area:
                    continue
            else:
                reference_threshold = base_threshold if scaled_regime else self.area.threshold_px2
                large = changed.area_px2 >= (
                    self.options.flash_area_union_scale * reference_threshold
                )
                if overlap_ratio < self.options.flash_area_overlap_ratio and not large:
                    continue

            for position in (index - 1, index):
                existing = flash_area[position]
                if existing is None or changed.area_px2 > existing.area_px2:
                    flash_area[position] = changed

        qualified: List[TransitionEvent] = []
        for event, area in zip(events, flash_area):
            if area is not None:
                qualified.append(replace(event, area=area))
        return qualified

    @profile
    def _merge_fast(self, events: List[TransitionEvent]) -> Tuple[List[TransitionEvent], int, int]:
        if not events:
            return [], 0, 0
        result: List[TransitionEvent] = []
        sequences = 0
        merged_transitions = 0
        index = 0
        while index < len(events):
            if index + 1 < len(events) and events[index + 1].direction == -events[index].direction:
                run = [events[index], events[index + 1]]
                cursor = index + 2
                while (
                    cursor < len(events)
                    and events[cursor].direction == -events[cursor - 1].direction
                    and events[cursor].start_time - events[cursor - 2].start_time <= self.fast_gap_s
                ):
                    run.append(events[cursor])
                    cursor += 1

                if len(run) >= 4:
                    union = np.logical_or.reduce([event.mask for event in run])
                    area = self.area.evaluate(union)
                    duration = max(event.duration_ms for event in run)
                    first = replace(
                        run[0],
                        mask=union,
                        area=area,
                        duration_ms=duration,
                        fast_merged=True,
                        merged_from=len(run),
                    )
                    end_event = run[-1]
                    if end_event.direction == first.direction:
                        end_event = run[-2]
                    last = replace(
                        end_event,
                        direction=-first.direction,
                        mask=union,
                        area=area,
                        duration_ms=duration,
                        fast_merged=True,
                        merged_from=len(run),
                    )
                    result.extend((first, last))
                    sequences += 1
                    merged_transitions += len(run) - 2
                else:
                    result.extend(run)
                index = cursor
            else:
                result.append(events[index])
                index += 1
        return result, sequences, merged_transitions

    @staticmethod
    def _max_in_window(times: List[float], window_seconds: float) -> int:
        if not times:
            return 0
        ordered = sorted(times)
        best = 0
        left = 0
        for right, timestamp in enumerate(ordered):
            while timestamp - ordered[left] > window_seconds:
                left += 1
            best = max(best, right - left + 1)
        return best

    @staticmethod
    def _extended_exposure_advisory(times: List[float], limit: int) -> bool:
        if len(times) < 2:
            return False
        ordered = sorted(times)
        required = 0.8 * float(limit) * 5.0
        left = 0
        for right, timestamp in enumerate(ordered):
            while timestamp - ordered[left] > 5.0:
                left += 1
            if right - left + 1 >= required:
                return True
        return False
