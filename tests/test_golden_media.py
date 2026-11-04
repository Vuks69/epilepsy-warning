"""Automated golden-media regression tests.

The library ships with unit tests over synthetic timing and area boundaries
(``tests/test_engine.py``, ``tests/test_area.py``) and a Phase-3 short-circuit
equivalence test over synthetic histories
(``tests/test_engine_optimization.py``).  Those do not exercise the real decode
path (GIF loop-repeat, loop-seam compositing, disposal, sampling), so this
module adds regression coverage over the actual media fixtures.

Two things are asserted:

1. **Verdict regression.** Every fixture in ``examples/triggering.lst`` must be
   flagged ``TRIGGERING`` and every fixture in
   ``examples/not-triggering.lst`` must stay safe, via the public
   :func:`epilepsy_warning.analyze_file` entry point (the full pipeline). The
   ``.lst`` files are the tracked source of truth; the media files they point
   at are gitignored, so this module is also responsible for fetching them.

2. **Schema/annotation sanity.** The result is not ``inconclusive`` and carries
   the standing non-compliance warning, so a regression that silently dropped
   the warnings would not hide here.

Media caching
-------------
The media files are gitignored (only the ``.lst`` files are tracked), so the
fixtures must be downloaded like :file:`util/download_gifs.sh` does and cached in
place.  This module mirrors that script: for each list it resolves the output
directory from the list path (``examples/triggering``), derives the
``<number>.<ext>`` filename per line with the same extension detection, and
downloads any missing files, throttling between downloads.  Files that already
exist on disk are reused, so repeated runs never re-download.

The equivalence cross-check (toggle ``TransitionEngine._enable_short_circuit``
on the real decode path) is opt-in because it doubles decode work; set
``EPILEPSY_GOLDEN_EQUIP=1`` to enable it.
"""

from __future__ import annotations

import os
import time
import unittest
import urllib.request
from dataclasses import dataclass

import numpy as np

from epilepsy_warning import AnalysisOptions, analyze_file
from epilepsy_warning.area import AreaEvaluator, TileGrid, tile_frame_uint8
from epilepsy_warning.decode import decode_file
from epilepsy_warning.engine import EngineResult, TransitionEngine

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRIGGERING_LIST = os.path.join(REPO_ROOT, "examples", "triggering.lst")
NOT_TRIGGERING_LIST = os.path.join(REPO_ROOT, "examples", "not-triggering.lst")

# Seconds to wait between actual downloads, so the CDN is not hammered on a
# fresh clone.  The cached copy means this only ever matters the one time the
# media is absent; reuse the util's 5s when you want to match it exactly.
DOWNLOAD_INTERVAL_SECONDS = float(os.environ.get("EPILEPSY_GOLDEN_INTERVAL", "2"))
DOWNLOAD_TIMEOUT_SECONDS = float(os.environ.get("EPILEPSY_GOLDEN_TIMEOUT", "30"))
_GOLDEN_USER_AGENT = "epilepsy-warning-golden-media-test"

# Warnings the pipeline appends on every result (see api.py).
STANDING_WARNINGS = ("not_a_compliance_determination", "tile_averaging_approximation")


@dataclass(frozen=True)
class GoldenFixture:
    index: int
    url: str
    path: str
    expected_triggering: bool


def _extension_for_url(url: str) -> str:
    """Derive the file extension for a URL, matching :file:`download_gifs.sh`.

    Take the basename after the last ``/``, drop any query string, then take the
    extension after the last ``.``.  Fall back to ``gif`` (lowercased) when no
    extension is present.
    """
    base = url.rsplit("/", 1)[-1]
    base = base.split("?", 1)[0]
    if "." in base:
        ext = base.rsplit(".", 1)[-1].lower()
    else:
        ext = ""
    return ext or "gif"


def _resolve_fixtures() -> tuple[list[GoldenFixture], list[GoldenFixture]]:
    """Resolve both lists into ordered fixtures.

    Files are numbered sequentially from 1 per list, in line order, so the
    cache filename is deterministic and shared with ``download_gifs.sh``.
    """
    triggering: list[GoldenFixture] = []
    not_triggering: list[GoldenFixture] = []
    for path, expected in (
        (TRIGGERING_LIST, True),
        (NOT_TRIGGERING_LIST, False),
    ):
        bucket = triggering if expected else not_triggering
        # Mirror util/download_gifs.sh: the output directory is derived from the
        # list's basename (``triggering.lst`` -> ``triggering``) joined with the
        # list's directory, so running it from ``examples/`` writes to
        # ``examples/triggering``.
        base_dir = os.path.join(os.path.dirname(path), os.path.splitext(os.path.basename(path))[0])
        with open(path, encoding="utf-8") as handle:
            for index, line in enumerate(handle, start=1):
                url = line.strip()
                if not url:
                    continue
                ext = _extension_for_url(url)
                bucket.append(
                    GoldenFixture(
                        index=index,
                        url=url,
                        path=os.path.join(base_dir, f"{index}.{ext}"),
                        expected_triggering=expected,
                    )
                )
    return triggering, not_triggering


def _is_cached(path: str) -> bool:
    return os.path.isfile(path) and os.path.getsize(path) > 0


def _download(url: str, dest: str, timeout: float) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": _GOLDEN_USER_AGENT})
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    if not data:
        raise RuntimeError("download returned no bytes")
    with open(tmp, "wb") as handle:
        handle.write(data)
    os.replace(tmp, dest)


