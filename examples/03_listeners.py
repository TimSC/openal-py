"""Listener: the virtual head of the listener in 3D space.

The listener state is global to the process (OpenAL semantics); the
Listener class is just a convenient handle for it.

Run with:  python examples/03_listeners.py
"""
from openal_py import Context, Device, Listener


def main() -> None:
    device = Device.default()
    ctx = Context(device)
    with ctx:
        L = Listener()

        # Where the head is, and which way it faces
        L.position = (0.0, 0.0, 0.0)
        L.direction = (0.0, 0.0, -1.0)   # looking down -z
        L.up = (0.0, 1.0, 0.0)
        print("position:  ", L.position)
        print("direction: ", L.direction)
        print("up:        ", L.up)

        # Moving the listener produces Doppler shifts for sources
        L.velocity = (0.0, 0.0, -5.0)
        print("velocity:  ", L.velocity)

        # Global master volume (1.0 = unchanged)
        L.gain = 0.8
        print("gain:      ", L.gain)

        # A second Listener object sees the same global state
        L2 = Listener()
        print("same state via L2:", L2.position, L2.gain)

        L.gain = 1.0


if __name__ == "__main__":
    main()
