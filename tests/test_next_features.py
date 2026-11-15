"""Real native regression coverage for the Explore feature requests."""
from array import array
import io
import struct
import sys
import threading
import wave

import pytest

from openal_py import (
    ALC, ALCError, ALLError, AudioEngine, AudioFormat, Buffer, LifecycleError, LoopbackDevice,
    ResourceClosedError, SoundFileDecoder, SourceState, StreamingSource, StreamState,
    ThreadAffinityError, _core,
)


@pytest.fixture
def offline():
    if not _core.is_alc_extension_present('ALC_SOFT_loopback'):
        pytest.skip('loopback unavailable')
    with LoopbackDevice() as device, device.create_context(sample_rate=44100) as ctx, ctx.activate():
        yield device, ctx


def test_exact_boolean_extension_results(ctx, device):
    for name in [next(iter(ctx.extensions)), 'AL_no_such_extension']:
        assert type(_core.is_extension_present(name)) is bool
        assert ctx.supports(name) is (name in ctx.extensions)
    for name in [next(iter(device.extensions)), 'ALC_no_such_extension']:
        assert type(_core.is_alc_extension_present(name, device.handle)) is bool
        assert device.supports(name) is (name in device.extensions)


@pytest.mark.parametrize('fmt', list(AudioFormat))
def test_loopback_reset_retains_actual_output(fmt):
    with LoopbackDevice() as device:
        if not device.supports('ALC_SOFT_HRTF') or not device.supports_format(sample_rate=44100, format=fmt):
            pytest.skip('format or HRTF reset unavailable')
        with device.create_context(sample_rate=44100, format=fmt) as ctx, ctx.activate():
            buffer = ctx.buffer_from_pcm(array('h', [12000] * 4410), format=AudioFormat.MONO16, sample_rate=44100)
            source = ctx.create_source(buffer=buffer, looping=True)
            source.play()
            for enabled in [True, False]:
                device.reset(hrtf=enabled)
                assert device.get_parameter(ALC.ALC_FREQUENCY) == 44100
                if not enabled:
                    assert not device.hrtf_enabled
                elif fmt.channels == 2 and device.hrtf_names:
                    assert device.hrtf_enabled
                pcm = device.render(441)
                assert len(pcm) == 441 * fmt.bytes_per_frame
                if fmt.bits == 8:
                    assert max(pcm) > 135
                else:
                    samples = array('h')
                    samples.frombytes(pcm)
                    assert max(samples) > 1000


def test_loopback_reset_overrides_and_failure(offline):
    device, ctx = offline
    if not device.supports('ALC_SOFT_HRTF'):
        pytest.skip('HRTF reset unavailable')
    device.reset(attributes={'ALC_FREQUENCY': 48000})
    device.reset(hrtf=False)
    assert device.get_parameter(ALC.ALC_FREQUENCY) == 48000
    device.reset(attributes={ALC.ALC_FORMAT_CHANNELS_SOFT: ALC.ALC_MONO_SOFT,
                             ALC.ALC_FORMAT_TYPE_SOFT: ALC.ALC_UNSIGNED_BYTE_SOFT})
    device.reset(hrtf=False)
    assert len(device.render(20)) == 20


def test_upload_preserves_handle_and_failed_metadata(offline):
    device, ctx = offline
    buffer = ctx.create_buffer()
    handle = buffer.handle
    source = ctx.create_source()
    for count in [100, 200, 50]:
        buffer.upload_pcm(array('h', [10000] * count), AudioFormat.MONO16, 44100)
        assert buffer.handle == handle and buffer.frame_count == count
        source.queue_buffers([buffer])
        with pytest.raises(ALLError):
            buffer.upload_pcm(b'\x80' * 20, AudioFormat.MONO8, 44100)
        assert buffer.format is AudioFormat.MONO16 and buffer.frame_count == count
        source.play()
        device.render(count + 100)
        with pytest.raises(ALLError):
            buffer.upload_pcm(b'\x80' * 20, AudioFormat.MONO8, 44100)
        source.unqueue_buffers()
    source.buffer = buffer
    with pytest.raises(ALLError):
        buffer.upload_pcm(b'\x80' * 20, AudioFormat.MONO8, 44100)
    source.buffer = None
    with pytest.raises(ValueError):
        buffer.upload_pcm(b'\0', AudioFormat.MONO8, 0)
    buffer.close()
    with pytest.raises(ResourceClosedError):
        buffer.upload_pcm(b'\0', AudioFormat.MONO8, 44100)


def wav_bytes(samples, width=2, channels=2):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(width)
        writer.setframerate(8000)
        writer.writeframes(samples)
    return stream.getvalue()


