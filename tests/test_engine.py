"""Engine ownership, activation, playback lifetime, and extension points."""
from array import array
import gc
import io
import threading
import weakref
import wave

import pytest

from openal_py import (
    AudioEngine, AudioFormat, Buffer, Context, ContextMismatchError, Device,
    LifecycleError, LoopbackDevice, ResourceClosedError, ResourceInUseError,
    Source, SourceState, ThreadAffinityError, _core,
)


def wav_data(frames=8000):
    file = io.BytesIO()
    with wave.open(file, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b'\0' * frames * 2)
    file.seek(0)
    return file


@pytest.fixture
def audio():
    with AudioEngine() as engine:
        yield engine


def sound(audio, frames=8000):
    return audio.sound_from_pcm(b'\0' * frames * 2, format=AudioFormat.MONO16, sample_rate=8000)


def test_engine_activates_temporarily_and_owns_all_resources(ctx):
    with AudioEngine(master_volume=0.5) as audio:
        device, context = audio.device, audio.context
        assert ctx.is_current
        asset = sound(audio)
        buffer = asset.buffer
        voice = audio.play(asset, looping=True, gain=0.4, pitch=1.2, position=(1, 2, 3))
        source = voice.source
        assert audio.master_volume == pytest.approx(0.5)
        audio.master_volume = 0.25
        assert audio.master_volume == pytest.approx(0.25)
        assert voice.gain == pytest.approx(0.4) and voice.pitch == pytest.approx(1.2)
        assert voice.position == (1, 2, 3)
        assert voice.is_playing() and voice.sound is asset
        assert asset.duration == pytest.approx(1.0)
        assert asset.frame_count == 8000 and asset.channels == 1
        assert asset.sample_rate == 8000 and asset.format is AudioFormat.MONO16
        assert ctx.is_current
    assert audio.closed and asset.closed and voice.closed
    assert context.closed and device.closed and buffer.closed and source.closed
    assert voice.finished and voice.state is SourceState.STOPPED
    assert voice.wait() is True
    audio.close()
    assert ctx.is_current
    with pytest.raises(ResourceClosedError):
        audio.play(asset)
    with pytest.raises(ResourceClosedError):
        _ = asset.duration


def test_injected_device_is_borrowed_and_other_context_survives(ctx, device):
    with AudioEngine(device) as audio:
        assert audio.device is device
        assert audio.context is not ctx
        audio.play(sound(audio), looping=True)
    assert audio.closed and not device.closed and ctx.is_current


def test_paths_cache_streams_do_not_and_close_invalidates_cache(audio, tmp_path):
    path = tmp_path / 'sound.wav'
    path.write_bytes(wav_data().getvalue())
    first = audio.load(path)
    assert audio.load(str(path)) is first
    assert audio.load(path, cache=False) is not first
    file = wav_data()
    stream_sound = audio.load(file)
    file.seek(0)
    assert audio.load(file) is not stream_sound
    assert not file.closed
    first.close()
    assert first.closed
    assert audio.load(path) is not first
    voice = audio.play(path, looping=True)
    voice.stop()
    stream = wav_data()
    audio.play(stream, looping=True).stop()
    assert not stream.closed


def test_voice_limit_pause_resume_stop_and_sound_lifetime():
    with AudioEngine(max_voices=1) as audio:
        asset = sound(audio)
        voice = audio.play(asset, looping=True)
        voice.pause()
        assert voice.state is SourceState.PAUSED
        assert audio.update() == 0
        with pytest.raises(ResourceInUseError):
            audio.play(asset)
        with pytest.raises(ResourceInUseError):
            asset.close()
        with pytest.raises(LifecycleError):
            voice.wait()
        assert voice.wait(timeout=0) is False
        voice.resume()
        assert voice.is_playing()
        with pytest.raises(LifecycleError):
            voice.wait()
        assert voice.wait(timeout=0.001) is False
        voice.stop()
        voice.close()
        assert voice.closed and voice.finished
        assert voice.wait(timeout=0) is True
        with pytest.raises(ResourceClosedError):
            voice.resume()
        second = audio.play(asset, looping=True)
        audio.stop_all()
        assert second.closed and audio.voices == ()
        asset.close()


def test_natural_wait_reclaims_source(audio):
    asset = sound(audio, frames=80)
    voice = audio.play(asset)
    assert voice.wait(timeout=2) is True
    assert voice.closed and audio.voices == ()
    assert not asset.closed


@pytest.mark.parametrize('timeout,interval', [(-1, 0.01), (float('inf'), 0.01),
    (float('nan'), 0.01), (None, 0), (None, -1), (None, float('nan'))])
def test_wait_rejects_invalid_inputs(audio, timeout, interval):
    voice = audio.play(sound(audio), looping=True)
    with pytest.raises(ValueError):
        voice.wait(timeout, poll_interval=interval)
    assert voice.is_playing()


