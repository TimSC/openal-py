"""Modern Python bindings for OpenAL-soft.

OpenAL is bundled by default. System OpenAL is used when the bundle is
unavailable or detects no playback devices. To select a specific implementation,
set ``OPENAL_PY_LIBRARY`` to its path before importing.

Quick start::

    import openal_py as al

    with al.Device.open() as device, device.create_context() as ctx:
        with ctx.activate():
            ctx.listener.position = (0.0, 1.6, 0.0)
            sound = ctx.load("sound.wav")
            voice = ctx.create_source(buffer=sound, gain=0.8)
            voice.play()
            # Keep the context alive until playback is finished.
"""
from __future__ import annotations

from openal_py._core import (
    library_path,
    get_library_version,
    get_extensions,
    is_extension_present,
    enumerate_devices,
)
from openal_py._errors import (
    OpenALError, ALLError, ALCError, LifecycleError, ResourceClosedError,
    ContextNotCurrentError, ContextMismatchError, ResourceInUseError,
)
from openal_py._types import AudioFile, PCMData, Vector3
from openal_py._constants import AL, ALC
from openal_py.device import Device
from openal_py.context import Context
from openal_py.listener import Listener
from openal_py.source import Source, SourceState
from openal_py.buffer import Buffer, AudioFormat, from_wav, from_file

__version__ = "0.1.0"

__all__ = [
    "AudioFile",
    "PCMData",
    "Vector3",
    "LifecycleError",
    "ResourceClosedError",
    "ContextNotCurrentError",
    "ContextMismatchError",
    "ResourceInUseError",
    "AL",
    "ALC",
    "AudioFormat",
    "Buffer",
    "Context",
    "Device",
    "Listener",
    "OpenALError",
    "ALLError",
    "ALCError",
    "Source",
    "SourceState",
    "check_al",
    "check_alc",
    "enumerate_devices",
    "from_file",
    "from_wav",
    "get_extensions",
    "get_library_version",
    "is_extension_present",
    "library_path",
]


def check_al() -> None:
    from openal_py import _core
    _core.check_al()


def check_alc(device: Device | None = None) -> None:
    from openal_py import _core
    _core.check_alc(None if device is None else device.handle)
