"""Public analysis entry points.

``analyze_file``, ``analyze_bytes``, and ``analyze_frames`` all run the same
transition engine.  Decoding is the only part that differs.  Every result
carries the standard profile, the working values used, the display/area
assumptions, and warnings about what was *not* checked.
"""

from __future__ import annotations

import time
from typing import Any, Iterable, List, Optional, Sequence

import numpy as np

from ._version import __version__
from .area import AreaEvaluator, TileGrid, tile_frame_uint8
from .decode import (
    DecodeState,
    FrameRecord,
    decode_bytes,
    decode_caller_frames,
    decode_file,
)
from .engine import EngineResult, TransitionEngine
from .errors import (
    AnalysisTimeoutError,
    DecodeError,
    InvalidFrameInputError,
    InvalidOptionsError,
)
from .options import AnalysisOptions
from .result import (
    AnalysisResult,
    AnalyzerInfo,
    Assumptions,
    Measurements,
    MediaInfo,
    StandardInfo,
)
from .standards import StandardProfile

_ENGINE_WARNINGS = (
    "not_a_compliance_determination",
    "tile_averaging_approximation",
)


def analyze_file(
    path: Any,
    options: Optional[AnalysisOptions] = None,
) -> AnalysisResult:
    """Analyze a media file on disk.

    The file is streamed frame by frame; nothing is written to disk and no
    network access is performed.
    """
    options = options or AnalysisOptions()
    records, state = decode_file(path, options)
    return _run(records, state, options)


def analyze_bytes(
    data: bytes,
    options: Optional[AnalysisOptions] = None,
) -> AnalysisResult:
    """Analyze still-image and GIF bytes held in memory.

    Video bytes are rejected: the available decoder needs a file-like path it
    can seek, so callers with video bytes must store them first and use
    :func:`analyze_file`.
    """
    options = options or AnalysisOptions()
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise InvalidOptionsError("data must be bytes-like")
    records, state = decode_bytes(bytes(data), options)
    return _run(records, state, options)


def analyze_frames(
    frames: Sequence[np.ndarray],
    timestamps: Sequence[float],
    durations: Optional[Sequence[float]] = None,
    options: Optional[AnalysisOptions] = None,
) -> AnalysisResult:
    """Analyze caller-supplied frames.

    ``timestamps`` are seconds from the start of playback.  ``durations`` are
    optional per-frame display durations in seconds.  Frames are consumed in
    order and are not copied beyond the current tile grid.
    """
    options = options or AnalysisOptions()
    if len(frames) != len(timestamps):
        raise InvalidFrameInputError("frames and timestamps must have the same length")
    if not frames:
        raise InvalidFrameInputError("no frames supplied")

    records, state = decode_caller_frames(frames, timestamps, durations, options)
    return _run(records, state, options)


def _run(
    records: Iterable[FrameRecord],
    state: DecodeState,
    options: AnalysisOptions,
) -> AnalysisResult:
    profile = options.resolved_profile()
    area_model = options.resolved_area_model(profile)

    engine: Optional[TransitionEngine] = None
    area: Optional[AreaEvaluator] = None
    grid: Optional[TileGrid] = None

    started = time.monotonic()
    frames = 0
    early_stop = False
    engine_result: Optional[EngineResult] = None
    analyzed_span: float = 0.0

    for record in records:
        if time.monotonic() - started > options.analysis_timeout_seconds:
            raise AnalysisTimeoutError(
                "Analysis exceeded analysis_timeout_seconds=%s" % options.analysis_timeout_seconds
            )

        frame = np.asarray(record.data)
        if frame.ndim < 2:
            raise DecodeError("decoded frame has no spatial dimensions")
        height, width = int(frame.shape[0]), int(frame.shape[1])
        if width <= 0 or height <= 0:
            raise DecodeError("decoded frame has empty dimensions")

        if engine is None:
            grid = TileGrid.for_size(width, height, options.tile_grid_max)
            area = AreaEvaluator(grid, options, area_model)
            engine = TransitionEngine(options, profile, area)

        assert engine is not None and grid is not None
        engine.add_frame(record.timestamp, tile_frame_uint8(frame, grid))
        frames += 1
        # The analyzed span is how much media was actually scanned. It grows
        # with every frame — including synthetic repeat cycles added for short
        # looping GIFs — so it can exceed the media's own duration; it is kept
        # separate from ``state.duration`` and reported on every result.
        analyzed_span = max(analyzed_span, record.timestamp + record.duration)

        if options.quick:
            # Quick mode probes after every frame and stops as soon as a
            # triggering prefix is confirmed. A triggering prefix is evidence
            # that the working values were exceeded within the frames seen so
            # far; a later frame could still merge a fast sequence back to safe,
            # so the verdict can over-report. It never under-reports: a non
            # triggering probe keeps scanning to a full result.
            if engine.quick_should_finish(record.timestamp):
                engine_result = engine.quick_finish()
                if engine_result.is_triggering:
                    early_stop = True
                    # The decoder was abandoned, so the true media duration is
                    # unknown: report it as 0 rather than a synthetic timestamp.
                    # The analyzed span was tracked on every preceding frame.
                    state.duration = 0.0
                    if analyzed_span > 0:
                        state.sampled_fps = frames / analyzed_span
                    break

    if engine is None or area is None or grid is None:
        raise DecodeError("No frames were decoded")

    if early_stop:
        # The quick result was computed just before early_stop was set above, so
        # it is always present here; the None branch is defensive.
        if engine_result is None:
            raise DecodeError("internal error: quick stop without a result")
        return _build_result(
            engine_result,
            state,
            options,
            profile,
            area,
            grid,
            frames,
            area_model,
            quick=True,
            analyzed_span_seconds=analyzed_span,
        )

    engine_result = engine.finish()
    return _build_result(
        engine_result,
        state,
        options,
        profile,
        area,
        grid,
        frames,
        area_model,
        analyzed_span_seconds=analyzed_span,
    )