def _ensure_cache(
    fixtures: list[GoldenFixture],
) -> tuple[list[GoldenFixture], list[tuple[GoldenFixture, Exception]]]:
    """Ensure every fixture exists on disk, downloading the missing ones.

    Already-cached files are always available.  Missing files are downloaded in
    order, throttled by :data:`DOWNLOAD_INTERVAL_SECONDS`.  A failed download
    is recorded as skipped rather than raised, so a dead URL or no network does
    not fail the suite.  Returns ``(available, skipped)``.
    """
    available: list[GoldenFixture] = []
    skipped: list[tuple[GoldenFixture, Exception]] = []
    pending = [(i, fx) for i, fx in enumerate(fixtures, start=1) if not _is_cached(fx.path)]
    for position, (_original_index, fixture) in enumerate(pending, start=1):
        try:
            _download(fixture.url, fixture.path, DOWNLOAD_TIMEOUT_SECONDS)
            print(f"[{position}/{len(pending)}] {fixture.url} -> {fixture.path}")
        except Exception as exc:  # noqa: BLE001 - network-independent skip
            print(f"[{position}/{len(pending)}] SKIPPED {fixture.url}: {exc}")
            skipped.append((fixture, exc))
            continue
        available.append(fixture)
        if DOWNLOAD_INTERVAL_SECONDS and position < len(pending):
            time.sleep(DOWNLOAD_INTERVAL_SECONDS)
    available.extend(fx for fx in fixtures if _is_cached(fx.path))
    return available, skipped


def _signature(result: EngineResult) -> tuple:
    """Full measured surface, for the short-circuit equivalence check."""
    return (
        result.is_triggering,
        tuple(result.reasons),
        result.luminance_transitions,
        result.red_transitions,
        result.max_luminance_transitions_per_second,
        result.max_red_transitions_per_second,
        result.max_luminance_flashes_per_second,
        result.max_red_flashes_per_second,
        result.max_flashes_per_second,
        result.max_area_px2,
        result.area_threshold_px2,
        result.max_flashing_area_ratio,
        result.max_flashing_area_screen_fraction,
        result.max_transition_duration_ms,
        result.synchronized_area_merges,
        result.fast_flash_sequences,
        result.merged_fast_flash_transitions,
        result.extended_exposure_advisory,
    )


def _engine_result(path: str, enable_short_circuit: bool, options: AnalysisOptions) -> EngineResult:
    """Run one file through the engine with the short-circuit flag set.

    Decoding is shared with the public pipeline (same loop-repeat/compositing),
    so toggling only the engine flag isolates Phase-3 short-circuit correctness.
    """
    records, _state = decode_file(path, options)
    profile = options.resolved_profile()
    area_model = options.resolved_area_model(profile)
    grid = None
    area = None
    engine = None
    for record in records:
        frame = np.asarray(record.data)
        height, width = int(frame.shape[0]), int(frame.shape[1])
        if engine is None:
            grid = TileGrid.for_size(width, height, options.tile_grid_max)
            area = AreaEvaluator(grid, options, area_model)
            engine = TransitionEngine(options, profile, area)
            engine._enable_short_circuit = enable_short_circuit
        engine.add_frame(record.timestamp, tile_frame_uint8(frame, grid))
    return engine.finish()


class GoldenMediaTests(unittest.TestCase):
    triggering: list[GoldenFixture] = []
    not_triggering: list[GoldenFixture] = []
    skipped: list[tuple[GoldenFixture, Exception]] = []

    @classmethod
    def setUpClass(cls) -> None:
        triggering, not_triggering = _resolve_fixtures()
        (cls.triggering, cls.skipped) = _ensure_cache(triggering)
        available_safe, _ = _ensure_cache(not_triggering)
        cls.not_triggering = available_safe
        if not cls.triggering and not cls.not_triggering:
            detail = "; ".join(f"{f.path} ({exc})" for f, exc in cls.skipped)
            raise unittest.SkipTest(
                f"no golden media cached and downloads failed: {detail}. "
                "Run util/download_gifs.sh or set EPILEPSY_GOLDEN_INTERVAL=0 to populate the cache."
            )

    def test_triggering_fixtures_are_triggering(self) -> None:
        for fixture in self.triggering:
            with self.subTest(path=fixture.path):
                result = analyze_file(fixture.path)
                self.assertTrue(
                    result.is_triggering,
                    msg=f"{fixture.path} expected TRIGGERING but was safe",
                )
                self.assertFalse(
                    result.inconclusive,
                    msg=f"{fixture.path} was inconclusive",
                )
                for warning in STANDING_WARNINGS:
                    self.assertIn(warning, result.warnings, msg=f"{fixture.path} missing {warning}")

    def test_not_triggering_fixtures_are_safe(self) -> None:
        for fixture in self.not_triggering:
            with self.subTest(path=fixture.path):
                result = analyze_file(fixture.path)
                self.assertFalse(
                    result.is_triggering,
                    msg=f"{fixture.path} expected safe but was flagged TRIGGERING",
                )
                self.assertFalse(
                    result.inconclusive,
                    msg=f"{fixture.path} was inconclusive",
                )
                for warning in STANDING_WARNINGS:
                    self.assertIn(warning, result.warnings, msg=f"{fixture.path} missing {warning}")

    def test_short_circuit_equivalence(self) -> None:
        if not os.environ.get("EPILEPSY_GOLDEN_EQUIP"):
            self.skipTest("set EPILEPSY_GOLDEN_EQUIP=1 to run this opt-in check")
        options = AnalysisOptions()
        for fixture in [*self.triggering, *self.not_triggering]:
            with self.subTest(path=fixture.path):
                enabled = _engine_result(fixture.path, True, options)
                disabled = _engine_result(fixture.path, False, options)
                self.assertEqual(
                    _signature(enabled),
                    _signature(disabled),
                    msg=f"short-circuit changed the measured surface for {fixture.path}",
                )


if __name__ == "__main__":
    unittest.main()
