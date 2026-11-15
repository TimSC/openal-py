"""End-to-end smoke test: open a device, play silence, verify round-trips."""
import openal_py
from openal_py import AudioFormat, Buffer, Context, Device, Listener, SourceState


def test_import_and_library():
    assert openal_py.library_path()
    major, minor = openal_py.get_library_version()
    assert major >= 1


def test_enumerate_devices():
    devices = openal_py.enumerate_devices()
    assert isinstance(devices, list)
    assert all(isinstance(d, str) for d in devices)


def test_full_playback_path(device, ctx):
    L = Listener()
    L.position = (0.0, 0.0, 1.0)
    assert L.position == (0.0, 0.0, 1.0)

    data = b"\x00\x00" * 2205  # 100 ms mono 16-bit @ 44.1 kHz
    buf = Buffer.from_pcm(ctx, data, AudioFormat.MONO16, 44100)
    src = ctx.create_source(buffer=buf, gain=0.8)
    assert src.state == SourceState.INITIAL
    src.play()
    assert src.is_playing()
    src.stop()
    assert src.state == SourceState.STOPPED
    assert src.buffer is buf
    src.delete()
    buf.delete()


def test_extension_query(ctx):
    exts = openal_py.get_extensions()
    assert "AL_EXT_FLOAT32" in exts
    assert openal_py.is_extension_present("AL_EXT_FLOAT32")
    assert not openal_py.is_extension_present("AL_NOPE_NOPE")
