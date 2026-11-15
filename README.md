# openal-py

A modern Python binding for [OpenAL-soft](https://github.com/kcat/openal-soft)
with a pythonic object model.

`openal-py` ships a **platform wheel** with the OpenAL library bundled by default:
install with `pip install openal-py` and no system OpenAL is normally needed.
Builds can omit the bundle and use a system installation instead.

## Quick start

```python
from openal_py import Device, Context, Buffer, AudioFormat

device = Device.default()
ctx = Context(device)

with ctx:  # makes the context current
    # 100 ms of silence
    data = b"\x00" * 4410  # mono 16-bit @ 44.1 kHz
    buf = Buffer.from_pcm(ctx, data, AudioFormat.MONO16, 44100)

    src = ctx.create_source(buffer=buf, gain=0.8)
    src.play()
    import time
    time.sleep(0.2)
    src.stop()
```

## Context ownership and cleanup

Source, buffer, and listener operations require their owning context to be
current. Use `with ctx:` around playback and parameter access; nested blocks
restore the previous context, including when an exception is raised.
`ctx.listener` returns a listener bound to `ctx`. `Listener()` binds to the
current managed context at construction and keeps that binding when contexts
switch. Operations on deleted objects or destroyed contexts raise `RuntimeError`.

A source retains its attached buffer until the buffer is replaced, unbound with
`source.buffer = None`, or the source is deleted. Assigning a buffer from a
different context or a deleted buffer raises `ValueError`.

`source.delete()` and `buffer.delete()` temporarily activate their owning context
for cleanup and restore the previous context. Failed deletion keeps the handle
available for retry. Explicitly destroy contexts before closing their devices;
`with ctx:` controls which context is current and does not destroy it on exit.

`AudioFormat` is an `IntEnum`; plain integer OpenAL format constants are also
accepted. WAV loading supports 8/16-bit mono/stereo PCM and rejects other sample
widths. The optional soundfile loader converts samples to unsigned PCM when an
8-bit format is requested.

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
| `06_lifecycle.py` | context managers, explicit delete, GC behavior |

```sh
python examples/01_quickstart.py
```

The test suite executes every example, so they can't rot.

## Loading audio files

`Buffer.from_wav()` covers WAV with no dependencies. For FLAC, OGG Vorbis,
Opus, MP3 and friends, install the optional `soundfile` dependency:

```sh
pip install openal-py[soundfile]
```

```python
buf = openal_py.Buffer.from_file(ctx, "sound.ogg")  # mono 16-bit
buf = openal_py.Buffer.from_file(ctx, "sound.ogg", openal_py.AudioFormat.STEREO16)
```

The file's channel count must match the format (no downmixing).

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
