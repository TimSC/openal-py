"""Cleanup state never retains its own public wrapper."""
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Callable, Iterator
import weakref

from openal_py import _core
from openal_py._errors import ResourceClosedError

if TYPE_CHECKING:
    from openal_py.device import Device


class DeviceState:
    def __init__(self, handle: int, owned: bool):
        self.handle: int | None = handle
        self.owned = owned
        self.contexts: weakref.WeakSet[ContextState] = weakref.WeakSet()

    def close(self) -> None:
        if self.handle is not None:
            if self.owned:
                _core.close_device(self.handle)
            self.handle = None


class ContextState:
    def __init__(self, handle: int, device: Device, owned: bool = True):
        self.handle: int | None = handle
        self.device = device
        self.owned = owned
        device._state.contexts.add(self)

    @contextmanager
    def current(self) -> Iterator[None]:
        if self.handle is None:
            raise ResourceClosedError("context has been destroyed")
        from openal_py.context import _contexts
        previous = _core.get_current_context()
        previous_owner = _contexts.get(previous)
        original = self.handle
        if previous != original and not _core.make_context_current(original):
            raise RuntimeError("could not make context current")
        try:
            yield
        finally:
            # Explicit closure inside a block must never restore a dead handle.
            restore = previous or None
            if previous_owner is not None and previous_owner.closed:
                restore = None
            elif previous == original and self.handle is None:
                restore = None
            _core.make_context_current(restore)

    def destroy(self) -> None:
        if self.handle is not None:
            if self.owned:
                if _core.get_current_context() == self.handle:
                    _core.make_context_current(None)
                _core.destroy_context(self.handle)
            self.handle = None


def quietly(callback: Callable[..., object], *args: object) -> None:
    try:
        callback(*args)
    except Exception:
        pass


def finalize(obj: object, callback: Callable[..., object]) -> weakref.finalize[Any, Any]:
    return weakref.finalize(obj, quietly, callback)


def release(context_state: ContextState, handle: int,
            delete: Callable[[list[int]], None], keepalive: list[Any] | None = None) -> None:
    if context_state.handle is not None:
        with context_state.current():
            delete([handle])
    if keepalive is not None:
        keepalive.clear()


def register(obj: object, context_state: ContextState, handle: int,
             delete: Callable[[list[int]], None], keepalive: list[Any] | None = None) -> weakref.finalize[Any, Any]:
    return weakref.finalize(obj, quietly, release, context_state, handle, delete, keepalive)
