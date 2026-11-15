"""Audio context abstraction."""
from __future__ import annotations

import weakref
from typing import Optional

from openal_py import _core, _finalize
from openal_py._constants import ALC
from openal_py.device import Device


_contexts = weakref.WeakValueDictionary()


class Context:
    """An OpenAL rendering context.

    At most one context is current process-wide; making this context
    current (e.g. via ``with ctx:``) routes all AL calls to it.

    Typical usage::

        device = Device.default()
        ctx = Context(device)
        with ctx:
            ...  # all AL objects created here
    """

    def __init__(self, device: Device, attributes: Optional[dict] = None):
        self._device = device
        handle = _core.create_context(
            device.handle,
            {getattr(ALC, k, k) if isinstance(k, str) else k: v
             for k, v in (attributes or {}).items()},
        )
        # Buffer identity registry: handle -> weakref, so objects can be GC'd.
        self._buffers: dict[int, weakref.ref] = {}  # noqa: F821
        self._state = _finalize.ContextState(handle, device)
        self._finalizer = weakref.finalize(
            self, _finalize.quietly, self._state.destroy
        )
        self._previous_contexts = []
        _contexts[handle] = self

    # -- properties ---------------------------------------------------------

    @property
    def _handle(self):
        return self._state.handle

    @property
    def handle(self) -> int:
        return self._handle

    @property
    def device(self) -> Device:
        return self._device

    @property
    def spec(self) -> str:
        return _core.get_device_spec(self._device.handle)

    @property
    def is_current(self) -> bool:
        return _core.get_current_context() == self._handle

    def _require_current(self):
        if self._handle is None:
            raise RuntimeError("context has been destroyed")
        if not self.is_current:
            raise RuntimeError("owning context must be current")

    @property
    def listener(self):
        """The listener bound to this context."""
        from openal_py.listener import Listener
        return Listener(self)

    # -- state --------------------------------------------------------------

    def make_current(self) -> int:
        """Make this context current; returns the previous context handle."""
        if self._handle is None:
            raise RuntimeError("context has been destroyed")
        previous = _core.get_current_context()
        if not _core.make_context_current(self._handle):
            raise RuntimeError("could not make context current")
        return previous

    def process(self) -> None:
        """Process context updates (mixing). Usually done automatically."""
        _core.process_context(self._handle)

    def suspend(self) -> None:
        _core.suspend_context(self._handle)

    def destroy(self) -> None:
        handle = self._handle
        self._state.destroy()
        _contexts.pop(handle, None)
        self._finalizer.detach()

    # -- object factories ----------------------------------------------------

    def create_source(self, **params) -> "Source":  # noqa: F821
        from openal_py.source import Source
        self._require_current()
        sources = _core.gen_sources(1)
        src = Source(self, sources[0])
        try:
            for name, value in params.items():
                if not isinstance(getattr(type(src), name, None), property):
                    raise TypeError(f"unknown source parameter: {name}")
                setattr(src, name, value)
        except Exception:
            src.delete()
            raise
        return src

    def create_buffer(self) -> "Buffer":  # noqa: F821
        from openal_py.buffer import Buffer
        self._require_current()
        h = _core.gen_buffers(1)[0]
        buf = Buffer(self, h)
        self._buffers[h] = weakref.ref(buf)
        return buf

    def get_buffer(self, handle: int) -> Optional["Buffer"]:  # noqa: F821
        """Canonical Buffer object for a handle (identity-stable)."""
        ref = self._buffers.get(handle)
        if ref is not None:
            buf = ref()
            if buf is not None and buf.handle == handle:
                return buf
            del self._buffers[handle]
        return None

    # -- context manager ------------------------------------------------------

    def __enter__(self) -> "Context":
        previous = self.make_current()
        self._previous_contexts.append(previous)
        return self

    def __exit__(self, *exc) -> None:
        previous = self._previous_contexts.pop()
        _core.make_context_current(previous or None)

    def __repr__(self) -> str:
        return f"Context(device={self._device!r}, current={self.is_current})"
