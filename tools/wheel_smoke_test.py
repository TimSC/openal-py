"""Exercise an installed bundled wheel without requiring playback hardware."""
from array import array
from pathlib import Path

import openal_py as al


def main() -> None:
    library = Path(al.library_path()).resolve()
    assert library.is_file(), library
    assert library.parent == Path(al.__file__).resolve().parent, library
    print('Loaded bundled OpenAL:', library, al.get_library_version())

    device = al.LoopbackDevice()
    with device, al.AudioEngine(device, sample_rate=48000) as audio:
        sound = audio.sound_from_pcm(array('h', [6000] * 4800),
                                     format=al.AudioFormat.MONO16, sample_rate=48000)
        audio.play(sound, looping=True)
        with audio.activate():
            pcm = device.render(480)
        assert any(pcm), 'Loopback playback produced only zero bytes'
        audio.stop_all()

        class Input(al.PCMStream):
            format = al.AudioFormat.MONO16
            sample_rate = 48000

            def __init__(self) -> None:
                self.remaining = 4800

            def read_frames(self, frames: int) -> bytes:
                count = min(frames, self.remaining)
                self.remaining -= count
                return array('h', [6000] * count).tobytes()

        voice = audio.play_stream(Input(), chunk_frames=480)
        for _ in range(100):
            with audio.activate():
                device.render(240)
            audio.update()
            if not voice.active:
                break
        assert not voice.active, 'Streaming playback did not finish'
        assert voice.state is al.StreamState.FINISHED, voice.state
    print('Installed-wheel smoke tests passed')


if __name__ == '__main__':
    main()
