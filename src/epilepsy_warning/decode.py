"""Media decoding.

The decoder boundary is explicit: a path or bytes in, timestamped RGB frames
out.  GIFs are decoded with Pillow so delays, disposal, and the loop transition
are handled.  Video is streamed through imageio/imageio-ffmpeg and timestamps
are derived from the container frame rate because the decoder does not expose
per-frame presentation timestamps.
"""

from __future__ import annotations

import io
import math
import os
from dataclasses import dataclass, field
from typing import Any, Iterator, List, Optional, Sequence, Tuple, Union

import imageio
import numpy as np
from PIL import Image, UnidentifiedImageError

from .errors import (
    DecodeError,
    LimitExceededError,
    UnsupportedFormatError,
    UnsupportedInputError,
)
from .options import AnalysisOptions

_GIF_FORMATS = {"gif"}
_STATIC_FORMATS = {"png", "jpeg", "webp", "bmp", "tiff"}
_VIDEO_FORMATS = {"mp4", "webm", "avi", "mkv", "mov"}


@dataclass(frozen=True)
class FrameRecord:
    data: np.ndarray
    timestamp: float
    duration: float
    synthetic: bool = False


@dataclass
class DecodeState:
    format: str
    width: Optional[int] = None
    height: Optional[int] = None
    bytes: Optional[int] = None
    color_space: str = "srgb_assumed"
    transfer: str = "srgb_assumed"
    warnings: List[str] = field(default_factory=list)
    truncated: bool = False
    frames_yielded: int = 0
    synthetic_frames: int = 0
    duration: float = 0.0
    sampled_fps: float = 0.0

    def add_warning(self, warning: str) -> None:
        if warning not in self.warnings:
            self.warnings.append(warning)


def detect_format(header: bytes) -> str:
    if header.startswith(b"GIF8"):
        return "gif"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith(b"BM"):
        return "bmp"
    if header.startswith(b"II*\x00") or header.startswith(b"MM\x00*"):
        return "tiff"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    if header[:4] == b"RIFF" and header[8:12] == b"AVI ":
        return "avi"
    if len(header) >= 8 and header[4:8] == b"ftyp":
        return "mp4"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    return "unknown"


