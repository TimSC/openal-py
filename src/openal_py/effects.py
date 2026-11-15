"""EFX effects, filters, auxiliary slots, and named parameter mappings."""
from __future__ import annotations

from collections.abc import MutableMapping
from enum import IntEnum
import operator
from typing import TYPE_CHECKING, Callable, Iterator, TypeVar, cast

from openal_py import _core, _finalize
from openal_py._constants import AL
from openal_py._errors import ContextMismatchError, ResourceClosedError
from openal_py._parameters import ParameterValue

if TYPE_CHECKING:
    from openal_py.context import Context


class EffectType(IntEnum):
    NULL = AL.AL_EFFECT_NULL
    REVERB = AL.AL_EFFECT_REVERB
    CHORUS = AL.AL_EFFECT_CHORUS
    DISTORTION = AL.AL_EFFECT_DISTORTION
    ECHO = AL.AL_EFFECT_ECHO
    FLANGER = AL.AL_EFFECT_FLANGER
    FREQUENCY_SHIFTER = AL.AL_EFFECT_FREQUENCY_SHIFTER
    VOCAL_MORPHER = AL.AL_EFFECT_VOCAL_MORPHER
    PITCH_SHIFTER = AL.AL_EFFECT_PITCH_SHIFTER
    RING_MODULATOR = AL.AL_EFFECT_RING_MODULATOR
    AUTOWAH = AL.AL_EFFECT_AUTOWAH
    COMPRESSOR = AL.AL_EFFECT_COMPRESSOR
    EQUALIZER = AL.AL_EFFECT_EQUALIZER
    EAX_REVERB = AL.AL_EFFECT_EAXREVERB


class FilterType(IntEnum):
    NULL = AL.AL_FILTER_NULL
    LOWPASS = AL.AL_FILTER_LOWPASS
    HIGHPASS = AL.AL_FILTER_HIGHPASS
    BANDPASS = AL.AL_FILTER_BANDPASS

