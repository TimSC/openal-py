"""Engine pumping and generic PCM input lifecycle, using real loopback playback."""
from collections import deque
import gc
import io
import threading
import weakref

import pytest

from openal_py import (AudioEngine, AudioFormat, LoopbackDevice, PCMStream,
                       ResourceInUseError, SoundFileStream, StreamState,
                       ThreadAffinityError)


class Input(PCMStream):
    format = AudioFormat.MONO16
    sample_rate = 44100

    def __init__(self, chunks):
        self.chunks = deque(chunks)
        self.close_count = 0
        self.requests = []

    def read_frames(self, frames):
        self.requests.append(frames)
        return self.chunks.popleft() if self.chunks else b''

    def close(self):
        self.close_count += 1


@pytest.fixture
def audio():
    with LoopbackDevice() as device, AudioEngine(device, sample_rate=44100, max_voices=2) as engine:
        yield engine


def render(audio, frames=1000):
    with audio.activate():
        audio.device.render(frames)


def test_stream_interface_is_abstract():
    with pytest.raises(TypeError):
        PCMStream()


def test_waiting_input_recovers_and_finishes_with_fixed_pool(audio):
    stream = Input([None, b'\0\0' * 100, None, None, b'\0\0' * 100, b''])
    voice = audio.play_stream(stream, chunk_frames=100, queue_depth=2)
    assert voice.active
    assert voice in audio.voices
    with audio.activate():
        handles = {buffer.handle for buffer in voice._playback._buffers}
    audio.update()
    render(audio)
    audio.update()
    assert voice.active  # temporary starvation cannot complete a voice
    audio.update()
    with audio.activate():
        assert handles == {buffer.handle for buffer in voice._playback._buffers}
    render(audio)
    assert audio.update() == 1
    assert not voice.active and voice.closed
    assert stream.close_count == 0
    assert not audio.voices


@pytest.mark.parametrize('owned', [False, True])
def test_pause_resume_close_and_input_ownership(audio, owned):
    stream = Input([b'\0\0' * 100, None])
    voice = audio.play_stream(stream, chunk_frames=100, close_stream=owned)
    voice.pause()
    render(audio)
    audio.update()
    assert voice.state is StreamState.PAUSED and voice.active
    voice.resume()
    assert voice.state is StreamState.PLAYING
    voice.close()
    voice.close()
    assert stream.close_count == int(owned)


def test_static_and_streaming_voices_share_limit_and_stop_all(audio):
    sound = audio.sound_from_pcm(b'\0\0' * 100, format=AudioFormat.MONO16, sample_rate=44100)
    audio.play(sound, looping=True)
    audio.play_stream(Input([None]))
    with pytest.raises(ResourceInUseError):
        audio.play_stream(Input([None]))
    with pytest.raises(ResourceInUseError):
        audio.play(sound)
    audio.stop_all()
    assert not audio.voices


def test_read_error_releases_voice_and_owned_input(audio):
    stream = Input([None])
    voice = audio.play_stream(stream, close_stream=True)
    def fail(frames):
        raise ValueError('read failed')
    stream.read_frames = fail
    with pytest.raises(ValueError, match='read failed'):
        audio.update()
    assert voice.closed and stream.close_count == 1
    assert not audio.voices


@pytest.mark.parametrize('bad', [b'1', b'\0\0' * 101])
def test_invalid_pcm_rejected_without_transferring_input(audio, bad):
    stream = Input([bad])
    with pytest.raises(ValueError, match='frame count'):
        audio.play_stream(stream, chunk_frames=100, close_stream=True)
    assert not audio.voices and stream.close_count == 0


def test_engine_close_releases_owned_stream(audio):
    stream = Input([None])
    voice = audio.play_stream(stream, close_stream=True)
    audio.close()
    assert voice.closed and stream.close_count == 1


def test_engine_gc_closes_owned_input():
    stream = Input([None])
    with LoopbackDevice() as device:
        engine = AudioEngine(device, sample_rate=44100)
        engine.play_stream(stream, close_stream=True)
        reference = weakref.ref(engine)
        del engine
        gc.collect()
        assert reference() is None
        assert stream.close_count == 1


def test_stream_thread_check_precedes_input_read(audio):
    stream = Input([None])
    voice = audio.play_stream(stream)
    errors = []
    def worker():
        for operation in (audio.update, voice.pause, voice.close):
            try:
                operation()
            except Exception as error:
                errors.append(error)
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(errors) == 3 and all(isinstance(error, ThreadAffinityError) for error in errors)
    assert len(stream.requests) == 1


def test_soundfile_stream_reads_chunks_and_borrows_file():
    sf = pytest.importorskip('soundfile')
    np = pytest.importorskip('numpy')
    file = io.BytesIO()
    sf.write(file, np.zeros(11), 8000, format='WAV', subtype='PCM_16')
    file.seek(0)
    with SoundFileStream(file) as stream:
        assert isinstance(stream, PCMStream)
        assert stream.format is AudioFormat.MONO16
        assert stream.sample_rate == 8000
        assert [len(stream.read_frames(4)) for _ in range(4)] == [8, 8, 6, 0]
    assert not file.closed


def test_failed_owned_input_close_can_be_retried(audio):
    stream = Input([None])
    audio.play_stream(stream, close_stream=True)
    def fail():
        raise RuntimeError('input cleanup failed')
    stream.close = fail
    with pytest.raises(RuntimeError, match='input cleanup failed'):
        audio.close()
    assert audio._state.streams
    stream.close = lambda: setattr(stream, 'close_count', stream.close_count + 1)
    audio.close()
    assert stream.close_count == 1
    assert not audio._state.streams
