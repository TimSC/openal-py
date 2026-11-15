"""Audio device abstraction."""
from __future__ import annotations

from typing import Optional

from openal_py import _core


class Device:
    """An OpenAL capture/rendering device.

    Created via :meth:`open` (or :meth:`default`). Call :meth:`close` or
    use as a context manager to release the device.
    """

    def __init__(self, handle: int, name: Optional[str] = None):
        self._handle = handle
        self._name = name

    # -- creation ---------------------------------------------------------

    @property
    def handle(self) -> int:
        return self._handle

    @property
    def name(self) -> Optional[str]:
        return self._name

    @classmethod
    def open(cls, name: Optional[str] = None) -> "Device":
        """Open a device by name (``None`` for the default device)."""
        handle = _core.open_device(name)
        return cls(handle, name)

    @classmethod
    def default(cls) -> "Device":
        return cls.open(None)

    # -- info -------------------------------------------------------------

    @property
    def spec(self) -> str:
        """Device specifier string."""
        return _core.get_device_spec(self._handle)

    @property
    def extensions(self) -> list:
        """ALC extensions supported by this device."""
        return _core.get_alc_extensions(self._handle)

    def is_alc_extension_present(self, name: str) -> bool:
        return _core.is_alc_extension_present(name, self._handle)

    @property
    def attributes(self) -> dict:
        """Standard device attributes as a {name: value} dict."""
        from openal_py import ALC
        names = (
            "ALC_FREQUENCY", "ALC_REFRESH", "ALC_SYNC",
            "ALC_MONO_SOURCES", "ALC_STEREO_SOURCES",
        )
        attrs = {}
        for name in names:
            try:
                attrs[name] = _core.get_integer(self._handle, getattr(ALC, name))
            except Exception:
                pass
        return attrs

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        if self._handle is not None:
            _core.close_device(self._handle)
            self._handle = None

    def __enter__(self) -> "Device":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:
        state = "closed" if self._handle is None else self._name or "default"
        return f"Device({state!r})"
