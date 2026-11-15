"""Synchronous playback conveniences over the managed OpenAL object API."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import math
import operator
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterator, Mapping, TypeVar, cast

from openal_py import _finalize
from openal_py.buffer import AudioFormat, Buffer
from openal_py.context import Context
from openal_py.device import Device
from openal_py.loopback import LoopbackDevice
from openal_py.source import Source, SourceState
from openal_py._errors import (
    ContextMismatchError, LifecycleError, ResourceClosedError, ResourceInUseError,
    ThreadAffinityError,
)
from openal_py._types import AudioFile, PCMData, Vector3

# Cooperating engines serialize process-wide context selection. The lower-level
# API remains explicit; callers must not manipulate it concurrently from elsewhere.
_activation_lock = threading.RLock()
_E = TypeVar("_E", bound="AudioEngine")
_S = TypeVar("_S", bound="Sound")
_V = TypeVar("_V", bound="Voice")


class _EngineState:
    """Finalizer state contains native wrappers, never Sound/Voice/AudioEngine."""

    def __init__(self, device: Device, context: Context, owns_device: bool):
        self.device = device
        self.context = context
        self.owns_device = owns_device
        self.sources: set[Source] = set()
        self.buffers: set[Buffer] = set()

    def close(self) -> None:
        # Continue teardown on failure; context destruction also frees any native
        # children that could not be deleted individually. Retain failed owners
        # for retry if context/device cleanup fails.
        errors: list[Exception] = []
        with _activation_lock:
            resources: list[Source | Buffer | Context] = [*self.sources, *self.buffers, self.context]
            for resource in resources:
                try:
                    resource.close()
                except Exception as error:
                    errors.append(error)
            if self.context.closed:
                self.sources.clear()
                self.buffers.clear()
            if self.owns_device:
                try:
                    self.device.close()
                except Exception as error:
                    errors.append(error)
        if errors:
            raise errors[0]


def _finite_nonnegative(value: float, name: str, *, positive: bool = False) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f'{name} must be finite and {"positive" if positive else "nonnegative"}')
    return number


class AudioEngine:
    """An owning-thread playback facade; no worker thread or automatic streaming.

    Named/default devices are owned. An injected Device (including LoopbackDevice)
    is borrowed; the engine owns only its newly created context and assets.
    ``update()`` and ``activate()`` are extension points for application loops and
    advanced operations on the existing low-level API.
    """

    def __init__(self, device: Device | str | None = None, *, sample_rate: int | None = None,
                 max_voices: int = 64, master_volume: float = 1.0,
                 attributes: Mapping[str | int, int] | None = None):
        limit = operator.index(max_voices)
        if limit <= 0:
            raise ValueError('max_voices must be positive')
        volume = _finite_nonnegative(master_volume, 'master_volume')
        self._thread = threading.current_thread()
        self._max_voices = limit
        self._voices: set[Voice] = set()
        self._sounds: set[Sound] = set()
        self._cache: dict[tuple[str, int | None], Sound] = {}
        self._entered = False
        with _activation_lock, ExitStack() as rollback:
            if isinstance(device, Device):
                opened = device
                owns_device = False
            else:
                opened = Device.open(device)
                owns_device = True
            if owns_device:
                rollback.callback(opened.close)
            context = (opened.create_context(attributes=attributes) if sample_rate is None else
                       opened.create_context(sample_rate=sample_rate, attributes=attributes))
            rollback.callback(context.close)
            with context.activate():
                context.listener.gain = volume
            self._state = _EngineState(opened, context, owns_device)
            self._finalizer = _finalize.finalize(self, self._state.close)
            rollback.pop_all()

    def _check_thread(self) -> None:
        if threading.current_thread() is not self._thread:
            raise ThreadAffinityError('AudioEngine operations require the thread that created it')

    def _require_open(self) -> None:
        self._check_thread()
        if self.closed:
            raise ResourceClosedError('audio engine has been closed')

    @property
    def closed(self) -> bool:
        return self._state.context.closed or self._state.device.closed

    @property
    def device(self) -> Device:
        """Advanced access; ownership follows the constructor's device argument."""
        self._require_open()
        return self._state.device

    @property
    def context(self) -> Context:
        """Advanced access; use activate() before calling context-dependent APIs."""
        self._require_open()
        return self._state.context

    @property
    def max_voices(self) -> int:
        return self._max_voices

    @contextmanager
    def activate(self) -> Iterator[Context]:
        """Select the engine context temporarily and preserve any outer context."""
        self._require_open()
        with _activation_lock, self._state.context.activate() as context:
            yield context

    @property
    def master_volume(self) -> float:
        with self.activate() as context:
            return context.listener.gain

    @master_volume.setter
    def master_volume(self, volume: float) -> None:
        self._require_open()
        value = _finite_nonnegative(volume, 'master_volume')
        with self.activate() as context:
            context.listener.gain = value

    def sound_from_buffer(self, buffer: Buffer) -> Sound:
        """Adopt a buffer from this engine's context, e.g. from a custom decoder.

        The buffer will close with the Sound or engine. The original caller must
        no longer manage its lifetime independently.
        """
        self._require_open()
        if not isinstance(buffer, Buffer):
            raise TypeError('expected Buffer')
        if buffer.context is not self._state.context:
            raise ContextMismatchError('buffer belongs to another context')
        if buffer.closed:
            raise ResourceClosedError('buffer has been closed')
        for sound in self._sounds:
            if sound._buffer is buffer:
                return sound
        sound = Sound(self, buffer)
        self._state.buffers.add(buffer)
        self._sounds.add(sound)
        return sound

    def sound_from_pcm(self, data: PCMData, *, format: AudioFormat | int,
                        sample_rate: int) -> Sound:
        with self.activate() as context:
            buffer = context.buffer_from_pcm(data, format=format, sample_rate=sample_rate)
            return self.sound_from_buffer(buffer)

    def load(self, file: AudioFile, *, format: AudioFormat | int | None = None,
             cache: bool = True) -> Sound:
        """Decode a Sound; cache filesystem paths until Sound/engine closure.

        Streams are never cached. Use cache=False to re-read a changed path.
        """
        self._require_open()
        key = None
        actual = file
        if isinstance(file, (str, os.PathLike)):
            path = Path(file).expanduser().resolve()
            actual = path
            if cache:
                key = (str(path), None if format is None else int(format))
                existing = self._cache.get(key)
                if existing is not None and not existing.closed:
                    return existing
        with self.activate() as context:
            sound = self.sound_from_buffer(context.load(actual, format=format))
        if key is not None:
            self._cache[key] = sound
        return sound

    def play(self, sound: Sound | AudioFile, *, gain: float = 1.0, pitch: float = 1.0,
             position: Vector3 = (0.0, 0.0, 0.0), looping: bool = False,
             relative: bool = False) -> Voice:
        """Start a retained voice; raise ResourceInUseError at the voice limit.

        Paths/streams are accepted as shorthand for load(). Completed sources
        are reclaimed before checking the limit. No voice stealing occurs.
        """
        self._require_open()
        if isinstance(sound, Sound):
            if sound._engine is not self:
                raise ContextMismatchError('sound belongs to another audio engine')
            if sound.closed:
                raise ResourceClosedError('sound has been closed')
        self._reap_finished()
        if len(self._voices) >= self.max_voices:
            raise ResourceInUseError('maximum simultaneous voices reached')
        asset = sound if isinstance(sound, Sound) else self.load(sound)
        with self.activate() as context:
            source = context.create_source(buffer=asset._buffer, gain=gain, pitch=pitch,
                                           position=position, looping=looping, relative=relative)
            voice = None
            try:
                voice = self._create_voice(asset, source)
                source.play()
                self._state.sources.add(source)
                self._voices.add(voice)
            except BaseException:
                if voice is not None:
                    self._voices.discard(voice)
                self._state.sources.discard(source)
                source.close()
                raise
            return voice

    def _create_voice(self, sound: Sound, source: Source) -> Voice:
        """Subclass hook, called with the engine context current before playback.

        Return a Voice (or subclass) using these same engine/sound/source objects.
        This is a useful place to attach application-specific routing or metadata.
        """
        return Voice(self, sound, source)

    @property
    def voices(self) -> tuple[Voice, ...]:
        """Current live voices after reclaiming completed playback."""
        self._reap_finished()
        return tuple(self._voices)

    def _release_voice(self, voice: Voice) -> None:
        voice._source.close()
        self._state.sources.discard(voice._source)
        self._voices.discard(voice)
        voice._finished = True

    def update(self) -> int:
        """Reclaim completed voices; return their count. Call from a frame loop.

        Subclasses can extend this method (calling super()) for their own
        streaming/refill policies. The base engine only manages static sounds.
        """
        return self._reap_finished()

    def _reap_finished(self) -> int:
        released = 0
        with self.activate():
            for voice in tuple(self._voices):
                if voice._source.closed or voice._source.state is SourceState.STOPPED:
                    self._release_voice(voice)
                    released += 1
        return released

    def stop_all(self) -> None:
        with self.activate():
            for voice in tuple(self._voices):
                self._release_voice(voice)

    def close(self) -> None:
        self._check_thread()
        try:
            self._state.close()
        finally:
            if self._state.context.closed:
                for voice in self._voices:
                    voice._finished = True
                self._voices.clear()
                self._sounds.clear()
                self._cache.clear()
                if not self._state.owns_device or self._state.device.closed:
                    self._finalizer.detach()

    def __enter__(self: _E) -> _E:
        self._require_open()
        if self._entered:
            raise LifecycleError('audio engine resource block cannot be nested')
        self._entered = True
        return self

    def __exit__(self, *_exc: object) -> None:
        try:
            self.close()
        finally:
            self._entered = False

    def __repr__(self) -> str:
        return f'AudioEngine(closed={self.closed}, max_voices={self.max_voices})'


