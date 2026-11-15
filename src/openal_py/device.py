"""Playback devices and their contexts."""
from __future__ import annotations

from typing import TYPE_CHECKING, Mapping
import weakref

from openal_py import _core, _finalize
from openal_py._constants import ALC
from openal_py._parameters import DeviceTiming, HRTFStatus, Parameter, resolve
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

    @staticmethod
    def default_name() -> str | None:
        parameter = 0x1012 if _core.is_alc_extension_present('ALC_ENUMERATE_ALL_EXT') else 0x1004
        return _core.alc_get_string(None, parameter)

    @property
    def version(self) -> tuple[int, int]:
        self._require_open()
        return (_core.get_integer(self.handle, ALC.ALC_MAJOR_VERSION),
                _core.get_integer(self.handle, ALC.ALC_MINOR_VERSION))

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

    def _require_extension(self, name: str) -> None:
        self._require_open()
        if not self.supports(name):
            raise NotImplementedError(f'{name} is unavailable on this device')

    def enum_value(self, name: str) -> int:
        self._require_open()
        return _core.enum_value(name, self.handle, True)

    def function_address(self, name: str) -> int | None:
        self._require_open()
        return _core.function_address(name, self.handle, True)

    def get_parameter(self, parameter: Parameter, *, count: int = 1) -> int | tuple[int, ...]:
        self._require_open()
        values = _core.get_integerv(self.handle, resolve(ALC, parameter), count)
        return values[0] if count == 1 else tuple(values)

    @property
    def timing(self) -> DeviceTiming:
        self._require_extension('ALC_SOFT_device_clock')
        return DeviceTiming(*_core.device_timing(self.handle))

    @property
    def hrtf_names(self) -> tuple[str, ...]:
        self._require_extension('ALC_SOFT_HRTF')
        count = _core.get_integer(self.handle, ALC.ALC_NUM_HRTF_SPECIFIERS_SOFT)
        return tuple(_core.device_string_index(self.handle, ALC.ALC_HRTF_SPECIFIER_SOFT, i) or ''
                     for i in range(count))

    @property
    def hrtf_status(self) -> HRTFStatus:
        self._require_extension('ALC_SOFT_HRTF')
        return HRTFStatus(_core.get_integer(self.handle, ALC.ALC_HRTF_STATUS_SOFT))

    @property
    def hrtf_enabled(self) -> bool:
        self._require_extension('ALC_SOFT_HRTF')
        return bool(_core.get_integer(self.handle, ALC.ALC_HRTF_SOFT))

    @property
    def hrtf_name(self) -> str | None:
        self._require_extension('ALC_SOFT_HRTF')
        return _core.alc_get_string(self.handle, ALC.ALC_HRTF_SPECIFIER_SOFT)

    def reset(self, *, hrtf: bool | None = None, hrtf_id: int | None = None,
              attributes: Mapping[str | int, int] | None = None) -> None:
        self._require_extension('ALC_SOFT_HRTF')
        attrs = {resolve(ALC, key): value for key, value in (attributes or {}).items()}
        if hrtf is not None:
            attrs[ALC.ALC_HRTF_SOFT] = int(hrtf)
        if hrtf_id is not None:
            attrs[ALC.ALC_HRTF_ID_SOFT] = hrtf_id
        _core.device_reset(self.handle, attrs)

    def reopen(self, name: str | None = None, *,
               attributes: Mapping[str | int, int] | None = None) -> None:
        self._require_extension('ALC_SOFT_reopen_device')
        attrs = {resolve(ALC, key): value for key, value in (attributes or {}).items()}
        _core.device_reset(self.handle, attrs, name, True)
        self._name = name

    def pause(self) -> None:
        self._require_extension('ALC_SOFT_pause_device')
        _core.device_pause(self.handle, True)

    def resume(self) -> None:
        self._require_extension('ALC_SOFT_pause_device')
        _core.device_pause(self.handle, False)

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
