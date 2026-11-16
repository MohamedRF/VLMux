"""Application-specific exception hierarchy for VLMux.

Every VLMux error carries a machine-readable ``code`` so agents, MCP tools,
and HTTP clients can make programmatic decisions (for example, retrying a
``stale_ref`` failure after taking a fresh snapshot) instead of parsing
human-oriented messages.
"""

from __future__ import annotations


class VLMuxError(Exception):
    """Base class for errors that VLMux can report safely."""

    code = "internal_error"


class ConfigurationError(VLMuxError):
    """Raised when configuration cannot be loaded or validated."""

    code = "configuration_error"


class ModelConnectionError(VLMuxError):
    """Raised when a model provider cannot be reached."""

    code = "model_connection_error"


class ModelResponseError(VLMuxError):
    """Raised when a model response cannot be interpreted safely."""

    code = "model_response_error"


class ActionValidationError(VLMuxError):
    """Raised when a proposed action violates the VAP schema."""

    code = "action_validation_error"


class StaleRefError(ActionValidationError):
    """Raised when an element reference no longer matches the desktop."""

    code = "stale_ref"


class AmbiguousTargetError(ActionValidationError):
    """Raised when a reference matches more candidates than expected."""

    code = "ambiguous_target"


class ActionExecutionError(VLMuxError):
    """Raised when an executor cannot complete an action."""

    code = "action_execution_error"


class RefUnavailableError(ActionExecutionError):
    """Raised when ref-based actions cannot run on this platform."""

    code = "ref_unavailable"


class HeadlessActionNotSupportedError(ActionExecutionError):
    """Raised when an element supports no headless invocation pattern."""

    code = "headless_not_supported"


class PolicyViolationError(VLMuxError):
    """Raised when policy prevents an action from executing."""

    code = "policy_violation"


class ScreenCaptureError(VLMuxError):
    """Raised when a screen observation cannot be captured."""

    code = "screen_capture_error"


class UnsupportedPlatformError(VLMuxError):
    """Raised when no implementation exists for the current platform."""

    code = "unsupported_platform"


class MaximumStepsExceeded(VLMuxError):
    """Raised when a runtime reaches its configured step limit."""

    code = "maximum_steps_exceeded"


def error_code(error: BaseException) -> str:
    """Return the machine-readable code for any exception, safely."""

    return getattr(error, "code", None) or "internal_error"
