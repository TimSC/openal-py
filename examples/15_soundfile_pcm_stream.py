"""Wrap an already-open SoundFile as a borrowed PCMStream and play it.

Install openal-py[soundfile], then run:
    python examples/15_soundfile_pcm_stream.py music.flac

Without a filename, play a short generated WAV. For ordinary paths, prefer the
built-in SoundFileStream; this adapter demonstrates integrating an existing reader.
"""
from __future__ import annotations

from array import array
import io
import math
import operator
import sys
import time
from typing import TYPE_CHECKING
import wave

from openal_py import AudioEngine, AudioFormat, PCMStream

if TYPE_CHECKING:
    import soundfile


class BorrowedSoundFileStream(PCMStream):
    """Read mono/stereo input as interleaved native-endian signed PCM16.

    Playback begins at the reader's current position. The caller must keep the
    reader open and avoid reading/seeking it independently during playback.
    close() inherits the no-op default: this adapter never closes its reader.
    """

    def __init__(self, reader: soundfile.SoundFile):
        if reader.channels not in (1, 2):
            raise ValueError('only mono and stereo inputs are supported')
        self._reader = reader
        self._format = AudioFormat.MONO16 if reader.channels == 1 else AudioFormat.STEREO16
        self._sample_rate = int(reader.samplerate)

    @property
    def format(self) -> AudioFormat:
        return self._format

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def read_frames(self, frames: int) -> bytes:
        count = operator.index(frames)
        if count <= 0:
            raise ValueError('frames must be positive')
        # SoundFile handles decoding and PCM16 conversion. At EOF this yields
        # empty bytes; short reads remain complete interleaved PCM frames.
        return bytes(self._reader.buffer_read(count, dtype='int16'))


def demo_wav() -> io.BytesIO:
    rate = 48000
    samples = array('h', (int(6000 * math.sin(2 * math.pi * 440 * i / rate))
                          for i in range(rate // 5)))
    if sys.byteorder != 'little':
        samples.byteswap()  # WAV stores little-endian PCM.
    file = io.BytesIO()
    with wave.open(file, 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(samples.tobytes())
    file.seek(0)
    return file


def main() -> None:
    try:
        import soundfile
    except ImportError:
        print('Install openal-py[soundfile] to run this example.')
        return

    file = sys.argv[1] if len(sys.argv) > 1 else demo_wav()
    # Exit order stops playback before the reader closes. Reads are synchronous;
    # blocking network inputs should feed a bounded queue from a producer thread.
    with soundfile.SoundFile(file) as reader, AudioEngine() as audio:
        with BorrowedSoundFileStream(reader) as stream, audio.play_stream(stream) as voice:
            while voice.active:
                audio.update()
                time.sleep(0.01)
        assert not reader.closed
        print('Playback complete; the caller still owns the SoundFile reader.')


if __name__ == '__main__':
    main()