# Parameter schemas from the vendored EFX header: (native enum, numeric kind).
_SCHEMAS: dict[str, dict[str, tuple[int, str]]] = {
    "REVERB": {
        "density": (AL.AL_REVERB_DENSITY, "float"),
        "diffusion": (AL.AL_REVERB_DIFFUSION, "float"),
        "gain": (AL.AL_REVERB_GAIN, "float"),
        "gain_hf": (AL.AL_REVERB_GAINHF, "float"),
        "decay_time": (AL.AL_REVERB_DECAY_TIME, "float"),
        "decay_hf_ratio": (AL.AL_REVERB_DECAY_HFRATIO, "float"),
        "reflections_gain": (AL.AL_REVERB_REFLECTIONS_GAIN, "float"),
        "reflections_delay": (AL.AL_REVERB_REFLECTIONS_DELAY, "float"),
        "late_reverb_gain": (AL.AL_REVERB_LATE_REVERB_GAIN, "float"),
        "late_reverb_delay": (AL.AL_REVERB_LATE_REVERB_DELAY, "float"),
        "air_absorption_gain_hf": (AL.AL_REVERB_AIR_ABSORPTION_GAINHF, "float"),
        "room_rolloff_factor": (AL.AL_REVERB_ROOM_ROLLOFF_FACTOR, "float"),
        "decay_hf_limit": (AL.AL_REVERB_DECAY_HFLIMIT, "int"),
    },
    "CHORUS": {
        "waveform": (AL.AL_CHORUS_WAVEFORM, "int"),
        "phase": (AL.AL_CHORUS_PHASE, "int"),
        "rate": (AL.AL_CHORUS_RATE, "float"),
        "depth": (AL.AL_CHORUS_DEPTH, "float"),
        "feedback": (AL.AL_CHORUS_FEEDBACK, "float"),
        "delay": (AL.AL_CHORUS_DELAY, "float"),
    },
    "DISTORTION": {
        "edge": (AL.AL_DISTORTION_EDGE, "float"),
        "gain": (AL.AL_DISTORTION_GAIN, "float"),
        "lowpass_cutoff": (AL.AL_DISTORTION_LOWPASS_CUTOFF, "float"),
        "eq_center": (AL.AL_DISTORTION_EQCENTER, "float"),
        "eq_bandwidth": (AL.AL_DISTORTION_EQBANDWIDTH, "float"),
    },
    "ECHO": {
        "delay": (AL.AL_ECHO_DELAY, "float"),
        "lr_delay": (AL.AL_ECHO_LRDELAY, "float"),
        "damping": (AL.AL_ECHO_DAMPING, "float"),
        "feedback": (AL.AL_ECHO_FEEDBACK, "float"),
        "spread": (AL.AL_ECHO_SPREAD, "float"),
    },
    "FLANGER": {
        "waveform": (AL.AL_FLANGER_WAVEFORM, "int"),
        "phase": (AL.AL_FLANGER_PHASE, "int"),
        "rate": (AL.AL_FLANGER_RATE, "float"),
        "depth": (AL.AL_FLANGER_DEPTH, "float"),
        "feedback": (AL.AL_FLANGER_FEEDBACK, "float"),
        "delay": (AL.AL_FLANGER_DELAY, "float"),
    },
    "FREQUENCY_SHIFTER": {
        "frequency": (AL.AL_FREQUENCY_SHIFTER_FREQUENCY, "float"),
        "left_direction": (AL.AL_FREQUENCY_SHIFTER_LEFT_DIRECTION, "int"),
        "right_direction": (AL.AL_FREQUENCY_SHIFTER_RIGHT_DIRECTION, "int"),
    },
    "VOCAL_MORPHER": {
        "phoneme_a": (AL.AL_VOCAL_MORPHER_PHONEMEA, "int"),
        "phoneme_a_coarse_tuning": (AL.AL_VOCAL_MORPHER_PHONEMEA_COARSE_TUNING, "int"),
        "phoneme_b": (AL.AL_VOCAL_MORPHER_PHONEMEB, "int"),
        "phoneme_b_coarse_tuning": (AL.AL_VOCAL_MORPHER_PHONEMEB_COARSE_TUNING, "int"),
        "waveform": (AL.AL_VOCAL_MORPHER_WAVEFORM, "int"),
        "rate": (AL.AL_VOCAL_MORPHER_RATE, "float"),
    },
    "PITCH_SHIFTER": {
        "coarse_tune": (AL.AL_PITCH_SHIFTER_COARSE_TUNE, "int"),
        "fine_tune": (AL.AL_PITCH_SHIFTER_FINE_TUNE, "int"),
    },
    "RING_MODULATOR": {
        "frequency": (AL.AL_RING_MODULATOR_FREQUENCY, "float"),
        "highpass_cutoff": (AL.AL_RING_MODULATOR_HIGHPASS_CUTOFF, "float"),
        "waveform": (AL.AL_RING_MODULATOR_WAVEFORM, "int"),
    },
    "AUTOWAH": {
        "attack_time": (AL.AL_AUTOWAH_ATTACK_TIME, "float"),
        "release_time": (AL.AL_AUTOWAH_RELEASE_TIME, "float"),
        "resonance": (AL.AL_AUTOWAH_RESONANCE, "float"),
        "peak_gain": (AL.AL_AUTOWAH_PEAK_GAIN, "float"),
    },
    "COMPRESSOR": {
        "enabled": (AL.AL_COMPRESSOR_ONOFF, "int"),
    },
    "EQUALIZER": {
        "low_gain": (AL.AL_EQUALIZER_LOW_GAIN, "float"),
        "low_cutoff": (AL.AL_EQUALIZER_LOW_CUTOFF, "float"),
        "mid1_gain": (AL.AL_EQUALIZER_MID1_GAIN, "float"),
        "mid1_center": (AL.AL_EQUALIZER_MID1_CENTER, "float"),
        "mid1_width": (AL.AL_EQUALIZER_MID1_WIDTH, "float"),
        "mid2_gain": (AL.AL_EQUALIZER_MID2_GAIN, "float"),
        "mid2_center": (AL.AL_EQUALIZER_MID2_CENTER, "float"),
        "mid2_width": (AL.AL_EQUALIZER_MID2_WIDTH, "float"),
        "high_gain": (AL.AL_EQUALIZER_HIGH_GAIN, "float"),
        "high_cutoff": (AL.AL_EQUALIZER_HIGH_CUTOFF, "float"),
    },
    "EAXREVERB": {
        "density": (AL.AL_EAXREVERB_DENSITY, "float"),
        "diffusion": (AL.AL_EAXREVERB_DIFFUSION, "float"),
        "gain": (AL.AL_EAXREVERB_GAIN, "float"),
        "gain_hf": (AL.AL_EAXREVERB_GAINHF, "float"),
        "gain_lf": (AL.AL_EAXREVERB_GAINLF, "float"),
        "decay_time": (AL.AL_EAXREVERB_DECAY_TIME, "float"),
        "decay_hf_ratio": (AL.AL_EAXREVERB_DECAY_HFRATIO, "float"),
        "decay_lf_ratio": (AL.AL_EAXREVERB_DECAY_LFRATIO, "float"),
        "reflections_gain": (AL.AL_EAXREVERB_REFLECTIONS_GAIN, "float"),
        "reflections_delay": (AL.AL_EAXREVERB_REFLECTIONS_DELAY, "float"),
        "reflections_pan": (AL.AL_EAXREVERB_REFLECTIONS_PAN, "vector"),
        "late_reverb_gain": (AL.AL_EAXREVERB_LATE_REVERB_GAIN, "float"),
        "late_reverb_delay": (AL.AL_EAXREVERB_LATE_REVERB_DELAY, "float"),
        "late_reverb_pan": (AL.AL_EAXREVERB_LATE_REVERB_PAN, "vector"),
        "echo_time": (AL.AL_EAXREVERB_ECHO_TIME, "float"),
        "echo_depth": (AL.AL_EAXREVERB_ECHO_DEPTH, "float"),
        "modulation_time": (AL.AL_EAXREVERB_MODULATION_TIME, "float"),
        "modulation_depth": (AL.AL_EAXREVERB_MODULATION_DEPTH, "float"),
        "air_absorption_gain_hf": (AL.AL_EAXREVERB_AIR_ABSORPTION_GAINHF, "float"),
        "hf_reference": (AL.AL_EAXREVERB_HFREFERENCE, "float"),
        "lf_reference": (AL.AL_EAXREVERB_LFREFERENCE, "float"),
        "room_rolloff_factor": (AL.AL_EAXREVERB_ROOM_ROLLOFF_FACTOR, "float"),
        "decay_hf_limit": (AL.AL_EAXREVERB_DECAY_HFLIMIT, "int"),
    },
    "LOWPASS": {
        "gain": (AL.AL_LOWPASS_GAIN, "float"),
        "gain_hf": (AL.AL_LOWPASS_GAINHF, "float"),
    },
    "HIGHPASS": {
        "gain": (AL.AL_HIGHPASS_GAIN, "float"),
        "gain_lf": (AL.AL_HIGHPASS_GAINLF, "float"),
    },
    "BANDPASS": {
        "gain": (AL.AL_BANDPASS_GAIN, "float"),
        "gain_lf": (AL.AL_BANDPASS_GAINLF, "float"),
        "gain_hf": (AL.AL_BANDPASS_GAINHF, "float"),
    },
}


