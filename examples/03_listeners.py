"""Listener: the virtual head of the listener in 3D space.

Each context has its own listener state. Listener objects bind to one
context and require it to be current.

Run with:  python examples/03_listeners.py
"""
from openal_py import Context, Device, Listener


def main() -> None:
    device = Device.default()
    ctx = Context(device)
    with ctx:
        L = ctx.listener

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

        # Context master volume (1.0 = unchanged)
        L.gain = 0.8
        print("gain:      ", L.gain)

        # A second Listener object bound to this context sees the same state
        L2 = Listener()
        print("same state via L2:", L2.position, L2.gain)

        L.gain = 1.0


if __name__ == "__main__":
    main()
