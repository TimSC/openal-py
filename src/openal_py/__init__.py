"""Modern Python bindings for OpenAL-soft.

OpenAL is bundled by default. System OpenAL is used when the bundle is
unavailable or detects no playback devices. To select a specific implementation,
set ``OPENAL_PY_LIBRARY`` to its path before importing.

Quick start::

    import openal_py as al

    with al.AudioEngine() as audio:
        sound = audio.load("sound.wav")
        voice = audio.play(sound, gain=0.8)
        voice.wait()
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
    ContextNotCurrentError, ContextMismatchError, ResourceInUseError, ThreadAffinityError,
)
from openal_py._types import AudioFile, PCMData, Vector3
from openal_py._constants import AL, ALC
from openal_py.device import Device
from openal_py.engine import AudioEngine, Sound, Voice
from openal_py.context import Context
from openal_py.listener import Listener
from openal_py.source import Source, SourceState, SourceType
from openal_py.capture import CaptureDevice
from openal_py.loopback import LoopbackDevice
from openal_py.group import SourceGroup
from openal_py.effects import Effect, EffectType, Filter, FilterType, AuxiliaryEffectSlot
from openal_py._parameters import DistanceModel, HRTFStatus, DeviceTiming, PlaybackLatency, Parameter, ParameterValue, NumericKind
from openal_py.buffer import Buffer, AudioFormat, from_wav, from_file
from openal_py.streaming import PCMDecoder, SoundFileDecoder, StreamingSource, StreamState

__version__ = "0.1.0"

__all__ = [
    "PCMDecoder",
    "SoundFileDecoder",
    "StreamingSource",
    "StreamState",
    "AudioEngine",
    "Sound",
    "Voice",
    "ThreadAffinityError",
    "Parameter",
    "ParameterValue",
    "NumericKind",
    "CaptureDevice",
    "LoopbackDevice",
    "SourceGroup",
    "SourceType",
    "Effect",
    "EffectType",
    "Filter",
    "FilterType",
    "AuxiliaryEffectSlot",
    "DistanceModel",
    "HRTFStatus",
    "DeviceTiming",
    "PlaybackLatency",
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
