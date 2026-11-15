"""Hardware-independent offline rendering through ALC_SOFT_loopback."""
from __future__ import annotations
import operator
from typing import Mapping

from openal_py import _core
from openal_py._constants import ALC
from openal_py.buffer import AudioFormat
from openal_py.context import Context, _contexts
from openal_py.device import Device
from openal_py._errors import ContextNotCurrentError


class LoopbackDevice(Device):
    def __init__(self, name: str | None = None):
        if not _core.is_alc_extension_present('ALC_SOFT_loopback'):
            raise NotImplementedError('selected OpenAL does not support ALC_SOFT_loopback')
        self._initialize(_core.loopback_open(name), name, True)

    def supports_format(self, *, sample_rate: int, format: AudioFormat = AudioFormat.STEREO16) -> bool:
        self._require_open()
        rate = operator.index(sample_rate)
        if not 0 < rate <= 2**31 - 1:
            raise ValueError('sample_rate must be a positive native integer')
        fmt = AudioFormat(format)
        channels = ALC.ALC_MONO_SOFT if fmt.channels == 1 else ALC.ALC_STEREO_SOFT
        sample_type = ALC.ALC_UNSIGNED_BYTE_SOFT if fmt.bits == 8 else ALC.ALC_SHORT_SOFT
        return _core.loopback_supported(self.handle, rate, channels, sample_type)

    def create_context(self, *, sample_rate: int | None = 48000,
                       attributes: Mapping[str | int, int] | None = None,
                       format: AudioFormat = AudioFormat.STEREO16) -> Context:
        self._require_open()
        if sample_rate is None:
            raise ValueError('loopback contexts require a sample rate')
        fmt = AudioFormat(format)
        if not self.supports_format(sample_rate=sample_rate, format=fmt):
            raise ValueError('loopback output format is unsupported')
        attrs = {getattr(ALC, key) if isinstance(key, str) else key: value
                 for key, value in (attributes or {}).items()}
        required = {
            ALC.ALC_FORMAT_CHANNELS_SOFT: ALC.ALC_MONO_SOFT if fmt.channels == 1 else ALC.ALC_STEREO_SOFT,
            ALC.ALC_FORMAT_TYPE_SOFT: ALC.ALC_UNSIGNED_BYTE_SOFT if fmt.bits == 8 else ALC.ALC_SHORT_SOFT,
        }
        for key, value in required.items():
            if key in attrs and attrs[key] != value:
                raise ValueError('attributes conflict with requested output format')
            attrs[key] = value
        # OpenAL output layout is per-device; prevent invalidating an older context's layout.
        if any(state.handle is not None for state in self._state.contexts):
            raise ValueError('a loopback device supports one live context; open another device')
        return Context(self, attrs, sample_rate=sample_rate)

    def render(self, frames: int) -> bytes:
        """Render PCM frames synchronously in the current context's output format."""
        self._require_open()
        current = _contexts.get(_core.get_current_context())
        if current is None or current.device is not self:
            raise ContextNotCurrentError('a context belonging to this loopback device must be current')
        return _core.loopback_render(self.handle, operator.index(frames))
