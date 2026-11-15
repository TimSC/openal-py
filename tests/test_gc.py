"""Garbage collection: objects must clean up C handles without leaks/CRASHES."""
import gc
import weakref

import pytest

from openal_py import ALLError, AudioFormat, Buffer, Context, Device, Source, _core


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
    with ctx.activate():
        src = ctx.create_source()
        buf = Buffer.from_pcm(ctx, b"\x00" * 100, AudioFormat.MONO8, 8000)
        src.buffer = buf
    ctx.close()
    del ctx
    dev.close()
    del src, buf
    gc.collect()  # finalizers run here; must be silent


def test_explicit_delete_then_gc():
    dev = Device.default()
    ctx = Context(dev)
    with ctx.activate():
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


@pytest.mark.parametrize("factory,is_live", [
    (lambda ctx: ctx.create_source(), _core.is_source),
    (lambda ctx: ctx.create_buffer(), _core.is_buffer),
])
def test_deleted_wrapper_gc_preserves_reused_handle(ctx, factory, is_live):
    old = factory(ctx)
    handle = old.handle
    old.delete()
    replacement = factory(ctx)
    assert replacement.handle == handle  # OpenAL-soft reuses the freed name
    del old
    gc.collect()
    assert is_live(replacement.handle)
    replacement.delete()


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("factory,is_live", [
    (lambda ctx: ctx.create_source(), _core.is_source),
    (lambda ctx: ctx.create_buffer(), _core.is_buffer),
])
def test_cleanup_uses_owning_context(ctx, device, explicit, factory, is_live):
    owned = factory(ctx)
    handle = owned.handle
    other = Context(device)
    try:
        with other.activate():
            survivor = factory(other)
            if explicit:
                owned.delete()
            del owned
            gc.collect()
            assert other.is_current
            assert is_live(survivor.handle)
        assert ctx.is_current
        assert not is_live(handle)
    finally:
        other.destroy()


def test_context_gc_does_not_retain_wrapper_or_clear_other_context(ctx, device):
    unused = Context(device)
    ref = weakref.ref(unused)
    del unused
    gc.collect()
    assert ref() is None
    assert ctx.is_current


def test_current_context_gc_clears_current(device):
    context = Context(device)
    context.make_current()
    ref = weakref.ref(context)
    del context
    gc.collect()
    assert ref() is None
    assert _core.get_current_context() == 0


def test_cleanup_after_context_destroy_preserves_other_context(ctx, device):
    other = Context(device)
    with other.activate():
        source = other.create_source()
    other.destroy()
    survivor = ctx.create_source()
    source.delete()
    del source, other
    gc.collect()
    assert ctx.is_current
    assert _core.is_source(survivor.handle)


def test_failed_buffer_delete_can_be_retried(ctx):
    buffer = ctx.create_buffer()
    source = ctx.create_source(buffer=buffer)
    handle = buffer.handle
    with pytest.raises(ALLError):
        buffer.delete()
    assert buffer.handle == handle
    source.delete()
    buffer.delete()
    assert not _core.is_buffer(handle)


@pytest.mark.parametrize("explicit", [False, True])
def test_context_destroyed_exactly_once(device, monkeypatch, explicit):
    context = Context(device)
    handle = context.handle
    calls = []
    destroy = _core.destroy_context

    def record_destroy(value):
        calls.append(value)
        destroy(value)

    monkeypatch.setattr(_core, "destroy_context", record_destroy)
    if explicit:
        context.destroy()
        context.destroy()
    del context
    gc.collect()
    assert calls == [handle]
