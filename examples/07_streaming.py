"""Queue PCM chunks and reclaim processed buffers in order."""
from openal_py import AudioFormat, Device


def main() -> None:
    with Device.open() as device, device.create_context() as ctx, ctx.activate():
        chunks = [ctx.buffer_from_pcm(b"\0" * 800, format=AudioFormat.MONO8,
                                      sample_rate=8000) for _ in range(3)]
        with ctx.create_source() as source:
            source.queue_buffers(chunks)
            print("queued:", source.buffers_queued)
            source.play()
            # A streaming application periodically unqueues completed chunks,
            # creates new chunks, and queues them. Stop makes every chunk processed.
            source.stop()
            returned = source.unqueue_buffers()
            print("returned in queue order:", returned == chunks)
            print("chunk duration:", chunks[0].duration)
        for chunk in chunks:
            chunk.close()


if __name__ == "__main__":
    main()