_R = TypeVar("_R", bound="_Resource")


class _Resource:
    _kind: str
    _delete: Callable[[list[int]], None]

    def _initialize(self, context: Context, handle: int, kind: str,
                    delete: Callable[[list[int]], None]) -> None:
        self._context = context
        self._handle: int | None = handle
        self._kind = kind
        self._delete = delete
        self._retained: list[object] = []
        self._finalizer = _finalize.register(self, context._state, handle, delete, self._retained)

    @property
    def context(self) -> Context:
        return self._context

    @property
    def closed(self) -> bool:
        return self._handle is None or self.context.closed

    @property
    def handle(self) -> int | None:
        return None if self.closed else self._handle

    def _require_current(self) -> None:
        if self.closed:
            raise ResourceClosedError(f'{self._kind} has been closed')
        self.context._require_current()

    def close(self) -> None:
        if self._handle is not None:
            _finalize.release(self.context._state, self._handle, self._delete, self._retained)
            self._handle = None
            self._finalizer.detach()

    def __enter__(self: _R) -> _R:
        self._require_current()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f'{type(self).__name__}(handle={self.handle}, closed={self.closed})'


class Parameters(MutableMapping[str, ParameterValue]):
    """A live, fixed-key mapping; values are validated by OpenAL."""

    def __init__(self, owner: Effect | Filter):
        self._owner = owner

    def __iter__(self) -> Iterator[str]:
        return iter(self._owner._schema)

    def __len__(self) -> int:
        return len(self._owner._schema)

    def __getitem__(self, key: str) -> ParameterValue:
        self._owner._require_current()
        parameter, kind = self._owner._schema[key]
        return cast(ParameterValue, _core.efx_get(
            self._owner._kind, self._owner.handle, parameter, integer=kind == 'int'))

    def __setitem__(self, key: str, value: ParameterValue) -> None:
        self._owner._require_current()
        parameter, kind = self._owner._schema[key]
        converted: ParameterValue
        if kind == 'int':
            if not isinstance(value, int):
                raise TypeError(f'{key} requires an integer')
            converted = operator.index(value)
        elif kind == 'float':
            if not isinstance(value, (int, float)):
                raise TypeError(f'{key} requires a number')
            converted = float(value)
        else:
            if not isinstance(value, (tuple, list)) or len(value) != 3:
                raise ValueError(f'{key} requires three components')
            converted = tuple(float(component) for component in value)
        if self._owner._kind == 'effect':
            _core.effect_set(self._owner.handle, parameter, converted)
        else:
            _core.filter_set(self._owner.handle, parameter, converted)

    def __delitem__(self, key: str) -> None:
        raise TypeError('native effect parameters cannot be deleted')


