"""Audio context abstraction."""
from __future__ import annotations

import weakref
from typing import Optional

from openal_py import _core
from openal_py._constants import ALC
from openal_py.device import Device


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
        self._handle = _core.create_context(
            device.handle,
            {getattr(ALC, k, k): v for k, v in (attributes or {}).items()},
        )
        # Buffer identity registry: handle -> weakref, so objects can be GC'd.
        self._buffers: dict[int, weakref.ref] = {}  # noqa: F821
        def _release() -> None:
            try:
                _core.make_context_current(None)
            except Exception:
                pass
            try:
                _core.destroy_context(self._handle)
            except Exception:
                pass
        weakref.finalize(self, _release)

    # -- properties ---------------------------------------------------------

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

    # -- state --------------------------------------------------------------

    def make_current(self) -> int:
        """Make this context current; returns the previous context handle."""
        return _core.make_context_current(self._handle)

    def process(self) -> None:
        """Process context updates (mixing). Usually done automatically."""
        _core.process_context(self._handle)

    def suspend(self) -> None:
        _core.suspend_context(self._handle)

    def destroy(self) -> None:
        if self._handle is not None:
            try:
                _core.destroy_context(self._handle)
            finally:
                self._handle = None

    # -- object factories ----------------------------------------------------

    def create_source(self, **params) -> "Source":  # noqa: F821
        from openal_py.source import Source
        sources = _core.gen_sources(1)
        src = Source(self, sources[0])
        for name, value in params.items():
            setattr(src, name, value)
        return src

    def create_buffer(self) -> "Buffer":  # noqa: F821
        from openal_py.buffer import Buffer
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
        self.make_current()
        return self

    def __exit__(self, *exc) -> None:
        _core.make_context_current(None)

    def __repr__(self) -> str:
        return f"Context(device={self._device!r}, current={self.is_current})"
