"""Standards profiles.

The profiles deliberately share one engine.  A profile changes thresholds, the
area model, and the provenance recorded in the result; it must never silently
claim compliance with a standard that is only partially implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from .errors import UnsupportedStandardError


@dataclass(frozen=True)
class StandardProfile:
    id: str
    version: str
    coverage: str
    luminance_model: str
    area_model: str
    max_flashes_per_second: float
    notes: Tuple[str, ...] = ()
    implemented: bool = True

    @property
    def max_transitions_per_second(self) -> int:
        """Three flashes per second is six alternating transitions."""
        return int(round(self.max_flashes_per_second * 2.0))


_PROFILES: Dict[str, StandardProfile] = {
    "wcag22": StandardProfile(
        id="wcag22",
        version="2.2",
        coverage="partial",
        luminance_model="wcag_relative",
        area_model="wcag_solid_angle",
        max_flashes_per_second=3.0,
        notes=(
            "WCAG 2.2 SC 2.3.1 with the 2023 ISO-harmonized red definition.",
            "WCAG does not add a separate scene-change or inversion rule.",
        ),
    ),
    "iso9241-391": StandardProfile(
        id="iso9241-391",
        version="2016",
        coverage="partial",
        luminance_model="cd_m2",
        area_model="screen_fraction",
        max_flashes_per_second=3.0,
        notes=(
            "ISO SDR/HDR luminance model; 65 Hz fast-flash handling.",
            "Scene-change classification is not implemented.",
        ),
    ),
    "itu-r-bt1702": StandardProfile(
        id="itu-r-bt1702",
        version="2023",
        coverage="partial",
        luminance_model="cd_m2",
        area_model="screen_fraction",
        max_flashes_per_second=3.0,
        notes=(
            "ITU-R SDR/HDR luminance model.",
            "The leading-edge pacing qualification (334/360 ms) is not implemented; "
            "the unqualified, more conservative rate rule is applied.",
        ),
    ),
    "ofcom": StandardProfile(
        id="ofcom",
        version="2017",
        coverage="partial",
        luminance_model="cd_m2",
        area_model="screen_fraction",
        max_flashes_per_second=3.0,
        notes=(
            "Ofcom/ITC SDR luminance model.",
            "The leading-edge pacing qualification is not implemented; the "
            "unqualified, more conservative rate rule is applied.",
        ),
    ),
    "nhk-jba": StandardProfile(
        id="nhk-jba",
        version="2020",
        coverage="not_implemented",
        luminance_model="cd_m2",
        area_model="screen_fraction",
        max_flashes_per_second=3.0,
        notes=(
            "Japan's area/contrast-dependent rates and scene-change rules are "
            "out of scope for this prototype.",
        ),
        implemented=False,
    ),
    "custom": StandardProfile(
        id="custom",
        version="custom",
        coverage="custom",
        luminance_model="wcag_relative",
        area_model="wcag_solid_angle",
        max_flashes_per_second=3.0,
        notes=("Explicit thresholds supplied by the caller.",),
    ),
}

_ALIASES = {
    "wcag": "wcag22",
    "wcag2.2": "wcag22",
    "iso": "iso9241-391",
    "iso9241-391": "iso9241-391",
    "itu": "itu-r-bt1702",
    "itu-r": "itu-r-bt1702",
    "itu-r-bt.1702": "itu-r-bt1702",
    "ofcom": "ofcom",
    "nhk": "nhk-jba",
    "nhk-jba": "nhk-jba",
    "japan": "nhk-jba",
    "custom": "custom",
}


def get_profile(standard: str) -> StandardProfile:
    key = standard.strip().lower()
    profile_id = _ALIASES.get(key, key)
    profile = _PROFILES.get(profile_id)
    if profile is None:
        supported = ", ".join(sorted(_PROFILES))
        raise UnsupportedStandardError(
            "Unsupported standard profile %r. Supported profiles: %s" % (standard, supported)
        )
    if not profile.implemented:
        raise UnsupportedStandardError(
            "The %s profile is not implemented in this prototype." % profile.id
        )
    return profile


def available_profiles() -> Tuple[str, ...]:
    return tuple(sorted(profile.id for profile in _PROFILES.values() if profile.implemented))
