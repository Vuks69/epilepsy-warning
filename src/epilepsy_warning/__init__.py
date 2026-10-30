"""Standards-explicit flashing-content analysis.

The public API is deliberately small: analyze a file, bytes, or caller-supplied
frames and receive a structured :class:`~epilepsy_warning.result.AnalysisResult`.
The default profile is WCAG 2.2 SC 2.3.1.  A triggering result is evidence that
the configured working values were exceeded; it is not a compliance
determination for the media, a player, or a display.
"""

from __future__ import annotations

from ._version import __version__
from .api import analyze_bytes, analyze_file, analyze_frames
from .errors import (
    AnalysisTimeoutError,
    DecodeError,
    EpilepsyWarningError,
    InvalidFrameInputError,
    InvalidOptionsError,
    LimitExceededError,
    UnsupportedFormatError,
    UnsupportedInputError,
    UnsupportedStandardError,
)
from .options import AnalysisOptions, DisplayGeometry
from .result import AnalysisResult
from .standards import StandardProfile, available_profiles, get_profile

__all__ = [
    "AnalysisOptions",
    "AnalysisResult",
    "AnalysisTimeoutError",
    "DecodeError",
    "DisplayGeometry",
    "EpilepsyWarningError",
    "InvalidFrameInputError",
    "InvalidOptionsError",
    "LimitExceededError",
    "StandardProfile",
    "UnsupportedFormatError",
    "UnsupportedInputError",
    "UnsupportedStandardError",
    "__version__",
    "analyze_bytes",
    "analyze_file",
    "analyze_frames",
    "available_profiles",
    "get_profile",
]
