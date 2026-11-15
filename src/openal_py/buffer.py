"""PCM buffers, metadata, and audio loading."""
from __future__ import annotations

from array import array
from enum import IntEnum
import os
import sys
from typing import TYPE_CHECKING
import wave

from openal_py import _core
from openal_py._resource import ContextResource
from openal_py._constants import AL
from openal_py._types import AudioFile, PCMData
from openal_py._parameters import Parameter, ParameterValue, resolve
from typing import cast

if TYPE_CHECKING:
    from openal_py.context import Context


class AudioFormat(IntEnum):
    MONO8 = AL.AL_FORMAT_MONO8
    MONO16 = AL.AL_FORMAT_MONO16
    STEREO8 = AL.AL_FORMAT_STEREO8
    STEREO16 = AL.AL_FORMAT_STEREO16

    @property
    def channels(self) -> int:
        return 1 if self in (self.MONO8, self.MONO16) else 2

    @property
    def bits(self) -> int:
        return 8 if self in (self.MONO8, self.STEREO8) else 16

    @property
    def bytes_per_frame(self) -> int:
        return self.channels * self.bits // 8


def _infer_format(channels: int, bits: int = 16) -> AudioFormat:
    for format in AudioFormat:
        if format.channels == channels and format.bits == bits:
            return format
    raise ValueError(f"unsupported audio layout: {channels} channels, {bits} bits")


