"""Audio buffer abstraction."""
from __future__ import annotations

import wave
import weakref
from enum import IntEnum
from typing import Optional

from openal_py import _core
from openal_py import _finalize
from openal_py._constants import AL


class AudioFormat(IntEnum):
    """OpenAL sample format (AL_FORMAT_*)."""

    MONO8 = AL.AL_FORMAT_MONO8
    MONO16 = AL.AL_FORMAT_MONO16
    STEREO8 = AL.AL_FORMAT_STEREO8
    STEREO16 = AL.AL_FORMAT_STEREO16


class Buffer:
    """A block of raw PCM sample data.

    Created via :meth:`Context.create_buffer` or the classmethods
    :meth:`from_pcm` / :meth:`from_wav`.
    """

    def __init__(self, context, handle: int, _owned: bool = True):
        self._context = context
        self._handle = handle
        self._finalizer = None
        if _owned:
            self._finalizer = _finalize.register(self, handle, _core.delete_buffers)

    # -- lifecycle ---------------------------------------------------------

    @property
    def handle(self) -> int:
        return self._handle

    def delete(self) -> None:
        if self._handle is not None:
            _finalize.release(self._context._state, self._handle, _core.delete_buffers)
            self._handle = None
            if self._finalizer is not None:
                self._finalizer.detach()

    # -- construction --------------------------------------------------------

    @classmethod
    def from_pcm(cls, context, data: bytes, format: AudioFormat | int,
                 frequency: int) -> "Buffer":
        """Create a buffer from raw interleaved PCM data."""
        context._require_current()
        buf = cls(context, _core.gen_buffers(1)[0])
        fmt = format.value if isinstance(format, AudioFormat) else format
        try:
            _core.buffer_data(buf._handle, fmt, data, frequency)
        except Exception:
            buf.delete()
            raise
        context._buffers[buf._handle] = weakref.ref(buf)
        return buf

    # format value -> (soundfile dtype, channel count)
    _SF_FORMATS = {
        AL.AL_FORMAT_MONO8: ("int16", 1),
        AL.AL_FORMAT_MONO16: ("int16", 1),
        AL.AL_FORMAT_STEREO8: ("int16", 2),
        AL.AL_FORMAT_STEREO16: ("int16", 2),
    }

    @classmethod
    def from_file(cls, context, filename: str,
                  format: AudioFormat | int = AudioFormat.MONO16) -> "Buffer":
        """Load an audio file (WAV, FLAC, OGG Vorbis, MP3, ...) via soundfile.

        Requires the optional ``soundfile`` package
        (``pip install openal-py[soundfile]``).  The file's channel count
        must match *format* (no downmixing is done).
        """
        try:
            import soundfile as sf
        except ImportError:
            raise ImportError(
                "Buffer.from_file() requires the 'soundfile' package: "
                "pip install soundfile"
            ) from None
        fmt = format.value if isinstance(format, AudioFormat) else int(format)
        try:
            sf_dtype, channels = cls._SF_FORMATS[fmt]
        except KeyError:
            raise ValueError(f"unsupported format for from_file: {fmt:#x}") from None
        data, rate = sf.read(str(filename), dtype=sf_dtype)
        n_ch = 1 if data.ndim == 1 else data.shape[1]
        if n_ch != channels:
            raise ValueError(
                f"file has {n_ch} channel(s), format expects {channels}; "
                "pass a matching format"
            )
        if fmt in (AL.AL_FORMAT_MONO8, AL.AL_FORMAT_STEREO8):
            data = ((data.astype("int32") >> 8) + 128).astype("uint8")
        return cls.from_pcm(context, data.tobytes(), fmt, int(rate))

    @classmethod
    def from_wav(cls, context, filename: str) -> "Buffer":
        """Create a buffer from a PCM WAV file (8/16-bit mono/stereo)."""
        with wave.open(filename, "rb") as w:
            channels = w.getnchannels()
            sample_width = w.getsampwidth()
            frequency = w.getframerate()
            data = w.readframes(w.getnframes())
        if sample_width not in (1, 2):
            raise ValueError(f"unsupported sample width: {sample_width} bytes")
        if channels == 1:
            fmt = AudioFormat.MONO16 if sample_width == 2 else AudioFormat.MONO8
        elif channels == 2:
            fmt = AudioFormat.STEREO16 if sample_width == 2 else AudioFormat.STEREO8
        else:
            raise ValueError(f"unsupported channel count: {channels}")
        return cls.from_pcm(context, data, fmt, frequency)

    def _require_current(self):
        if self._handle is None:
            raise RuntimeError("buffer has been deleted")
        self._context._require_current()

    # -- info -------------------------------------------------------------------

    @property
    def frequency(self) -> int:
        self._require_current()
        return _core.buffer_geti(self._handle, AL.AL_FREQUENCY)

    @property
    def channels(self) -> int:
        self._require_current()
        return _core.buffer_geti(self._handle, AL.AL_CHANNELS)

    @property
    def size(self) -> int:
        self._require_current()
        return _core.buffer_geti(self._handle, AL.AL_SIZE)

    def __repr__(self) -> str:
        if self._handle is None:
            return "Buffer(deleted)"
        return (f"Buffer(handle={self._handle}, freq={self.frequency}, "
                f"channels={self.channels})")


def from_wav(context, filename: str) -> Buffer:
    """Module-level convenience: ``openal_py.from_wav(ctx, 'a.wav')``."""
    return Buffer.from_wav(context, filename)


def from_file(context, filename: str, format: AudioFormat | int = AudioFormat.MONO16) -> Buffer:
    """Module-level convenience: ``openal_py.from_file(ctx, 'a.flac')``.

    Requires the optional ``soundfile`` package.
    """
    return Buffer.from_file(context, filename, format)
