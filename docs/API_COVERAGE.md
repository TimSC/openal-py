# Python API coverage

The object API follows OpenAL 1.1 functionality rather than duplicating every
C numeric type, scalar/vector spelling, or reserved buffer-parameter form.
The canonical function list is the vendored `openal-soft/registry/xml/al.xml`;
OpenAL 1.1 defines 73 AL and 20 ALC entry points in this registry.

| Core functionality | Python interface |
|---|---|
| Playback device enumeration, default names, open/close | `enumerate_devices()`, `Device.default_name()`, `Device.open()`, resource blocks |
| Context creation, attributes, destruction, current context | `device.create_context()`, `ctx.activate()`, `ctx.make_current()`, `ctx.close()` |
| Processing and suspension | `ctx.process()`, `ctx.suspend()` |
| Errors | Checked calls raise `ALLError`/`ALCError`; `check_al()`/`check_alc()` are explicit checks |
| AL/ALC strings, integer queries, extension checks | Context info properties, device version/spec, `extensions`, `supports()`, `get_parameter()` |
| Enum and function lookup | `ctx.enum_value()`/`function_address()`, device equivalents |
| Global numeric queries and capability enable/disable | `ctx.get_parameter(kind=...)`, `enable()`, `disable()`, `is_enabled()` |
| Distance models and Doppler | `distance_model`, `doppler_factor`, `speed_of_sound`; legacy `doppler_velocity` also available |
| Listener parameters | Position, velocity, gain, direction, up, atomic `orientation`, typed parameter access |
| Source creation, destruction, validation | `ctx.create_source()`, `close()`, validated `Source.from_handle()` |
| Source state, attenuation, cones, gain bounds | Properties including `source_type`, min/max gain, cone angles/gain |
| Playback, individual or batched | Source methods; `ctx.group(sources)` with play/pause/stop/rewind |
| Static buffers, PCM upload and metadata | `ctx.buffer_from_pcm()`, reusable `Buffer.upload_pcm()`, buffer metadata, validated `Buffer.from_handle()` |
| Core parameter access | `get_parameter()`/`set_parameter()` on listener, source and buffer |
| Queued streaming | `queue_buffers()`, `unqueue_buffers()`, queue counts and retained references |
| Optional streaming helper | `StreamingSource`, bounded reusable pool, explicit `update()`, `PCMDecoder` and optional `SoundFileDecoder` |
| Playback offsets | `offset_seconds`, `offset_samples`, `offset_bytes` |
| Capture enumeration/open/start/stop/read/close | `CaptureDevice.devices()`, `default_name()`, `recording()`, `read()`, resource blocks |

Numeric C getters are consolidated into Python numeric results. Object parameter
getters use registered output shapes, so an unknown extension cannot silently
write beyond the allocated output array. Generic setters still obey native OpenAL
validation; the reserved core buffer setters do not create new writable core
parameters. Resource bindings must use object properties and routing methods,
not raw integer setters that would bypass retention and ownership checks.

## Playback facade

`AudioEngine` is a synchronous convenience layer over the same objects. It owns
its context and assets, automatically activates around calls, caches filesystem
loads, retains voices until completion, and releases completed native sources via
`update()`/state queries/waits. It opens and owns a default/named device or borrows
an injected `Device`. `Sound` and `Voice` preserve access to native wrappers via
explicit activation. Owning-thread checks raise `ThreadAffinityError` before
native work. The `update()` and `_create_voice()` hooks permit application-level
extensions without reproducing context/resource management. No additional native
entry points or automatic streaming backend are introduced by the facade.

## Optional extensions

| Extension family | Interface |
|---|---|
| EFX standard effects, including EAX reverb | `EffectType`, `Effect`, `ctx.create_effect()`, named `parameters` mappings |
| EFX lowpass/highpass/bandpass filters | `FilterType`, `Filter`, `ctx.create_filter()` |
| EFX auxiliary slots and routing | `AuxiliaryEffectSlot`, `ctx.create_effect_slot()`, `source.direct_filter`, `set_send()`/`get_send()` |
| EFX source/listener controls | Air absorption, room rolloff, cone HF gain, automatic filter gain controls, `listener.meters_per_unit` |
| `ALC_SOFT_loopback` | `LoopbackDevice`, format checks, synchronous `render(frames)` |
| `AL_SOFT_loop_points` | `buffer.loop_points` |
| `AL_SOFT_deferred_updates` | Nested, exception-safe `ctx.deferred_updates()` |
| `AL_SOFT_source_latency` | `source.latency`, reported in seconds |
| `ALC_SOFT_device_clock` | `device.timing`, reported in nanoseconds |
| `ALC_SOFT_HRTF` | HRTF names, current status/name, `reset(hrtf=..., hrtf_id=...)` |
| `ALC_SOFT_reopen_device` | `device.reopen()` |
| `ALC_SOFT_pause_device` | `device.pause()`, `device.resume()` |

Check `ctx.supports()` or `device.supports()` for optional features. Dedicated
extension interfaces raise `NotImplementedError` when unavailable. Extension
functions may be resolved through OpenAL's procedure lookup, not just shared
library exports; procedure-only addresses are refreshed for the current context
or device rather than reused across potentially different drivers.

This is **not complete coverage of every vendor extension** in the registry.
Native callback registration, debug/event callbacks, callback buffers, foldback,
specialized compressed/sample-buffer APIs, and the direct-context extension
families still need specialized Python wrappers. `function_address()` provides an
advanced FFI escape hatch, not automatic argument, pointer, or callback lifetime
management. Prefer the managed APIs where available.

## Validation limits

Tests exercise real playback through the null backend, deterministic loopback PCM,
all standard EFX parameter schemas, routing, lifecycle failures, and procedure-only
symbol resolution. Capture's Python behavior is tested against a deterministic
backend, and invalid native counts/formats are tested without opening hardware.
Real microphone capture and platform-specific drivers require separate hardware
validation. Passing tests are not a full OpenAL conformance certification.
