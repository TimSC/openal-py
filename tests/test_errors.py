"""Error types: codes, names, hierarchy, and propagation from the core."""
import pytest

from openal_py import AL, ALC, _core
from openal_py._errors import ALCError, ALLError, OpenALError


# -- exception types ----------------------------------------------------------

def test_hierarchy():
    assert issubclass(ALLError, OpenALError)
    assert issubclass(ALCError, OpenALError)
    assert issubclass(OpenALError, Exception)


def test_al_error_message():
    e = ALLError(AL.AL_INVALID_ENUM)
    assert "AL_INVALID_ENUM" in str(e)
    assert "0xa002" in str(e)
    assert e.code == AL.AL_INVALID_ENUM


def test_alc_error_message():
    e = ALCError(ALC.ALC_INVALID_DEVICE)
    assert "ALC" in str(e)
    assert "ALC_INVALID_DEVICE" in str(e)
    assert e.code == ALC.ALC_INVALID_DEVICE


def test_unknown_code_has_no_name():
    e = ALLError(0x1234)
    assert "0x1234" in str(e)


def test_alc_error_is_not_al_error():
    with pytest.raises(ALCError):
        raise ALCError(ALC.ALC_INVALID_DEVICE)


# -- error propagation from the core ------------------------------------------

def test_play_invalid_source(ctx):
    with pytest.raises(ALLError) as ei:
        _core.source_play(0xDEAD)
    assert ei.value.code == AL.AL_INVALID_NAME


def test_is_source_accepts_invalid_handle(ctx):
    # alIsSource is a predicate: no error, just False
    assert _core.is_source(0xDEAD) is False


def test_buffer_geti_invalid_buffer(ctx):
    with pytest.raises(ALLError):
        _core.buffer_geti(0xDEAD, AL.AL_FREQUENCY)


def test_listener_invalid_param(ctx):
    with pytest.raises(ALLError) as ei:
        _core.listener_set(0x1234, 1.0)
    assert ei.value.code == AL.AL_INVALID_ENUM


def test_listener_get_invalid_param(ctx):
    with pytest.raises(ALLError):
        _core.listener_get(0x1234)


def test_device_attribute_invalid_parameter(device):
    # Invalid raw device pointers have implementation-dependent behavior.
    with pytest.raises(ALCError) as ei:
        _core.get_integer(device.handle, 0xDEAD)
    assert ei.value.code == ALC.ALC_INVALID_ENUM


def test_error_cleared_after_handling(ctx):
    # A raised error must not poison subsequent calls
    with pytest.raises(ALLError):
        _core.source_play(0xDEAD)
    src = ctx.create_source()
    try:
        assert src.state.value == AL.AL_INITIAL  # no stale error
    finally:
        src.delete()
