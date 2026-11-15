"""Shared decoding and PCM conversion policies (SoundFile remains optional)."""
from __future__ import annotations

import os
import struct
from typing import Any, BinaryIO, cast

from openal_py._types import AudioFile


class RelativeStream:
    """Borrow a seekable stream, making its current position the file origin."""

    def __init__(self, stream: BinaryIO):
        self.stream = stream
        self.origin = stream.tell()

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)

    def readinto(self, buffer: Any) -> int:
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def tell(self) -> int:
        return self.stream.tell() - self.origin

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.stream.seek(offset + self.origin if whence == 0 else offset, whence) - self.origin


def soundfile_input(file: AudioFile) -> Any:
    return os.fspath(file) if isinstance(file, (str, os.PathLike)) else RelativeStream(file)


def soundfile_module() -> Any:
    try:
        import soundfile
    except ImportError:
        raise ImportError('install openal-py[soundfile] to load this audio format') from None
    return soundfile


def wav_requires_decoder(stream: BinaryIO) -> bool:
    """Inspect the fmt chunk without consuming the caller's stream.

    Leave malformed/truncated headers to wave's normal error handling. Skip
    unknown chunks by seeking rather than allocating their declared sizes.
    """
    position = stream.tell()
    try:
        header = stream.read(12)
        if len(header) != 12 or header[:4] != b'RIFF' or header[8:] != b'WAVE':
            return False
        end = position + 8 + struct.unpack('<I', header[4:8])[0]
        while stream.tell() + 8 <= end:
            chunk = stream.read(8)
            if len(chunk) != 8:
                return False
            size = struct.unpack('<I', chunk[4:])[0]
            if stream.tell() + size > end:
                return False
            if chunk[:4] == b'fmt ':
                fmt = stream.read(min(size, 16))
                if len(fmt) < 16:
                    return False
                encoding, _, _, _, _, bits = struct.unpack('<HHIIHH', fmt)
                return encoding != 1 or bits not in (8, 16)
            stream.seek(size + size % 2, 1)
        return False
    finally:
        stream.seek(position)


def decoded_pcm(data: Any, *, floating: bool, mono: bool, bits: int) -> bytes:
    """Convert SoundFile frames to native-endian PCM.

    Mono uses the arithmetic channel mean, rounded down for integer PCM.
    Floating samples are scaled by 32768 and rounded down, then clipped. NaN
    becomes silence and infinities become the corresponding full-scale value.
    PCM8 is unsigned, centered at 128.
    """
    import numpy as np
    if mono:
        data = data.astype('float64').mean(axis=1, keepdims=True)
    if floating:
        data = np.nan_to_num(data, nan=0.0, posinf=1.0, neginf=-1.0)
        data = np.floor(np.clip(data, -1.0, 1.0) * 32768).clip(-32768, 32767)
    elif mono:
        data = np.floor(data)
    data = data.astype('int16')
    if bits == 8:
        data = ((data.astype('int32') >> 8) + 128).astype('uint8')
    return cast(bytes, data.tobytes())
