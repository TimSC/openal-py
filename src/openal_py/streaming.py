"""Explicit, creating-thread streaming with a bounded reusable buffer pool."""
from __future__ import annotations

from enum import Enum
import operator
import threading
from typing import Protocol

from openal_py._audio import decoded_pcm, soundfile_input, soundfile_module
from openal_py._errors import LifecycleError, ResourceClosedError, ThreadAffinityError
from openal_py._types import AudioFile, PCMData
from openal_py.buffer import AudioFormat, Buffer, _infer_format
from openal_py.context import Context
from openal_py.source import Source, SourceState


class PCMDecoder(Protocol):
    """Fixed-layout native-endian PCM decoder; an empty read means final EOF.

    read_frames must return complete frames, at most the requested count. An
    optional rewind() method enables looping. Caller decoders are borrowed by
    default; transfer cleanup responsibility with close_decoder=True.
    """

    @property
    def format(self) -> AudioFormat: ...

    @property
    def sample_rate(self) -> int: ...

    def read_frames(self, frames: int) -> PCMData: ...

    def close(self) -> None: ...


class SoundFileDecoder:
    """Optional SoundFile adapter, preserving channels unless mono=True.

    Closing the adapter releases the decoder, never a caller-owned binary stream.
    """

    def __init__(self, file: AudioFile, *, format: AudioFormat | int | None = None,
                 mono: bool = False):
        sf = soundfile_module()
        self._reader = sf.SoundFile(soundfile_input(file))
        try:
            channels = self._reader.channels
            _infer_format(channels)
            output_channels = 1 if mono else channels
            self.format = _infer_format(output_channels) if format is None else AudioFormat(format)
            if self.format.channels != output_channels:
                raise ValueError(f'file has {output_channels} channel(s), format expects {self.format.channels}')
            self.sample_rate = int(self._reader.samplerate)
            self._floating = self._reader.subtype in ('FLOAT', 'DOUBLE')
            self._mono = mono and channels == 2
        except BaseException:
            self._reader.close()
            raise

    def read_frames(self, frames: int) -> bytes:
        count = operator.index(frames)
        if count <= 0:
            raise ValueError('frames must be positive')
        data = self._reader.read(count, dtype='float64' if self._floating else 'int16', always_2d=True)
        return decoded_pcm(data, floating=self._floating, mono=self._mono, bits=self.format.bits)

    def rewind(self) -> None:
        self._reader.seek(0)

    def close(self) -> None:
        self._reader.close()


class StreamState(str, Enum):
    INITIAL = 'initial'
    PLAYING = 'playing'
    PAUSED = 'paused'
    STOPPED = 'stopped'
    FINISHED = 'finished'
    ERROR = 'error'
    CLOSED = 'closed'


