"""Real EFX objects, routing, parameter values, and cleanup."""
import gc
import weakref
import pytest

from openal_py import EffectType, FilterType, ALLError, ContextMismatchError, ResourceClosedError, _core


@pytest.fixture
def efx(ctx):
    if not ctx.device.supports('ALC_EXT_EFX'):
        pytest.skip('EFX unavailable')
    return ctx


@pytest.mark.parametrize('type', list(EffectType))
def test_effect_types_and_parameters(efx, type):
    with efx.create_effect(type) as effect:
        assert effect.type is type
        assert _core.efx_is('effect', effect.handle)
        # Round-trip every supported parameter through its declared numeric type.
        for key, original in dict(effect.parameters).items():
            effect.parameters[key] = original
            assert effect.parameters[key] == pytest.approx(original)
        handle = effect.handle
    assert effect.closed and not _core.efx_is('effect', handle)


@pytest.mark.parametrize('type', list(FilterType))
def test_filter_types_and_parameters(efx, type):
    with efx.create_filter(type) as filter:
        assert filter.type is type
        for key, original in dict(filter.parameters).items():
            filter.parameters[key] = original
            assert filter.parameters[key] == pytest.approx(original)
        handle = filter.handle
    assert not _core.efx_is('filter', handle)


def test_effect_values_validation_and_refresh(efx):
    effect = efx.create_effect(decay_time=1.2, decay_hf_limit=True)
    slot = efx.create_effect_slot(effect=effect, gain=0.4, auto_send=False)
    assert effect.parameters['decay_time'] == pytest.approx(1.2)
    assert slot.effect is effect and slot.gain == pytest.approx(0.4) and not slot.auto_send
    effect.configure(decay_time=2.0)
    slot.refresh()
    with pytest.raises(KeyError):
        effect.configure(nonexistent=1.0)
    with pytest.raises(ALLError):
        effect.parameters['decay_time'] = -1.0
    with pytest.raises(TypeError):
        effect.parameters['decay_hf_limit'] = 0.5
    with pytest.raises(TypeError):
        del effect.parameters['gain']
    slot.close()
    effect.close()
    with pytest.raises(ResourceClosedError):
        _ = effect.parameters['gain']


@pytest.mark.parametrize('cleanup', ['explicit', 'gc'])
def test_routes_retain_resources_until_source_cleanup(efx, cleanup):
    effect = efx.create_effect()
    slot = efx.create_effect_slot(effect=effect)
    filter = efx.create_filter(gain_hf=0.2)
    references = [weakref.ref(resource) for resource in (effect, slot, filter)]
    handles = [('effect', effect.handle), ('slot', slot.handle), ('filter', filter.handle)]
    source = efx.create_source()
    source.direct_filter = filter
    source.set_send(0, slot, filter=filter)
    del effect, slot, filter
    gc.collect()
    assert all(reference() is not None for reference in references)
    if cleanup == 'explicit':
        source.close()
    else:
        del source
    gc.collect()
    assert all(reference() is None for reference in references)
    assert all(not _core.efx_is(kind, handle) for kind, handle in handles)


def test_routing_rejection_and_failed_slot_close_can_retry(efx, device):
    source = efx.create_source()
    effect = efx.create_effect()
    slot = efx.create_effect_slot(effect=effect)
    source.set_send(0, slot)
    handle = slot.handle
    with pytest.raises(ALLError):
        slot.close()
    assert slot.handle == handle
    with device.create_context() as other:
        with other.activate():
            foreign = other.create_filter()
        with pytest.raises(ContextMismatchError):
            source.direct_filter = foreign
    assert efx.is_current
    source.set_send(0, None)
    slot.close()
    effect.close()
    assert not _core.efx_is('slot', handle)
    with pytest.raises(ValueError):
        source.set_send(-1, None)


def test_eax_vector_pan(efx):
    with efx.create_effect(EffectType.EAX_REVERB, reflections_pan=(0.1, 0.2, 0.3)) as effect:
        assert effect.parameters['reflections_pan'] == pytest.approx((0.1, 0.2, 0.3))
        with pytest.raises(ValueError):
            effect.parameters['reflections_pan'] = (1.0, 2.0)


def test_failed_construction_releases_handle(efx, monkeypatch):
    handles = []
    generate = _core.gen_effects
    def record(n):
        result = generate(n)
        handles.extend(result)
        return result
    monkeypatch.setattr(_core, 'gen_effects', record)
    with pytest.raises(KeyError):
        efx.create_effect(unknown=1.0)
    assert handles and not _core.efx_is('effect', handles[0])


def test_efx_source_and_listener_controls(efx):
    source = efx.create_source()
    source.air_absorption_factor = 0.5
    source.room_rolloff_factor = 0.4
    source.cone_outer_gain_hf = 0.3
    assert source.air_absorption_factor == pytest.approx(0.5)
    assert source.room_rolloff_factor == pytest.approx(0.4)
    assert source.cone_outer_gain_hf == pytest.approx(0.3)
    for name in ('direct_filter_gain_hf_auto', 'auxiliary_send_filter_gain_auto',
                 'auxiliary_send_filter_gain_hf_auto'):
        setattr(source, name, False)
        assert getattr(source, name) is False
    listener = efx.listener
    listener.meters_per_unit = 2.0
    assert listener.meters_per_unit == pytest.approx(2.0)
    slot = efx.create_effect_slot()
    source.set_send(0, slot)
    assert source.get_send(0) == (slot, None)
    source.set_send(0, None)
    assert source.get_send(0) is None
    slot.close()
