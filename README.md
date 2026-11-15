# openal-py

A modern Python binding for [OpenAL-soft](https://github.com/kcat/openal-soft)
with a pythonic object model.

`openal-py` ships a **platform wheel** with the OpenAL library bundled by default:
install with `pip install openal-py` and no system OpenAL is normally needed.
Builds can omit the bundle and use a system installation instead.

## Quick start

```python
import time
from openal_py import Device, AudioFormat

with Device.open() as device, device.create_context(sample_rate=48000) as ctx:
    with ctx.activate():
        # 100 ms of mono 16-bit silence at 44.1 kHz
        sound = ctx.buffer_from_pcm(
            b"\x00" * 8820, format=AudioFormat.MONO16, sample_rate=44100,
        )
        voice = ctx.create_source(buffer=sound, gain=0.8, position=(2, 0, -5))
        voice.play()
        time.sleep(0.2)
        voice.stop()
```

## Resource lifetime and activation

`with device:` and `with ctx:` manage lifetime and call `close()` on exit.
A context resource block does **not** make it current. Use `with ctx.activate():`
for playback, creation, and parameter access. Nested activation restores the
previous context, including on exceptions. Closing a context releases its native
sources and buffers; their wrappers then report `closed=True` and `handle=None`.

All resources have an idempotent `close()` and a `closed` property. Sources and
buffers also support resource blocks and expose their owning `context`.
`delete()` on sources/buffers and `destroy()` on contexts are aliases for `close()`.
Close contexts before their device; closing a device with live managed contexts
raises `ResourceInUseError`. Source and buffer cleanup temporarily activates their
context and restores the previous one, even when called outside an activation
block. Native deletion failures retain the handle for retry.

`ctx.listener` is bound to `ctx`; `Listener()` binds to the current managed
context at construction. Positions, velocities, and directions accept arbitrary
three-element numeric sequences, including arrays. Representations never query
native playback state, so `repr()` is safe outside an activation block and after
closure. Inspect `source.state` explicitly when playback state is needed.

`ResourceClosedError` and `ContextNotCurrentError` are `LifecycleError` subclasses
(and `RuntimeError` subclasses), separate from native `ALLError`/`ALCError`.
Assigning buffers across contexts raises `ContextMismatchError`, a `ValueError`.
`ctx.extensions`/`ctx.supports(name)` inspect AL capabilities;
`device.extensions`/`device.supports(name)` inspect ALC capabilities. Extension
collections are immutable sets and depend on the selected implementation.

## Creation and playback

`device.create_context(sample_rate=48000)` requests a context sample rate; the
device may negotiate a different rate. Advanced attributes can be supplied as an
`attributes` mapping of ALC constant names or integer values.

`ctx.create_source()` has explicit keyword parameters: `buffer`, `gain`, `pitch`,
`position`, `velocity`, `direction`, `looping`, `relative`, `reference_distance`,
`max_distance`, and `rolloff_factor`. The same properties remain mutable afterward.
A source retains its attached buffer until replacement, unbinding with
`source.buffer = None`, or source closure. Buffers must share the source's context.

Use `play()`, `pause()`, `stop()`, and `rewind()` for playback control. Rewind
returns the source to `SourceState.INITIAL`. Seek with `offset_seconds`,
`offset_samples`, or `offset_bytes`; playback offsets follow OpenAL's source state
rules and are most useful while playing or paused.

For streaming, queue compatible chunks and reclaim processed entries:

```python
# Inside ctx.activate(), with chunks created in this context:
source = ctx.create_source()
source.queue_buffers(chunks)
source.play()
# On subsequent updates:
completed = source.unqueue_buffers()  # all processed entries, in order
# Replenish with source.queue_buffers(new_chunks) as needed.
```

`buffers_queued` and `buffers_processed` report queue counts. `unqueue_buffers(n)`
requests an explicit count and raises if entries are not yet processed. Queued
buffers are retained, including duplicate entries, until unqueued or source
closure. A failed queue/unqueue leaves references and native queue unchanged.
`source.buffer` describes a static attachment and returns `None` for streaming
sources. Queue chunks must have compatible formats and sample rates.

Buffers expose `sample_rate`, `channels`, `bits`, `format`, `size` (bytes),
`frame_count`, and `duration` (seconds). `frequency` aliases `sample_rate`.
`AudioFormat` is an `IntEnum` with `channels`, `bits`, and `bytes_per_frame`.
`ctx.buffer_from_pcm()` accepts buffer-protocol objects, including `bytes`,
`bytearray`, `memoryview`, and numeric arrays, containing interleaved native-endian
PCM. Plain OpenAL integer formats are accepted for extension formats.

For external native resources, use `Device.from_handle`, `Context.from_handle`,
`Source.from_handle`, or `Buffer.from_handle` with explicit context/device ownership.
Wrappers borrow by default; `owned=True` transfers cleanup responsibility. Borrowed
wrappers do not release native resources on close. The external owner must keep
borrowed handles and their native dependencies alive and release them afterward.
Do not wrap one native resource under multiple owners.

The wheel includes `py.typed` and native extension type stubs. Shared aliases
`AudioFile`, `PCMData`, and `Vector3` describe file inputs, PCM buffers, and vectors.

## Examples

Runnable examples live in `examples/` (also shipped inside the wheel at
`openal_py/examples/`). Each one is a complete script:

| Example | What it shows |
|---|---|
| `01_quickstart.py` | device → context → buffer → play a sine tone |
| `02_devices.py` | enumeration, attributes, opening by name |
| `03_listeners.py` | position, orientation, velocity, gain |
| `04_buffers.py` | raw PCM, stereo, WAV, and any format via optional `soundfile` |
| `05_sources.py` | parameters, state machine, simultaneous voices |
| `06_lifecycle.py` | resource lifetime, activation, retained buffers, GC |
| `07_streaming.py` | queued PCM chunks and processed-buffer reclamation |

```sh
python examples/01_quickstart.py
```

The test suite executes every example, so they can't rot.

## Loading audio files

`ctx.load(path_or_file)` loads 8/16-bit mono/stereo WAV without optional dependencies.
It accepts filesystem paths, `PathLike` values, and seekable binary file objects;
caller-owned streams remain open. WAV loading preserves sample width by default.
For FLAC, OGG and other formats supported by libsndfile, install:

```sh
pip install openal-py[soundfile]
```

```python
# Inside ctx.activate():
sound = ctx.load("sound.ogg")                  # infer mono/stereo, decode to 16-bit
quiet = ctx.load("stereo.wav", format=AudioFormat.STEREO8)  # explicit width conversion
```

The file's channel count is preserved. An explicit format must match that channel
count; loading never silently downmixes. `Buffer.from_wav()` and `Buffer.from_file()`
remain available when a particular decoder is needed. `from_wav()` rejects sample
widths other than 8/16-bit; soundfile supports its own broader decoder capabilities.

## Design

- **Two-layer architecture**
  - `openal_py._core` — a thin, typed Cython extension that wraps every
    function in `al.h` / `alc.h` with exact C types. No Python semantics.
  - `openal_py` — plain Python classes (`Device`, `Context`, `Buffer`,
    `Source`, `Listener`) that provide the pythonic API.
- **Runtime library selection** — prefer the bundled shared library when it
  detects playback devices, otherwise try system OpenAL. The extension has no
  link-time dependency on OpenAL. Set `OPENAL_PY_LIBRARY` to explicitly select
  an implementation.
- **Generated bindings** — `_al_api.pxd`, `_api_table.c` and `_constants.py`
  are generated from `registry/xml/al.xml` (the same canonical source that
  generates the C headers) by `codegen/generate_api.py`. Regenerate with:

  ```sh
  python3 codegen/generate_api.py
  ```

## Bundling and system OpenAL

`bundle_openal` is a Meson boolean option, default **ON**. Disable it for a
system-library-only installation or wheel:

```sh
pip install . -Csetup-args=-Dbundle_openal=false
pip wheel . -Csetup-args=-Dbundle_openal=false
# Or configure Meson directly:
meson setup build -Dbundle_openal=false
```

With bundling OFF, only the vendored OpenAL headers are needed to build the
binding; building the OpenAL shared library first is unnecessary. With bundling
ON, `openal_libdir` supplies the shared library to install alongside the extension.

At import, the binding tries:

1. `OPENAL_PY_LIBRARY`, if set. This is authoritative; an invalid override raises
   `ImportError` without silently selecting another implementation.
2. The bundled library, if present and loadable, when playback-device enumeration
   detects at least one device.
3. System OpenAL, using platform discovery and conventional loader names
   (`libopenal.so.1` on Linux, `OpenAL32.dll` on Windows, and OpenAL dylib/framework
   locations on macOS).

If system OpenAL is unavailable but the bundle loads without detecting playback
devices, retain the bundle for headless/loopback use. If neither library loads,
import raises `ImportError` with the attempted library names. No playback device
is opened during import. Enumeration is the backend-detection signal; a listed
device may still fail to open later, for example if permissions change.

The chosen implementation stays fixed for the process so existing handles never
cross between libraries. `openal_py.library_path()` identifies the selected path
or loader name. Optional functions missing from a system implementation raise
`NotImplementedError` when called.

## Development

The OpenAL-soft source is a git submodule at `openal-soft/`. Build it first
(CMake, with whatever audio backends you want — `ENABLE_NULL` is enough for
headless development):

```sh
git submodule update --init --recursive
cmake -S openal-soft -B openal-soft/build -DCMAKE_BUILD_TYPE=Release -DENABLE_NULL=ON
cmake --build openal-soft/build
```

Then build and test the binding:

```sh
meson setup build
meson compile -C build
meson install -C build --destdir /tmp/opy
PYTHONPATH=/tmp/opy/usr/local/lib/python3/dist-packages pytest tests/
mypy
```

The bundled library location is configurable via the `openal_libdir` meson
option (default: `openal-soft/build`).

Building a wheel:

```sh
pip wheel . -w dist/
```

## Building wheels for PyPI

PyPI does not accept generic `linux_x86_64` wheels, so the Linux wheels are
built inside a manylinux container and repaired with `auditwheel`:

```sh
tools/build_manylinux_wheels.sh                      # CPython 3.10-3.13
tools/build_manylinux_wheels.sh --python-tags "cp311-cp311 cp312-cp312"
CONTAINER_ENGINE=podman tools/build_manylinux_wheels.sh
```

The script builds `libopenal` from the `openal-soft/` submodule with the
image's own toolchain (into `openal-soft/build`, the meson default), then
builds and repairs one wheel per interpreter into `wheelhouse/`. The
ALSA and PulseAudio backends are required, and PipeWire is built if found
(their dev packages are installed from the image's repos; its pipewire is
too old for openal-soft, so the backend is currently absent). The audio
libraries are not bundled — the backends dlopen them at runtime, so on
systems without them the matching backends are simply unavailable. The
default image is
`quay.io/pypa/manylinux_2_28_x86_64`: openal-soft 1.25 needs C++20 (gcc
11+), which that image's gcc-toolset-14 provides (manylinux2014's gcc 4.8
cannot build it). `--image` picks another policy; missing interpreters
are skipped with a warning.

Windows wheels are built natively (64-bit Windows, Visual Studio Build
Tools, CMake and the `py` launcher):

```powershell
.\tools\build_windows_wheels.ps1                      # CPython 3.10-3.14
.\tools\build_windows_wheels.ps1 -PythonVersions 3.11,3.12
```

It builds `openal.dll` from the submodule, one `win_amd64` wheel per
version, checks that the wheel contains exactly one `openal_py/openal.dll`,
validates with twine, and collects everything in `wheelhouse/`.

Validate and upload:

```sh
python3 -m twine check wheelhouse/*.whl
python3 -m twine upload wheelhouse/*.whl
```