@pytest.mark.parametrize('width', [1, 2])
def test_dependency_free_mono_and_conflicts(ctx, monkeypatch, width):
    monkeypatch.setitem(sys.modules, 'soundfile', None)
    pcm = bytes([0, 255, 128, 128]) if width == 1 else struct.pack('<4h', -32768, 32767, 1000, 3000)
    stream = io.BytesIO(wav_bytes(pcm, width))
    buffer = ctx.load(stream, mono=True)
    assert buffer.channels == 1 and buffer.frame_count == 2 and buffer.bits == width * 8
    assert not stream.closed
    stream.seek(0)
    with pytest.raises(ValueError, match='format expects'):
        ctx.load(stream, mono=True, format=AudioFormat.STEREO16)


@pytest.mark.parametrize('subtype', ['PCM_24', 'FLOAT', 'DOUBLE'])
@pytest.mark.parametrize('input_kind', ['path', 'stream', 'offset'])
def test_wav_fallback_amplitude_and_stream_origin(ctx, tmp_path, monkeypatch, subtype, input_kind):
    sf = pytest.importorskip('soundfile')
    np = pytest.importorskip('numpy')
    payload = io.BytesIO()
    sf.write(payload, np.array([[-1., 1.], [-.5, -.5], [.5, .5]]), 8000,
             format='WAV', subtype=subtype)
    if input_kind == 'path':
        file = tmp_path / 'audio.wav'
        file.write_bytes(payload.getvalue())
    else:
        prefix = b'prefix' if input_kind == 'offset' else b''
        file = io.BytesIO(prefix + payload.getvalue())
        file.seek(len(prefix))
    uploaded = []
    original = _core.buffer_data

    def record(handle, format, data, rate):
        uploaded.append(data)
        return original(handle, format, data, rate)

    monkeypatch.setattr(_core, 'buffer_data', record)
    buffer = ctx.load(file, mono=True)
    assert buffer.format is AudioFormat.MONO16
    assert buffer.frame_count == 3
    actual = array('h')
    actual.frombytes(uploaded[0])
    # PCM24's positive endpoint is one quantization step below 1.
    assert list(actual)[1:] == [-16384, 16384]
    assert abs(actual[0]) <= 1
    if input_kind != 'path':
        assert not file.closed


def test_fallback_missing_decoder_and_corrupt_data(ctx, monkeypatch):
    monkeypatch.setitem(sys.modules, 'soundfile', None)
    with pytest.raises(ImportError, match='soundfile'):
        ctx.load(io.BytesIO(wav_bytes(b'\0' * 12, width=3, channels=1)))
    with pytest.raises((wave.Error, EOFError, ValueError)):
        ctx.load(io.BytesIO(b'RIFF\x04\x00\x00\x00WAVE'))
    truncated = wav_bytes(b'\0' * 40, channels=1)[:-2]
    with pytest.raises(ValueError, match='truncated'):
        ctx.load(io.BytesIO(truncated))


def test_engine_mono_cache_separate(tmp_path):
    path = tmp_path / 'stereo.wav'
    path.write_bytes(wav_bytes(b'\0' * 80))
    with LoopbackDevice() as device, AudioEngine(device) as audio:
        stereo = audio.load(path)
        mono = audio.load(path, mono=True)
        assert stereo.channels == 2 and mono.channels == 1
        assert mono is audio.load(path, mono=True)
        assert stereo is audio.load(path)


class Decoder:
    format = AudioFormat.MONO16
    sample_rate = 44100

    def __init__(self, frames=1000):
        self.frames = frames
        self.position = 0
        self.closed = False
        self.requests = []

    def read_frames(self, count):
        self.requests.append(count)
        count = min(count, self.frames - self.position)
        self.position += count
        return array('h', [10000] * count)

    def rewind(self):
        self.position = 0

    def close(self):
        self.closed = True


def test_stream_natural_completion_bounded_pool(offline):
    device, ctx = offline
    decoder = Decoder(1003)
    with StreamingSource(ctx, decoder, chunk_frames=100, queue_depth=3) as stream:
        stream.play()
        handles = {buffer.handle for buffer in stream._buffers}
        for _ in range(30):
            device.render(50)
            stream.update()
            assert {buffer.handle for buffer in stream._buffers} == handles
            assert stream.source.buffers_queued <= 3
            assert 0 <= stream.buffered_duration <= 300 / 44100
            if stream.finished:
                break
        assert stream.finished and decoder.position == 1003
        assert stream.underrun_count == 0
        assert max(decoder.requests) <= 100
        assert len(handles) == 3
    assert stream.closed and not decoder.closed
    assert all(not _core.is_buffer(handle) for handle in handles)


