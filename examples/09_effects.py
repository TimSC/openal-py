"""Named EFX parameters, a lowpass filter, and a reverb send."""
from openal_py import AudioFormat, Device, EffectType, FilterType


def main() -> None:
    with Device.open() as device, device.create_context() as ctx, ctx.activate():
        if not device.supports('ALC_EXT_EFX'):
            print('selected device does not support EFX')
            return
        effect = ctx.create_effect(EffectType.REVERB, decay_time=1.8, gain=0.3)
        slot = ctx.create_effect_slot(effect=effect)
        lowpass = ctx.create_filter(FilterType.LOWPASS, gain_hf=0.4)
        sound = ctx.buffer_from_pcm(b'\0' * 800, format=AudioFormat.MONO8, sample_rate=8000)
        source = ctx.create_source(buffer=sound, cone_inner_angle=90, cone_outer_angle=180)
        source.direct_filter = lowpass
        source.set_send(0, slot)
        effect.parameters['decay_time'] = 2.2
        slot.refresh()  # Slots copy parameters; refresh after editing an effect.
        print('effect parameters:', dict(effect.parameters))
        print('filter parameters:', dict(lowpass.parameters))
        print('send:', source.get_send(0))
        source.set_send(0, None)
        source.direct_filter = None
        source.close()
        slot.close()
        lowpass.close()
        effect.close()


if __name__ == '__main__':
    main()
