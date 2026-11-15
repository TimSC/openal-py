"""OpenAL error types."""
from openal_py import _constants

_AL_NAMES = {getattr(_constants.AL, n): n for n in dir(_constants.AL)
             if isinstance(getattr(_constants.AL, n), int)}
_ALC_NAMES = {getattr(_constants.ALC, n): n for n in dir(_constants.ALC)
              if isinstance(getattr(_constants.ALC, n), int)}


class OpenALError(Exception):
    """Base class for OpenAL errors."""

    api = "AL"
    _names = _AL_NAMES

    def __init__(self, code: int) -> None:
        self.code = int(code)
        name = self._names.get(self.code)
        msg = f"{self.api} error {self.code:#x}"
        if name:
            msg += f" ({name})"
        super().__init__(msg)


class ALLError(OpenALError):
    """Error from an AL (rendering) call; code from alGetError()."""


class ALCError(OpenALError):
    """Error from an ALC (device/context) call; code from alcGetError()."""

    api = "ALC"
    _names = _ALC_NAMES


class LifecycleError(RuntimeError):
    """Invalid use of an OpenAL resource's lifetime or activation state."""


class ResourceClosedError(LifecycleError):
    """An operation requires a live resource."""


class ContextNotCurrentError(LifecycleError):
    """An operation requires the owning context to be current."""


class ResourceInUseError(LifecycleError):
    """A resource cannot close while dependent resources remain live."""


class ContextMismatchError(ValueError):
    """Resources belong to different contexts."""
