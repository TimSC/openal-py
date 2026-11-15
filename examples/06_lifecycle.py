"""Resource blocks close objects; activation blocks select contexts."""
import gc
import weakref

from openal_py import AudioFormat, Device


def main() -> None:
    with Device.open() as device:
        with device.create_context() as ctx:
            print("resource block does not activate:", ctx.is_current)
            with ctx.activate():
                print("current:", ctx.is_current)
                with device.create_context() as other:
                    with other.activate():
                        print("inner current:", other.is_current)
                    print("outer restored:", ctx.is_current)
                with ctx.buffer_from_pcm(b"\0" * 100, format=AudioFormat.MONO8,
                                         sample_rate=8000) as buffer:
                    with ctx.create_source(buffer=buffer) as source:
                        print("live resources:", source, buffer)
                    print("source closed:", source.closed)
                print("buffer closed:", buffer.closed)

                # The source retains its buffer even without a caller reference.
                buffer = ctx.buffer_from_pcm(b"\0" * 100, format=AudioFormat.MONO8,
                                             sample_rate=8000)
                reference = weakref.ref(buffer)
                source = ctx.create_source(buffer=buffer)
                del buffer
                gc.collect()
                print("attached buffer retained:", reference() is source.buffer)
                source.close()
                gc.collect()
                print("buffer collected:", reference() is None)
            print("activation ended; context still open:", not ctx.closed)
        print("context closed:", ctx.closed)
    print("device closed:", device.closed)


if __name__ == "__main__":
    main()
