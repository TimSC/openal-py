"""Non-blocking microphone capture in PCM frames."""
from __future__ import annotations

from contextlib import contextmanager
import operator
from typing import Iterator

from openal_py import _core, _finalize
from openal_py.buffer import AudioFormat
from openal_py._errors import ResourceClosedError


class _CaptureState:
    def __init__(self, handle: int):
        self.handle: int | None = handle
        self.capturing = False

    def close(self) -> None:
        if self.handle is not None:
            _core.capture_close(self.handle)
            self.handle = None
            self.capturing = False


class CaptureDevice:
    """A capture ring buffer; read() returns only already-available PCM frames.

    Resource blocks close the device; recording() starts/stops acquisition.
    """

    def __init__(self, name: str | None = None, *, sample_rate: int = 44100,
                 format: AudioFormat = AudioFormat.MONO16, buffer_frames: int | None = None):
        self._sample_rate = operator.index(sample_rate)
        self._format = AudioFormat(format)
        frames = self._sample_rate if buffer_frames is None else operator.index(buffer_frames)
        if not 0 < self._sample_rate <= 2**31 - 1 or not 0 < frames <= 2**31 - 1:
            raise ValueError('sample_rate and buffer_frames must be positive native integers')
        self._name = name
        self._state = _CaptureState(_core.capture_open(name, self._sample_rate, int(self._format), frames))
        self._finalizer = _finalize.finalize(self, self._state.close)

    @classmethod
    def open(cls, name: str | None = None, *, sample_rate: int = 44100,
             format: AudioFormat = AudioFormat.MONO16, buffer_frames: int | None = None) -> CaptureDevice:
        return cls(name, sample_rate=sample_rate, format=format, buffer_frames=buffer_frames)

    @staticmethod
    def devices() -> tuple[str, ...]:
        return tuple(_core.capture_devices())

    @staticmethod
    def default_name() -> str | None:
        return _core.alc_get_string(None, 0x311)

    @property
    def handle(self) -> int | None:
        return self._state.handle

    @property
    def closed(self) -> bool:
        return self.handle is None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def format(self) -> AudioFormat:
        return self._format

    @property
    def capturing(self) -> bool:
        return self._state.capturing

    def _require_open(self) -> None:
        if self.closed:
            raise ResourceClosedError('capture device has been closed')

    @property
    def available_frames(self) -> int:
        self._require_open()
        return _core.capture_available(self.handle)

    def start(self) -> None:
        self._require_open()
        _core.capture_start(self.handle)
        self._state.capturing = True

    def stop(self) -> None:
        self._require_open()
        _core.capture_stop(self.handle)
        self._state.capturing = False

    @contextmanager
    def recording(self) -> Iterator[CaptureDevice]:
        self._require_open()
        already_recording = self.capturing
        if not already_recording:
            self.start()
        try:
            yield self
        finally:
            if not already_recording and not self.closed:
                self.stop()

    def read(self, frames: int | None = None) -> bytes:
        self._require_open()
        n = self.available_frames if frames is None else operator.index(frames)
        if n < 0 or n > self.available_frames:
            raise ValueError('frames must be nonnegative and no greater than available_frames')
        return _core.capture_read(self.handle, n)

    def close(self) -> None:
        self._state.close()
        self._finalizer.detach()

    def __enter__(self) -> CaptureDevice:
        self._require_open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f'CaptureDevice(name={self._name!r}, sample_rate={self.sample_rate}, closed={self.closed})'