def test_loopback_update_reclaims_unreferenced_voices_and_reuses_budget():
    if not _core.is_alc_extension_present('ALC_SOFT_loopback'):
        pytest.skip('loopback unavailable')
    with LoopbackDevice() as device, AudioEngine(device, sample_rate=8000, max_voices=1) as audio:
        asset = audio.sound_from_pcm(array('h', [20000] * 80),
                                     format=AudioFormat.MONO16, sample_rate=8000)
        voice = audio.play(asset)
        handle = voice.source.handle
        with pytest.raises(LifecycleError, match="rendering frames"):
            voice.wait()
        reference = weakref.ref(voice)
        del voice
        gc.collect()
        assert reference() is not None
        with audio.activate():
            pcm = device.render(160)
        decoded = array('h')
        decoded.frombytes(pcm)
        assert max(decoded) > 1000
        assert audio.update() == 1
        gc.collect()
        assert reference() is None
        with audio.activate():
            assert not _core.is_source(handle)
        assert audio.play(asset).sound is asset
    assert device.closed  # the outer device block closes its own resource


def test_engine_rejects_foreign_sounds_and_buffers(device):
    with AudioEngine(device) as first, AudioEngine(device) as second:
        asset = sound(first)
        with pytest.raises(ContextMismatchError):
            second.play(asset)
        with pytest.raises(ContextMismatchError):
            second.sound_from_buffer(asset.buffer)
        asset.close()
        with pytest.raises(ResourceClosedError):
            first.play(asset)


def test_extension_points_adopt_buffer_and_update_hook(device):
    class UpdatingEngine(AudioEngine):
        updates = 0
        def update(self):
            self.updates += 1
            return super().update()
    with UpdatingEngine(device) as audio:
        with audio.activate() as context:
            buffer = context.buffer_from_pcm(b'\0' * 16000,
                                             format=AudioFormat.MONO16, sample_rate=8000)
        asset = audio.sound_from_buffer(buffer)
        assert audio.sound_from_buffer(buffer) is asset
        voice = audio.play(asset, looping=True)
        assert audio.updates == 0
        audio.update()
        assert audio.updates == 1
        with audio.activate():
            voice.source.reference_distance = 2
            assert voice.source.reference_distance == 2
        voice.stop()
    assert buffer.closed


def test_owning_thread_checks_precede_native_operations(audio):
    asset = sound(audio)
    voice = audio.play(asset, looping=True)
    errors = []
    def worker():
        for operation in (lambda: audio.play(asset), lambda: audio.master_volume,
                          voice.pause, lambda: asset.duration, audio.update,
                          audio.stop_all, asset.close, audio.close):
            try:
                operation()
            except Exception as error:
                errors.append(error)
    thread = threading.Thread(target=worker)
    # Holding activation makes this a deadlock regression: the thread must fail
    # affinity checks before trying to acquire the engine activation lock.
    with audio.activate():
        thread.start()
        thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(errors) == 8 and all(isinstance(error, ThreadAffinityError) for error in errors)
    assert voice.is_playing() and not audio.closed


def test_failed_play_closes_source_but_retains_reusable_asset(audio, monkeypatch):
    generated = []
    gen = _core.gen_sources
    def record(n):
        handles = gen(n)
        generated.extend(handles)
        return handles
    def fail(self):
        raise RuntimeError('play failed')
    asset = sound(audio)
    monkeypatch.setattr(_core, 'gen_sources', record)
    monkeypatch.setattr(Source, 'play', fail)
    with pytest.raises(RuntimeError, match='play failed'):
        audio.play(asset)
    assert audio.voices == () and not asset.closed
    with audio.activate():
        assert generated and not _core.is_source(generated[0])


@pytest.mark.parametrize('borrowed', [False, True])
def test_failed_context_creation_closes_only_owned_device(monkeypatch, borrowed):
    injected = Device.open() if borrowed else None
    closed = []
    close = _core.close_device
    def record(handle):
        closed.append(handle)
        close(handle)
    def fail(self, **kwargs):
        raise RuntimeError('context failed')
    monkeypatch.setattr(_core, 'close_device', record)
    monkeypatch.setattr(Device, 'create_context', fail)
    try:
        with pytest.raises(RuntimeError, match='context failed'):
            AudioEngine(injected)
        if borrowed:
            assert not injected.closed and closed == []
        else:
            assert len(closed) == 1
    finally:
        if injected is not None:
            injected.close()


