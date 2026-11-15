"""Public factories, independent lifetime/activation, and audio metadata."""
from array import array
from collections import UserList
import gc
import inspect
import io
import weakref
import wave

import pytest

from openal_py import (
    ALC, AudioFormat, Buffer, Context, ContextMismatchError,
    ContextNotCurrentError, Device, LifecycleError, Listener,
    ResourceClosedError, ResourceInUseError, Source, _core,
)


def wav_stream(channels=2, width=2):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(8000)
        output.writeframes(b"\0" * channels * width * 80)
    stream.seek(0)
    return stream


def test_context_resource_block_does_not_activate_and_closes(device):
    previous = _core.get_current_context()
    with device.create_context(sample_rate=48000) as context:
        assert not context.closed
        assert _core.get_current_context() == previous
        with pytest.raises(ContextNotCurrentError):
            context.create_source()
        with context.activate():
            assert context.is_current
            source = context.create_source()
            buffer = context.create_buffer()
            listener = context.listener
        assert not context.closed
    assert context.closed and source.closed and buffer.closed and listener.closed
    assert source.handle is None and buffer.handle is None
    assert _core.get_current_context() == previous
    assert "closed=True" in repr(source)
    with pytest.raises(ResourceClosedError):
        context.make_current()


def test_lifetime_exception_closes_and_restores_outer(ctx, device):
    with pytest.raises(ValueError):
        with device.create_context() as inner, inner.activate():
            raise ValueError("test")
    assert inner.closed
    assert ctx.is_current


def test_context_resource_block_cannot_reenter(device):
    with device.create_context() as context:
        with pytest.raises(LifecycleError):
            with context:
                pass
        assert not context.closed


def test_close_inside_nested_activation_does_not_restore_dead_handle(device):
    with device.create_context() as context:
        with context.activate():
            with context.activate():
                context.close()
    assert _core.get_current_context() == 0


def test_device_close_rejects_live_context_and_can_retry():
    device = Device.open()
    context = device.create_context()
    with pytest.raises(ResourceInUseError):
        device.close()
    assert not device.closed
    context.close()
    device.close()
    assert device.closed
    with pytest.raises(ResourceClosedError):
        device.create_context()


def test_device_gc_releases_native_handle(monkeypatch):
    calls = []
    close = _core.close_device

    def record(handle):
        calls.append(handle)
        close(handle)

    monkeypatch.setattr(_core, "close_device", record)
    device = Device.open()
    handle = device.handle
    ref = weakref.ref(device)
    del device
    gc.collect()
    assert ref() is None and calls == [handle]


def test_factories_have_explicit_signatures_and_validate_before_creation(ctx, monkeypatch):
    signature = inspect.signature(ctx.create_source)
    assert "buffer" in signature.parameters and "position" in signature.parameters
    assert not any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
    calls = []
    monkeypatch.setattr(_core, "gen_sources", lambda n: calls.append(n))
    with pytest.raises(TypeError):
        ctx.create_source(gaim=0.5)
    assert calls == []


@pytest.mark.parametrize("format", list(AudioFormat))
def test_pcm_metadata_and_buffer_protocol(ctx, format):
    frames = 800
    data = bytearray(frames * format.bytes_per_frame)
    with ctx.buffer_from_pcm(memoryview(data), format=format, sample_rate=8000) as buffer:
        assert buffer.context is ctx
        assert buffer.sample_rate == 8000
        assert buffer.format is format
        assert buffer.channels == format.channels
        assert buffer.bits == format.bits
        assert buffer.size == len(data)
        assert buffer.frame_count == frames
        assert buffer.duration == pytest.approx(0.1)
    assert buffer.closed
    buffer.close()


def test_empty_buffer_metadata(ctx):
    with ctx.create_buffer() as buffer:
        assert buffer.format is None
        assert buffer.frame_count == 0
        assert buffer.duration == 0.0


@pytest.mark.parametrize("stream", [False, True])
def test_load_wav_infers_stereo_and_preserves_file_ownership(ctx, tmp_path, stream):
    file = wav_stream()
    if not stream:
        path = tmp_path / "stereo.wav"
        path.write_bytes(file.getvalue())
        file = path
    buffer = ctx.load(file)
    assert buffer.format is AudioFormat.STEREO16
    assert buffer.frame_count == 80
    if stream:
        assert not file.closed


