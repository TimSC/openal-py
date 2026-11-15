"""Render a synchronized pair of voices to PCM without audio hardware."""
from array import array
import math
import tempfile
from pathlib import Path
import wave

from openal_py import AudioFormat, DistanceModel, LoopbackDevice


def main() -> None:
    try:
        device = LoopbackDevice()
    except NotImplementedError as error:
        print(error)
        return
    rate = 48000
    frames = rate // 10
    with device, device.create_context(sample_rate=rate) as ctx, ctx.activate():
        ctx.distance_model = DistanceModel.INVERSE_CLAMPED
        voices = []
        for frequency in (440, 660):
            samples = array('h', (int(6000 * math.sin(2 * math.pi * frequency * i / rate))
                                  for i in range(frames)))
            sound = ctx.buffer_from_pcm(samples, format=AudioFormat.MONO16, sample_rate=rate)
            voices.append(ctx.create_source(buffer=sound, gain=0.5))
        ctx.group(voices).play()
        pcm = device.render(frames)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'chord.wav'
            with wave.open(str(path), 'wb') as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(rate)
                # WAV PCM is little-endian; OpenAL output is native-endian.
                samples = array('h')
                samples.frombytes(pcm)
                import sys
                if sys.byteorder != 'little':
                    samples.byteswap()
                output.writeframes(samples.tobytes())
            print('rendered frames:', frames, 'WAV bytes:', path.stat().st_size)


if __name__ == '__main__':
    main()
