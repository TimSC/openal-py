"""Listener (the "camera" / head of the listener) abstraction."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from openal_py._types import Vector3
from openal_py._errors import ContextNotCurrentError

if TYPE_CHECKING:
    from openal_py.context import Context

from openal_py import _core
from openal_py._constants import AL


class Listener:
    """Listener bound to a context; operations require that context current.

    With no argument, bind to the current managed Context at construction.
    """

    def __init__(self, context: Context | None = None):
        if context is None:
            from openal_py.context import _contexts
            context = _contexts.get(_core.get_current_context())
            if context is None:
                raise ContextNotCurrentError("a managed context must be current")
        context._require_open()
        self._context = context

    @property
    def context(self) -> Context:
        return self._context

    @property
    def closed(self) -> bool:
        return self.context.closed

    def _get(self, pname: int, n: int = 1) -> Any:
        self._context._require_current()
        return _core.listener_get(pname, n)

    def _set(self, pname: int, value: Any) -> None:
        self._context._require_current()
        _core.listener_set(pname, value)

    # -- 3f parameters ------------------------------------------------------

    @property
    def position(self) -> tuple[float, float, float]:
        return cast(tuple[float, float, float], self._get(AL.AL_POSITION, 3))

    @position.setter
    def position(self, value: Vector3) -> None:
        self._set(AL.AL_POSITION, value)

    @property
    def velocity(self) -> tuple[float, float, float]:
        return cast(tuple[float, float, float], self._get(AL.AL_VELOCITY, 3))

    @velocity.setter
    def velocity(self, value: Vector3) -> None:
        self._set(AL.AL_VELOCITY, value)

    @property
    def direction(self) -> tuple[float, float, float]:
        return self._orientation6[:3]

    @direction.setter
    def direction(self, value: Vector3) -> None:
        if len(value) != 3:
            raise ValueError("expected a three-component vector")
        o = self._orientation6
        self._set(AL.AL_ORIENTATION, (*value, *o[3:]))

    @property
    def up(self) -> tuple[float, float, float]:
        return self._orientation6[3:]

    @up.setter
    def up(self, value: Vector3) -> None:
        if len(value) != 3:
            raise ValueError("expected a three-component vector")
        o = self._orientation6
        self._set(AL.AL_ORIENTATION, (*o[:3], *value))

    @property
    def _orientation6(self) -> tuple[float, float, float, float, float, float]:
        return cast(tuple[float, float, float, float, float, float], self._get(AL.AL_ORIENTATION, 6))

    # -- scalar parameters ----------------------------------------------------

    @property
    def gain(self) -> float:
        return cast(float, self._get(AL.AL_GAIN))

    @gain.setter
    def gain(self, value: float) -> None:
        self._set(AL.AL_GAIN, float(value))

    def __repr__(self) -> str:
        return f"Listener(context={self.context!r})"