class StreamingSource:
    """An opt-in streaming voice; call update() regularly on its creating thread.

    Native operations require the supplied context to be current. No worker is
    started. The source and a fixed buffer pool are owned by this helper; do not
    queue, stop, loop, or close its exposed source independently. Stop is terminal;
    create a new helper to replay. FINISHED specifically means natural EOF.
    """

    def __init__(self, context: Context, decoder: PCMDecoder, *, chunk_frames: int = 8192,
                 queue_depth: int = 4, looping: bool = False, close_decoder: bool = False):
        self._thread = threading.current_thread()
        self.context = context
        self.decoder = decoder
        self._owns_decoder = close_decoder
        self._chunk_frames = operator.index(chunk_frames)
        self._queue_depth = operator.index(queue_depth)
        self._format = AudioFormat(decoder.format)
        self._rate = operator.index(decoder.sample_rate)
        if not 0 < self.chunk_frames <= (2**31 - 1) // self._format.bytes_per_frame:
            raise ValueError('chunk_frames must be positive and fit a native PCM buffer')
        if not 0 < self.queue_depth <= 2**31 - 1:
            raise ValueError('queue_depth must be between 1 and INT_MAX')
        if not 0 < self._rate <= 2**31 - 1:
            raise ValueError('sample_rate must be between 1 and INT_MAX')
        if looping and not callable(getattr(decoder, 'rewind', None)):
            raise ValueError('looping requires a decoder with rewind()')
        self._state = StreamState.INITIAL
        self._eof = False
        self.looping = looping
        self._started = False
        self._starved = False
        self._underruns = 0
        self._error: Exception | None = None
        self._buffers: list[Buffer] = []
        self._free: list[Buffer] = []
        self._queued: list[Buffer] = []
        context._require_current()
        self.source = Source(context)
        try:
            for _ in range(self.queue_depth):
                self._buffers.append(Buffer(context))
            self._free = list(self._buffers)
        except BaseException:
            self.close()
            raise

    @classmethod
    def from_file(cls, context: Context, file: AudioFile, *,
                  format: AudioFormat | int | None = None, mono: bool = False,
                  chunk_frames: int = 8192, queue_depth: int = 4,
                  looping: bool = False) -> StreamingSource:
        """Open an owned SoundFile decoder; binary input streams remain borrowed."""
        context._require_current()
        decoder = SoundFileDecoder(file, format=format, mono=mono)
        try:
            return cls(context, decoder, chunk_frames=chunk_frames, queue_depth=queue_depth,
                       looping=looping, close_decoder=True)
        except BaseException:
            decoder.close()
            raise

    def _check_thread(self) -> None:
        if threading.current_thread() is not self._thread:
            raise ThreadAffinityError('streaming operations require the creating thread')

    @property
    def chunk_frames(self) -> int:
        return self._chunk_frames

    @property
    def queue_depth(self) -> int:
        return self._queue_depth

    @property
    def looping(self) -> bool:
        return self._looping

    @looping.setter
    def looping(self, enabled: bool) -> None:
        self._check_thread()
        if enabled and not callable(getattr(self.decoder, 'rewind', None)):
            raise ValueError('looping requires a decoder with rewind()')
        self._looping = bool(enabled)
        if enabled:
            self._eof = False

    def _require_current(self) -> None:
        self._check_thread()
        if self.closed:
            raise ResourceClosedError('stream has been closed')
        self.context._require_current()

    @property
    def closed(self) -> bool:
        return self.source.closed

    @property
    def state(self) -> StreamState:
        self._check_thread()
        return self._state

    @property
    def finished(self) -> bool:
        return self.state is StreamState.FINISHED

    @property
    def error(self) -> Exception | None:
        self._check_thread()
        return self._error

    @property
    def underrun_count(self) -> int:
        self._check_thread()
        return self._underruns

    @property
    def buffered_duration(self) -> float:
        """Unconsumed source-audio seconds; pitch affects wall-clock duration."""
        self._require_current()
        if self.source.state is SourceState.STOPPED:
            return 0.0
        return max(0.0, sum(buffer.frame_count for buffer in self._queued) / self._rate
                   - self.source.offset_seconds)

    def _read_chunk(self) -> bytes:
        result = bytearray()
        frame_size = self._format.bytes_per_frame
        rewound_empty = False
        while len(result) < self.chunk_frames * frame_size:
            remaining = self.chunk_frames - len(result) // frame_size
            data = memoryview(self.decoder.read_frames(remaining)).tobytes()
            if len(data) % frame_size or len(data) > remaining * frame_size:
                raise ValueError('decoder returned an invalid PCM frame count')
            if data:
                result.extend(data)
                rewound_empty = False
            elif self.looping and not rewound_empty:
                rewind = getattr(self.decoder, 'rewind', None)
                if not callable(rewind):
                    raise ValueError('looping requires a decoder with rewind()')
                rewind()
                rewound_empty = True
            else:
                self._eof = True
                break
        return bytes(result)

    def play(self) -> None:
        self._require_current()
        if self._state not in (StreamState.INITIAL, StreamState.PAUSED, StreamState.PLAYING):
            raise LifecycleError('a terminal stream cannot be replayed')
        if self._state is StreamState.PLAYING:
            return
        self._state = StreamState.PLAYING
        self.update()

    def pause(self) -> None:
        self._require_current()
        if self._state is StreamState.PLAYING:
            self.source.pause()
            self._state = StreamState.PAUSED

    def resume(self) -> None:
        self._require_current()
        if self._state is StreamState.PAUSED:
            self.play()

    def update(self) -> None:
        """Reclaim/refill queued buffers and recover starvation, or record EOF.

        Decoder failures are retained in error, resources are closed, and the
        original exception is raised. Call close() even after context shutdown
        to release an owned decoder.
        """
        self._require_current()
        if self._state not in (StreamState.PLAYING, StreamState.PAUSED):
            return
        try:
            if self._started and self.source.state is SourceState.STOPPED:
                self._starved = True
            for buffer in self.source.unqueue_buffers():
                self._queued.remove(buffer)
                self._free.append(buffer)
            pending: list[Buffer] = []
            while self._free and not self._eof:
                pcm = self._read_chunk()
                if pcm:
                    buffer = self._free.pop()
                    buffer.upload_pcm(pcm, self._format, self._rate)
                    pending.append(buffer)
            # Decoding can take long enough for the old queue to drain. Remove
            # those entries before restarting, without discarding fresh PCM.
            old_count = len(self._queued)
            if pending:
                self.source.queue_buffers(pending)
                self._queued.extend(pending)
            native_state = self.source.state
            if native_state is SourceState.STOPPED:
                if old_count:
                    for buffer in self.source.unqueue_buffers(old_count):
                        self._queued.remove(buffer)
                        self._free.append(buffer)
                self._starved = self._started
                # A stopped source marks even fresh queue entries processed.
                # Rewind the retained fresh queue so paused updates cannot
                # discard it before resume, and play starts at its beginning.
                self.source.rewind()
                native_state = SourceState.INITIAL
            if self._eof and not self._queued:
                self._state = StreamState.FINISHED
            elif self._queued and self._state is StreamState.PLAYING:
                if native_state is not SourceState.PLAYING:
                    if self._starved:
                        self._underruns += 1
                    self.source.play()
                    self._started = True
                    self._starved = False
        except Exception as error:
            self._error = error
            try:
                self.close()
            except Exception as cleanup_error:
                raise error from cleanup_error
            finally:
                self._state = StreamState.ERROR
            raise

    def stop(self) -> None:
        self._require_current()
        self.source.stop()
        self.source.buffer = None  # Detach all queue entries, including initial queues.
        self._queued.clear()
        self._free = list(self._buffers)
        self._state = StreamState.STOPPED

    def close(self) -> None:
        """Release owned resources; no current context is required for cleanup."""
        self._check_thread()
        errors: list[Exception] = []
        for resource in [self.source, *self._buffers]:
            try:
                resource.close()
            except Exception as error:
                errors.append(error)
        if self._owns_decoder:
            try:
                self.decoder.close()
                self._owns_decoder = False
            except Exception as error:
                errors.append(error)
        if errors:
            raise errors[0]
        self._queued.clear()
        self._free.clear()
        self._state = StreamState.CLOSED

    def __enter__(self) -> StreamingSource:
        self._require_current()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
