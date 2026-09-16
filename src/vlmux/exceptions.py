"""Application-specific exception hierarchy for VLMux."""


class VLMuxError(Exception):
    """Base class for errors that VLMux can report safely."""


class ConfigurationError(VLMuxError):
    """Raised when configuration cannot be loaded or validated."""


class ModelConnectionError(VLMuxError):
    """Raised when a model provider cannot be reached."""


class ModelResponseError(VLMuxError):
    """Raised when a model response cannot be interpreted safely."""


class ActionValidationError(VLMuxError):
    """Raised when a proposed action violates the VAP schema."""


class ActionExecutionError(VLMuxError):
    """Raised when an executor cannot complete an action."""


class PolicyViolationError(VLMuxError):
    """Raised when policy prevents an action from executing."""


class ScreenCaptureError(VLMuxError):
    """Raised when a screen observation cannot be captured."""


class UnsupportedPlatformError(VLMuxError):
    """Raised when no implementation exists for the current platform."""


class MaximumStepsExceeded(VLMuxError):
    """Raised when a runtime reaches its configured step limit."""
