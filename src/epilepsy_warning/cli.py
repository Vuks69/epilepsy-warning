"""Command-line interface for :mod:`epilepsy_warning`.

Exit codes: ``0`` safe, ``1`` triggering, ``2`` error or inconclusive analysis.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence

from ._version import __version__
from .api import analyze_file
from .errors import EpilepsyWarningError, InvalidOptionsError
from .options import AnalysisOptions, DisplayGeometry
from .result import AnalysisResult
from .standards import available_profiles, get_profile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="epilepsy-scan",
        description=(
            "Detect flashing content using a standards profile. "
            "This is not a compliance or medical determination."
        ),
    )
    parser.add_argument("paths", nargs="*", metavar="FILE", help="media file to analyze")
    parser.add_argument(
        "--standard",
        default="wcag22",
        metavar="PROFILE",
        help="standards profile (default: wcag22); see --list-standards",
    )
    parser.add_argument(
        "--list-standards", action="store_true", help="list available profiles and exit"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--screen-diagonal-in",
        type=float,
        metavar="INCHES",
        help="known display diagonal for the WCAG 10-degree field",
    )
    parser.add_argument(
        "--viewing-distance-cm",
        type=float,
        metavar="CM",
        help="known viewing distance for the WCAG 10-degree field",
    )
    parser.add_argument(
        "--aspect-ratio",
        type=float,
        default=16.0 / 9.0,
        metavar="RATIO",
        help="display aspect ratio used with display geometry (default: 1.7778)",
    )
    parser.add_argument(
        "--area-model",
        choices=("wcag_solid_angle", "screen_fraction"),
        help="override the profile's area model",
    )
    parser.add_argument(
        "--max-flashes-per-second",
        type=float,
        metavar="RATE",
        help="override the profile's flash rate limit (default: 3)",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        metavar="BYTES",
        help="maximum accepted input size",
    )
    parser.add_argument(
        "--max-duration-seconds",
        type=float,
        metavar="SECONDS",
        help="maximum analyzed duration",
    )
    parser.add_argument("--max-frames", type=int, metavar="COUNT", help="maximum analyzed frames")
    parser.add_argument(
        "--sample-fps",
        type=float,
        metavar="FPS",
        help="decode video at this rate instead of the native frame rate",
    )
    parser.add_argument(
        "--strict-limits",
        action="store_true",
        help="fail instead of truncating when a limit is reached",
    )
    parser.add_argument(
        "--no-fast-flash-merge",
        action="store_true",
        help="disable the 65 Hz fast-flash merge",
    )
    parser.add_argument(
        "--extended-exposure",
        action="store_true",
        help="report the extended-exposure advisory (five seconds)",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def _options_from_args(args: argparse.Namespace) -> AnalysisOptions:
    display = None
    if args.screen_diagonal_in is not None or args.viewing_distance_cm is not None:
        if args.screen_diagonal_in is None or args.viewing_distance_cm is None:
            raise InvalidOptionsError(
                "--screen-diagonal-in and --viewing-distance-cm must be supplied together"
            )
        display = DisplayGeometry(
            screen_diagonal_in=args.screen_diagonal_in,
            viewing_distance_cm=args.viewing_distance_cm,
            aspect_ratio=args.aspect_ratio,
        )

    overrides: Dict[str, Any] = {
        "standard": args.standard,
        "display": display,
        "strict_limits": args.strict_limits,
        "enable_fast_flash_merge": not args.no_fast_flash_merge,
        "extended_exposure": args.extended_exposure,
    }
    if args.area_model is not None:
        overrides["area_model"] = args.area_model
    if args.max_flashes_per_second is not None:
        overrides["max_flashes_per_second"] = args.max_flashes_per_second
    if args.max_bytes is not None:
        overrides["max_bytes"] = args.max_bytes
    if args.max_duration_seconds is not None:
        overrides["max_duration_seconds"] = args.max_duration_seconds
    if args.max_frames is not None:
        overrides["max_frames"] = args.max_frames
    if args.sample_fps is not None:
        overrides["sample_fps"] = args.sample_fps

    return AnalysisOptions(**overrides)


def _print_human(path: str, result: AnalysisResult) -> None:
    label = {
        "triggering": "TRIGGERING",
        "inconclusive": "INCONCLUSIVE",
    }.get(result.risk, "Safe")
    print(
        "%s  %s  (profile=%s, coverage=%s)"
        % (label, path, result.standard.id, result.standard.profile_coverage)
    )

    measurements = result.measurements
    print(
        "  rate: luminance %d transitions/s (%.1f flashes/s), "
        "red %d transitions/s (%.1f flashes/s)"
        % (
            measurements.max_luminance_transitions_per_second,
            measurements.max_luminance_flashes_per_second,
            measurements.max_red_transitions_per_second,
            measurements.max_red_flashes_per_second,
        )
    )
    print(
        "  area: %.0f px2 (threshold %.0f px2, ratio %.2f)"
        % (
            measurements.max_area_px2,
            measurements.area_threshold_px2,
            measurements.max_flashing_area_ratio,
        )
    )
    print(
        "  media: %s %dx%d, %.2f s, %d frames at %.1f fps"
        % (
            result.media.format,
            result.media.width,
            result.media.height,
            measurements.duration_seconds,
            measurements.frames_analyzed,
            measurements.sampled_fps,
        )
    )
    if result.reasons:
        print("  reasons: %s" % ", ".join(result.reasons))
    if result.warnings:
        print("  warnings: %s" % ", ".join(result.warnings))


def _print_json(path: str, result: AnalysisResult) -> None:
    payload = {"path": path}
    payload.update(result.to_dict())
    print(json.dumps(payload, sort_keys=False))


def _list_standards() -> None:
    for profile_id in available_profiles():
        profile = get_profile(profile_id)
        print("%s  version=%s  coverage=%s" % (profile.id, profile.version, profile.coverage))
        for note in profile.notes:
            print("  %s" % note)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_standards:
        _list_standards()
        return 0

    if not args.paths:
        parser.print_usage(sys.stderr)
        print("epilepsy-scan: at least one FILE is required", file=sys.stderr)
        return 2

    try:
        options = _options_from_args(args)
    except EpilepsyWarningError as exc:
        print("epilepsy-scan: %s" % exc, file=sys.stderr)
        return 2

    statuses: List[int] = []
    payloads: List[Dict[str, Any]] = []
    for path in args.paths:
        try:
            result = analyze_file(path, options)
        except (EpilepsyWarningError, OSError) as exc:
            print("ERROR  %s  (%s)" % (path, exc), file=sys.stderr)
            statuses.append(2)
            payloads.append({"path": path, "error": str(exc)})
            continue

        if args.json:
            payload = {"path": path}
            payload.update(result.to_dict())
            payloads.append(payload)
        else:
            _print_human(path, result)

        if result.is_triggering:
            statuses.append(1)
        elif result.inconclusive:
            statuses.append(2)
        else:
            statuses.append(0)

    if args.json:
        if len(payloads) == 1:
            print(json.dumps(payloads[0], sort_keys=False))
        else:
            print(json.dumps(payloads, sort_keys=False))

    if 1 in statuses:
        return 1
    if 2 in statuses:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