class Effect(_Resource):
    """An immutable effect type with mutable, named parameters.

    Slots copy effect settings: call slot.refresh() after changing parameters.
    """

    def __init__(self, context: Context, type: EffectType = EffectType.REVERB,
                 **parameters: ParameterValue):
        context._require_current()
        if not context.device.supports('ALC_EXT_EFX'):
            raise NotImplementedError('selected device does not support ALC_EXT_EFX')
        self._type = EffectType(type)
        self._schema = _SCHEMAS.get('EAXREVERB' if self.type == EffectType.EAX_REVERB else self.type.name, {})
        self._initialize(context, _core.gen_effects(1)[0], 'effect', _core.delete_effects)
        try:
            _core.effect_set(self.handle, AL.AL_EFFECT_TYPE, int(self.type))
            self.configure(**parameters)
        except BaseException:
            self.close()
            raise

    @property
    def type(self) -> EffectType:
        return self._type

    @property
    def parameters(self) -> Parameters:
        return Parameters(self)

    def configure(self, **parameters: ParameterValue) -> None:
        """Apply named settings in order; native value errors stop at the failing key."""
        unknown = parameters.keys() - self._schema.keys()
        if unknown:
            raise KeyError(next(iter(unknown)))
        for key, value in parameters.items():
            self.parameters[key] = value


class Filter(_Resource):
    def __init__(self, context: Context, type: FilterType = FilterType.LOWPASS,
                 **parameters: ParameterValue):
        context._require_current()
        if not context.device.supports('ALC_EXT_EFX'):
            raise NotImplementedError('selected device does not support ALC_EXT_EFX')
        self._type = FilterType(type)
        self._schema = _SCHEMAS.get(self.type.name, {})
        self._initialize(context, _core.gen_filters(1)[0], 'filter', _core.delete_filters)
        try:
            _core.filter_set(self.handle, AL.AL_FILTER_TYPE, int(self.type))
            self.configure(**parameters)
        except BaseException:
            self.close()
            raise

    @property
    def type(self) -> FilterType:
        return self._type

    @property
    def parameters(self) -> Parameters:
        return Parameters(self)

    def configure(self, **parameters: ParameterValue) -> None:
        unknown = parameters.keys() - self._schema.keys()
        if unknown:
            raise KeyError(next(iter(unknown)))
        for key, value in parameters.items():
            self.parameters[key] = value


class AuxiliaryEffectSlot(_Resource):
    def __init__(self, context: Context, *, effect: Effect | None = None,
                 gain: float = 1.0, auto_send: bool = True):
        context._require_current()
        if not context.device.supports('ALC_EXT_EFX'):
            raise NotImplementedError('selected device does not support ALC_EXT_EFX')
        self._initialize(context, _core.gen_auxiliary_effect_slots(1)[0], 'slot',
                         _core.delete_auxiliary_effect_slots)
        try:
            self.effect = effect
            self.gain = gain
            self.auto_send = auto_send
        except BaseException:
            self.close()
            raise

    @property
    def effect(self) -> Effect | None:
        self._require_current()
        return cast(Effect, self._retained[0]) if self._retained else None

    @effect.setter
    def effect(self, effect: Effect | None) -> None:
        self._require_current()
        if effect is not None:
            if not isinstance(effect, Effect):
                raise TypeError('expected Effect or None')
            if effect.context is not self.context:
                raise ContextMismatchError('effect belongs to another context')
            effect._require_current()
        _core.auxiliary_effect_slot_set(self.handle, AL.AL_EFFECTSLOT_EFFECT,
                                        0 if effect is None else effect.handle)
        self._retained[:] = [] if effect is None else [effect]

    def refresh(self) -> None:
        """Copy the associated effect's latest parameters into this slot."""
        self.effect = self.effect

    @property
    def gain(self) -> float:
        self._require_current()
        return float(_core.efx_get('slot', self.handle, AL.AL_EFFECTSLOT_GAIN))

    @gain.setter
    def gain(self, gain: float) -> None:
        self._require_current()
        _core.auxiliary_effect_slot_set(self.handle, AL.AL_EFFECTSLOT_GAIN, float(gain))

    @property
    def auto_send(self) -> bool:
        self._require_current()
        return bool(_core.efx_get('slot', self.handle, AL.AL_EFFECTSLOT_AUXILIARY_SEND_AUTO, True))

    @auto_send.setter
    def auto_send(self, enabled: bool) -> None:
        self._require_current()
        _core.auxiliary_effect_slot_set(self.handle, AL.AL_EFFECTSLOT_AUXILIARY_SEND_AUTO, int(enabled))
