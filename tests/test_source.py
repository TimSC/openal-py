"""Source: state machine, parameter round-trips, buffer binding."""
import pytest

from openal_py import AL, AudioFormat, Buffer, Source, SourceState
from openal_py._errors import ALLError


@pytest.fixture
def buf(ctx):
    b = Buffer.from_pcm(ctx, b"\x00\x00" * 2205, AudioFormat.MONO16, 44100)
    yield b
    if b.handle is not None:
        b.delete()


def test_source_defaults(ctx):
    src = ctx.create_source()
    try:
        assert src.state == SourceState.INITIAL
        assert src.gain == pytest.approx(1.0)
        assert src.pitch == pytest.approx(1.0)
        assert src.looping is False
        assert src.relative is False
        assert src.reference_distance == pytest.approx(1.0)
        assert src.max_distance == pytest.approx(3.4028234663852886e+38)  # AL_MAXFLOAT
        assert src.rolloff_factor == pytest.approx(1.0)
        assert src.position == pytest.approx((0.0, 0.0, 0.0))
        assert src.velocity == pytest.approx((0.0, 0.0, 0.0))
        assert src.direction == pytest.approx((0.0, 0.0, 0.0))
        assert src.buffer is None
    finally:
        src.delete()


def test_parameter_roundtrip(ctx, buf):
    src = ctx.create_source()
    try:
        src.gain = 0.5
        assert src.gain == pytest.approx(0.5)
        src.pitch = 1.5
        assert src.pitch == pytest.approx(1.5)
        src.looping = True
        assert src.looping is True
        src.relative = True
        assert src.relative is True
        src.reference_distance = 5.0
        assert src.reference_distance == pytest.approx(5.0)
        src.max_distance = 100.0
        assert src.max_distance == pytest.approx(100.0)
        src.rolloff_factor = 2.0
        assert src.rolloff_factor == pytest.approx(2.0)
        src.position = (1.0, -2.0, 3.0)
        assert src.position == pytest.approx((1.0, -2.0, 3.0))
        src.velocity = (0.1, 0.2, 0.3)
        assert src.velocity == pytest.approx((0.1, 0.2, 0.3))
        src.direction = (0.0, 0.0, 1.0)
        assert src.direction == pytest.approx((0.0, 0.0, 1.0))
    finally:
        src.delete()


def test_state_machine(ctx, buf):
    src = ctx.create_source(buffer=buf)
    try:
        assert src.state == SourceState.INITIAL
        src.play()
        assert src.state == SourceState.PLAYING
        assert src.is_playing()
        src.pause()
        assert src.state == SourceState.PAUSED
        assert not src.is_playing()
        src.play()  # resume from pause
        assert src.state == SourceState.PLAYING
        src.stop()
        assert src.state == SourceState.STOPPED
        assert not src.is_playing()
    finally:
        src.delete()


def test_unbound_source_play_is_stopped(ctx):
    # OpenAL-soft: play() with no buffer leaves the source not playing
    src = ctx.create_source()
    try:
        src.play()
        assert not src.is_playing()
    finally:
        src.delete()


def test_buffer_binding(ctx, buf):
    src = ctx.create_source()
    try:
        src.buffer = buf
        assert src.buffer is buf
        src.buffer = None
        assert src.buffer is None
    finally:
        src.delete()


def test_buffer_binding_rejects_non_buffer(ctx, buf):
    src = ctx.create_source()
    try:
        with pytest.raises(TypeError):
            src.buffer = 42
    finally:
        src.delete()


def test_multiple_independent_sources(ctx, buf):
    s1 = ctx.create_source(buffer=buf, gain=0.3)
    s2 = ctx.create_source(buffer=buf, gain=0.9)
    try:
        assert s1.handle != s2.handle
        s1.play()
        s2.play()
        assert s1.state == SourceState.PLAYING
        assert s2.state == SourceState.PLAYING
        s1.stop()
        assert s1.state == SourceState.STOPPED
        assert s2.state == SourceState.PLAYING
    finally:
        s1.delete()
        s2.delete()


def test_get_i_raw(ctx, buf):
    src = ctx.create_source(buffer=buf)
    try:
        # _geti is used by .buffer; check raw access too
        assert src._geti(AL.AL_SOURCE_STATE) == AL.AL_INITIAL
    finally:
        src.delete()


def test_source_repr(ctx, buf):
    src = ctx.create_source()
    r = repr(src)
    assert "Source" in r
    src.delete()
    assert "deleted" in repr(src)
