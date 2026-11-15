"""Playback controls, offsets, spatial parameters, and simultaneous voices."""
import math
import struct
import time

from openal_py import AudioFormat, Device


def tone(frequency: float, rate: int, seconds: float) -> bytes:
    count = int(rate * seconds)
    samples = [int(10000 * math.sin(2 * math.pi * frequency * i / rate))
               for i in range(count)]
    return struct.pack(f"<{count}h", *samples)


def main() -> None:
    with Device.open() as device, device.create_context() as ctx, ctx.activate():
        rate = 44100
        sound = ctx.buffer_from_pcm(tone(440, rate, 0.3),
                                    format=AudioFormat.MONO16, sample_rate=rate)
        with ctx.create_source(buffer=sound, gain=0.7, position=(2, 0, 0),
                               max_distance=10, rolloff_factor=1.5) as source:
            print("position:", source.position, "gain:", source.gain)
            source.play()
            print("playing:", source.is_playing())
            source.pause()
            source.offset_seconds = 0.05
            print("offset in samples:", source.offset_samples)
            source.play()
            source.stop()
            source.rewind()
            print("rewound:", source.state)

        # Sources retain their buffers, including those created inline.
        voices = [ctx.create_source(
            buffer=ctx.buffer_from_pcm(tone(frequency, rate, 0.5),
                                       format=AudioFormat.MONO16, sample_rate=rate),
            gain=0.3,
        ) for frequency in (523.25, 659.25, 783.99)]
        for voice in voices:
            voice.play()
        time.sleep(0.6)
        for voice in voices:
            voice.close()
        print("voices closed:", all(voice.closed for voice in voices))


if __name__ == "__main__":
    main()
