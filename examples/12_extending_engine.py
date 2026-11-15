"""Extend voice setup and application updates while reusing engine ownership."""
from openal_py import AudioEngine, AudioFormat, Sound, Source, Voice


class RelativeEngine(AudioEngine):
    """Example policy: all voices are positioned relative to the listener."""

    def __init__(self) -> None:
        self.updates = 0
        super().__init__()

    def _create_voice(self, sound: Sound, source: Source) -> Voice:
        # This hook runs before playback, with the engine context current.
        # Attach filters/sends here or return an application-specific Voice subclass.
        source.relative = True
        return super()._create_voice(sound, source)

    def update(self) -> int:
        self.updates += 1
        # Add application-specific scheduling or refill work here.
        return super().update()


def main() -> None:
    with RelativeEngine() as audio:
        sound = audio.sound_from_pcm(b'\0' * 160, format=AudioFormat.MONO16, sample_rate=8000)
        voice = audio.play(sound, position=(1, 0, 0))
        voice.wait(timeout=2)
        print('application updates:', audio.updates)


if __name__ == '__main__':
    main()