class Buffer(ContextResource):
    """A PCM buffer. Construction creates an empty, owned native buffer."""

    def __init__(self, context: Context):
        context._require_current()
        self._initialize(context, _core.gen_buffers(1)[0], True)

    def _initialize(self, context: Context, handle: int, owned: bool) -> None:
        self._initialize_resource(context, handle, _core.delete_buffers, owned=owned)
        self._format: AudioFormat | int | None = None
        context._buffers[handle] = self

    @classmethod
    def from_handle(cls, context: Context, handle: int, *, owned: bool = False) -> Buffer:
        """Wrap a native buffer; borrowed wrappers never delete the native name."""
        context._require_current()
        existing = context.get_buffer(handle)
        if existing is not None:
            if existing._owned != owned:
                raise ValueError("buffer handle already has a different owner")
            return existing
        if not isinstance(handle, int) or handle <= 0 or not _core.is_buffer(handle):
            raise ValueError("expected a live buffer handle in the current context")
        buffer = cls.__new__(cls)
        buffer._initialize(context, handle, owned)
        return buffer

    def _after_close(self, handle: int) -> None:
        if self.context._buffers.get(handle) is self:
            self.context._buffers.pop(handle, None)

    delete = ContextResource.close

    @classmethod
    def from_pcm(cls, context: Context, data: PCMData, format: AudioFormat | int,
                 sample_rate: int) -> Buffer:
        """Upload interleaved native-endian PCM from any buffer-protocol object."""
        context._require_current()
        pcm = memoryview(data).tobytes()
        buffer = cls(context)
        try:
            _core.buffer_data(buffer._handle, int(format), pcm, sample_rate)
        except Exception:
            buffer.close()
            raise
        buffer._format = format
        return buffer

    @classmethod
    def from_file(cls, context: Context, file: AudioFile,
                  format: AudioFormat | int | None = None) -> Buffer:
        """Decode via optional soundfile; infer mono/stereo 16-bit by default.

        Explicit formats change sample width, never the file's channel count.
        Caller-owned file objects remain open.
        """
        context._require_current()
        try:
            import soundfile as sf
        except ImportError:
            raise ImportError("install openal-py[soundfile] to load this audio format") from None
        data, rate = sf.read(os.fspath(file) if isinstance(file, os.PathLike) else file,
                             dtype="int16", always_2d=True)
        channels = data.shape[1]
        fmt = _infer_format(channels) if format is None else AudioFormat(format)
        if channels != fmt.channels:
            raise ValueError(f"file has {channels} channel(s), format expects {fmt.channels}")
        if fmt.bits == 8:
            data = ((data.astype("int32") >> 8) + 128).astype("uint8")
        return cls.from_pcm(context, data, fmt, int(rate))

    @classmethod
    def from_wav(cls, context: Context, file: AudioFile,
                 *, format: AudioFormat | int | None = None) -> Buffer:
        """Decode 8/16-bit mono/stereo WAV, accepting paths or binary streams."""
        context._require_current()
        with wave.open(os.fspath(file) if isinstance(file, os.PathLike) else file, "rb") as wav:
            channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            if width not in (1, 2):
                raise ValueError(f"unsupported sample width: {width} bytes")
            natural = _infer_format(channels, width * 8)
            fmt = natural if format is None else AudioFormat(format)
            if fmt.channels != channels:
                raise ValueError(f"file has {channels} channel(s), format expects {fmt.channels}")
            data = wav.readframes(wav.getnframes())
        if width == 2:
            samples = array("h")
            samples.frombytes(data)
            if sys.byteorder != "little":
                samples.byteswap()
            pcm = bytes((sample >> 8) + 128 for sample in samples) if fmt.bits == 8 else samples.tobytes()
        elif fmt.bits == 16:
            pcm = array("h", ((sample - 128) << 8 for sample in data)).tobytes()
        else:
            pcm = data
        return cls.from_pcm(context, pcm, fmt, rate)

    def _info(self, parameter: int) -> int:
        self._require_current()
        return _core.buffer_geti(self._handle, parameter)

    @property
    def sample_rate(self) -> int:
        return self._info(AL.AL_FREQUENCY)

    frequency = sample_rate

    @property
    def channels(self) -> int:
        return self._info(AL.AL_CHANNELS)

    @property
    def bits(self) -> int:
        return self._info(AL.AL_BITS)

    @property
    def size(self) -> int:
        """Native PCM storage size in bytes."""
        return self._info(AL.AL_SIZE)

    @property
    def format(self) -> AudioFormat | int | None:
        self._require_current()
        if self._format is not None:
            try:
                return AudioFormat(self._format)
            except ValueError:
                return self._format
        if not self.sample_rate or not self.bits or not self.channels:
            return None
        return _infer_format(self.channels, self.bits)

    @property
    def frame_count(self) -> int:
        frame_size = self.channels * self.bits // 8
        return self.size // frame_size if frame_size else 0

    @property
    def duration(self) -> float:
        """Duration in seconds (zero for an empty buffer)."""
        rate = self.sample_rate
        return self.frame_count / rate if rate else 0.0

    def get_parameter(self, parameter: Parameter, *, integer: bool = True) -> ParameterValue:
        self._require_current()
        return cast(ParameterValue, _core.object_parameter('buffer', self.handle, resolve(AL, parameter), integer))

    def set_parameter(self, parameter: Parameter, value: ParameterValue) -> None:
        self._require_current()
        _core.buffer_set(self.handle, resolve(AL, parameter), value)

    @property
    def loop_points(self) -> tuple[int, int]:
        self._require_current()
        if not self.context.supports('AL_SOFT_loop_points'):
            raise NotImplementedError('AL_SOFT_loop_points is unavailable')
        return cast(tuple[int, int], self.get_parameter(AL.AL_LOOP_POINTS_SOFT))

    @loop_points.setter
    def loop_points(self, points: tuple[int, int]) -> None:
        self._require_current()
        if not self.context.supports('AL_SOFT_loop_points'):
            raise NotImplementedError('AL_SOFT_loop_points is unavailable')
        self.set_parameter(AL.AL_LOOP_POINTS_SOFT, points)



def from_wav(context: Context, file: AudioFile) -> Buffer:
    return Buffer.from_wav(context, file)


def from_file(context: Context, file: AudioFile,
              format: AudioFormat | int | None = None) -> Buffer:
    return Buffer.from_file(context, file, format)
