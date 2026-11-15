"""Capture lifecycle and non-blocking frame reads without microphone hardware."""
import gc
import pytest
from openal_py import AudioFormat, CaptureDevice, ResourceClosedError, _core


@pytest.fixture
def capture_backend(monkeypatch):
    state = {'available': 10, 'calls': [], 'frame_size': 2}
    def opened(name, rate, format, frames):
        state['calls'].append(('open', name, rate, format, frames))
        state['frame_size'] = AudioFormat(format).bytes_per_frame
        return 123
    def read(handle, frames):
        state['available'] -= frames
        return b'\x7f' * frames * state['frame_size']
    monkeypatch.setattr(_core, 'capture_open', opened)
    monkeypatch.setattr(_core, 'capture_close', lambda h: state['calls'].append(('close', h)))
    monkeypatch.setattr(_core, 'capture_start', lambda h: state['calls'].append(('start', h)))
    monkeypatch.setattr(_core, 'capture_stop', lambda h: state['calls'].append(('stop', h)))
    monkeypatch.setattr(_core, 'capture_available', lambda h: state['available'])
    monkeypatch.setattr(_core, 'capture_read', read)
    monkeypatch.setattr(_core, 'capture_devices', lambda: ['microphone'])
    return state


@pytest.mark.parametrize('format', list(AudioFormat))
def test_capture_reads_frames_and_retains_ownership(capture_backend, format):
    assert CaptureDevice.devices() == ('microphone',)
    with CaptureDevice.open('microphone', sample_rate=8000, format=format) as device:
        assert not device.capturing and device.available_frames == 10
        with device.recording():
            assert device.capturing
            with device.recording():
                assert len(device.read(3)) == 3 * format.bytes_per_frame
            assert device.capturing
        assert not device.capturing
        assert len(device.read()) == 7 * format.bytes_per_frame
        assert device.read() == b''
        with pytest.raises(ValueError):
            device.read(1)
    assert device.closed
    with pytest.raises(ResourceClosedError):
        device.read()
    device.close()
    assert [call[0] for call in capture_backend['calls']].count('start') == 1
    assert [call[0] for call in capture_backend['calls']].count('close') == 1


def test_capture_gc_and_recording_exception(capture_backend):
    device = CaptureDevice()
    with pytest.raises(ValueError):
        with device.recording():
            raise ValueError('test')
    assert not device.capturing
    del device
    gc.collect()
    assert capture_backend['calls'][-1] == ('close', 123)


@pytest.mark.parametrize('rate,frames', [(0, 1), (-1, 1), (1, 0), (1, -1), (2**31, 1)])
def test_capture_invalid_sizes_fail_before_open(rate, frames, capture_backend):
    with pytest.raises(ValueError):
        CaptureDevice(sample_rate=rate, buffer_frames=frames)
    assert capture_backend['calls'] == []


@pytest.mark.parametrize('rate,frames', [(0, 1), (-1, 1), (1, 0), (1, -1), (2**31, 1)])
def test_native_capture_validation_never_opens_device(rate, frames):
    with pytest.raises(ValueError):
        _core.capture_open(None, rate, int(AudioFormat.MONO16), frames)
