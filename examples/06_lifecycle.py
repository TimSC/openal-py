"""Lifecycle: context managers, explicit delete, and garbage collection.

Run with:  python examples/06_lifecycle.py
"""
import gc

from openal_py import AudioFormat, Buffer, Context, Device


def main() -> None:
    device = Device.default()

    # --- context manager makes current / clears on exit -------------------
    ctx = Context(device)
    print("current on entry? ", end="")
    with ctx:
        print(ctx.is_current)
    print("current on exit?  ", ctx.is_current)

    # --- explicit delete ----------------------------------------------------
    with ctx:
        buf = Buffer.from_pcm(ctx, b"\x00" * 100, AudioFormat.MONO8, 8000)
        src = ctx.create_source(buffer=buf)
        print("before delete: src.handle =", src.handle)
        src.delete()
        print("after delete:  src.handle =", src.handle, "| repr:", repr(src))
        buf.delete()

    # --- garbage collection --------------------------------------------------
    # When a wrapper is dropped, its C handle is released automatically
    # (even if the context is already gone -- no crashes, no leaks).
    with ctx:
        src2 = ctx.create_source()
        buf2 = Buffer.from_pcm(ctx, b"\x00" * 100, AudioFormat.MONO8, 8000)
        src2.buffer = buf2
        h_src, h_buf = src2.handle, buf2.handle
        del src2, buf2
        gc.collect()
        from openal_py import _core
        print("GC released source?", not _core.is_source(h_src))
        print("GC released buffer?", not _core.is_buffer(h_buf))

    ctx.destroy()
    device.close()


if __name__ == "__main__":
    main()
