"""Real loopback output and capability-gated optional controls."""
from array import array
import pytest
from openal_py import AudioFormat, ContextNotCurrentError, LoopbackDevice, HRTFStatus, _core


@pytest.fixture
def loopback():
    if not _core.is_alc_extension_present('ALC_SOFT_loopback'):
        pytest.skip('loopback unavailable')
    with LoopbackDevice() as device:
        yield device


@pytest.mark.parametrize('format', list(AudioFormat))
def test_loopback_formats_and_rendered_signal(loopback, format):
    assert loopback.supports_format(sample_rate=8000, format=format)
    with loopback.create_context(sample_rate=8000, format=format) as ctx, ctx.activate():
        assert len(loopback.render(10)) == 10 * format.bytes_per_frame
        # Render audible data and verify actual output, not just output length.
        data = array('h', [20000] * 800)
        buffer = ctx.buffer_from_pcm(data, format=AudioFormat.MONO16, sample_rate=8000)
        source = ctx.create_source(buffer=buffer)
        source.play()
        pcm = loopback.render(800)
        assert len(pcm) == 800 * format.bytes_per_frame
        if format.bits == 16:
            decoded = array('h')
            decoded.frombytes(pcm)
            assert max(decoded) > 1000
        else:
            assert max(pcm) > 135
        assert loopback.render(0) == b''
        with pytest.raises(ValueError):
            loopback.render(-1)
        with pytest.raises(ValueError):
            loopback.create_context()
    with pytest.raises(ContextNotCurrentError):
        loopback.render(1)


def test_latency_and_device_controls(ctx, device):
    if device.supports('ALC_SOFT_device_clock'):
        timing = device.timing
        assert timing.clock_ns >= 0 and timing.latency_ns >= 0
    if ctx.supports('AL_SOFT_source_latency'):
        source = ctx.create_source()
        timing = source.latency
        assert timing.offset_seconds >= 0 and timing.latency_seconds >= 0
    if device.supports('ALC_SOFT_HRTF'):
        assert isinstance(device.hrtf_names, tuple)
        assert isinstance(device.hrtf_enabled, bool)
        assert isinstance(device.hrtf_status, HRTFStatus)
        assert isinstance(device.hrtf_name, (str, type(None)))
    if device.supports('ALC_SOFT_pause_device'):
        device.pause()
        device.resume()


def test_missing_extensions_are_clear_python_errors(ctx, device, monkeypatch):
    monkeypatch.setattr(device, 'supports', lambda name: False)
    for operation in [ctx.create_effect, ctx.create_filter, ctx.create_effect_slot,
                      lambda: device.timing, lambda: device.hrtf_names,
                      device.reset, device.reopen, device.pause, device.resume]:
        with pytest.raises(NotImplementedError):
            operation()
    monkeypatch.setattr(ctx, 'supports', lambda name: False)
    source = ctx.create_source()
    with pytest.raises(NotImplementedError):
        _ = source.latency
    with pytest.raises(NotImplementedError):
        with ctx.deferred_updates():
            pass


def test_reset_and_reopen_arguments_and_ownership(device, monkeypatch):
    calls = []
    monkeypatch.setattr(device, 'supports', lambda name: True)
    monkeypatch.setattr(_core, 'device_reset', lambda *args: calls.append(args))
    original_name = device.name
    device.reset(hrtf=True, hrtf_id=0)
    device.reopen('another device')
    assert len(calls) == 2
    assert calls[0][0] == device.handle and len(calls[0][1]) == 2
    assert calls[1] == (device.handle, {}, 'another device', True)
    assert device.name == 'another device'
    device._name = original_name


def test_real_device_reset_and_reopen():
    from openal_py import Device
    with Device.open() as device, device.create_context() as ctx, ctx.activate():
        source = ctx.create_source()
        if device.supports('ALC_SOFT_HRTF'):
            device.reset(hrtf=False)
            assert not device.hrtf_enabled
        if device.supports('ALC_SOFT_reopen_device'):
            device.reopen()
            assert ctx.is_current
            source.gain = 0.4
            assert source.gain == pytest.approx(0.4)
