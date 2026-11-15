"""Audio source abstraction."""
from __future__ import annotations

from enum import IntEnum
import operator
from typing import TYPE_CHECKING, Any, cast, Iterable

from openal_py._types import Vector3
from openal_py._errors import ContextMismatchError, ResourceClosedError

if TYPE_CHECKING:
    from openal_py.context import Context
    from openal_py.buffer import Buffer

from openal_py import _core
from openal_py import _finalize
from openal_py._constants import AL


class SourceState(IntEnum):
    INITIAL = AL.AL_INITIAL
    PLAYING = AL.AL_PLAYING
    PAUSED = AL.AL_PAUSED
    STOPPED = AL.AL_STOPPED


class Source:
    """A single playback voice.

    Created via :meth:`Context.create_source` or ``Source(context)``.
    Parameters map to their OpenAL names with leading ``al`` removed:
    ``source.gain``, ``source.position``, ``source.looping``, ...
    """

    def __init__(self, context: Context):
        context._require_current()
        self._initialize(context, _core.gen_sources(1)[0], True)

    def _initialize(self, context: Context, handle: int, owned: bool) -> None:
        self._context = context
        self._handle: int | None = handle
        self._owned = owned
        self._buffer_refs: list[Buffer] = []
        self._finalizer = (_finalize.register(
            self, context._state, handle, _core.delete_sources, self._buffer_refs
        ) if owned else None)
        context._sources[handle] = self

    @classmethod
    def from_handle(cls, context: Context, handle: int, *, owned: bool = False) -> Source:
        """Wrap an external source; owned=True transfers native cleanup."""
        context._require_current()
        existing = context._sources.get(handle)
        if existing is not None and not existing.closed:
            if existing._owned != owned:
                raise ValueError("source handle already has a different owner")
            return existing
        if not isinstance(handle, int) or handle <= 0 or not _core.is_source(handle):
            raise ValueError("expected a live source handle in the current context")
        source = cls.__new__(cls)
        source._initialize(context, handle, owned)
        return source

    @property
    def context(self) -> Context:
        return self._context

    @property
    def closed(self) -> bool:
        return self._handle is None or self.context.closed

    @property
    def handle(self) -> int | None:
        return None if self.closed else self._handle

    def close(self) -> None:
        if self._handle is not None:
            if self._owned:
                _finalize.release(
                    self.context._state, self._handle, _core.delete_sources, self._buffer_refs
                )
            else:
                self._buffer_refs.clear()
            self.context._sources.pop(self._handle, None)
            self._handle = None
            if self._finalizer is not None:
                self._finalizer.detach()

    delete = close

    def _require_current(self) -> None:
        if self.closed:
            raise ResourceClosedError("source has been deleted or its context closed")
        self.context._require_current()

    def __enter__(self) -> Source:
        self._require_current()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- state --------------------------------------------------------------

    @property
    def state(self) -> SourceState:
        self._require_current()
        return SourceState(_core.source_geti(self._handle, AL.AL_SOURCE_STATE))

    def play(self) -> None:
        self._require_current()
        _core.source_play(self._handle)

    def pause(self) -> None:
        self._require_current()
        _core.source_pause(self._handle)

    def stop(self) -> None:
        self._require_current()
        _core.source_stop(self._handle)

    def is_playing(self) -> bool:
        return self.state == SourceState.PLAYING

    # -- scalar parameters ---------------------------------------------------

    def _set(self, pname: int, value: Any) -> None:
        self._require_current()
        _core.source_set(self._handle, pname, value)

    def _get(self, pname: int, n: int = 1) -> Any:
        self._require_current()
        return _core.source_get(self._handle, pname, n)

    def _geti(self, pname: int) -> int:
        self._require_current()
        return _core.source_geti(self._handle, pname)

    @property
    def gain(self) -> float:
        return cast(float, self._get(AL.AL_GAIN))

    @gain.setter
    def gain(self, value: float) -> None:
        self._set(AL.AL_GAIN, float(value))

    @property
    def pitch(self) -> float:
        return cast(float, self._get(AL.AL_PITCH))

    @pitch.setter
    def pitch(self, value: float) -> None:
        self._set(AL.AL_PITCH, float(value))

    @property
    def looping(self) -> bool:
        return self._geti(AL.AL_LOOPING) != 0

    @looping.setter
    def looping(self, value: bool) -> None:
        self._set(AL.AL_LOOPING, int(bool(value)))

    @property
    def relative(self) -> bool:
        return self._geti(AL.AL_SOURCE_RELATIVE) != 0

    @relative.setter
    def relative(self, value: bool) -> None:
        self._set(AL.AL_SOURCE_RELATIVE, int(bool(value)))

    @property
    def reference_distance(self) -> float:
        return cast(float, self._get(AL.AL_REFERENCE_DISTANCE))

    @reference_distance.setter
    def reference_distance(self, value: float) -> None:
        self._set(AL.AL_REFERENCE_DISTANCE, float(value))

    @property
    def max_distance(self) -> float:
        return cast(float, self._get(AL.AL_MAX_DISTANCE))

    @max_distance.setter
    def max_distance(self, value: float) -> None:
        self._set(AL.AL_MAX_DISTANCE, float(value))

    @property
    def rolloff_factor(self) -> float:
        return cast(float, self._get(AL.AL_ROLLOFF_FACTOR))

    @rolloff_factor.setter
    def rolloff_factor(self, value: float) -> None:
        self._set(AL.AL_ROLLOFF_FACTOR, float(value))

    # -- vector parameters -----------------------------------------------------

    @property
    def position(self) -> tuple[float, float, float]:
        return cast(tuple[float, float, float], self._get(AL.AL_POSITION, 3))

    @position.setter
    def position(self, value: Vector3) -> None:
        self._set(AL.AL_POSITION, value)

    @property
    def velocity(self) -> tuple[float, float, float]:
        return cast(tuple[float, float, float], self._get(AL.AL_VELOCITY, 3))

    @velocity.setter
    def velocity(self, value: Vector3) -> None:
        self._set(AL.AL_VELOCITY, value)

    @property
    def direction(self) -> tuple[float, float, float]:
        return cast(tuple[float, float, float], self._get(AL.AL_DIRECTION, 3))

    @direction.setter
    def direction(self, value: Vector3) -> None:
        self._set(AL.AL_DIRECTION, value)

    # -- buffer -----------------------------------------------------------------

    @property
    def buffer(self) -> Buffer | None:
        from openal_py.buffer import Buffer
        if self._geti(AL.AL_SOURCE_TYPE) == AL.AL_STREAMING:
            return None
        h = self._geti(AL.AL_BUFFER)
        if h == 0:
            return None
        if self._buffer_refs and self._buffer_refs[0].handle == h:
            return self._buffer_refs[0]
        return self._context.get_buffer(h) or Buffer.from_handle(self._context, h)

    @buffer.setter
    def buffer(self, value: Buffer | None) -> None:
        from openal_py.buffer import Buffer
        if value is None:
            h = 0
        elif isinstance(value, Buffer):
            if value._context is not self._context:
                raise ContextMismatchError("buffer belongs to a different context")
            if value.closed:
                raise ValueError("buffer has been deleted")
            assert value.handle is not None
            h = value.handle
        else:
            raise TypeError(f"expected Buffer or None, got {type(value)!r}")
        self._set(AL.AL_BUFFER, h)
        self._buffer_refs[:] = [] if value is None else [value]

    def rewind(self) -> None:
        """Return the source to INITIAL, resetting its playback position."""
        self._require_current()
        _core.source_rewind(self._handle)

    @property
    def offset_seconds(self) -> float:
        return cast(float, self._get(AL.AL_SEC_OFFSET))

    @offset_seconds.setter
    def offset_seconds(self, value: float) -> None:
        self._set(AL.AL_SEC_OFFSET, float(value))

    @property
    def offset_samples(self) -> int:
        return self._geti(AL.AL_SAMPLE_OFFSET)

    @offset_samples.setter
    def offset_samples(self, value: int) -> None:
        self._set(AL.AL_SAMPLE_OFFSET, operator.index(value))

    @property
    def offset_bytes(self) -> int:
        return self._geti(AL.AL_BYTE_OFFSET)

    @offset_bytes.setter
    def offset_bytes(self, value: int) -> None:
        self._set(AL.AL_BYTE_OFFSET, operator.index(value))

    @property
    def buffers_queued(self) -> int:
        return self._geti(AL.AL_BUFFERS_QUEUED)

    @property
    def buffers_processed(self) -> int:
        return self._geti(AL.AL_BUFFERS_PROCESSED)

    def queue_buffers(self, buffers: Iterable[Buffer]) -> None:
        """Append compatible buffers atomically and retain every queue entry."""
        from openal_py.buffer import Buffer
        self._require_current()
        entries = list(buffers)
        for buffer in entries:
            if not isinstance(buffer, Buffer):
                raise TypeError("queue entries must be Buffer objects")
            if buffer.context is not self.context:
                raise ContextMismatchError("buffer belongs to a different context")
            if buffer.closed:
                raise ResourceClosedError("cannot queue a deleted buffer")
        handles = []
        for buffer in entries:
            assert buffer.handle is not None
            handles.append(buffer.handle)
        _core.source_queue_buffers(self._handle, handles)
        self._buffer_refs.extend(entries)

    def unqueue_buffers(self, count: int | None = None) -> list[Buffer]:
        """Remove processed entries in queue order; default to all processed entries."""
        from openal_py.buffer import Buffer
        self._require_current()
        n = self.buffers_processed if count is None else operator.index(count)
        if n < 0:
            raise ValueError("count must be nonnegative")
        handles = _core.source_unqueue_buffers(self._handle, n)
        result = []
        for handle in handles:
            index = next((i for i, buffer in enumerate(self._buffer_refs)
                          if buffer.handle == handle), None)
            if index is not None:
                buffer = self._buffer_refs.pop(index)
            else:
                buffer = self.context.get_buffer(handle) or Buffer.from_handle(self.context, handle)
            result.append(buffer)
        return result

    def __repr__(self) -> str:
        return f"Source(handle={self.handle}, closed={self.closed})"