@pytest.mark.parametrize('frames', [0, 1, 13])
def test_stream_short_loop_and_empty_input(offline, frames):
    device, ctx = offline
    decoder = Decoder(frames)
    with StreamingSource(ctx, decoder, chunk_frames=100, queue_depth=2, looping=True) as stream:
        stream.play()
        for _ in range(5):
            device.render(50)
            stream.update()
        assert stream.finished is (frames == 0)
        assert stream.underrun_count == 0


def test_stream_pause_starvation_recovery_and_stop(offline):
    device, ctx = offline
    with StreamingSource(ctx, Decoder(10000), chunk_frames=100, queue_depth=2) as stream:
        stream.play()
        stream.pause()
        before = stream.buffered_duration
        device.render(1000)
        stream.update()
        assert stream.state is StreamState.PAUSED
        assert stream.buffered_duration == before
        stream.resume()
        device.render(1000)
        assert stream.source.state is SourceState.STOPPED
        assert not stream.finished
        stream.update()
        assert stream.underrun_count == 1
        assert stream.source.state is SourceState.PLAYING
        stream.update()
        assert stream.underrun_count == 1
        stream.stop()
        assert stream.state is StreamState.STOPPED and not stream.finished
        assert stream.source.buffers_queued == 0
        with pytest.raises(LifecycleError):
            stream.play()


def test_stream_decoder_failure_and_owned_cleanup(offline):
    _, ctx = offline
    decoder = Decoder()
    def fail(count):
        raise ValueError('broken decoder')
    decoder.read_frames = fail
    stream = StreamingSource(ctx, decoder, close_decoder=True)
    with pytest.raises(ValueError, match='broken decoder'):
        stream.play()
    assert stream.closed and decoder.closed
    assert stream.state is StreamState.ERROR and isinstance(stream.error, ValueError)
    stream.close()


def test_stream_thread_affinity_and_context_shutdown(offline):
    _, ctx = offline
    decoder = Decoder()
    stream = StreamingSource(ctx, decoder, close_decoder=True)
    errors = []
    def other_thread():
        try:
            stream.play()
        except Exception as error:
            errors.append(error)
    worker = threading.Thread(target=other_thread)
    worker.start()
    worker.join()
    assert isinstance(errors[0], ThreadAffinityError)
    ctx.close()
    stream.close()
    assert decoder.closed


