"""Audio source abstraction."""
from __future__ import annotations

from enum import IntEnum
from typing import Optional, Sequence

from openal_py import _core
from openal_py import _finalize
from openal_py._constants import AL


class SourceState(IntEnum):
    INITIAL = AL.AL_INITIAL
    PLAYING = AL.AL_PLAYING
    PAUSED = AL.AL_PAUSED
    STOPPED = AL.AL_STOPPED


class Source:
    """A single playback voice.

    Created via :meth:`Context.create_source` (or directly with a handle).
    Parameters map to their OpenAL names with leading ``al`` removed:
    ``source.gain``, ``source.position``, ``source.looping``, ...
    """

    def __init__(self, context, handle: int):
        self._context = context
        self._handle = handle
        _finalize.register(self, handle, _core.delete_sources)

    # -- lifecycle ---------------------------------------------------------

    @property
    def handle(self) -> int:
        return self._handle

    def delete(self) -> None:
        if self._handle is not None:
            if getattr(self._context, "_handle", None) is None:
                # context already destroyed; its objects die with it
                self._handle = None
                return
            try:
                _core.source_set(self._handle, AL.AL_BUFFER, 0)  # unbind buffer
            except Exception:
                pass
            try:
                _core.delete_sources([self._handle])
            finally:
                self._handle = None

    # -- state --------------------------------------------------------------

    @property
    def state(self) -> SourceState:
        return SourceState(_core.source_geti(self._handle, AL.AL_SOURCE_STATE))

    def play(self) -> None:
        _core.source_play(self._handle)

    def pause(self) -> None:
        _core.source_pause(self._handle)

    def stop(self) -> None:
        _core.source_stop(self._handle)

    def is_playing(self) -> bool:
        return self.state == SourceState.PLAYING

    # -- scalar parameters ---------------------------------------------------

    def _set(self, pname, value) -> None:
        _core.source_set(self._handle, pname, value)

    def _get(self, pname, n: int = 1):
        return _core.source_get(self._handle, pname, n)

    def _geti(self, pname) -> int:
        return _core.source_geti(self._handle, pname)

    @property
    def gain(self) -> float:
        return self._get(AL.AL_GAIN)

    @gain.setter
    def gain(self, value: float) -> None:
        self._set(AL.AL_GAIN, float(value))

    @property
    def pitch(self) -> float:
        return self._get(AL.AL_PITCH)

    @pitch.setter
    def pitch(self, value: float) -> None:
        self._set(AL.AL_PITCH, float(value))

    @property
    def looping(self) -> bool:
        return self._geti(AL.AL_LOOPING) != 0

    @looping.setter
    def looping(self, value: bool) -> None:
        self._set(AL.AL_LOOPING, int(bool(value)))

    @property
    def relative(self) -> bool:
        return self._geti(AL.AL_SOURCE_RELATIVE) != 0

    @relative.setter
    def relative(self, value: bool) -> None:
        self._set(AL.AL_SOURCE_RELATIVE, int(bool(value)))

    @property
    def reference_distance(self) -> float:
        return self._get(AL.AL_REFERENCE_DISTANCE)

    @reference_distance.setter
    def reference_distance(self, value: float) -> None:
        self._set(AL.AL_REFERENCE_DISTANCE, float(value))

    @property
    def max_distance(self) -> float:
        return self._get(AL.AL_MAX_DISTANCE)

    @max_distance.setter
    def max_distance(self, value: float) -> None:
        self._set(AL.AL_MAX_DISTANCE, float(value))

    @property
    def rolloff_factor(self) -> float:
        return self._get(AL.AL_ROLLOFF_FACTOR)

    @rolloff_factor.setter
    def rolloff_factor(self, value: float) -> None:
        self._set(AL.AL_ROLLOFF_FACTOR, float(value))

    # -- vector parameters -----------------------------------------------------

    @property
    def position(self) -> tuple[float, float, float]:
        return self._get(AL.AL_POSITION, 3)

    @position.setter
    def position(self, value: Sequence[float]) -> None:
        self._set(AL.AL_POSITION, value)

    @property
    def velocity(self) -> tuple[float, float, float]:
        return self._get(AL.AL_VELOCITY, 3)

    @velocity.setter
    def velocity(self, value: Sequence[float]) -> None:
        self._set(AL.AL_VELOCITY, value)

    @property
    def direction(self) -> tuple[float, float, float]:
        return self._get(AL.AL_DIRECTION, 3)

    @direction.setter
    def direction(self, value: Sequence[float]) -> None:
        self._set(AL.AL_DIRECTION, value)

    # -- buffer -----------------------------------------------------------------

    @property
    def buffer(self) -> Optional["Buffer"]:  # noqa: F821
        from openal_py.buffer import Buffer
        h = self._geti(AL.AL_BUFFER)
        if h == 0:
            return None
        return self._context.get_buffer(h) or Buffer(self._context, h, _owned=False)

    @buffer.setter
    def buffer(self, value) -> None:
        from openal_py.buffer import Buffer
        if value is None:
            h = 0
        elif isinstance(value, Buffer):
            h = value.handle
        else:
            raise TypeError(f"expected Buffer or None, got {type(value)!r}")
        self._set(AL.AL_BUFFER, h)

    def __repr__(self) -> str:
        return f"Source(handle={self._handle}, state={self.state.name if self._handle is not None else 'deleted'})"
