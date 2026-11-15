"""Quickstart: open the default device and play a short tone.

Run with:  python examples/01_quickstart.py
"""
import math
import struct

from openal_py import AudioFormat, Device


def make_sine(freq: float, sample_rate: int, seconds: float) -> bytes:
    """44.1 kHz mono 16-bit sine wave."""
    n = int(sample_rate * seconds)
    return struct.pack(f"<{n}h", *[int(12000 * math.sin(2 * math.pi * freq * i / sample_rate)) for i in range(n)])


def main() -> None:
    with Device.open() as device, device.create_context() as ctx, ctx.activate():
        print("device:", device.spec)
        tone = ctx.buffer_from_pcm(make_sine(440.0, 44100, 0.5), format=AudioFormat.MONO16, sample_rate=44100)
        src = ctx.create_source(buffer=tone, gain=0.5)
        src.play()
        print("playing 440 Hz for 0.5 s ...")
        import time
        time.sleep(0.6)
        src.stop()
        print("state after stop:", src.state)


if __name__ == "__main__":
    main()
