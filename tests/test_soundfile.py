"""Buffer.from_file() interop with the optional soundfile package."""
import os
import pathlib
import struct
import sys
import wave

import pytest

sf = pytest.importorskip("soundfile")

from openal_py import AudioFormat, Buffer  # noqa: E402
from openal_py._constants import AL  # noqa: E402


def _write_wav(path: pathlib.Path, rate: int = 44100, n: int = 4410,
               channels: int = 1) -> None:
    samples = struct.pack(f"<{n}h", *[int(8000 * (i % 7) / 7 - 3) for i in range(n)])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((samples * channels) if channels == 2 else samples)


class TestFromFile:
    def test_wav_mono16(self, ctx, tmp_path):
        p = tmp_path / "a.wav"
        _write_wav(p)
        buf = Buffer.from_file(ctx, str(p))
        assert buf.frequency == 44100
        assert buf.channels == 1
        assert buf.size == 4410 * 2

    def test_wav_stereo16(self, ctx, tmp_path):
        p = tmp_path / "s.wav"
        _write_wav(p, channels=2)
        buf = Buffer.from_file(ctx, str(p), AudioFormat.STEREO16)
        assert buf.channels == 2

    def test_flac(self, ctx, tmp_path):
        import numpy as np
        p = tmp_path / "a.flac"
        x = (np.sin(2 * np.pi * 440 * np.arange(4410) / 44100) * 8000).astype(np.float64)
        sf.write(str(p), x, 44100)
        buf = Buffer.from_file(ctx, str(p))
        assert buf.frequency == 44100
        assert buf.channels == 1

    def test_ogg_vorbis(self, ctx, tmp_path):
        import numpy as np
        p = tmp_path / "a.ogg"
        x = (np.sin(2 * np.pi * 440 * np.arange(8820) / 44100) * 8000).astype(np.float64)
        sf.write(str(p), x, 44100)
        buf = Buffer.from_file(ctx, str(p))
        assert buf.frequency == 44100
        assert buf.channels == 1
        assert buf.size > 0

    def test_ogg_stereo(self, ctx, tmp_path):
        import numpy as np
        p = tmp_path / "s.ogg"
        x = np.column_stack([
            np.sin(2 * np.pi * 440 * np.arange(8820) / 44100) * 8000,
            np.sin(2 * np.pi * 880 * np.arange(8820) / 44100) * 8000,
        ]).astype(np.float64)
        sf.write(str(p), x, 44100)
        buf = Buffer.from_file(ctx, str(p), AudioFormat.STEREO16)
        assert buf.channels == 2

    def test_channel_mismatch(self, ctx, tmp_path):
        p = tmp_path / "m.wav"
        _write_wav(p)  # mono
        with pytest.raises(ValueError, match="1 channel"):
            Buffer.from_file(ctx, str(p), AudioFormat.STEREO16)

    def test_int_format_passthrough(self, ctx, tmp_path):
        p = tmp_path / "i.wav"
        _write_wav(p)
        buf = Buffer.from_file(ctx, str(p), AL.AL_FORMAT_MONO16)
        assert buf.channels == 1

    def test_module_level_convenience(self, ctx, tmp_path):
        from openal_py import from_file
        p = tmp_path / "c.wav"
        _write_wav(p)
        buf = from_file(ctx, str(p))
        assert buf.frequency == 44100

    def test_missing_soundfile(self, ctx, tmp_path, monkeypatch):
        # Force `import soundfile` to fail
        monkeypatch.setitem(sys.modules, "soundfile", None)
        p = tmp_path / "x.wav"
        _write_wav(p)
        with pytest.raises(ImportError, match="soundfile"):
            Buffer.from_file(ctx, str(p))
