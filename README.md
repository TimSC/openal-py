# openal-py

A modern Python binding for [OpenAL-soft](https://github.com/kcat/openal-soft)
with a pythonic object model.

`openal-py` ships a **platform wheel** with the OpenAL library bundled inside
it: install with `pip install openal-py` and no system OpenAL is needed.

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
- **Bundled library** — the shared library is installed next to the
  extension and dlopen'd at import time. Override with the
  `OPENAL_PY_LIBRARY` environment variable.
- **Generated bindings** — `_al_api.pxd`, `_api_table.c` and `_constants.py`
  are generated from `registry/xml/al.xml` (the same canonical source that
  generates the C headers) by `codegen/generate_api.py`. Regenerate with:

  ```sh
  python3 codegen/generate_api.py
  ```

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
