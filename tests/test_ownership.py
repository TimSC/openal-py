"""Context isolation and attached-buffer lifetime guarantees."""
import gc
import weakref

import pytest

from openal_py import AudioFormat, Buffer, Context, Listener, _core


def test_operations_require_owning_context(ctx, device):
    source = ctx.create_source()
    buffer = ctx.create_buffer()
    listener = Listener()
    other = Context(device)
    try:
        with other.activate():
            survivor = other.create_source(gain=0.4)
            operations = [source.play, source.pause, source.stop,
                          lambda: source.state, lambda: source.gain,
                          lambda: setattr(source, "gain", 0.2),
                          lambda: buffer.frequency, lambda: buffer.channels,
                          lambda: buffer.size, lambda: listener.position,
                          lambda: setattr(listener, "gain", 0.5),
                          ctx.create_source, ctx.create_buffer,
                          lambda: Buffer.from_pcm(ctx, b"\0", AudioFormat.MONO8, 8000)]
            for operation in operations:
                with pytest.raises(RuntimeError, match="owning context"):
                    operation()
            assert survivor.gain == pytest.approx(0.4)
        assert ctx.listener._context is ctx
        assert listener._context is ctx
    finally:
        other.destroy()


def test_incompatible_and_deleted_buffers_rejected(ctx, device):
    source = ctx.create_source()
    other = Context(device)
    try:
        with other.activate():
            foreign = other.create_buffer()
        with pytest.raises(ValueError, match="different context"):
            source.buffer = foreign
        deleted = ctx.create_buffer()
        deleted.delete()
        with pytest.raises(ValueError, match="deleted"):
            source.buffer = deleted
        assert source.buffer is None
    finally:
        other.destroy()


@pytest.mark.parametrize("cleanup", ["unbind", "delete", "gc"])
def test_source_keeps_buffer_alive_until_detached(ctx, cleanup):
    buffer = Buffer.from_pcm(ctx, b"\0" * 64, AudioFormat.MONO8, 8000)
    handle = buffer.handle
    reference = weakref.ref(buffer)
    source = ctx.create_source(buffer=buffer)
    del buffer
    gc.collect()
    assert reference() is source.buffer
    assert _core.is_buffer(handle)
    if cleanup == "unbind":
        source.buffer = None
    elif cleanup == "delete":
        source.delete()
    else:
        del source
    gc.collect()
    assert reference() is None
    assert not _core.is_buffer(handle)


def test_failed_rebind_retains_original_buffer(ctx):
    first = Buffer.from_pcm(ctx, b"\0" * 8000, AudioFormat.MONO8, 8000)
    second = ctx.create_buffer()
    source = ctx.create_source(buffer=first, looping=True)
    source.play()
    from openal_py import ALLError
    with pytest.raises(ALLError):
        source.buffer = second
    assert source.buffer is first
    source.delete()


def test_deleted_and_destroyed_objects_rejected(ctx):
    source = ctx.create_source()
    buffer = ctx.create_buffer()
    listener = Listener(ctx)
    source.delete()
    buffer.delete()
    with pytest.raises(RuntimeError, match="deleted"):
        source.play()
    with pytest.raises(RuntimeError, match="deleted"):
        _ = buffer.size
    ctx.destroy()
    with pytest.raises(RuntimeError, match="destroyed"):
        _ = listener.gain


def test_listener_requires_context():
    _core.make_context_current(None)
    with pytest.raises(RuntimeError, match="managed context"):
        Listener()
