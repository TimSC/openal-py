"""Playback devices and their contexts."""
from __future__ import annotations

from typing import TYPE_CHECKING, Mapping
import weakref

from openal_py import _core, _finalize
from openal_py._errors import ALCError, ResourceClosedError, ResourceInUseError

if TYPE_CHECKING:
    from openal_py.context import Context


_devices: weakref.WeakValueDictionary[int, Device] = weakref.WeakValueDictionary()


class Device:
    """A playback device. Exiting its resource block closes the device.

    Close all contexts before closing their device.
    """

    def __init__(self, name: str | None = None):
        self._initialize(_core.open_device(name), name, True)

    def _initialize(self, handle: int, name: str | None, owned: bool) -> None:
        self._state = _finalize.DeviceState(handle, owned)
        self._name = name
        _devices[handle] = self
        self._finalizer = _finalize.finalize(self, self._state.close)

    @classmethod
    def from_handle(cls, handle: int, *, owned: bool = False,
                    name: str | None = None) -> Device:
        """Wrap an external handle; owned=True transfers cleanup responsibility."""
        if not isinstance(handle, int) or handle <= 0:
            raise ValueError("expected a nonzero device handle")
        existing = _devices.get(handle)
        if existing is not None:
            if existing._state.owned != owned:
                raise ValueError("device handle already has a different owner")
            return existing
        device = cls.__new__(cls)
        device._initialize(handle, name, owned)
        return device

    @classmethod
    def open(cls, name: str | None = None) -> Device:
        return cls(name)

    @classmethod
    def default(cls) -> Device:
        return cls()

    @property
    def handle(self) -> int | None:
        return self._state.handle

    @property
    def closed(self) -> bool:
        return self.handle is None

    @property
    def name(self) -> str | None:
        return self._name

    def _require_open(self) -> None:
        if self.closed:
            raise ResourceClosedError("device has been closed")

    def create_context(self, *, sample_rate: int | None = None,
                       attributes: Mapping[str | int, int] | None = None) -> Context:
        from openal_py.context import Context
        self._require_open()
        return Context(self, attributes, sample_rate=sample_rate)

    @property
    def spec(self) -> str:
        self._require_open()
        return _core.get_device_spec(self.handle)

    @property
    def extensions(self) -> frozenset[str]:
        self._require_open()
        return frozenset(_core.get_alc_extensions(self.handle))

    def supports(self, extension: str) -> bool:
        self._require_open()
        return _core.is_alc_extension_present(extension, self.handle)

    @property
    def attributes(self) -> dict[str, int]:
        from openal_py import ALC
        self._require_open()
        result = {}
        for name in ("ALC_FREQUENCY", "ALC_REFRESH", "ALC_SYNC",
                     "ALC_MONO_SOURCES", "ALC_STEREO_SOURCES"):
            try:
                result[name] = _core.get_integer(self.handle, getattr(ALC, name))
            except ALCError:
                continue
        return result

    def close(self) -> None:
        if any(state.handle is not None for state in self._state.contexts):
            raise ResourceInUseError("close the device's contexts before the device")
        handle = self.handle
        self._state.close()
        if handle is not None:
            _devices.pop(handle, None)
        self._finalizer.detach()

    def __enter__(self) -> Device:
        self._require_open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"Device(name={self._name!r}, closed={self.closed})"
