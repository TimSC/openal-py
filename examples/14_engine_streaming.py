"""A custom PCMStream with bounded, engine-managed streaming buffers."""
from array import array

from openal_py import AudioEngine, AudioFormat, LoopbackDevice, PCMStream


class ToneStream(PCMStream):
    @property
    def format(self) -> AudioFormat:
        return AudioFormat.MONO16

    @property
    def sample_rate(self) -> int:
        return 48000

    def __init__(self) -> None:
        self.remaining = 4800

    def read_frames(self, frames: int) -> bytes:
        count = min(frames, self.remaining)
        self.remaining -= count
        return array('h', [6000] * count).tobytes()


def main() -> None:
    # Loopback makes the example runnable without audio hardware. With a normal
    # AudioEngine(), pump update() in your application loop as audio plays.
    device = LoopbackDevice()
    with device, AudioEngine(device, sample_rate=48000) as audio:
        with ToneStream() as stream, audio.play_stream(stream, chunk_frames=480) as voice:
            while voice.active:
                with audio.activate():
                    device.render(240)
                audio.update()
            print('Stream complete:', voice.state.value)


if __name__ == '__main__':
    main()
