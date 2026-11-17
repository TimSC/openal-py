"""Shutdown failures must retain ownership; process exit must not hang."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from unittest.mock import patch

import pytest

from openal_py import AudioEngine, Context, Device, LifecycleError, _core


def test_context_detach_failure_keeps_handle_and_finalizer():
    device = Device.open()
    context = Context(device)
    previous = context.make_current()
    handle = context.handle
    try:
        with patch.object(_core, 'make_context_current', return_value=False), \
                patch.object(_core, 'destroy_context', wraps=_core.destroy_context) as destroy:
            with pytest.raises(LifecycleError, match='detach'):
                context.close()
            destroy.assert_not_called()
            assert context.handle == handle
            assert context._finalizer.alive
            assert _core.get_current_context() == handle
        context.close()
        assert context.closed and not context._finalizer.alive
        context.close()
    finally:
        context.close()
        _core.make_context_current(previous or None)
        device.close()


def test_engine_can_retry_after_context_detach_failure():
    audio = AudioEngine()
    previous = audio.context.make_current()
    device = audio.device
    try:
        with patch.object(_core, 'make_context_current', return_value=False), \
                patch.object(_core, 'destroy_context', wraps=_core.destroy_context) as destroy:
            with pytest.raises(LifecycleError, match='detach'):
                audio.close()
            destroy.assert_not_called()
            assert not audio.closed and not device.closed
            assert audio._finalizer.alive
        audio.close()
        assert audio.closed and device.closed
        assert not audio._finalizer.alive
        audio.close()
    finally:
        audio.close()
        _core.make_context_current(previous or None)


@pytest.mark.parametrize('kind', ['raw', 'engine', 'streaming'])
@pytest.mark.parametrize('exceptional', [False, True])
def test_interpreter_exit_with_queued_playback(kind, exceptional):
    script = '''
        import atexit
        import sys
        from openal_py import AudioEngine, AudioFormat, Device, SourceState, StreamingSource

        class Decoder:
            format = AudioFormat.MONO16
            sample_rate = 8000
            def read_frames(self, frames):
                return bytes(frames * 2)
            def close(self):
                print('decoder closed', flush=True)

        kind, exceptional = sys.argv[1:]
        if kind == 'engine':
            audio = AudioEngine()
            asset = audio.sound_from_pcm(bytes(16000), format=AudioFormat.MONO16,
                                         sample_rate=8000)
            voice = audio.play(asset, looping=True)
            with audio.activate():
                assert voice.source.state == SourceState.PLAYING
        else:
            device = Device.open()
            context = device.create_context()
            context.make_current()
            if kind == 'raw':
                buffers = [context.buffer_from_pcm(bytes(16000), format=AudioFormat.MONO16,
                                                   sample_rate=8000) for _ in range(3)]
                source = context.create_source()
                source.queue_buffers(buffers)
                source.play()
                assert source.state == SourceState.PLAYING
            else:
                stream = StreamingSource(context, Decoder(), close_decoder=True)
                stream.play()
                stream.update()
                assert stream.source.state == SourceState.PLAYING
                atexit.register(stream.close)
        print('playback queued', flush=True)
        if exceptional == 'True':
            raise SystemExit(7)
    '''
    import openal_py
    env = {**os.environ, 'ALSOFT_DRIVERS': 'null',
           'PYTHONPATH': str(Path(openal_py.__file__).resolve().parents[1])}
    result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c',
                             textwrap.dedent(script), kind, str(exceptional)],
                            env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == (7 if exceptional else 0), result.stdout + result.stderr
    assert 'playback queued' in result.stdout
    assert 'Fatal Python error' not in result.stderr
    if kind == 'streaming':
        assert 'decoder closed' in result.stdout