def _read_header_path(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(64)
    except OSError as exc:
        raise DecodeError("Could not read %s: %s" % (path, exc)) from exc


def decode_file(
    path: Union[str, os.PathLike], options: AnalysisOptions
) -> Tuple[Iterator[FrameRecord], DecodeState]:
    path = os.fspath(path)
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise DecodeError("Could not stat %s: %s" % (path, exc)) from exc
    if size > options.max_bytes:
        raise LimitExceededError("Input is %d bytes; max_bytes is %d" % (size, options.max_bytes))

    fmt = detect_format(_read_header_path(path))
    if fmt == "unknown":
        raise UnsupportedFormatError("Unsupported or unrecognized media format for %s" % path)

    if fmt in _GIF_FORMATS or fmt in _STATIC_FORMATS:
        state = DecodeState(format=fmt, bytes=size)
        return _pillow_frames(path, fmt, options, state), state
    if fmt in _VIDEO_FORMATS:
        state = DecodeState(format=fmt, bytes=size)
        return _video_frames(path, fmt, options, state), state
    raise UnsupportedFormatError("Unsupported media format %r" % fmt)


def decode_bytes(
    data: bytes, options: AnalysisOptions
) -> Tuple[Iterator[FrameRecord], DecodeState]:
    if len(data) > options.max_bytes:
        raise LimitExceededError(
            "Input is %d bytes; max_bytes is %d" % (len(data), options.max_bytes)
        )
    fmt = detect_format(data[:64])
    if fmt in _GIF_FORMATS or fmt in _STATIC_FORMATS:
        state = DecodeState(format=fmt, bytes=len(data))
        return _pillow_frames(io.BytesIO(data), fmt, options, state), state
    if fmt in _VIDEO_FORMATS:
        raise UnsupportedInputError(
            "Video bytes are not decoded from memory; pass a path to analyze_file "
            "or let the consumer write the bytes to storage first"
        )
    raise UnsupportedFormatError("Unsupported or unrecognized media format in bytes")


def decode_caller_frames(
    frames: Sequence[np.ndarray],
    timestamps: Sequence[float],
    durations: Optional[Sequence[float]],
    options: AnalysisOptions,
) -> Tuple[Iterator[FrameRecord], DecodeState]:
    if len(frames) != len(timestamps):
        raise DecodeError("frames and timestamps must have the same length")
    if len(frames) == 0:
        raise DecodeError("no frames supplied")
    if durations is not None and len(durations) != len(frames):
        raise DecodeError("frames and durations must have the same length")

    state = DecodeState(format="frames", bytes=None)
    state.add_warning("caller_supplied_frames")
    return _sequence_frames(frames, timestamps, durations, options, state), state


def _check_pixels(frame: np.ndarray, options: AnalysisOptions) -> None:
    if frame.ndim < 2:
        raise DecodeError("decoded frame has no spatial dimensions")
    pixels = int(frame.shape[0]) * int(frame.shape[1])
    if pixels > options.max_pixels:
        raise LimitExceededError(
            "Frame is %d pixels; max_pixels is %d" % (pixels, options.max_pixels)
        )


def _alpha_composite_rgba(dst: np.ndarray, src: np.ndarray) -> np.ndarray:
    """Composite an RGBA source over an RGBA destination.

    This is the integer alpha-compositing formula Pillow uses, vectorized in
    numpy so the decoder does not churn through PIL image objects for every
    frame.  Fully transparent and fully opaque sources take cheap paths.  The
    inputs are never mutated; the returned array may alias either input.
    """
    source_alpha = src[..., 3]
    if not source_alpha.any():
        return dst
    if np.all(source_alpha == 255):
        return src

    destination = dst.astype(np.int32)
    source = src.astype(np.int32)
    source_alpha = source[..., 3]
    destination_alpha = destination[..., 3]

    blend = destination_alpha * (255 - source_alpha)
    output_alpha_255 = source_alpha * 255 + blend
    coefficient_1 = np.zeros_like(output_alpha_255)
    np.floor_divide(
        source_alpha * 255 * 255 * (1 << 7),
        output_alpha_255,
        out=coefficient_1,
        where=source_alpha > 0,
    )
    coefficient_2 = 255 * (1 << 7) - coefficient_1

    output = np.empty_like(destination)
    for channel in range(3):
        value = source[..., channel] * coefficient_1 + destination[..., channel] * (coefficient_2)
        value += 0x80 << 7
        # SHIFTFORDIV255(value) >> 7, matching Pillow's AlphaComposite.c.
        output[..., channel] = (((value >> 8) + value) >> 8) >> 7
    value = output_alpha_255 + 0x80
    output[..., 3] = ((value >> 8) + value) >> 8

    transparent = source_alpha == 0
    if transparent.any():
        output[transparent] = destination[transparent]
    return output.astype(np.uint8)


def _pillow_frames(
    source: Any, fmt: str, options: AnalysisOptions, state: DecodeState
) -> Iterator[FrameRecord]:
    try:
        with Image.open(source) as image:
            frame_count = int(getattr(image, "n_frames", 1))
            state.width, state.height = image.size
            if frame_count <= 1:
                state.add_warning("single_frame_media")
            state.add_warning("color_space_assumed_srgb")

            # Read global GIF fields before seeking: Pillow exposes
            # ``transparency`` (and sometimes ``loop``) only on the frame where
            # the extension first appears, usually index 0.
            has_transparency = image.info.get("transparency") is not None
            loop = image.info.get("loop")

            usable_count = min(frame_count, options.max_frames + 1)
            if frame_count > usable_count:
                state.truncated = True
                state.add_warning("frame_limit_reached")

            durations: List[float] = []
            delay_assumed = False

            # Browsers repeat looping GIFs indefinitely.  A clip shorter than
            # one second cannot contain a one-second flash window, so analyze
            # enough cycles to cover a full window plus one loop.  The reported
            # media duration stays the length of the clip itself.
            #
            # Durations are read during the first decode pass.  Only short
            # looping clips need extra passes, so ordinary GIFs avoid the
            # former full extra seek/decode used solely to collect delays.
            repeats = fmt == "gif" and frame_count > 1 and loop is not None and loop != 1
            total_duration = 0.0
            cycles = 1
            repeated = False

            timestamp = 0.0
            first_frame: Optional[np.ndarray] = None
            last_end = 0.0
            blank = np.full((image.size[1], image.size[0], 4), 255, dtype=np.uint8)

            frame_limit_hit = False
            pending_limit_warning: Optional[str] = None
            cycle = 0
            while cycle < cycles:
                # Each loop starts from a fresh canvas; GIF disposal does not
                # carry across the loop seam.  ``blank`` is never mutated, so
                # it can be used directly without a defensive copy.
                canvas = blank
                for index in range(min(frame_count, usable_count)):
                    if timestamp >= options.max_duration_seconds:
                        state.truncated = True
                        if options.strict_limits:
                            state.add_warning("duration_limit_reached")
                            raise LimitExceededError(
                                "Media exceeds max_duration_seconds=%s"
                                % options.max_duration_seconds
                            )
                        # Deferred so cycle 0 keeps the original warning order:
                        # the delay/transparency warnings were once emitted
                        # before any frame was decoded.
                        pending_limit_warning = "duration_limit_reached"
                        frame_limit_hit = True
                        break
                    if state.frames_yielded >= options.max_frames:
                        state.truncated = True
                        if options.strict_limits:
                            state.add_warning("frame_limit_reached")
                            raise LimitExceededError(
                                "Media exceeds max_frames=%d" % options.max_frames
                            )
                        pending_limit_warning = "frame_limit_reached"
                        frame_limit_hit = True
                        break

                    image.seek(index)
                    if cycle == 0:
                        delay = float(image.info.get("duration", 0) or 0) / 1000.0
                        if delay <= 0:
                            delay = 0.1
                            delay_assumed = True
                        durations.append(delay)
                    else:
                        delay = durations[index]
                    disposal = int(getattr(image, "disposal_method", 0) or 0)
                    # Disposal 3 restores the canvas as it was before this
                    # frame.  The compositing helpers never mutate their
                    # inputs, so keeping a reference is enough; no copy needed.
                    previous_canvas = canvas if disposal == 3 else None
                    source = np.asarray(image.convert("RGBA"))
                    canvas = _alpha_composite_rgba(canvas, source)
                    frame = canvas[..., :3]
                    if disposal == 2:
                        canvas = blank
                    elif previous_canvas is not None:
                        canvas = previous_canvas
                    _check_pixels(frame, options)
                    if cycle == 0 and index == 0:
                        # The canvas is replaced rather than mutated on every
                        # frame, so retaining this view does not alias a later
                        # canvas.
                        first_frame = frame

                    yield FrameRecord(frame, timestamp, delay, synthetic=cycle > 0)
                    state.frames_yielded += 1
                    if cycle > 0:
                        state.synthetic_frames += 1
                    last_end = timestamp + delay
                    timestamp += delay
                if cycle == 0 and frame_limit_hit and len(durations) < usable_count:
                    # A limit cut the first pass short.  Finish collecting the
                    # delays so the reported duration and the repeat decision
                    # match a full pre-pass; only truncated inputs pay for this.
                    for index in range(len(durations), usable_count):
                        image.seek(index)
                        delay = float(image.info.get("duration", 0) or 0) / 1000.0
                        if delay <= 0:
                            delay = 0.1
                            delay_assumed = True
                        durations.append(delay)
                if delay_assumed:
                    state.add_warning("gif_delay_assumed")
                if cycle == 0 and has_transparency:
                    # GIF/PNG transparency has no inherent background.
                    # Composite onto white, the usual page background, so
                    # transparent areas do not become opaque black.  Disposal
                    # is applied explicitly because Pillow does not composite
                    # it into convert("RGBA").
                    state.add_warning("transparency_composited_white")
                if pending_limit_warning is not None:
                    state.add_warning(pending_limit_warning)
                if frame_limit_hit:
                    break
                if cycle == 0:
                    total_duration = sum(durations)
                    if repeats and 0.0 < total_duration < 1.0:
                        target = min(
                            options.max_duration_seconds,
                            total_duration + max(total_duration, 1.0),
                        )
                        wanted = int(math.ceil((target / total_duration) - 1e-9))
                        frame_cap = max(1, options.max_frames // max(1, len(durations)))
                        cycles = max(1, min(wanted, frame_cap))
                        if cycles > 1:
                            repeated = True
                            state.add_warning("gif_loop_repeated_analysis")
                cycle += 1

            total_duration = sum(durations)

            if (
                not repeated
                and repeats
                and not state.truncated
                and first_frame is not None
                and total_duration < options.max_duration_seconds
                and state.frames_yielded < options.max_frames
            ):
                yield FrameRecord(
                    first_frame,
                    total_duration,
                    durations[0],
                    synthetic=True,
                )
                state.synthetic_frames += 1
                state.frames_yielded += 1
                state.add_warning("gif_loop_wrap_analyzed")
                last_end = total_duration

            if repeated:
                state.duration = last_end if state.truncated else total_duration
            else:
                state.duration = total_duration if not state.truncated else last_end
            real_frames = max(0, state.frames_yielded - state.synthetic_frames)
            if state.duration > 0:
                state.sampled_fps = real_frames / state.duration
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise DecodeError("Could not decode %s: %s" % (fmt, exc)) from exc


def _video_frames(
    path: str, fmt: str, options: AnalysisOptions, state: DecodeState
) -> Iterator[FrameRecord]:
    reader = None
    try:
        reader = imageio.get_reader(path)
        metadata = reader.get_meta_data() or {}
        state.add_warning("color_space_assumed_srgb")
        state.add_warning("video_timestamps_from_constant_fps")

        native_fps = float(metadata.get("fps") or 0)
        if native_fps <= 0:
            native_fps = float(options.sample_fps or 30.0)
            state.add_warning("frame_rate_assumed")
        size = metadata.get("size") or metadata.get("source_size")
        if size:
            state.width, state.height = int(size[0]), int(size[1])

        step = 1
        if options.sample_fps is not None and native_fps > options.sample_fps:
            step = max(1, int(round(native_fps / options.sample_fps)))
        sampled_fps = native_fps / step
        state.sampled_fps = sampled_fps
        if sampled_fps < 60.0:
            state.add_warning("sample_rate_below_60hz")

        frame_duration = step / native_fps
        container_duration = float(metadata.get("duration") or 0)
        if container_duration > options.max_duration_seconds:
            state.add_warning("duration_limit_reached")

        for index, frame in enumerate(reader):
            if index % step != 0:
                continue
            timestamp = index / native_fps
            if timestamp >= options.max_duration_seconds:
                state.truncated = True
                state.add_warning("duration_limit_reached")
                if options.strict_limits:
                    raise LimitExceededError(
                        "Media exceeds max_duration_seconds=%s" % options.max_duration_seconds
                    )
                break
            if state.frames_yielded >= options.max_frames:
                state.truncated = True
                state.add_warning("frame_limit_reached")
                if options.strict_limits:
                    raise LimitExceededError("Media exceeds max_frames=%d" % options.max_frames)
                break

            frame = np.asarray(frame)
            _check_pixels(frame, options)
            if state.width is None or state.height is None:
                state.height, state.width = int(frame.shape[0]), int(frame.shape[1])
            yield FrameRecord(frame, timestamp, frame_duration)
            state.frames_yielded += 1
            state.duration = timestamp + frame_duration

        if state.frames_yielded == 0:
            raise DecodeError("No frames decoded from %s" % path)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DecodeError("Could not decode video %s: %s" % (path, exc)) from exc
    finally:
        if reader is not None:
            try:
                reader.close()
            except Exception:
                pass


def _sequence_frames(
    frames: Sequence[np.ndarray],
    timestamps: Sequence[float],
    durations: Optional[Sequence[float]],
    options: AnalysisOptions,
    state: DecodeState,
) -> Iterator[FrameRecord]:
    state.add_warning("color_space_assumed_srgb")
    last_timestamp = -1.0
    for index, (frame, timestamp) in enumerate(zip(frames, timestamps)):
        if timestamp < last_timestamp:
            raise DecodeError("timestamps must be non-decreasing")
        last_timestamp = float(timestamp)
        if timestamp >= options.max_duration_seconds:
            state.truncated = True
            state.add_warning("duration_limit_reached")
            break
        if state.frames_yielded >= options.max_frames:
            state.truncated = True
            state.add_warning("frame_limit_reached")
            break

        array = np.asarray(frame)
        _check_pixels(array, options)
        if state.width is None or state.height is None:
            state.height, state.width = int(array.shape[0]), int(array.shape[1])

        if durations is not None:
            duration = float(durations[index])
        elif index + 1 < len(timestamps):
            duration = float(timestamps[index + 1]) - float(timestamp)
        else:
            duration = 1.0 / 60.0
        if duration < 0:
            raise DecodeError("frame durations must be non-negative")

        yield FrameRecord(array, float(timestamp), duration)
        state.frames_yielded += 1
        state.duration = float(timestamp) + duration

    if state.frames_yielded == 0:
        raise DecodeError("No frames supplied")
    if state.duration > 0:
        state.sampled_fps = state.frames_yielded / state.duration
