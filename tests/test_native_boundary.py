"""Malformed native inputs must fail before allocation or pointer access."""
import pytest

from openal_py import AL, ALC, _core


@pytest.mark.parametrize("count", [-1, 2**31, 2**64])
@pytest.mark.parametrize("generate", [
    _core.gen_sources, _core.gen_buffers, _core.gen_effects,
    _core.gen_filters, _core.gen_auxiliary_effect_slots,
])
def test_invalid_generation_counts(ctx, count, generate):
    with pytest.raises(ValueError, match="count"):
        generate(count)


@pytest.mark.parametrize("count", [-1, 2**31, 2**64])
def test_invalid_query_and_unqueue_counts(ctx, count):
    source = ctx.create_source()
    with pytest.raises(ValueError, match="count"):
        _core.source_unqueue_buffers(source.handle, count)
    with pytest.raises(ValueError, match="count"):
        _core.get_integerv(ctx.device.handle, ALC.ALC_FREQUENCY, count)


@pytest.mark.parametrize("generate,delete", [
    (_core.gen_sources, _core.delete_sources),
    (_core.gen_buffers, _core.delete_buffers),
    (_core.gen_effects, _core.delete_effects),
    (_core.gen_filters, _core.delete_filters),
    (_core.gen_auxiliary_effect_slots, _core.delete_auxiliary_effect_slots),
])
def test_zero_count_is_safe(ctx, generate, delete):
    assert generate(0) == []
    delete([])


@pytest.mark.parametrize("value", [[], [1], [1, 2, 3], [1] * 7, 1.0])
def test_orientation_requires_six_values(ctx, value):
    with pytest.raises(ValueError, match="6 component"):
        _core.listener_set(AL.AL_ORIENTATION, value)


@pytest.mark.parametrize("count", [-1, 0, 1, 3, 7])
def test_orientation_query_requires_six_values(ctx, count):
    with pytest.raises(ValueError, match="6 component"):
        _core.listener_get(AL.AL_ORIENTATION, count)


@pytest.mark.parametrize("value", [[], [1], [1, 2], [1] * 6, 1.0])
def test_position_requires_three_values(ctx, value):
    source = ctx.create_source()
    with pytest.raises(ValueError, match="3 component"):
        _core.source_set(source.handle, AL.AL_POSITION, value)
    with pytest.raises(ValueError, match="3 component"):
        _core.listener_set(AL.AL_POSITION, value)


def test_effect_pan_vector_length_and_conversion(ctx):
    effects = _core.gen_effects(1)
    try:
        _core.effect_set(effects[0], AL.AL_EFFECT_TYPE, AL.AL_EFFECT_EAXREVERB)
        for bad in ([], [0.0], [0.0, 0.0], [0.0] * 4):
            with pytest.raises(ValueError, match="3 component"):
                _core.effect_set(effects[0], AL.AL_EAXREVERB_REFLECTIONS_PAN, bad)
        with pytest.raises(TypeError):
            _core.effect_set(effects[0], AL.AL_EAXREVERB_REFLECTIONS_PAN, [0.0, object(), 0.0])
        _core.effect_set(effects[0], AL.AL_EAXREVERB_REFLECTIONS_PAN, [0.0, 0.0, 0.0])
    finally:
        _core.delete_effects(effects)


@pytest.mark.parametrize("generate,setter,delete,pname", [
    (_core.gen_filters, _core.filter_set, _core.delete_filters, AL.AL_LOWPASS_GAIN),
    (_core.gen_auxiliary_effect_slots, _core.auxiliary_effect_slot_set,
     _core.delete_auxiliary_effect_slots, AL.AL_EFFECTSLOT_GAIN),
])
def test_scalar_vector_lengths_and_conversion(ctx, generate, setter, delete, pname):
    handles = generate(1)
    try:
        for bad in ([], [0.0, 0.0]):
            with pytest.raises(ValueError):
                setter(handles[0], pname, bad)
        with pytest.raises(TypeError):
            setter(handles[0], pname, [object()])
    finally:
        delete(handles)


def test_context_attribute_conversion_failure(device):
    with pytest.raises(TypeError):
        _core.create_context(device.handle, {ALC.ALC_FREQUENCY: object()})
    handle = _core.create_context(device.handle, {ALC.ALC_FREQUENCY: 44100})
    _core.destroy_context(handle)


@pytest.mark.parametrize("frequency", [0, -1, 2**31])
def test_invalid_pcm_frequency(ctx, frequency):
    buffer = ctx.create_buffer()
    with pytest.raises(ValueError, match="frequency"):
        _core.buffer_data(buffer.handle, AL.AL_FORMAT_MONO8, b"\0", frequency)


def test_allocation_failure_raises_memory_error():
    import os
    import subprocess
    import sys
    import textwrap

    if sys.platform != "linux":
        pytest.skip("requires Linux address-space limits")
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent('''
            import resource
            from openal_py import _core
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            limit = 128 * 1024 * 1024
            if hard != resource.RLIM_INFINITY:
                limit = min(limit, hard)
            resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
            try:
                _core.gen_buffers(2**29)
            except MemoryError:
                pass
            else:
                raise AssertionError("allocation should have failed")
        ''')],
        env=dict(os.environ), capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
