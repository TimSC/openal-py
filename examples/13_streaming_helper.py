"""Drive bounded streaming synchronously using hardware-independent rendering."""
from array import array

from openal_py import AudioFormat, LoopbackDevice, StreamingSource


class ToneDecoder:
    """A small dependency-free example of the PCMDecoder interface."""

    format = AudioFormat.MONO16
    sample_rate = 48000

    def __init__(self) -> None:
        self.remaining = 4800

    def read_frames(self, frames: int) -> bytes:
        count = min(frames, self.remaining)
        self.remaining -= count
        return array('h', [6000] * count).tobytes()

    def close(self) -> None:
        pass


def main() -> None:
    device = LoopbackDevice()
    with device, device.create_context() as ctx, ctx.activate():
        with StreamingSource(ctx, ToneDecoder(), chunk_frames=480, queue_depth=3,
                             close_decoder=True) as stream:
            stream.play()
            stream.pause()
            device.render(480)
            stream.resume()
            # Deliberately miss a refill deadline, then recover.
            device.render(1920)
            stream.update()
            while not stream.finished:
                device.render(240)
                stream.update()
            print('Natural completion; underruns:', stream.underrun_count)


if __name__ == '__main__':
    main()
