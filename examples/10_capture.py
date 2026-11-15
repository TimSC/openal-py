"""List microphones; explicitly pass --record to acquire one second of PCM.

    python examples/10_capture.py
    python examples/10_capture.py --record --seconds 1

No microphone is opened unless --record is supplied.
"""
import argparse
import time

from openal_py import CaptureDevice


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', action='store_true')
    parser.add_argument('--seconds', type=float, default=1.0)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('--seconds must be positive')
    print('capture devices:', CaptureDevice.devices())
    if not args.record:
        return
    with CaptureDevice(sample_rate=16000) as microphone:
        chunks = []
        deadline = time.monotonic() + args.seconds
        with microphone.recording():
            while time.monotonic() < deadline:
                chunks.append(microphone.read())
                time.sleep(0.01)
        chunks.append(microphone.read())
        pcm = b''.join(chunks)
        print('captured frames:', len(pcm) // microphone.format.bytes_per_frame)


if __name__ == '__main__':
    main()
