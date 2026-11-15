"""Listener (the "camera" / head of the listener) abstraction."""
from __future__ import annotations

from typing import Sequence

from openal_py import _core
from openal_py._constants import AL


class Listener:
    """Wrapper around the current context's listener parameters.

    Not a handle-based object: OpenAL has exactly one listener per
    context, so this is a plain namespace over the ``alListener*``
    calls. Requires a current context.
    """

    # -- 3f parameters ------------------------------------------------------

    @property
    def position(self) -> tuple[float, float, float]:
        return _core.listener_get(AL.AL_POSITION, 3)

    @position.setter
    def position(self, value: Sequence[float]) -> None:
        _core.listener_set(AL.AL_POSITION, value)

    @property
    def velocity(self) -> tuple[float, float, float]:
        return _core.listener_get(AL.AL_VELOCITY, 3)

    @velocity.setter
    def velocity(self, value: Sequence[float]) -> None:
        _core.listener_set(AL.AL_VELOCITY, value)

    @property
    def direction(self) -> tuple[float, float, float]:
        return self._orientation6[:3]

    @direction.setter
    def direction(self, value: Sequence[float]) -> None:
        o = self._orientation6
        _core.listener_set(AL.AL_ORIENTATION, (*value, *o[3:]))

    @property
    def up(self) -> tuple[float, float, float]:
        return self._orientation6[3:]

    @up.setter
    def up(self, value: Sequence[float]) -> None:
        o = self._orientation6
        _core.listener_set(AL.AL_ORIENTATION, (*o[:3], *value))

    @property
    def _orientation6(self) -> tuple:
        return _core.listener_get(AL.AL_ORIENTATION, 6)

    # -- scalar parameters ----------------------------------------------------

    @property
    def gain(self) -> float:
        return _core.listener_get(AL.AL_GAIN)

    @gain.setter
    def gain(self, value: float) -> None:
        _core.listener_set(AL.AL_GAIN, float(value))

    def __repr__(self) -> str:
        return (f"Listener(position={self.position}, "
                f"direction={self.direction})")
