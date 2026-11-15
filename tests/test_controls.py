"""Core OpenAL controls consolidated into Python properties and groups."""
import pytest

from openal_py import AL, ALC, AudioFormat, DistanceModel, SourceState, SourceType
from openal_py import ContextMismatchError, ResourceClosedError, _core


def test_context_acoustics_and_info(ctx):
    assert ctx.vendor and ctx.renderer and ctx.version
    for model in DistanceModel:
        ctx.distance_model = model
        assert ctx.distance_model is model
    ctx.doppler_factor = 0.5
    ctx.doppler_velocity = 2.0
    ctx.speed_of_sound = 300.0
    assert ctx.doppler_factor == pytest.approx(0.5)
    assert ctx.doppler_velocity == pytest.approx(2.0)
    assert ctx.speed_of_sound == pytest.approx(300.0)
    assert ctx.get_parameter('AL_DOPPLER_FACTOR', kind='double') == pytest.approx(0.5)
    assert ctx.get_parameter(AL.AL_DISTANCE_MODEL, kind='int') == int(ctx.distance_model)
    assert ctx.get_parameter(AL.AL_DOPPLER_FACTOR, kind='bool') is True
    assert ctx.enum_value('AL_GAIN') == AL.AL_GAIN
    assert ctx.function_address('alSourcePlay')
    assert ctx.device.enum_value('ALC_FREQUENCY') == ALC.ALC_FREQUENCY
    assert ctx.device.function_address('alcOpenDevice')
    assert ctx.device.get_parameter('ALC_FREQUENCY') > 0


def test_capability_controls(ctx):
    if not ctx.supports('AL_EXT_source_distance_model'):
        pytest.skip('source distance model capability unavailable')
    ctx.enable(AL.AL_SOURCE_DISTANCE_MODEL)
    assert ctx.is_enabled('AL_SOURCE_DISTANCE_MODEL')
    ctx.disable('AL_SOURCE_DISTANCE_MODEL')
    assert not ctx.is_enabled(AL.AL_SOURCE_DISTANCE_MODEL)


def test_remaining_source_properties_and_orientation(ctx):
    source = ctx.create_source(min_gain=0.1, max_gain=0.9, cone_inner_angle=30,
                               cone_outer_angle=90, cone_outer_gain=0.25)
    assert source.min_gain == pytest.approx(0.1)
    assert source.max_gain == pytest.approx(0.9)
    assert source.cone_inner_angle == pytest.approx(30)
    assert source.cone_outer_angle == pytest.approx(90)
    assert source.cone_outer_gain == pytest.approx(0.25)
    assert source.source_type is SourceType.UNDETERMINED
    source.set_parameter('AL_GAIN', 0.3)
    assert source.get_parameter('AL_GAIN') == pytest.approx(0.3)
    source.position = (1, 2, 3)
    assert source.get_parameter('AL_POSITION', integer=True) == (1, 2, 3)
    listener = ctx.listener
    listener.orientation = ((1, 0, 0), (0, 0, 1))
    assert listener.orientation == ((1, 0, 0), (0, 0, 1))
    assert listener.get_parameter('AL_ORIENTATION', integer=True) == (1, 0, 0, 0, 0, 1)
    listener.set_parameter('AL_GAIN', 0.7)
    assert listener.gain == pytest.approx(0.7)
    with pytest.raises(ValueError):
        source.set_parameter('AL_BUFFER', 12)


def test_batch_commands_and_validation(ctx, device):
    buffer = ctx.buffer_from_pcm(b'\0' * 16000, format=AudioFormat.MONO16, sample_rate=8000)
    sources = [ctx.create_source(buffer=buffer, looping=True) for _ in range(3)]
    group = ctx.group(sources)
    assert tuple(group) == tuple(sources) and len(group) == 3
    for operation, state in [('play', SourceState.PLAYING), ('pause', SourceState.PAUSED),
                             ('stop', SourceState.STOPPED), ('rewind', SourceState.INITIAL)]:
        getattr(group, operation)()
        assert all(source.state is state for source in sources)
    sources[0].close()
    with pytest.raises(ResourceClosedError):
        group.play()
    assert sources[1].state is SourceState.INITIAL
    with device.create_context() as other, other.activate():
        foreign = other.create_source()
        with pytest.raises(ContextMismatchError):
            ctx.group([foreign])
    with pytest.raises(ValueError):
        ctx.group([sources[1], sources[1]])
    ctx.group([]).play()


def test_deferred_updates_nesting_and_exception(ctx):
    if not ctx.supports('AL_SOFT_deferred_updates'):
        pytest.skip('deferred updates unavailable')
    with pytest.raises(ValueError):
        with ctx.deferred_updates():
            assert ctx.get_parameter('AL_DEFERRED_UPDATES_SOFT', kind='bool')
            with ctx.deferred_updates():
                pass
            assert ctx.get_parameter('AL_DEFERRED_UPDATES_SOFT', kind='bool')
            raise ValueError('test')
    assert not ctx.get_parameter('AL_DEFERRED_UPDATES_SOFT', kind='bool')


def test_loop_points_and_safe_generic_queries(ctx):
    buffer = ctx.buffer_from_pcm(b'\0' * 160, format=AudioFormat.MONO16, sample_rate=8000)
    assert buffer.get_parameter('AL_SIZE') == 160
    if ctx.supports('AL_SOFT_loop_points'):
        buffer.loop_points = (10, 40)
        assert buffer.loop_points == (10, 40)
    with pytest.raises(ValueError, match='safe output shape'):
        buffer.get_parameter(0xDEADB)
    with pytest.raises(ValueError):
        _core.object_parameter('listener', 0, 0xDEADB)


def test_device_default_name_and_version(ctx, device):
    assert isinstance(device.default_name(), (str, type(None)))
    major, minor = device.version
    assert major >= 1 and minor >= 0