def test_soundfile_stream_adapter_and_borrowed_stream(offline):
    pytest.importorskip('soundfile')
    device, ctx = offline
    file = io.BytesIO(wav_bytes(struct.pack('<400h', *([1000, 3000] * 200))))
    with StreamingSource.from_file(ctx, file, mono=True, chunk_frames=50, queue_depth=2) as stream:
        assert stream.decoder.format is AudioFormat.MONO16
        stream.play()
        for _ in range(12):
            device.render(25 * 44100 // 8000)
            stream.update()
            if stream.finished:
                break
        assert stream.finished
    assert not file.closed


@pytest.mark.parametrize('width,fmt,expected', [
    (1, AudioFormat.MONO16, [-128, 0]),
    (1, AudioFormat.MONO8, [127, 128]),
    (2, AudioFormat.MONO16, [-1, 2000]),
    (2, AudioFormat.MONO8, [127, 135]),
])
def test_mono_exact_samples_and_default_preservation(ctx, monkeypatch, width, fmt, expected):
    pcm = bytes([0, 255, 128, 128]) if width == 1 else struct.pack('<4h', -32768, 32767, 1000, 3000)
    file = io.BytesIO(wav_bytes(pcm, width))
    uploaded = []
    original = _core.buffer_data
    def record(handle, format, data, rate):
        uploaded.append(data)
        return original(handle, format, data, rate)
    monkeypatch.setattr(_core, 'buffer_data', record)
    ctx.load(file, mono=True, format=fmt)
    if fmt.bits == 16:
        samples = array('h')
        samples.frombytes(uploaded[-1])
        assert list(samples) == expected
    else:
        assert list(uploaded[-1]) == expected
    file.seek(0)
    stereo = ctx.load(file)
    assert stereo.channels == 2 and uploaded[-1] == pcm


def test_float_clipping_and_nonfinite_values(ctx, monkeypatch):
    sf = pytest.importorskip('soundfile')
    np = pytest.importorskip('numpy')
    file = io.BytesIO()
    sf.write(file, np.array([-2., -1., -.5, 0., .5, 1., 2., np.nan, np.inf, -np.inf]),
             8000, format='WAV', subtype='FLOAT')
    file.seek(0)
    uploaded = []
    original = _core.buffer_data
    def record(handle, format, data, rate):
        uploaded.append(data)
        return original(handle, format, data, rate)
    monkeypatch.setattr(_core, 'buffer_data', record)
    ctx.load(file)
    samples = array('h')
    samples.frombytes(uploaded[-1])
    assert list(samples) == [-32768, -32768, -16384, 0, 16384, 32767, 32767, 0, 32767, -32768]


def test_stream_reclaims_queue_drained_during_decode(offline):
    device, ctx = offline
    decoder = Decoder(10000)
    with StreamingSource(ctx, decoder, chunk_frames=100, queue_depth=3) as stream:
        stream.play()
        device.render(100)
        read = decoder.read_frames
        def slow_read(count):
            # Drain the remaining native queue while the helper is decoding its
            # replacement. None of the old processed audio may be replayed.
            device.render(1000)
            return read(count)
        decoder.read_frames = slow_read
        stream.update()
        assert stream.underrun_count == 1
        assert stream.source.state is SourceState.PLAYING
        assert stream.source.buffers_queued == 1
        decoder.read_frames = read
        stream.update()
        assert stream.source.buffers_queued == 3


def test_pause_after_starvation_preserves_refilled_audio(offline):
    device, ctx = offline
    decoder = Decoder(10000)
    with StreamingSource(ctx, decoder, chunk_frames=100, queue_depth=2) as stream:
        stream.play()
        device.render(1000)
        stream.pause()
        stream.update()
        position = decoder.position
        handles = list(stream._queued)
        for _ in range(3):
            device.render(1000)
            stream.update()
        assert decoder.position == position
        assert stream._queued == handles
        assert stream.state is StreamState.PAUSED and stream.underrun_count == 0
        stream.resume()
        assert stream.underrun_count == 1
        assert stream.source.state is SourceState.PLAYING


@pytest.mark.parametrize('kwargs', [{'chunk_frames': 0}, {'queue_depth': -1},
                                  {'chunk_frames': 2**31}, {'queue_depth': 2**31}])
def test_stream_rejects_invalid_bounds(offline, kwargs):
    _, ctx = offline
    with pytest.raises(ValueError):
        StreamingSource(ctx, Decoder(), **kwargs)


def test_stream_invalid_decoder_frames_and_nonseekable_loop(offline):
    _, ctx = offline
    decoder = Decoder()
    decoder.rewind = None
    with pytest.raises(ValueError, match='rewind'):
        StreamingSource(ctx, decoder, looping=True)
    decoder.read_frames = lambda frames: b'\0'  # half a PCM16 frame
    stream = StreamingSource(ctx, decoder)
    with pytest.raises(ValueError, match='frame count'):
        stream.play()
    assert stream.closed and stream.state is StreamState.ERROR
    assert not decoder.closed


def test_stream_empty_and_partial_input_are_not_underruns(offline):
    device, ctx = offline
    for frames in [0, 3, 100, 200]:
        with StreamingSource(ctx, Decoder(frames), chunk_frames=100, queue_depth=2) as stream:
            stream.play()
            device.render(1000)
            stream.update()
            assert stream.finished
            assert stream.underrun_count == 0


def test_stream_cleanup_restores_other_context(offline):
    device, ctx = offline
    decoder = Decoder()
    stream = StreamingSource(ctx, decoder, close_decoder=True)
    stream.play()
    # Use a separate device because loopback devices support one live context.
    with LoopbackDevice() as other_device, other_device.create_context() as other, other.activate():
        stream.close()
        assert other.is_current and decoder.closed
    assert ctx.is_current


def test_from_file_failure_keeps_input_stream_open(offline):
    pytest.importorskip('soundfile')
    _, ctx = offline
    file = io.BytesIO(wav_bytes(b'\0' * 40))
    with pytest.raises(ValueError):
        StreamingSource.from_file(ctx, file, chunk_frames=0)
    assert not file.closed


def test_loopback_reset_before_context_requires_configuration():
    with LoopbackDevice() as device:
        if not device.supports('ALC_SOFT_HRTF'):
            pytest.skip('HRTF reset unavailable')
        with pytest.raises(ValueError, match='output attributes'):
            device.reset(hrtf=False)


def test_loopback_new_context_and_failed_reset_do_not_stale_cache():
    with LoopbackDevice() as device:
        if not device.supports('ALC_SOFT_HRTF'):
            pytest.skip('HRTF reset unavailable')
        for rate in [44100, 48000]:
            with device.create_context(sample_rate=rate) as ctx, ctx.activate():
                device.reset(hrtf=False)
                with pytest.raises(ALCError):
                    device.reset(attributes={'ALC_FORMAT_CHANNELS_SOFT': -1})
                device.reset(hrtf=False)
                assert device.get_parameter(ALC.ALC_FREQUENCY) == rate
                assert len(device.render(3)) == 12