@pytest.mark.parametrize("width,format,expected", [
    (1, AudioFormat.MONO16, array("h", [-32768, 0, 32512]).tobytes()),
    (2, AudioFormat.MONO8, bytes([0, 128, 255])),
])
def test_load_wav_explicit_width_conversion(ctx, monkeypatch, width, format, expected):
    import struct
    file = io.BytesIO()
    with wave.open(file, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(width)
        output.setframerate(8000)
        output.writeframes(bytes([0, 128, 255]) if width == 1 else struct.pack("<3h", -32768, 0, 32767))
    file.seek(0)
    uploaded = []
    upload = _core.buffer_data

    def record(handle, format, data, rate):
        uploaded.append(data)
        upload(handle, format, data, rate)

    monkeypatch.setattr(_core, "buffer_data", record)
    buffer = ctx.load(file, format=format)
    assert buffer.format is format
    assert uploaded == [expected]
    assert not file.closed


def test_load_wav_does_not_downmix_implicitly(ctx):
    with pytest.raises(ValueError, match="channel"):
        ctx.load(wav_stream(), format=AudioFormat.MONO16)


def test_general_sequences_and_safe_representations(ctx, device):
    source = ctx.create_source(position=UserList([1, 2, 3]))
    listener = ctx.listener
    listener.velocity = array("d", [4, 5, 6])
    listener.direction = UserList([0, 0, -1])
    assert source.position == (1, 2, 3)
    assert listener.velocity == (4, 5, 6)
    buffer = ctx.create_buffer()
    with device.create_context() as other, other.activate():
        assert "Source(" in repr(source)
        assert "Buffer(" in repr(buffer)
        assert "Listener(" in repr(listener)
    assert source.context is buffer.context is listener.context is ctx


def test_capabilities_are_scoped_to_context_and_device(ctx, device):
    assert isinstance(ctx.extensions, frozenset)
    assert isinstance(device.extensions, frozenset)
    for extension in ctx.extensions:
        assert ctx.supports(extension)
    assert not ctx.supports("AL_NOT_AN_EXTENSION")


def test_context_attribute_conflict(device):
    with pytest.raises(ValueError, match="conflicting"):
        device.create_context(sample_rate=48000, attributes={ALC.ALC_FREQUENCY: 44100})


@pytest.mark.parametrize("kind", ["source", "buffer"])
@pytest.mark.parametrize("owned", [False, True])
def test_from_handle_ownership(ctx, kind, owned):
    cls = Source if kind == "source" else Buffer
    gen = _core.gen_sources if kind == "source" else _core.gen_buffers
    delete = _core.delete_sources if kind == "source" else _core.delete_buffers
    live = _core.is_source if kind == "source" else _core.is_buffer
    handle = gen(1)[0]
    resource = cls.from_handle(ctx, handle, owned=owned)
    assert cls.from_handle(ctx, handle, owned=owned) is resource
    with pytest.raises(ValueError, match="different owner"):
        cls.from_handle(ctx, handle, owned=not owned)
    resource.close()
    assert live(handle) is (not owned)
    if not owned:
        delete([handle])


def test_borrowed_device_and_context_do_not_delete_external_handles():
    device_handle = _core.open_device()
    device = Device.from_handle(device_handle)
    context_handle = _core.create_context(device_handle)
    context = Context.from_handle(device, context_handle)
    with context.activate():
        assert context.is_current
    context.close()
    assert _core.get_contexts_device(context_handle) == device_handle
    _core.destroy_context(context_handle)
    device.close()
    assert _core.get_device_spec(device_handle)
    _core.close_device(device_handle)


def test_lifecycle_exceptions_are_separate_from_native_errors():
    from openal_py import OpenALError
    assert issubclass(ResourceClosedError, LifecycleError)
    assert issubclass(ContextNotCurrentError, LifecycleError)
    assert not issubclass(LifecycleError, OpenALError)
    assert issubclass(ContextMismatchError, ValueError)


def test_load_wav_detects_content_without_filename_suffix(ctx, tmp_path, monkeypatch):
    import sys
    path = tmp_path / "audio"
    path.write_bytes(wav_stream().getvalue())
    monkeypatch.setitem(sys.modules, "soundfile", None)
    buffer = ctx.load(path)
    assert buffer.format is AudioFormat.STEREO16
    assert buffer.frame_count == 80
