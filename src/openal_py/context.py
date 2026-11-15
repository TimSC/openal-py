"""Resource lifetime and explicit activation for rendering contexts."""
from __future__ import annotations

from contextlib import contextmanager
import operator
from typing import TYPE_CHECKING, Iterator, Mapping, Iterable, cast
import weakref

from openal_py import _core, _finalize
from openal_py._constants import AL, ALC
from openal_py._parameters import DistanceModel, NumericKind, Parameter, ParameterValue, resolve
from openal_py._errors import ContextNotCurrentError, LifecycleError, ResourceClosedError
from openal_py._types import AudioFile, PCMData, Vector3

if TYPE_CHECKING:
    from openal_py.buffer import AudioFormat, Buffer
    from openal_py.device import Device
    from openal_py.listener import Listener
    from openal_py.group import SourceGroup
    from openal_py.effects import Effect, EffectType, Filter, FilterType, AuxiliaryEffectSlot
    from openal_py.source import Source

_contexts: weakref.WeakValueDictionary[int, Context] = weakref.WeakValueDictionary()


class Context:
    """An OpenAL context. Resource blocks close; activation blocks select.

    with device.create_context() as ctx:
        with ctx.activate():
            source = ctx.create_source()
    """

    def __init__(self, device: Device, attributes: Mapping[str | int, int] | None = None,
                 *, sample_rate: int | None = None):
        device._require_open()
        attrs = {getattr(ALC, key) if isinstance(key, str) else key: value
                 for key, value in (attributes or {}).items()}
        if sample_rate is not None:
            rate = operator.index(sample_rate)
            if not 0 < rate <= 2**31 - 1:
                raise ValueError("sample_rate must be between 1 and INT_MAX")
            if ALC.ALC_FREQUENCY in attrs and attrs[ALC.ALC_FREQUENCY] != rate:
                raise ValueError("conflicting sample_rate and ALC_FREQUENCY")
            attrs[ALC.ALC_FREQUENCY] = rate
        self._initialize(device, _core.create_context(device.handle, attrs), True)

    def _initialize(self, device: Device, handle: int, owned: bool) -> None:
        self._device = device
        self._state = _finalize.ContextState(handle, device, owned)
        self._buffers: weakref.WeakValueDictionary[int, Buffer] = weakref.WeakValueDictionary()
        self._sources: weakref.WeakValueDictionary[int, Source] = weakref.WeakValueDictionary()
        self._entered = False
        self._finalizer = _finalize.finalize(self, self._state.destroy)
        _contexts[handle] = self

    @classmethod
    def from_handle(cls, device: Device, handle: int, *, owned: bool = False) -> Context:
        """Wrap an external context; ownership is borrowed by default."""
        device._require_open()
        if not isinstance(handle, int) or handle <= 0:
            raise ValueError("expected a nonzero context handle")
        existing = _contexts.get(handle)
        if existing is not None:
            if existing.device is not device or existing._state.owned != owned:
                raise ValueError("context handle already has a different owner")
            return existing
        if _core.get_contexts_device(handle) != device.handle:
            raise ValueError("context does not belong to this device")
        context = cls.__new__(cls)
        context._initialize(device, handle, owned)
        return context

    @property
    def handle(self) -> int | None:
        return self._state.handle

    @property
    def _handle(self) -> int | None:
        return self.handle

    @property
    def closed(self) -> bool:
        return self.handle is None

    @property
    def device(self) -> Device:
        return self._device

    @property
    def is_current(self) -> bool:
        return not self.closed and _core.get_current_context() == self.handle

    def _require_open(self) -> None:
        if self.closed:
            raise ResourceClosedError("context has been destroyed")

    def _require_current(self) -> None:
        self._require_open()
        if not self.is_current:
            raise ContextNotCurrentError("owning context must be current")

    @property
    def listener(self) -> Listener:
        from openal_py.listener import Listener
        self._require_open()
        return Listener(self)

    @property
    def extensions(self) -> frozenset[str]:
        self._require_current()
        return frozenset(_core.get_extensions())

    def supports(self, extension: str) -> bool:
        self._require_current()
        return _core.is_extension_present(extension)

    @contextmanager
    def activate(self) -> Iterator[Context]:
        """Temporarily make this context current, restoring the previous one."""
        self._require_open()
        with self._state.current():
            yield self

    def make_current(self) -> int:
        """Select this context and return the previous raw context handle (0 if none)."""
        self._require_open()
        previous = _core.get_current_context()
        if not _core.make_context_current(self.handle):
            raise LifecycleError("could not make context current")
        return previous

    def process(self) -> None:
        self._require_open()
        _core.process_context(self.handle)

    def suspend(self) -> None:
        self._require_open()
        _core.suspend_context(self.handle)

    def close(self) -> None:
        handle = self.handle
        self._state.destroy()
        if handle is not None:
            _contexts.pop(handle, None)
        self._finalizer.detach()

    destroy = close

    def create_source(
        self, *, buffer: Buffer | None = None, gain: float = 1.0, pitch: float = 1.0,
        position: Vector3 = (0.0, 0.0, 0.0), velocity: Vector3 = (0.0, 0.0, 0.0),
        direction: Vector3 = (0.0, 0.0, 0.0), looping: bool = False,
        relative: bool = False, reference_distance: float = 1.0,
        max_distance: float = 3.4028234663852886e38, rolloff_factor: float = 1.0,
        min_gain: float = 0.0, max_gain: float = 1.0, cone_inner_angle: float = 360.0,
        cone_outer_angle: float = 360.0, cone_outer_gain: float = 0.0,
    ) -> Source:
        """Create a voice with explicit, discoverable playback parameters."""
        from openal_py.source import Source
        self._require_current()
        source = Source(self)
        try:
            source.buffer = buffer
            source.gain = gain
            source.pitch = pitch
            source.position = position
            source.velocity = velocity
            source.direction = direction
            source.looping = looping
            source.relative = relative
            source.reference_distance = reference_distance
            source.max_distance = max_distance
            source.rolloff_factor = rolloff_factor
            source.min_gain = min_gain
            source.max_gain = max_gain
            source.cone_inner_angle = cone_inner_angle
            source.cone_outer_angle = cone_outer_angle
            source.cone_outer_gain = cone_outer_gain
        except Exception:
            source.close()
            raise
        return source

    def create_buffer(self) -> Buffer:
        from openal_py.buffer import Buffer
        return Buffer(self)

    def buffer_from_pcm(self, data: PCMData, *, format: AudioFormat | int,
                        sample_rate: int) -> Buffer:
        from openal_py.buffer import Buffer
        return Buffer.from_pcm(self, data, format, sample_rate)

    def load(self, file: AudioFile, *, format: AudioFormat | int | None = None) -> Buffer:
        """Load WAV without dependencies, or other formats via soundfile.

        Accept paths or seekable binary streams; preserve the channel count.
        """
        import os
        from openal_py.buffer import Buffer
        self._require_current()
        if isinstance(file, (str, os.PathLike)):
            with open(file, "rb") as stream:
                header = stream.read(12)
        else:
            position = file.tell()
            try:
                header = file.read(12)
            finally:
                file.seek(position)
        wav = header[:4] == b"RIFF" and header[8:12] == b"WAVE"
        if wav:
            return Buffer.from_wav(self, file, format=format)
        return Buffer.from_file(self, file, format=format)

    def get_buffer(self, handle: int) -> Buffer | None:
        buffer = self._buffers.get(handle)
        return buffer if buffer is not None and not buffer.closed else None

    def group(self, sources: Iterable[Source]) -> SourceGroup:
        from openal_py.group import SourceGroup
        self._require_open()
        return SourceGroup(self, sources)

    def create_effect(self, type: EffectType | None = None, **parameters: ParameterValue) -> Effect:
        from openal_py.effects import Effect, EffectType
        return Effect(self, EffectType.REVERB if type is None else type, **parameters)

    def create_filter(self, type: FilterType | None = None, **parameters: ParameterValue) -> Filter:
        from openal_py.effects import Filter, FilterType
        return Filter(self, FilterType.LOWPASS if type is None else type, **parameters)

    def create_effect_slot(self, *, effect: Effect | None = None,
                           gain: float = 1.0, auto_send: bool = True) -> AuxiliaryEffectSlot:
        from openal_py.effects import AuxiliaryEffectSlot
        return AuxiliaryEffectSlot(self, effect=effect, gain=gain, auto_send=auto_send)

    def get_parameter(self, parameter: Parameter, *, kind: NumericKind = 'float') -> float | int | bool:
        self._require_current()
        return cast(float | int | bool, _core.global_parameter(resolve(AL, parameter), kind))

    def enum_value(self, name: str) -> int:
        self._require_current()
        return _core.enum_value(name)

    def function_address(self, name: str) -> int | None:
        """Advanced FFI escape hatch; the caller must supply the native signature."""
        self._require_current()
        return _core.function_address(name)

    def enable(self, capability: Parameter) -> None:
        self._require_current()
        _core.capability(resolve(AL, capability), True)

    def disable(self, capability: Parameter) -> None:
        self._require_current()
        _core.capability(resolve(AL, capability), False)

    def is_enabled(self, capability: Parameter) -> bool:
        self._require_current()
        return bool(_core.capability(resolve(AL, capability)))

    @contextmanager
    def deferred_updates(self) -> Iterator[Context]:
        self._require_current()
        if not self.supports('AL_SOFT_deferred_updates'):
            raise NotImplementedError('AL_SOFT_deferred_updates is unavailable')
        was_deferred = bool(self.get_parameter(AL.AL_DEFERRED_UPDATES_SOFT, kind='bool'))
        if not was_deferred:
            _core.defer_updates(True)
        try:
            yield self
        finally:
            if not was_deferred and not self.closed:
                with self.activate():
                    _core.defer_updates(False)

    @property
    def vendor(self) -> str:
        self._require_current()
        return _core.get_string(AL.AL_VENDOR) or ''

    @property
    def renderer(self) -> str:
        self._require_current()
        return _core.get_string(AL.AL_RENDERER) or ''

    @property
    def version(self) -> str:
        self._require_current()
        return _core.get_string(AL.AL_VERSION) or ''

    @property
    def distance_model(self) -> DistanceModel:
        self._require_current()
        return DistanceModel(_core.get_int(AL.AL_DISTANCE_MODEL))

    @distance_model.setter
    def distance_model(self, value: DistanceModel) -> None:
        self._require_current()
        _core.distance_model(int(value))

    @property
    def doppler_factor(self) -> float:
        self._require_current()
        return _core.get_float(AL.AL_DOPPLER_FACTOR)

    @doppler_factor.setter
    def doppler_factor(self, value: float) -> None:
        self._require_current()
        _core.doppler_factor(float(value))

    @property
    def doppler_velocity(self) -> float:
        self._require_current()
        return _core.get_float(AL.AL_DOPPLER_VELOCITY)

    @doppler_velocity.setter
    def doppler_velocity(self, value: float) -> None:
        self._require_current()
        _core.doppler_velocity(float(value))

    @property
    def speed_of_sound(self) -> float:
        self._require_current()
        return _core.get_float(AL.AL_SPEED_OF_SOUND)

    @speed_of_sound.setter
    def speed_of_sound(self, value: float) -> None:
        self._require_current()
        _core.speed_of_sound(float(value))

    def __enter__(self) -> Context:
        self._require_open()
        if self._entered:
            raise LifecycleError("context resource block cannot be nested; use activate()")
        self._entered = True
        return self

    def __exit__(self, *_exc: object) -> None:
        try:
            self.close()
        finally:
            self._entered = False

    def __repr__(self) -> str:
        return f"Context(handle={self.handle}, closed={self.closed})"
