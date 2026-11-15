"""Queue ownership, atomic failure, and playback controls."""
import gc
import weakref

import pytest

from openal_py import ALLError, AudioFormat, ContextMismatchError, ResourceClosedError, SourceState


def chunk(ctx, rate=8000):
    return ctx.buffer_from_pcm(b"\0" * 800, format=AudioFormat.MONO8, sample_rate=rate)


def test_queue_unqueue_order_duplicates_and_lifetime(ctx):
    first, second = chunk(ctx), chunk(ctx)
    references = [weakref.ref(first), weakref.ref(second)]
    source = ctx.create_source()
    source.queue_buffers([first, second, first])
    assert source.buffer is None
    assert source.buffers_queued == 3
    assert source.buffers_processed == 0
    with pytest.raises(ALLError):
        source.unqueue_buffers(1)
    del first, second
    gc.collect()
    assert all(reference() is not None for reference in references)
    source.play()
    source.stop()
    assert source.buffers_processed == 3
    returned = source.unqueue_buffers(2)
    assert returned == [reference() for reference in references]
    last = source.unqueue_buffers()
    assert last[0] is returned[0]
    assert source.buffers_queued == 0
    assert source.unqueue_buffers() == []
    del returned, last
    gc.collect()
    assert all(reference() is None for reference in references)


@pytest.mark.parametrize("close", [False, True])
def test_source_cleanup_releases_queued_buffers(ctx, close):
    source = ctx.create_source()
    buffer = chunk(ctx)
    handle = buffer.handle
    ref = weakref.ref(buffer)
    source.queue_buffers([buffer, buffer])
    del buffer
    if close:
        source.close()
    else:
        del source
    gc.collect()
    from openal_py import _core
    assert ref() is None
    assert not _core.is_buffer(handle)


def test_queue_failure_is_atomic(ctx, device):
    source = ctx.create_source()
    first = chunk(ctx)
    mismatched = chunk(ctx, rate=16000)
    with pytest.raises(ALLError):
        source.queue_buffers([first, mismatched])
    assert source.buffers_queued == 0
    with device.create_context() as other, other.activate():
        foreign = chunk(other)
    # The foreign context is closed but its different ownership is still rejected.
    with pytest.raises(ContextMismatchError):
        source.queue_buffers([first, foreign])
    assert source.buffers_queued == 0
    mismatched.close()
    with pytest.raises(ResourceClosedError):
        source.queue_buffers([mismatched])
    source.queue_buffers([first])
    assert source.buffers_queued == 1


def test_unqueue_failure_retains_queue_entries(ctx):
    source = ctx.create_source()
    buffer = chunk(ctx)
    reference = weakref.ref(buffer)
    source.queue_buffers([buffer])
    source.play()
    source.stop()
    with pytest.raises(ALLError):
        source.unqueue_buffers(2)
    with pytest.raises(ValueError):
        source.unqueue_buffers(-1)
    assert source.buffers_queued == 1
    del buffer
    gc.collect()
    assert reference() is not None
    result = source.unqueue_buffers()
    assert result == [reference()]


def test_playback_offsets_and_rewind(ctx):
    buffer = ctx.buffer_from_pcm(b"\0" * 16000, format=AudioFormat.MONO16, sample_rate=8000)
    source = ctx.create_source(buffer=buffer, looping=True)
    source.play()
    source.pause()
    source.offset_samples = 200
    assert source.offset_samples == 200
    assert source.offset_bytes == 400
    assert source.offset_seconds == pytest.approx(0.025)
    source.offset_bytes = 800
    assert source.offset_samples == 400
    source.offset_seconds = 0.1
    assert source.offset_samples == 800
    source.rewind()
    assert source.state is SourceState.INITIAL
    assert source.offset_samples == 0
