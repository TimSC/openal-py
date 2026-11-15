"""Device discovery, capabilities, and explicit resource ownership."""
from openal_py import Device, enumerate_devices


def main() -> None:
    for name in enumerate_devices():
        print("available:", name)
    with Device.open() as device:
        name = device.spec
        print("default:", name)
        print("attributes:", device.attributes)
        print("ALC extensions:", sorted(device.extensions))
        with device.create_context(sample_rate=48000) as ctx, ctx.activate():
            print("AL extensions:", sorted(ctx.extensions))
            print("float32 samples supported:", ctx.supports("AL_EXT_FLOAT32"))
    print("closed:", device.closed, ctx.closed)
    with Device.open(name) as reopened:
        print("opened by name:", reopened.spec)


if __name__ == "__main__":
    main()