class Sound:
    """An engine-owned audio asset. Obtain through load()/sound_from_pcm()."""

    def __init__(self, engine: AudioEngine, buffer: Buffer):
        self._engine = engine
        self._buffer = buffer

    @property
    def closed(self) -> bool:
        return self._buffer.closed

    @property
    def buffer(self) -> Buffer:
        """Advanced access; native operations require engine.activate()."""
        self._engine._require_open()
        if self.closed:
            raise ResourceClosedError('sound has been closed')
        return self._buffer

    @property
    def duration(self) -> float:
        with self._engine.activate():
            return self._buffer.duration

    @property
    def sample_rate(self) -> int:
        with self._engine.activate():
            return self._buffer.sample_rate

    @property
    def channels(self) -> int:
        with self._engine.activate():
            return self._buffer.channels

    @property
    def format(self) -> AudioFormat | int | None:
        with self._engine.activate():
            return self._buffer.format

    @property
    def frame_count(self) -> int:
        with self._engine.activate():
            return self._buffer.frame_count

    def close(self) -> None:
        self._engine._check_thread()
        if not self.closed:
            self._engine._reap_finished()
            if any(voice._sound is self for voice in self._engine._voices):
                raise ResourceInUseError('sound still has active voices; stop them first')
            with self._engine.activate():
                self._buffer.close()
        self._engine._state.buffers.discard(self._buffer)
        self._engine._sounds.discard(self)
        for key, value in tuple(self._engine._cache.items()):
            if value is self:
                del self._engine._cache[key]

    def __enter__(self: _S) -> _S:
        self._engine._require_open()
        if self.closed:
            raise ResourceClosedError('sound has been closed')
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f'Sound(closed={self.closed})'


