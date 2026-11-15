"""Buffers: raw PCM and WAV files.

Run with:  python examples/04_buffers.py
"""
import math
import struct

from openal_py import AudioFormat, Buffer, Context, Device


def main() -> None:
    device = Device.default()
    ctx = Context(device)
    with ctx:
        # --- raw PCM -----------------------------------------------------
        # 100 ms of 440 Hz sine, mono 16-bit @ 44.1 kHz
        rate = 44100
        n = rate // 10
        samples = struct.pack(f"<{n}h", *[int(12000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n)])
        buf = Buffer.from_pcm(ctx, samples, AudioFormat.MONO16, rate)
        print("PCM buffer:  freq=%d ch=%d size=%d bytes" % (buf.frequency, buf.channels, buf.size))

        # --- stereo -------------------------------------------------------
        stereo = Buffer.from_pcm(ctx, b"\x00" * (2 * n), AudioFormat.STEREO16, rate)
        print("stereo:      ch=%d" % stereo.channels)
        stereo.delete()

        # --- WAV file -----------------------------------------------------
        # (write a tiny WAV first in real usage)
        import wave, tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        with wave.open(wav_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"\x00\x00" * 4410)
        wav_buf = Buffer.from_wav(ctx, wav_path)
        print("WAV buffer:  freq=%d ch=%d size=%d" % (wav_buf.frequency, wav_buf.channels, wav_buf.size))
        os.unlink(wav_path)

        # --- any format via optional soundfile (pip install soundfile) ------
        try:
            import numpy, soundfile, tempfile
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
                ogg_path = f.name
            soundfile.write(ogg_path, numpy.zeros(n, dtype="float64"), rate, format="OGG")
            ogg_buf = Buffer.from_file(ctx, ogg_path)
            print("OGG buffer:  freq=%d ch=%d (via soundfile)" % (ogg_buf.frequency, ogg_buf.channels))
            os.unlink(ogg_path)
        except ImportError:
            print("OGG buffer:  (soundfile not installed; pip install soundfile)")

        # Attach to a source and play
        src = ctx.create_source(buffer=buf, gain=0.5)
        src.play()
        import time
        time.sleep(0.15)
        src.stop()
        src.delete()      # unbinds the buffer before it is deleted
        buf.delete()
        wav_buf.delete()


if __name__ == "__main__":
    main()
