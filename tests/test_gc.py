"""Garbage collection: objects must clean up C handles without leaks/CRASHES."""
import gc

from openal_py import AudioFormat, Buffer, Context, Device, Source


def test_source_gc_with_live_context(ctx):
    src = ctx.create_source()
    h = src.handle
    del src
    gc.collect()
    # the handle must be gone
    assert not _core_is_source(h)


def test_buffer_gc_with_live_context(ctx):
    buf = Buffer.from_pcm(ctx, b"\x00\x00" * 100, AudioFormat.MONO16, 44100)
    h = buf.handle
    del buf
    gc.collect()
    assert not _core_is_buffer(h)


def test_objects_gc_after_context_destroy():
    # Objects outliving their context must not raise in their finalizers.
    dev = Device.default()
    ctx = Context(dev)
    with ctx:
        src = ctx.create_source()
        buf = Buffer.from_pcm(ctx, b"\x00" * 100, AudioFormat.MONO8, 8000)
        src.buffer = buf
    # ctx (and its device) about to die
    del ctx
    dev.close()
    del src, buf
    gc.collect()  # finalizers run here; must be silent


def test_explicit_delete_then_gc():
    dev = Device.default()
    ctx = Context(dev)
    with ctx:
        src = ctx.create_source()
        src.delete()
        h = src.handle
        del src
        gc.collect()
        assert h is None


def _core_is_source(h):
    from openal_py import _core
    return _core.is_source(h)


def _core_is_buffer(h):
    from openal_py import _core
    return _core.is_buffer(h)
