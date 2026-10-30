"""Typed errors raised by the epilepsy-warning library."""

from __future__ import annotations


class EpilepsyWarningError(Exception):
    """Base class for all library errors."""


class InvalidOptionsError(EpilepsyWarningError, ValueError):
    """The analysis options are invalid or unsupported."""


class UnsupportedStandardError(InvalidOptionsError):
    """The requested standards profile is not implemented."""


class UnsupportedFormatError(EpilepsyWarningError):
    """The input format is not supported by the available decoders."""


class UnsupportedInputError(EpilepsyWarningError):
    """The input source is valid but cannot be decoded in this form."""


class DecodeError(EpilepsyWarningError):
    """The media could not be decoded."""


class LimitExceededError(EpilepsyWarningError):
    """The input exceeds a hard resource limit."""


class AnalysisTimeoutError(EpilepsyWarningError):
    """The analysis deadline was exceeded."""


class InvalidFrameInputError(EpilepsyWarningError, ValueError):
    """Caller-supplied frames or timestamps are invalid."""
