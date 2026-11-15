"""Quickstart: open the default device and play a short tone.

Run with:  python examples/01_quickstart.py
"""
import math
import struct

from openal_py import AudioFormat, Buffer, Context, Device


def make_sine(freq: float, sample_rate: int, seconds: float) -> bytes:
    """44.1 kHz mono 16-bit sine wave."""
    n = int(sample_rate * seconds)
    return struct.pack(f"<{n}h", *[int(12000 * math.sin(2 * math.pi * freq * i / sample_rate)) for i in range(n)])


def main() -> None:
    device = Device.default()
    print("device:", device.spec)

    ctx = Context(device)
    with ctx:  # makes the context current for the duration of the block
        tone = Buffer.from_pcm(ctx, make_sine(440.0, 44100, 0.5), AudioFormat.MONO16, 44100)
        src = ctx.create_source(buffer=tone, gain=0.5)
        src.play()
        print("playing 440 Hz for 0.5 s ...")
        import time
        time.sleep(0.6)
        src.stop()
        print("state after stop:", src.state)


if __name__ == "__main__":
    main()
