"""Buffers: formats, info queries, WAV loading."""
import wave

import pytest

from openal_py import AL, AudioFormat, Buffer
from openal_py._errors import ALLError


def _write_wav(path, channels, sample_width, rate, frames):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(rate)
        # 16-bit: center 0x8000; 8-bit: center 0x80
        center = b"\x00\x80" if sample_width == 2 else b"\x80"
        w.writeframes(center * (frames * channels))


@pytest.mark.parametrize(
    ("fmt", "channels", "bytes", "freq"),
    [
        (AudioFormat.MONO8, 1, 8000, 8000),
        (AudioFormat.MONO16, 1, 16000, 44100),
        (AudioFormat.STEREO8, 2, 16000, 8000),
        (AudioFormat.STEREO16, 2, 32000, 44100),
    ],
)
def test_from_pcm_formats(ctx, fmt, channels, bytes, freq):
    data = b"\x00" * bytes
    buf = Buffer.from_pcm(ctx, data, fmt, freq)
    try:
        assert buf.frequency == freq
        assert buf.channels == channels
        assert buf.size == bytes
    finally:
        buf.delete()


def test_from_pcm_accepts_plain_int_format(ctx):
    buf = Buffer.from_pcm(ctx, b"\x00" * 100, AL.AL_FORMAT_MONO16, 22050)
    try:
        assert buf.channels == 1
    finally:
        buf.delete()


def test_from_pcm_rejects_bad_format(ctx):
    with pytest.raises(ALLError):
        Buffer.from_pcm(ctx, b"\x00" * 100, 0xDEAD, 44100)


def test_from_pcm_rejects_bad_frequency(ctx):
    with pytest.raises(ValueError):
        Buffer.from_pcm(ctx, b"\x00" * 100, AudioFormat.MONO16, -1)


def test_create_buffer_empty(ctx):
    buf = ctx.create_buffer()
    try:
        assert buf.handle != 0
        assert buf.frequency == 0  # unbound buffer
    finally:
        buf.delete()


@pytest.mark.parametrize(
    ("channels", "width"), [(1, 1), (1, 2), (2, 1), (2, 2)]
)
def test_from_wav(ctx, tmp_path, channels, width):
    wav = tmp_path / "tone.wav"
    _write_wav(wav, channels, width, 22050, 1102)
    buf = Buffer.from_wav(ctx, str(wav))
    try:
        assert buf.channels == channels
        assert buf.frequency == 22050
        assert buf.size == 1102 * channels * width
    finally:
        buf.delete()


def test_from_wav_rejects_3_channel(tmp_path, ctx):
    wav = tmp_path / "odd.wav"
    _write_wav(wav, 3, 2, 22050, 100)
    with pytest.raises(ValueError):
        Buffer.from_wav(ctx, str(wav))


def test_buffer_identity_via_source(ctx):
    buf = Buffer.from_pcm(ctx, b"\x00\x00" * 100, AudioFormat.MONO16, 44100)
    src = ctx.create_source(buffer=buf)
    try:
        assert src.buffer is buf  # canonical object, not a new wrapper
    finally:
        src.delete()
        buf.delete()


def test_delete_idempotent(ctx):
    buf = Buffer.from_pcm(ctx, b"\x00" * 100, AudioFormat.MONO8, 8000)
    buf.delete()
    buf.delete()  # must not raise
    assert buf.handle is None


def test_buffer_repr(ctx):
    buf = Buffer.from_pcm(ctx, b"\x00" * 100, AudioFormat.MONO16, 8000)
    r = repr(buf)
    assert "Buffer" in r
    buf.delete()
    assert "deleted" in repr(buf)


@pytest.mark.parametrize("width", [3, 4])
def test_wav_rejects_unsupported_sample_width(ctx, tmp_path, width):
    path = tmp_path / "wide.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(width)
        output.setframerate(8000)
        output.writeframes(b"\0" * width * 10)
    with pytest.raises(ValueError, match="sample width"):
        Buffer.from_wav(ctx, str(path))


def test_audio_format_is_int_enum():
    from enum import IntEnum
    assert isinstance(AudioFormat.MONO8, IntEnum)
    assert AudioFormat(AL.AL_FORMAT_MONO16) is AudioFormat.MONO16


def test_failed_upload_releases_allocated_buffer(ctx, monkeypatch):
    from openal_py import _core
    generated = []
    gen_buffers = _core.gen_buffers

    def record(n):
        handles = gen_buffers(n)
        generated.extend(handles)
        return handles

    monkeypatch.setattr(_core, "gen_buffers", record)
    with pytest.raises(ALLError):
        Buffer.from_pcm(ctx, b"\0", 0xDEAD, 8000)
    assert generated and not _core.is_buffer(generated[0])
