# openal-py

A modern Python binding for [OpenAL-soft](https://github.com/kcat/openal-soft)
with a pythonic object model.

`openal-py` ships a **platform wheel** with the OpenAL library bundled by default:
install with `pip install openal-py` and no system OpenAL is normally needed.
Builds can omit the bundle and use a system installation instead.

[Read the documentation](https://openal-py.readthedocs.io/).

## Quick start

```python
from openal_py import AudioEngine

with AudioEngine() as audio:
    sound = audio.load("explosion.wav")
    voice = audio.play(sound, position=(2, 0, -5), gain=0.8)
    voice.wait()
```

`AudioEngine` owns playback resources and selects its context automatically. It
runs synchronously on the thread that created it, with no worker thread or hidden
event loop. `load()` returns a reusable `Sound`; `play()` returns a `Voice` and
retains it even when the caller drops the handle. Paths and binary streams can
also be passed directly to `play()`.

Use `sound_from_pcm(data, format=..., sample_rate=...)` for generated PCM.
Sound metadata (`duration`, `sample_rate`, `channels`, `format`, `frame_count`)
and common voice controls (`gain`, `pitch`, `position`, `looping`, `pause()`,
`resume()`, `stop()`) handle activation internally. `master_volume` controls the
engine listener's gain without changing individual voice gains.

Call `audio.update()` in a frame loop to reclaim completed sources. `play()`,
`audio.voices`, playback-state queries, and `Voice.wait()` also reclaim completed
voices. `stop()`/`close()` release a voice; start another playback with `play()`.
Completed voices report `STOPPED`/`finished=True` even after their native source is
released. Engine closure releases voices, sounds, context, and its owned device
in that order. Sound and Voice also support resource blocks. Close an unused
Sound explicitly to release its buffer; active voices must be stopped first.

`wait(timeout=...)` returns `True` for completion or `False` on timeout; a timeout
does not stop playback. Paused/looping voices require a timeout to avoid waiting
forever on the same thread that must control them. The wait polls synchronously
and does not pump UI events. An application's event loop should call `update()`
and inspect `voice.finished` instead of blocking. Loopback playback advances only
when frames are rendered; render them explicitly and call `update()`, or use a
finite wait with an application update hook that drives rendering.

`max_voices` defaults to 64. Completed voices are reaped before enforcing the
limit; reaching it raises `ResourceInUseError` without stealing an existing voice.
Filesystem loads are cached by resolved path and requested format until Sound or
engine closure. Streams are never cached. `load(..., cache=False)` bypasses the
cache to read fresh data without replacing an existing cache entry.

### Extending the engine

The facade deliberately reuses the existing object API:

- Pass `AudioEngine(device=existing_device)` to borrow a device, including a
  `LoopbackDevice`. The engine creates and owns a fresh context but leaves the
  injected device open. Devices opened from names/defaults are owned and closed.
- `with audio.activate() as ctx:` exposes the full managed context for effects,
  listener/acoustic settings, offline rendering, and custom integrations.
- `voice.source` and `sound.buffer` expose the underlying objects. Native calls
  on them require activation; do not manage their lifetimes independently.
- `sound_from_buffer(buffer)` adopts a custom-decoded buffer from this engine's
  context, keeping asset ownership and shutdown behavior consistent.
- Override `update()` (calling `super()`) for application scheduling/refill work.
  Internal reclamation does not invoke this hook, so scheduling a new `play()`
  from an update does not recursively run another application update. Wait polls
  do invoke `update()`. Override `_create_voice(sound, source)` to configure routing before playback
  or return a `Voice` subclass. The hook runs with the engine context current;
  exceptions roll back the new source. Return a voice using the supplied assets.

The engine plays static sounds and streams refilled by `update()`. Voice stealing
and a background audio thread are left to explicit extensions. Operations on an
engine, its sounds, and its voices must run on the creating thread; misuse raises
`ThreadAffinityError`. Engine activations serialize cooperating engines, but raw
OpenAL context manipulation must still be serialized by the application. Use
resource blocks or explicit `close()` for deterministic cleanup.

## Explicit OpenAL API

The underlying interface remains available when direct control is preferable:

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

`buffer.upload_pcm(data, format, sample_rate)` refills an existing native buffer.
Unqueue it from every source first; processed buffers still in a queue and static
attachments cannot be updated. A failed upload retains the prior format metadata.

### Optional streaming helper

`StreamingSource` owns a reusable buffer pool and an OpenAL source. It runs on
its creating thread, requires its context to be current for playback operations,
and advances only when the application calls `update()`. For example:

```python
from openal_py import Device, StreamingSource
import time

with Device() as device, device.create_context() as ctx, ctx.activate():
    with StreamingSource.from_file(ctx, "music.ogg", chunk_frames=8192,
                                   queue_depth=4, looping=False) as stream:
        stream.play()
        while not stream.finished:
            stream.update()
            time.sleep(0.01)  # In a GUI or game, call update() from the frame loop.
```

File streaming uses the optional SoundFile dependency. `format=` chooses PCM
width and `mono=True` averages stereo channels. For dependency-free custom
decoding, pass a `PCMDecoder` to `StreamingSource(ctx, decoder, ...)`: it exposes
`format`, `sample_rate`, `read_frames(n)` and `close()`. Reads return at most `n`
complete native-endian PCM frames; empty data means final EOF. An optional
`rewind()` enables looping. Each read and the PCM pool are bounded by
`chunk_frames` and `queue_depth`; custom decoders must bound their own storage.

`pause()`/`resume()` preserve playback position. `stop()` is terminal;
`finished` specifically reports natural EOF after the queue drains.
`state` distinguishes initial, playing, paused, stopped, finished, error and
closed states. Late updates can starve the native queue; `update()` restarts it
and increments `underrun_count`. `buffered_duration` reports unconsumed audio
seconds before pitch adjustment. Decoder failures close owned resources, retain
the exception in `error`, and re-raise it.

Use a resource block or `close()` even after context shutdown. File decoders
opened by the helper are owned; caller-provided decoders are borrowed unless
`close_decoder=True`. Caller binary streams remain open. `stream.source` exposes
position, gain and effect controls; leave its queue, looping and lifetime to the
helper. Looping rewinds the decoder rather than enabling native source looping.
`AudioEngine.play_stream()` manages this helper for you:

```python
import time
from openal_py import AudioEngine, SoundFileStream

with AudioEngine() as audio, SoundFileStream("music.flac") as stream:
    with audio.play_stream(stream) as voice:
        while voice.active:
            audio.update()
            time.sleep(0.01)
```

Subclass `PCMStream` to supply procedural audio, microphone input, or queued
network audio. Implement fixed `format` and `sample_rate` properties and
`read_frames(count)`, returning at most `count` complete, interleaved native-endian
PCM frames. `b""` means permanent EOF; `None` means temporarily unavailable.
Short reads are supported. Reads must return promptly because they run on the
engine's owning thread; use a bounded producer queue for blocking inputs.
`PCMDecoder` also accepts objects implementing this interface without inheritance.
`SoundFileStream` is the stream-oriented name for `SoundFileDecoder`.

Streaming voices share `max_voices` with static voices and expose `pause()`,
`resume()`, `stop()`/`close()`, `state`, `error`, and `underrun_count`. `active`
remains true while paused or waiting for data. Call `audio.update()` regularly to
refill and reclaim them; there is no background worker. Inputs are borrowed by
default. Set `close_stream=True` to transfer cleanup responsibility after successful
startup. An engine closes transferred inputs on completion, stop, or shutdown.
Seeking and looping remain optional decoder capabilities on `StreamingSource`.

For external native resources, use `Device.from_handle`, `Context.from_handle`,
`Source.from_handle`, or `Buffer.from_handle` with explicit context/device ownership.
Wrappers borrow by default; `owned=True` transfers cleanup responsibility. Borrowed
wrappers do not release native resources on close. The external owner must keep
borrowed handles and their native dependencies alive and release them afterward.
Do not wrap one native resource under multiple owners.

The wheel includes `py.typed` and native extension type stubs. Shared aliases
`AudioFile`, `PCMData`, and `Vector3` describe file inputs, PCM buffers, and vectors.

## Demos

- [openal-explore](https://github.com/TimSC/openal-explore): A PySide6 scene editor and spatial audio demo for `openal-py`. The player stays at the centre while the world scrolls. Audio comes from stationary points or sources travelling along editable polylines.
- [python-quake2](https://github.com/TimSC/python-quake2): A port of the id Software Quake II engine (version 3.21) from C to Python.

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
| `08_offline_rendering.py` | synchronized voices rendered to WAV without audio hardware |
| `09_effects.py` | reverb, filters, effect sends and named parameters |
| `10_capture.py` | microphone discovery; recording requires explicit `--record` |
| `11_audio_engine.py` | simple playback, reusable sounds, voice controls, waiting |
| `12_extending_engine.py` | voice factory and application update hooks |
| `13_streaming_helper.py` | bounded streaming, pause/resume and loopback recovery |
| `14_engine_streaming.py` | custom PCM stream and engine-managed buffer refilling |
| `15_soundfile_pcm_stream.py` | wrap an already-open SoundFile as a borrowed PCM stream |

```sh
python examples/01_quickstart.py
```

The test suite executes every example, so they can't rot.

## Loading audio files

`ctx.load(path_or_file)` loads 8/16-bit mono/stereo WAV without optional dependencies.
It accepts filesystem paths, `PathLike` values, and seekable binary file objects;
caller-owned streams remain open. WAV loading preserves sample width by default.
WAV encodings beyond PCM8/16 (including PCM24 and floating point), FLAC, OGG and
other formats use optional SoundFile. Install:

```sh
pip install openal-py[soundfile]
```

```python
# Inside ctx.activate():
sound = ctx.load("sound.ogg")                  # infer mono/stereo, decode to 16-bit
quiet = ctx.load("stereo.wav", format=AudioFormat.STEREO8)  # explicit width conversion
positional = ctx.load("stereo.wav", mono=True)  # opt-in stereo mean for spatial audio
```

The file's channel count is preserved by default. `mono=True` averages stereo
channels; integer means round down with sufficient intermediate precision. PCM8
is unsigned and centered at 128. An explicit format must match the resulting
channel count, so `mono=True` conflicts with a stereo format. More than two input
channels remain unsupported. Floating-point file samples are scaled to PCM16,
rounded down and clipped; NaN becomes silence and infinities become full scale.
PCM8 conversion then takes the upper eight bits and adds 128.

`mono=True` is also accepted by `AudioEngine.load`, `Buffer.from_wav`,
`Buffer.from_file` and module loading helpers. Engine cache entries distinguish
mono and channel-preserving loads. To play a positional stereo asset through the
engine, use `audio.play(audio.load(path, mono=True), position=(2, 0, -5))`.

`Buffer.from_wav()` and `Buffer.from_file()`
remain available when a particular decoder is needed. `from_wav()` rejects sample
widths other than 8/16-bit; soundfile supports its own broader decoder capabilities.
Seekable binary inputs can start at a nonzero position; that position becomes
the audio file's origin for SoundFile decoding. Automatic WAV format inspection
preserves the position before selecting a decoder.

## Remaining core controls and extensions

The core playback/capture functionality of OpenAL 1.1 is available through managed
objects. Equivalent scalar/vector C variants are consolidated into Python numeric
values and tuples; see the [coverage matrix](docs/API_COVERAGE.md) for scope and
remaining vendor-extension gaps.

Inside `ctx.activate()`, configure `ctx.distance_model` (`DistanceModel`),
`ctx.doppler_factor`, or `ctx.speed_of_sound`. Source properties include `min_gain`,
`max_gain`, `cone_inner_angle`, `cone_outer_angle`, `cone_outer_gain`, and
`source_type`. Set listener forward/up together through `listener.orientation`.
`ctx.group(voices)` retains a group and issues native batch play/pause/stop/rewind
commands. The group does not own or independently close its sources.

`get_parameter()` on contexts, devices, sources, listeners and buffers accepts
integer constants or full names such as `"AL_GAIN"`. Object queries use registered
output shapes; `integer=True` selects integer object results. Context queries use
`kind="float"`, `"double"`, `"int"` or `"bool"`. `set_parameter()` supports native
object parameters, while resource bindings use the managed properties.
`ctx.vendor`, `renderer` and `version`, plus `device.version`, expose implementation
information. Enum lookup and advanced FFI procedure lookup are available through
`enum_value()` and `function_address()`.

With EFX support, create effects, filters and slots:

```python
# Inside ctx.activate():
reverb = ctx.create_effect(EffectType.REVERB, decay_time=1.8)
slot = ctx.create_effect_slot(effect=reverb)
lowpass = ctx.create_filter(FilterType.LOWPASS, gain_hf=0.4)
voice.direct_filter = lowpass
voice.set_send(0, slot)
reverb.parameters["decay_time"] = 2.2
slot.refresh()  # Native slots copy effect parameters.
```

`EffectType` covers all 13 standard effects plus NULL, and `FilterType` covers
lowpass/highpass/bandpass plus NULL. `parameters` is a live, fixed-key mapping;
`configure(**parameters)` applies named settings in order and stops on an error.
Sources retain routed slots and filters. Unbind sends or close their sources before
closing slots. Effect/filter/slot resource blocks follow the same lifetime and
context rules as buffers and sources. EFX source controls include air absorption,
room rolloff, HF cone gain and automatic filter gains; listener scaling is exposed
as `meters_per_unit`.

`LoopbackDevice` renders PCM synchronously without audio hardware. Its
`create_context(sample_rate=..., format=AudioFormat.STEREO16)` selects output
layout; `render(frames)` returns native-endian PCM. Use one live context per
loopback device so another context cannot change the output layout unexpectedly.
See the offline example for writing WAV with the proper byte order.

Capture uses a separate device and does not require a rendering context:

```python
with CaptureDevice(sample_rate=16000) as microphone:
    with microphone.recording():
        # In an application's update loop:
        pcm = microphone.read()  # All currently available frames; does not wait.
```

`read(n)` rejects requests exceeding `available_frames`; sizes are in PCM frames,
not bytes. Supply `buffer_frames` to configure ring capacity. `recording()` restores
previous recording state on exit, including for nested blocks and exceptions.
The capture example only opens a microphone when explicitly run with `--record`.

Optional controls include `buffer.loop_points`, `ctx.deferred_updates()`,
`source.latency` (seconds), `device.timing` (nanoseconds), HRTF status/names and
`device.reset(hrtf=..., hrtf_id=...)`, device reopen, pause and resume. Reset/reopen
can reconfigure an active playback device; actual support depends on the driver.
Dedicated optional interfaces raise `NotImplementedError` if unsupported.

## Design

- **Two-layer architecture**
  - `openal_py._core` — checked Cython wrappers for the Python-facing
    operations, backed by generated native declarations and trampolines.
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

The build requires Meson 1.11 or newer, matching the Python build requirements.
Wheel builds disable OpenAL examples, utilities, and test programs using the
upstream `ALSOFT_EXAMPLES`, `ALSOFT_UTILS`, and `ALSOFT_TESTS` options.

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
tools/build_manylinux_wheels.sh                      # CPython 3.11-3.15
tools/build_manylinux_wheels.sh --python-tags "cp311-cp311 cp312-cp312"
CONTAINER_ENGINE=podman tools/build_manylinux_wheels.sh
```

The script builds `libopenal` from the `openal-soft/` submodule with the
image's own toolchain in a private container workspace, then builds and repairs
one wheel per interpreter. The checkout is mounted read-only; build inputs are
copied without Git metadata, local build trees, or compiled artifacts. A unique
`wheelhouse/manylinux_2_28_x86_64.XXXXXXXX/` output directory is created for each
run (the prefix follows `--image`). Existing wheels and `openal-soft/build` are
preserved, and concurrent runs have separate build and output directories. The
ALSA, PulseAudio, JACK, and PortAudio backends are required. PipeWire is built
if found, but the default image currently supplies headers older than OpenAL
requires. JACK and PortAudio development packages are installed from EPEL, with
PowerTools (AlmaLinux 8) or CRB (9+) enabled for their dependencies. Missing required backends
fail the build instead of silently reducing support. The audio
libraries are not bundled — the backends dlopen them at runtime, so on
systems without them the matching backends are simply unavailable. The
default image is
`quay.io/pypa/manylinux_2_28_x86_64`: openal-soft 1.25 needs C++20 (gcc
11+), which that image's gcc-toolset-14 provides (manylinux2014's gcc 4.8
cannot build it). `--image` picks another policy; missing interpreters
are skipped with a warning.

Run the PowerShell build script on 64-bit Windows with Visual Studio Build
Tools (the C++ workload). CMake must be on PATH when building OpenAL from
source.

Install the Python install manager to provide the `py` command:

```powershell
winget install 9NQ7512CXL7T -e --accept-package-agreements --disable-interactivity
```

Install the 64-bit Python versions you want to build for before running the
script. The default builds require CPython 3.11 through 3.15:

```powershell
py install 3.11 3.12 3.13 3.14 3.15
```

The script checks for these interpreters and installs their build dependencies,
but does not install missing Python versions. From the repository root, run:

```powershell
.\tools\build_windows_wheels.ps1                      # CPython 3.11-3.15
.\tools\build_windows_wheels.ps1 -PythonVersions 3.11,3.12
```

It builds `openal.dll` from the submodule, one `win_amd64` wheel per
version, checks that the wheel contains exactly one `openal_py/openal.dll`,
validates with twine, and collects wheels in a unique `wheelhouse/windows.RUN_ID/`
directory. CMake and Python wheel builds use a private temporary source snapshot,
including when `-OpenAlSource` selects a custom checkout. The development tree and
existing wheels are preserved. `-KeepBuildArtifacts` retains the private workspace
for inspection; otherwise only that invocation's temporary directory is removed.

To bundle an official OpenAL Soft Windows binary distribution instead of building
OpenAL from source:

```powershell
.\tools\build_windows_wheels.ps1 -OpenAlBinaryDistribution "C:\Downloads\openal-soft-1.25.2-bin"
```

This uses the distribution's `include/AL` headers and bundles
`bin/Win64/soft_oal.dll` as `openal_py/openal.dll`. It skips the OpenAL CMake
build; Visual Studio Build Tools are still needed for the Python extension.
`-OpenAlBinaryDistribution` and `-OpenAlSource` are mutually exclusive.

Each script prints its output directory. Select the completed run to validate
and upload (replace the example path below with that printed directory):

```sh
wheel_run="wheelhouse/the-directory-printed-by-the-build"
python3 -m twine check "$wheel_run"/*.whl
python3 -m twine upload "$wheel_run"/*.whl
```

### GitHub Actions builds and publishing

Commit `.github/workflows/wheels.yml` and `tools/wheel_smoke_test.py` along with
any build-script or package changes they depend on. Push the workflow to the
repository's default branch, then open **Actions → Build wheels → Run workflow**.
Choose a platform and Python version, or `all` for Python 3.11–3.15 across Linux
x86_64, Windows x64, and macOS Apple Silicon and Intel. A full run starts 20 build
jobs. An unavailable requested Python version fails its job rather than silently
omitting a wheel. macOS wheels currently target macOS 15 or newer.

The default `artifacts` selection only builds and tests wheels. Download the
`wheels-*` artifacts from the completed run. Windows bundles the checksum-verified
OpenAL Soft 1.25.2 binary release; Linux and macOS compile the submodule. Each job
installs its wheel and checks bundled-library loading, loopback playback, and
streaming completion before uploading an artifact. These are smoke tests, not a
replacement for running the full project test suite.

To enable publishing, create GitHub repository environments named `pypi` and/or
`testpypi`. Configure required reviewers for `pypi` if available. In the corresponding
[PyPI](https://pypi.org/manage/account/publishing/) or
[TestPyPI](https://test.pypi.org/manage/account/publishing/) publishing settings,
add a GitHub Trusted Publisher:

| Field | Value |
| --- | --- |
| Owner | `TimSC` |
| Repository | `openal-py` |
| Workflow filename | `wheels.yml` |
| Environment | `pypi` or `testpypi`, matching the selected service |

For an existing project, add the publisher in that project's publishing settings;
for a new project, register a pending publisher through your account. No API token
is needed. Choose `testpypi` or `pypi` when starting a run to publish the selected
wheels only after every selected build passes. There is no automatic publication
on pushes or tags. Already-published wheel filenames cannot be replaced; update
the project version before publishing a new release. This workflow publishes
wheels only, not a source distribution.