class Voice:
    """One playback instance. stop()/close() release it; replay via engine.play()."""

    def __init__(self, engine: AudioEngine, sound: Sound, source: Source):
        self._engine = engine
        self._sound = sound
        self._source = source
        self._finished = False

    @property
    def closed(self) -> bool:
        return self._source.closed

    @property
    def sound(self) -> Sound:
        return self._sound

    def _require_open(self) -> None:
        self._engine._require_open()
        if self.closed:
            raise ResourceClosedError('voice has finished or been closed')

    @property
    def source(self) -> Source:
        """Advanced access; use engine.activate() for native source operations."""
        self._require_open()
        return self._source

    @property
    def state(self) -> SourceState:
        self._engine._check_thread()
        if self._finished:
            return SourceState.STOPPED
        if self._source.closed:
            self._engine._release_voice(self)
            return SourceState.STOPPED
        self._engine._require_open()
        with self._engine.activate():
            state = self._source.state
            if state is SourceState.STOPPED:
                self._engine._release_voice(self)
            return state

    @property
    def finished(self) -> bool:
        return self.state is SourceState.STOPPED

    def is_playing(self) -> bool:
        return self.state is SourceState.PLAYING

    def pause(self) -> None:
        self._require_open()
        with self._engine.activate():
            self._source.pause()

    def resume(self) -> None:
        self._require_open()
        with self._engine.activate():
            self._source.play()

    def stop(self) -> None:
        self._engine._check_thread()
        if self._finished:
            return
        if self._source.closed:
            self._engine._release_voice(self)
            return
        self._engine._require_open()
        with self._engine.activate():
            self._engine._release_voice(self)

    close = stop

    def wait(self, timeout: float | None = None, *, poll_interval: float = 0.01) -> bool:
        """Wait for completion; return False on timeout without stopping playback.

        A paused/looping voice requires a timeout, since only the owning thread
        can change it. This method polls synchronously and does not pump events.
        """
        self._engine._check_thread()
        interval = _finite_nonnegative(poll_interval, 'poll_interval', positive=True)
        duration = None if timeout is None else _finite_nonnegative(timeout, 'timeout')
        if self.finished:
            return True
        if duration is None and isinstance(self._engine._state.device, LoopbackDevice):
            raise LifecycleError('loopback playback requires rendering frames; use a timeout or render() and update()')
        if duration is None and (self.looping or self.state is SourceState.PAUSED):
            raise LifecycleError('paused or looping voices require a wait timeout')
        deadline = None if duration is None else time.monotonic() + duration
        while not self.finished:
            if deadline is None and (self.looping or self.state is SourceState.PAUSED):
                raise LifecycleError('paused or looping voices require a wait timeout')
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            time.sleep(interval if remaining is None else min(interval, remaining))
            self._engine.update()
        return True

    def _get(self, name: str) -> Any:
        self._require_open()
        with self._engine.activate():
            return getattr(self._source, name)

    def _set(self, name: str, value: Any) -> None:
        self._require_open()
        with self._engine.activate():
            setattr(self._source, name, value)

    @property
    def gain(self) -> float:
        return float(self._get('gain'))

    @gain.setter
    def gain(self, value: float) -> None:
        self._set('gain', value)

    @property
    def pitch(self) -> float:
        return float(self._get('pitch'))

    @pitch.setter
    def pitch(self, value: float) -> None:
        self._set('pitch', value)

    @property
    def position(self) -> tuple[float, float, float]:
        return cast(tuple[float, float, float], self._get('position'))

    @position.setter
    def position(self, value: Vector3) -> None:
        self._set('position', value)

    @property
    def looping(self) -> bool:
        return bool(self._get('looping'))

    @looping.setter
    def looping(self, enabled: bool) -> None:
        self._set('looping', enabled)

    def __enter__(self: _V) -> _V:
        self._require_open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f'Voice(closed={self.closed}, finished={self._finished})'