def test_failed_initial_volume_cleans_context_then_device_and_restores_outer(ctx, monkeypatch):
    calls = []
    destroy, close = _core.destroy_context, _core.close_device
    def destroy_context(handle):
        calls.append('context')
        destroy(handle)
    def close_device(handle):
        calls.append('device')
        close(handle)
    def fail(*args):
        raise RuntimeError('listener failed')
    monkeypatch.setattr(_core, 'destroy_context', destroy_context)
    monkeypatch.setattr(_core, 'close_device', close_device)
    monkeypatch.setattr(_core, 'listener_set', fail)
    with pytest.raises(RuntimeError, match='listener failed'):
        AudioEngine()
    assert calls == ['context', 'device']
    assert ctx.is_current


def test_shutdown_order_and_exception_cleanup(monkeypatch):
    audio = AudioEngine()
    asset = sound(audio)
    voice = audio.play(asset, looping=True)
    calls = []
    for cls, name in ((Source, 'source'), (Buffer, 'buffer'), (Context, 'context'), (Device, 'device')):
        original = cls.close
        def record(self, _close=original, _name=name):
            calls.append(_name)
            return _close(self)
        monkeypatch.setattr(cls, 'close', record)
    with pytest.raises(ValueError):
        with audio:
            raise ValueError('body failed')
    assert calls == ['source', 'buffer', 'context', 'device']
    assert voice.closed and asset.closed and audio.closed


def test_shutdown_continues_after_child_failure(monkeypatch):
    audio = AudioEngine()
    asset = sound(audio)
    voice = audio.play(asset, looping=True)
    device = audio.device
    def fail(self):
        raise RuntimeError('source close failed')
    monkeypatch.setattr(Source, 'close', fail)
    with pytest.raises(RuntimeError, match='source close failed'):
        audio.close()
    assert audio.closed and device.closed and asset.closed and voice.closed
    audio.close()


def test_engine_finalizer_does_not_retain_wrapper_or_clear_other_context(ctx):
    audio = AudioEngine()
    audio.play(sound(audio), looping=True)
    reference = weakref.ref(audio)
    context = weakref.ref(audio.context)
    device = weakref.ref(audio.device)
    del audio
    gc.collect()
    assert reference() is None
    assert context() is None and device() is None
    assert ctx.is_current


@pytest.mark.parametrize('kwargs', [{'max_voices': 0}, {'max_voices': -1},
    {'master_volume': -1}, {'master_volume': float('nan')}, {'master_volume': float('inf')}])
def test_invalid_configuration_does_not_open_device(monkeypatch, kwargs):
    calls = []
    monkeypatch.setattr(_core, 'open_device', lambda *args: calls.append(args))
    with pytest.raises(ValueError):
        AudioEngine(**kwargs)
    assert calls == []


def test_voice_factory_hook_runs_before_playback(device):
    from openal_py import Voice
    class TaggedVoice(Voice):
        tag = 'application voice'
    class CustomEngine(AudioEngine):
        def _create_voice(self, asset, source):
            assert self.context.is_current
            assert source.state is SourceState.INITIAL
            source.relative = True
            return TaggedVoice(self, asset, source)
    with CustomEngine(device) as audio:
        voice = audio.play(sound(audio), looping=True)
        assert isinstance(voice, TaggedVoice) and voice.tag == 'application voice'
        with audio.activate():
            assert voice.source.relative


def test_low_level_source_closure_is_reclaimed(audio):
    asset = sound(audio)
    voice = audio.play(asset, looping=True)
    with audio.activate():
        voice.source.close()
    assert voice.finished and audio.voices == ()
    asset.close()
    assert asset.closed


def test_voice_factory_failure_rolls_back_new_source(device, monkeypatch):
    class FailingEngine(AudioEngine):
        def _create_voice(self, sound, source):
            raise RuntimeError('voice factory failed')
    with FailingEngine(device) as audio:
        asset = sound(audio)
        handles = []
        generate = _core.gen_sources
        def record(count):
            result = generate(count)
            handles.extend(result)
            return result
        monkeypatch.setattr(_core, 'gen_sources', record)
        with pytest.raises(RuntimeError, match='voice factory failed'):
            audio.play(asset)
        assert audio.voices == ()
        with audio.activate():
            assert handles and not _core.is_source(handles[0])


def test_sound_and_voice_resource_blocks_close_on_exception(audio):
    with pytest.raises(ValueError):
        with sound(audio) as asset:
            with audio.play(asset, looping=True) as voice:
                raise ValueError('body failed')
    assert asset.closed and voice.closed and audio.voices == ()
    assert not audio.closed


def test_update_hook_can_schedule_playback_without_recursive_updates(device):
    class SchedulingEngine(AudioEngine):
        calls = 0
        pending = None
        def update(self):
            self.calls += 1
            if self.pending is not None:
                self.play(self.pending, looping=True)
                self.pending = None
            return super().update()
    with SchedulingEngine(device) as audio:
        audio.pending = sound(audio)
        audio.update()
        assert audio.calls == 1
        assert len(audio.voices) == 1
        assert audio.calls == 1