def _build_result(
    engine_result: EngineResult,
    state: DecodeState,
    options: AnalysisOptions,
    profile: StandardProfile,
    area: AreaEvaluator,
    grid: TileGrid,
    frames: int,
    area_model: str,
    quick: bool = False,
    analyzed_span_seconds: float = 0.0,
) -> AnalysisResult:
    warnings: List[str] = []
    for warning in state.warnings:
        if warning not in warnings:
            warnings.append(warning)
    for warning in _ENGINE_WARNINGS:
        warnings.append(warning)

    if profile.coverage != "complete":
        warnings.append("profile_coverage_%s" % profile.coverage)
    if area.uses_assumed_display:
        warnings.append("area_normalized_to_416_css_px")
    if area.source_scaled:
        warnings.append("area_threshold_scaled_to_source")
    if options.display is not None and area_model == "wcag_solid_angle":
        warnings.append("display_geometry_caller_supplied")
    if options.sample_fps is not None:
        warnings.append("frames_sampled")
    if state.truncated:
        warnings.append("analysis_incomplete")
    if quick:
        warnings.append("analysis_early_stopped")

    is_triggering = engine_result.is_triggering
    inconclusive = bool(state.truncated)
    if is_triggering:
        risk = "triggering"
    elif inconclusive:
        risk = "inconclusive"
    else:
        risk = "none"

    measurements = Measurements(
        luminance_transitions=engine_result.luminance_transitions,
        red_transitions=engine_result.red_transitions,
        max_luminance_transitions_per_second=(engine_result.max_luminance_transitions_per_second),
        max_red_transitions_per_second=engine_result.max_red_transitions_per_second,
        max_luminance_flashes_per_second=(engine_result.max_luminance_flashes_per_second),
        max_red_flashes_per_second=engine_result.max_red_flashes_per_second,
        max_flashes_per_second=engine_result.max_flashes_per_second,
        max_area_px2=engine_result.max_area_px2,
        area_threshold_px2=engine_result.area_threshold_px2,
        max_flashing_area_ratio=engine_result.max_flashing_area_ratio,
        max_flashing_area_screen_fraction=(engine_result.max_flashing_area_screen_fraction),
        max_transition_duration_ms=engine_result.max_transition_duration_ms,
        synchronized_area_merges=engine_result.synchronized_area_merges,
        fast_flash_sequences=engine_result.fast_flash_sequences,
        merged_fast_flash_transitions=(engine_result.merged_fast_flash_transitions),
        duration_seconds=state.duration,
        analyzed_span_seconds=analyzed_span_seconds,
        frames_analyzed=frames,
        sampled_fps=state.sampled_fps,
    )

    assumptions = Assumptions(
        color_space=options.effective_color_space,
        luminance_model=profile.luminance_model,
        reference_luminance_cd_m2=options.reference_luminance_cd_m2,
        max_transition_duration_ms=options.max_transition_duration_ms,
        synchronicity_window_ms=options.synchronicity_window_ms,
        fast_flash_hz=options.fast_flash_hz,
        fast_flash_merge_enabled=options.enable_fast_flash_merge,
        flash_area_overlap_ratio=options.flash_area_overlap_ratio,
        flash_area_union_scale=options.flash_area_union_scale,
        flash_area_scaled_overlap_ratio=options.flash_area_scaled_overlap_ratio,
        flash_area_frame_fraction=options.flash_area_frame_fraction,
        max_flashes_per_second=options.max_flashes_per_second,
        max_transitions_per_second=options.max_transitions_per_second,
        area_model=area_model,
        area_subarea_css_px=options.area_subarea_css_px,
        display_assumed=area.uses_assumed_display,
        display_geometry=(options.display.to_dict() if options.display is not None else None),
        tile_grid=grid.to_dict(),
        field_width_px=area.field_width_px,
        field_height_px=area.field_height_px,
        area_base_threshold_px2=area.base_threshold_px2,
        area_source_scaled=area.source_scaled,
    )

    media = MediaInfo(
        format=state.format,
        width=int(state.width or grid.width),
        height=int(state.height or grid.height),
        bytes=state.bytes,
        color_space=state.color_space,
        transfer=state.transfer,
    )

    analyzer = AnalyzerInfo(
        name="epilepsy-warning",
        version=__version__,
        options_hash=options.fingerprint(),
    )

    return AnalysisResult(
        standard=StandardInfo(
            id=profile.id,
            version=profile.version,
            profile_coverage=profile.coverage,
        ),
        is_triggering=is_triggering,
        risk=risk,
        inconclusive=inconclusive,
        reasons=list(engine_result.reasons),
        measurements=measurements,
        assumptions=assumptions,
        media=media,
        warnings=warnings,
        analyzer=analyzer,
        quick=quick,
    )
