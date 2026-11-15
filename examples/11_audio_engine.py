"""Simple playback with automatic activation and deterministic shutdown."""
from array import array
import io
import math
import sys
import wave

from openal_py import AudioEngine


def main() -> None:
    rate = 8000
    samples = array('h', (int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(400)))
    if sys.byteorder != 'little':
        samples.byteswap()
    file = io.BytesIO()
    with wave.open(file, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples.tobytes())
    file.seek(0)

    with AudioEngine(master_volume=0.6, max_voices=8) as audio:
        sound = audio.load(file)  # Paths work too; caller-owned streams stay open.
        voice = audio.play(sound, gain=0.8, position=(2, 0, -5))
        print('duration:', sound.duration)
        print('completed:', voice.wait(timeout=2))
        loop = audio.play(sound, looping=True)
        loop.pause()
        loop.gain = 0.3
        loop.resume()
        print('still looping:', not loop.wait(timeout=0))
        loop.stop()
        print('live voices:', len(audio.voices))
        # Advanced operations remain available without adding engine wrappers.
        with audio.activate() as ctx:
            ctx.listener.position = (0, 1.6, 0)
    print('engine closed:', audio.closed, 'stream still open:', not file.closed)


if __name__ == '__main__':
    main()
