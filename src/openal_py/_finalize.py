"""Resource cleanup state that never retains its Python wrapper."""
from __future__ import annotations

from contextlib import contextmanager
import weakref

from openal_py import _core


class ContextState:
    """Keep the device alive and share context liveness with child finalizers."""

    def __init__(self, handle, device):
        self.handle = handle
        self.device = device

    @contextmanager
    def current(self):
        if self.handle is None:
            raise RuntimeError("context has been destroyed")
        previous = _core.get_current_context()
        changed = previous != self.handle
        if changed:
            if not _core.make_context_current(self.handle):
                raise RuntimeError("could not make context current")
        try:
            yield
        finally:
            if changed:
                _core.make_context_current(previous or None)

    def destroy(self):
        if self.handle is not None:
            if _core.get_current_context() == self.handle:
                _core.make_context_current(None)
            _core.destroy_context(self.handle)
            self.handle = None


def quietly(callback, *args):
    """Best-effort cleanup for GC; explicit cleanup still reports failures."""
    try:
        callback(*args)
    except Exception:
        pass


def release(context_state, handle, delete, keepalive=None):
    if context_state.handle is not None:
        with context_state.current():
            delete([handle])
    if keepalive is not None:
        keepalive.clear()


def register(obj, handle, delete, keepalive=None):
    """Return a cancellable finalizer routed through the owning context."""
    return weakref.finalize(
        obj, quietly, release, obj._context._state, handle, delete, keepalive
    )
