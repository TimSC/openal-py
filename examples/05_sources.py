"""Sources: playback state, parameters, and multiple simultaneous voices.

Run with:  python examples/05_sources.py
"""
import struct
import time

from openal_py import AudioFormat, Buffer, Context, Device


def tone(freq: float, rate: int, seconds: float) -> bytes:
    import math
    n = int(rate * seconds)
    return struct.pack(f"<{n}h", *[int(10000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)])


def main() -> None:
    device = Device.default()
    ctx = Context(device)
    with ctx:
        rate = 44100
        buf = Buffer.from_pcm(ctx, tone(440.0, rate, 0.3), AudioFormat.MONO16, rate)

        # --- a single source with parameters -----------------------------
        src = ctx.create_source(buffer=buf)
        src.gain = 0.7
        src.pitch = 1.0
        src.position = (2.0, 0.0, 0.0)       # 2 m to the listener's right
        src.reference_distance = 1.0         # full volume at 1 m
        src.max_distance = 10.0              # quiet beyond this
        src.rolloff_factor = 1.5             # falloff speed
        src.looping = False
        print("position:", src.position, "| gain:", src.gain)

        src.play()
        print("state:", src.state, "| playing:", src.is_playing())
        src.pause()
        print("paused:", src.state)
        src.play()   # resume
        src.stop()
        print("stopped:", src.state)

        # --- multiple simultaneous voices (chord) -------------------------
        a = ctx.create_source(buffer=Buffer.from_pcm(ctx, tone(523.25, rate, 0.5), AudioFormat.MONO16, rate))
        b = ctx.create_source(buffer=Buffer.from_pcm(ctx, tone(659.25, rate, 0.5), AudioFormat.MONO16, rate))
        c = ctx.create_source(buffer=Buffer.from_pcm(ctx, tone(783.99, rate, 0.5), AudioFormat.MONO16, rate))
        for s in (a, b, c):
            s.gain = 0.3
            s.play()
        print("chord playing:", a.state, b.state, c.state)
        time.sleep(0.6)
        for s in (a, b, c):
            s.stop()

        # Buffers can be shared between sources
        print("a.buffer is buf?", a.buffer is not None)


if __name__ == "__main__":
    main()
