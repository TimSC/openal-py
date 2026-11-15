"""Devices: enumeration, inspection, and opening by name.

Run with:  python examples/02_devices.py
"""
from openal_py import Device, enumerate_devices


def main() -> None:
    # All available device names (usually one per audio backend)
    for name in enumerate_devices():
        print("available:", name)

    dev = Device.default()
    print("\ndefault device:")
    print("  spec:", dev.spec)
    print("  attributes:", dev.attributes)
    print("  ALC extensions:")
    for ext in dev.extensions:
        print("   -", ext)
    dev.close()

    # Open a specific device by name; the handle is independent of default()
    name = Device.default().spec
    dev2 = Device.open(name)
    print("\nreopened by name:", dev2.spec)
    dev2.close()

    # Devices are context managers too
    with Device.default() as d:
        print("\ncontext-manager device:", d.spec)


if __name__ == "__main__":
    main()
