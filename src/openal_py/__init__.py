"""Modern Python bindings for OpenAL-soft.

OpenAL is bundled by default. System OpenAL is used when the bundle is
unavailable or detects no playback devices. To select a specific implementation,
set ``OPENAL_PY_LIBRARY`` to its path before importing.

Quick start::

    import openal_py as al

    device = al.Device.default()
    with al.Context(device) as ctx:
        listener = ctx.listener
        listener.position = (0.0, 1.6, 0.0)

        buf = al.Buffer.from_wav(ctx, "sound.wav")
        src = ctx.create_source()
        src.buffer = buf
        src.play()
"""
from openal_py._core import (
    library_path,
    get_library_version,
    get_extensions,
    is_extension_present,
    enumerate_devices,
)
from openal_py._errors import OpenALError, ALLError, ALCError
from openal_py._constants import AL, ALC
from openal_py.device import Device
from openal_py.context import Context
from openal_py.listener import Listener
from openal_py.source import Source, SourceState
from openal_py.buffer import Buffer, AudioFormat, from_wav, from_file

__version__ = "0.1.0"

__all__ = [
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


def check_al():
    from openal_py import _core
    _core.check_al()


def check_alc(device=None):
    from openal_py import _core
    _core.check_alc(device)
