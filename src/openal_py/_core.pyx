"""Thin Cython core: typed, error-checked wrappers over the OpenAL C API.

The actual function bodies live in the (bundled) libopenal shared library.
All calls go through the generated _api_table trampolines, which resolves
symbols via dlopen at import time:
  - default: the bundled library installed next to this module
  - override: $OPENAL_PY_LIBRARY pointing at any libopenal.so

This module is deliberately un-pythonic. Build object models on top
(openal_py.source, openal_py.buffer, ...).
"""
# cython: language_level=3
from libc.stdint cimport int64_t
from libc.stdlib cimport calloc, free
from cpython cimport PyLong_AsVoidPtr

cdef extern from "stddef.h":
    void* NULL

cimport _al_api

# Re-expose C types unqualified (functions are called via _al_api).
cdef extern from "AL/alc.h":
    ctypedef struct ALCdevice "ALCdevice"
    ctypedef struct ALCcontext "ALCcontext"
    ctypedef int ALCint
    ctypedef int ALCenum
    ctypedef char ALCboolean

cdef extern from "AL/al.h":
    ctypedef unsigned int ALuint
    ctypedef int ALint
    ctypedef int ALsizei
    ctypedef int ALenum
    ctypedef float ALfloat
    ctypedef char ALchar
    ctypedef char ALbyte
    ctypedef void ALvoid

from openal_py._errors import ALLError, ALCError


cdef inline void* _ptr(object h):
    """Convert an integer handle (or None) to a raw C pointer."""
    if h is None:
        return NULL
    return <void*> PyLong_AsVoidPtr(h)


cdef inline ALCdevice* _dev(object d):
    return <ALCdevice*> _ptr(d)


cdef inline ALCcontext* _ctx(object c):
    return <ALCcontext*> _ptr(c)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def _bundled_lib_path() -> bytes:
    """Path of the libopenal bundled next to this extension module."""
    import os
    import platform
    cdef bytes base
    base = os.path.dirname(os.path.abspath(__file__)).encode("utf-8")
    system = platform.system().lower()
    if system == "windows":
        name = b"openal.dll"
    elif system == "darwin":
        name = b"libopenal.1.dylib"
    else:
        name = b"libopenal.so.1"
    return base + b"/" + name


def _init():
    """Resolve OpenAL symbols. Called at import time."""
    import os
    cdef const char* path = NULL
    cdef bytes lib_bytes
    lib = os.environ.get("OPENAL_PY_LIBRARY")
    if lib:
        lib_bytes = lib.encode("utf-8")
        path = lib_bytes
    else:
        lib_bytes = _bundled_lib_path()
        path = lib_bytes
    if not _al_api.openal_py_init(path):
        raise ImportError(
            "openal_py: failed to initialize OpenAL library"
            + (f" ({lib})" if lib else f" ({lib_bytes.decode()})")
        )


_init()


def library_path() -> str:
    """Path (or description) of the OpenAL library in use."""
    cdef const char* p = _al_api.openal_py_library_path()
    return p.decode("utf-8") if p != NULL else ""


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

cdef inline void _check_al() except *:
    cdef ALenum e = _al_api.alGetError()
    if e != 0:
        raise ALLError(e)


cdef inline void _check_alc(object device) except *:
    cdef ALenum e = _al_api.alcGetError(_dev(device))
    if e != 0:
        raise ALCError(e)


# Public aliases (the Python layer uses these names for deferred checks).
check_al = _check_al
check_alc = _check_alc


# ---------------------------------------------------------------------------
# Strings / info
# ---------------------------------------------------------------------------

cdef inline str _cstr(const ALchar* s) except *:
    if s == NULL:
        return None
    return s.decode("utf-8")


def get_library_version() -> tuple:
    """(major, minor) ALC version of the loaded library."""
    cdef ALCint major, minor

    _al_api.alcGetIntegerv(<ALCdevice*> NULL, 0x1000, 1, &major)   # ALC_MAJOR_VERSION
    _al_api.alcGetIntegerv(<ALCdevice*> NULL, 0x1001, 1, &minor)   # ALC_MINOR_VERSION
    _check_alc(None)
    return (major, minor)


def get_device_spec(device) -> str:
    s = _cstr(_al_api.alcGetString(_dev(device), 0x1005))  # ALC_DEVICE_SPECIFIER
    _check_alc(device)
    return s


def get_alc_extensions(device=None) -> list:
    """ALC extensions for a device (or the default device)."""
    _check_alc(device)
    s = _cstr(_al_api.alcGetString(_dev(device), 0x1006))  # ALC_EXTENSIONS
    return s.split() if s else []


def get_extensions() -> list:
    """OpenAL extensions available in the current context."""
    _check_al()
    s = _cstr(_al_api.alGetString(0xB004))  # AL_EXTENSIONS
    return s.split() if s else []


def get_string(pname) -> str:
    """alGetString for the current context (None if unavailable)."""
    s = _cstr(_al_api.alGetString(<ALenum> pname))
    _check_al()
    return s


def alc_get_string(device, pname) -> str:
    """Raw alcGetString string (may contain NUL separators)."""
    s = _cstr(_al_api.alcGetString(_dev(device), <ALCenum> pname))
    _check_alc(device)
    return s


def is_extension_present(name: str) -> bool:
    """Check an AL extension (requires a current context)."""
    _check_al()
    cdef bytes b = name.encode("ascii")
    return _al_api.alIsExtensionPresent(b)


def is_alc_extension_present(name: str, device=None) -> bool:
    _check_alc(device)
    cdef bytes b = name.encode("ascii")
    return _al_api.alcIsExtensionPresent(_dev(device), b)


# ---------------------------------------------------------------------------
# Devices (ALC)
# ---------------------------------------------------------------------------

def enumerate_devices() -> list:
    """Names of available devices (null-separated list from ALC)."""
    s = _cstr(_al_api.alcGetString(<ALCdevice*> NULL, 0x1013))  # ALC_ALL_DEVICES_SPECIFIER
    _check_alc(None)
    return [d for d in (s or "").split("\x00") if d]


def open_device(name: str | None = None) -> int:
    """Open a device. Returns the device handle (an integer)."""
    cdef ALCdevice* dev
    cdef bytes name_bytes
    cdef const ALchar* n = NULL
    if name:
        name_bytes = name.encode("ascii")
        n = name_bytes
    dev = _al_api.alcOpenDevice(n)
    if dev == NULL:
        raise ALCError(-1)
    return <unsigned long long> dev


def close_device(device) -> None:
    _al_api.alcCloseDevice(_dev(device))
    _check_alc(None)


# ---------------------------------------------------------------------------
# Contexts (ALC)
# ---------------------------------------------------------------------------

def create_context(device, attributes: dict | None = None) -> int:
    """Create a context. `attributes` maps ALC pname -> int value."""
    cdef ALCint* attrs = NULL
    cdef ALCcontext* ctx
    cdef Py_ssize_t n, i
    if attributes:
        n = len(attributes)
        attrs = <ALCint*> calloc(2 * n + 1, 4)
        i = 0
        for k, v in attributes.items():
            attrs[2 * i] = <ALCint> k
            attrs[2 * i + 1] = <ALCint> v
            i += 1
    ctx = _al_api.alcCreateContext(_dev(device), attrs)
    if attrs != NULL:
        free(attrs)
    if ctx == NULL:
        _check_alc(device)
        raise ALCError(-1)
    return <unsigned long long> ctx


def make_context_current(context: int | None) -> bool:
    """Make a context current (pass None to clear). Returns success."""
    cdef ALCboolean ok = _al_api.alcMakeContextCurrent(_ctx(context))
    _check_alc(None)
    return ok != 0


def process_context(context) -> None:
    _al_api.alcProcessContext(_ctx(context))
    _check_alc(None)


def suspend_context(context) -> None:
    _al_api.alcSuspendContext(_ctx(context))
    _check_alc(None)


def destroy_context(context) -> None:
    _al_api.alcDestroyContext(_ctx(context))
    _check_alc(None)


def get_current_context() -> int:
    cdef ALCcontext* c = _al_api.alcGetCurrentContext()
    return <unsigned long long> c


def get_contexts_device(context) -> int:
    cdef ALCdevice* d = _al_api.alcGetContextsDevice(_ctx(context))
    _check_alc(None)
    return <unsigned long long> d


def is_context(context) -> bool:
    """True if `context` is a live context handle."""
    cdef ALCdevice* d = _al_api.alcGetContextsDevice(_ctx(context))
    return d != NULL


def get_integer(device, pname) -> int:
    """Query a device attribute (via alcGetIntegerv)."""
    cdef ALCint v
    _al_api.alcGetIntegerv(_dev(device), <ALCenum> pname, 1, &v)
    _check_alc(device)
    return v


def get_integerv(device, pname, n: int = 1) -> list:
    """Query several device attributes (via alcGetIntegerv)."""
    cdef ALCint* buf = <ALCint*> calloc(n, 4)
    cdef int64_t i
    try:
        _al_api.alcGetIntegerv(_dev(device), <ALCenum> pname, <ALsizei> n, buf)
        _check_alc(device)
        return [buf[i] for i in range(n)]
    finally:
        free(buf)


# ---------------------------------------------------------------------------
# Listener (AL)
# ---------------------------------------------------------------------------

cdef inline bint _all_ints(object v):
    cdef int64_t i
    for i in range(len(v)):
        if not isinstance(v[i], (int, bool)) or isinstance(v[i], float):
            return False
    return True


def listener_set(pname, value) -> None:
    cdef ALenum p = <ALenum> pname
    cdef ALfloat buf6[6]
    cdef int64_t i
    try:
        if isinstance(value, (int, bool)) and not isinstance(value, float):
            _al_api.alListeneri(p, <ALint> value)
        elif isinstance(value, float):
            _al_api.alListenerf(p, <ALfloat> value)
        elif isinstance(value, (tuple, list)) and len(value) == 3 and _all_ints(value):
            _al_api.alListener3i(p, <ALint> value[0], <ALint> value[1], <ALint> value[2])
        elif isinstance(value, (tuple, list)) and len(value) == 3:
            _al_api.alListener3f(p, <ALfloat> value[0], <ALfloat> value[1], <ALfloat> value[2])
        elif isinstance(value, (tuple, list)) and len(value) == 6:
            # e.g. AL_ORIENTATION: (dirX, dirY, dirZ, upX, upY, upZ)
            for i in range(6):
                buf6[i] = <ALfloat> value[i]
            _al_api.alListenerfv(p, buf6)
        else:
            raise TypeError(f"listener_set: unsupported value for {pname!r}")
    finally:
        _check_al()


def listener_get(pname, n: int = 1):
    cdef ALenum p = <ALenum> pname
    cdef ALfloat a, b, c, v
    cdef ALfloat buf6[6]
    try:
        if n == 3:
            _al_api.alGetListener3f(p, &a, &b, &c)
            _check_al()
            return (a, b, c)
        if n == 6:
            _al_api.alGetListenerfv(p, buf6)
            _check_al()
            return tuple(float(buf6[i]) for i in range(6))
        _al_api.alGetListenerf(p, &v)
        _check_al()
        return v
    except ALLError:
        raise


# ---------------------------------------------------------------------------
# Sources (AL)
# ---------------------------------------------------------------------------

def gen_sources(n: int = 1) -> list:
    cdef int64_t count = <int64_t> n
    cdef ALuint* arr = <ALuint*> calloc(count, 4)
    try:
        _al_api.alGenSources(count, arr)
        _check_al()
        return [arr[i] for i in range(count)]
    finally:
        free(arr)


def delete_sources(sources) -> None:
    cdef int64_t n = len(sources)
    cdef int64_t i
    cdef ALuint* arr = <ALuint*> calloc(n, 4)
    try:
        for i in range(n):
            arr[i] = <ALuint> sources[i]
        _al_api.alDeleteSources(<ALsizei> n, arr)
        _check_al()
    finally:
        free(arr)


def is_source(source) -> bool:
    _check_al()
    return _al_api.alIsSource(<ALuint> source) != 0


def source_play(source) -> None:
    _al_api.alSourcePlay(<ALuint> source)
    _check_al()


def source_pause(source) -> None:
    _al_api.alSourcePause(<ALuint> source)
    _check_al()


def source_stop(source) -> None:
    _al_api.alSourceStop(<ALuint> source)
    _check_al()


def source_set(source, pname, value) -> None:
    """Set a source parameter: scalar float/int, or 1/3-tuple."""
    cdef ALuint s = <ALuint> source
    cdef ALenum p = <ALenum> pname
    try:
        if isinstance(value, (int, bool)) and not isinstance(value, float):
            _al_api.alSourcei(s, p, <ALint> value)
        elif isinstance(value, float):
            _al_api.alSourcef(s, p, <ALfloat> value)
        elif isinstance(value, (tuple, list)) and len(value) == 1:
            _al_api.alSourcef(s, p, <ALfloat> value[0])
        elif isinstance(value, (tuple, list)) and len(value) == 3 and _all_ints(value):
            _al_api.alSource3i(s, p, <ALint> value[0], <ALint> value[1], <ALint> value[2])
        elif isinstance(value, (tuple, list)) and len(value) == 3:
            _al_api.alSource3f(s, p, <ALfloat> value[0], <ALfloat> value[1], <ALfloat> value[2])
        else:
            raise TypeError(f"source_set: unsupported value for {pname!r}")
    finally:
        _check_al()


def source_get(source, pname, n: int = 1):
    """Get a source parameter (1 -> float, 3 -> tuple)."""
    cdef ALuint s = <ALuint> source
    cdef ALenum p = <ALenum> pname
    cdef ALfloat a, b, c, v
    try:
        if n == 3:
            _al_api.alGetSource3f(s, p, &a, &b, &c)
            _check_al()
            return (a, b, c)
        _al_api.alGetSourcef(s, p, &v)
        _check_al()
        return v
    except ALLError:
        raise


def source_geti(source, pname) -> int:
    cdef ALint v
    _al_api.alGetSourcei(<ALuint> source, <ALenum> pname, &v)
    _check_al()
    return v


def source_queue_buffers(source, buffers) -> None:
    cdef int64_t n = len(buffers)
    cdef int64_t i
    cdef ALuint* arr = <ALuint*> calloc(n, 4)
    try:
        for i in range(n):
            arr[i] = <ALuint> buffers[i]
        _al_api.alSourceQueueBuffers(<ALuint> source, <ALsizei> n, arr)
        _check_al()
    finally:
        free(arr)


def source_unqueue_buffers(source, n: int) -> list:
    cdef int64_t i
    cdef ALuint* arr = <ALuint*> calloc(n, 4)
    try:
        _al_api.alSourceUnqueueBuffers(<ALuint> source, <ALsizei> n, arr)
        _check_al()
        return [arr[i] for i in range(n)]
    finally:
        free(arr)


# ---------------------------------------------------------------------------
# Buffers (AL)
# ---------------------------------------------------------------------------

def gen_buffers(n: int = 1) -> list:
    cdef int64_t count = <int64_t> n
    cdef ALuint* arr = <ALuint*> calloc(count, 4)
    try:
        _al_api.alGenBuffers(count, arr)
        _check_al()
        return [arr[i] for i in range(count)]
    finally:
        free(arr)


def delete_buffers(buffers) -> None:
    cdef int64_t n = len(buffers)
    cdef int64_t i
    cdef ALuint* arr = <ALuint*> calloc(n, 4)
    try:
        for i in range(n):
            arr[i] = <ALuint> buffers[i]
        _al_api.alDeleteBuffers(<ALsizei> n, arr)
        _check_al()
    finally:
        free(arr)


def is_buffer(buffer) -> bool:
    _check_al()
    return _al_api.alIsBuffer(<ALuint> buffer) != 0


def buffer_data(buffer, format: int, data: bytes, frequency: int) -> None:
    """Fill a buffer with raw PCM sample data (bytes)."""
    cdef int64_t size = len(data)
    _al_api.alBufferData(
        <ALuint> buffer, <ALenum> format, <const ALchar*> data,
        <ALsizei> size, <ALint> frequency)
    _check_al()


def buffer_geti(buffer, pname) -> int:
    cdef ALint v
    _al_api.alGetBufferi(<ALuint> buffer, <ALenum> pname, &v)
    _check_al()
    return v


# ---------------------------------------------------------------------------
# Global AL state
# ---------------------------------------------------------------------------

def get_float(pname) -> float:
    cdef ALfloat v = _al_api.alGetFloat(<ALenum> pname)
    _check_al()
    return v


def get_int(pname) -> int:
    cdef ALint v = _al_api.alGetInteger(<ALenum> pname)
    _check_al()
    return v


def speed_of_sound(value: float) -> None:
    _al_api.alSpeedOfSound(<ALfloat> value)
    _check_al()


def doppler_factor(value: float) -> None:
    _al_api.alDopplerFactor(<ALfloat> value)
    _check_al()


def doppler_velocity(value: float) -> None:
    _al_api.alDopplerVelocity(<ALfloat> value)
    _check_al()


def distance_model(model) -> None:
    _al_api.alDistanceModel(<ALenum> model)
    _check_al()


# ---------------------------------------------------------------------------
# Pollable error codes (in addition to the check-and-raise above)
# ---------------------------------------------------------------------------

def get_error() -> int:
    """alGetError: return (and clear) the last AL error code."""
    return _al_api.alGetError()


def alc_get_error(device) -> int:
    """alcGetError: return (and clear) the last ALC error code."""
    return _al_api.alcGetError(_dev(device))


# ---------------------------------------------------------------------------
# EFX (AL_EXT_EFX)
# ---------------------------------------------------------------------------

def gen_effects(n: int = 1) -> list:
    cdef int64_t count = <int64_t> n
    cdef ALuint* arr = <ALuint*> calloc(count, 4)
    try:
        _al_api.alGenEffects(count, arr)
        _check_al()
        return [arr[i] for i in range(count)]
    finally:
        free(arr)


def delete_effects(effects) -> None:
    cdef int64_t n = len(effects)
    cdef int64_t i
    cdef ALuint* arr = <ALuint*> calloc(n, 4)
    try:
        for i in range(n):
            arr[i] = <ALuint> effects[i]
        _al_api.alDeleteEffects(<ALsizei> n, arr)
        _check_al()
    finally:
        free(arr)


def effect_set(effect, pname, value) -> None:
    """Set an effect parameter: scalar float/int, or a float list."""
    cdef ALuint e = <ALuint> effect
    cdef ALenum p = <ALenum> pname
    cdef ALfloat* buf
    cdef int64_t n, i
    try:
        if isinstance(value, (int, bool)) and not isinstance(value, float):
            _al_api.alEffecti(e, p, <ALint> value)
        elif isinstance(value, float):
            _al_api.alEffectf(e, p, <ALfloat> value)
        elif isinstance(value, (tuple, list)):
            n = len(value)
            buf = <ALfloat*> calloc(n, 4)
            for i in range(n):
                buf[i] = <ALfloat> value[i]
            _al_api.alEffectfv(e, p, buf)
            free(buf)
        else:
            raise TypeError(f"effect_set: unsupported value for {pname!r}")
    finally:
        _check_al()


def gen_filters(n: int = 1) -> list:
    cdef int64_t count = <int64_t> n
    cdef ALuint* arr = <ALuint*> calloc(count, 4)
    try:
        _al_api.alGenFilters(count, arr)
        _check_al()
        return [arr[i] for i in range(count)]
    finally:
        free(arr)


def delete_filters(filters) -> None:
    cdef int64_t n = len(filters)
    cdef int64_t i
    cdef ALuint* arr = <ALuint*> calloc(n, 4)
    try:
        for i in range(n):
            arr[i] = <ALuint> filters[i]
        _al_api.alDeleteFilters(<ALsizei> n, arr)
        _check_al()
    finally:
        free(arr)


def filter_set(f, pname, value) -> None:
    """Set a filter parameter: scalar float/int, or a float list."""
    cdef ALuint flt = <ALuint> f
    cdef ALenum p = <ALenum> pname
    cdef ALfloat* buf
    cdef int64_t n, i
    try:
        if isinstance(value, (int, bool)) and not isinstance(value, float):
            _al_api.alFilteri(flt, p, <ALint> value)
        elif isinstance(value, float):
            _al_api.alFilterf(flt, p, <ALfloat> value)
        elif isinstance(value, (tuple, list)):
            n = len(value)
            buf = <ALfloat*> calloc(n, 4)
            for i in range(n):
                buf[i] = <ALfloat> value[i]
            _al_api.alFilterfv(flt, p, buf)
            free(buf)
        else:
            raise TypeError(f"filter_set: unsupported value for {pname!r}")
    finally:
        _check_al()


def gen_auxiliary_effect_slots(n: int = 1) -> list:
    cdef int64_t count = <int64_t> n
    cdef ALuint* arr = <ALuint*> calloc(count, 4)
    try:
        _al_api.alGenAuxiliaryEffectSlots(count, arr)
        _check_al()
        return [arr[i] for i in range(count)]
    finally:
        free(arr)


def delete_auxiliary_effect_slots(slots) -> None:
    cdef int64_t n = len(slots)
    cdef int64_t i
    cdef ALuint* arr = <ALuint*> calloc(n, 4)
    try:
        for i in range(n):
            arr[i] = <ALuint> slots[i]
        _al_api.alDeleteAuxiliaryEffectSlots(<ALsizei> n, arr)
        _check_al()
    finally:
        free(arr)


def auxiliary_effect_slot_set(slot, pname, value) -> None:
    """Set an auxiliary effect slot parameter: scalar float/int, or a float list."""
    cdef ALuint sl = <ALuint> slot
    cdef ALenum p = <ALenum> pname
    cdef ALfloat* buf
    cdef int64_t n, i
    try:
        if isinstance(value, (int, bool)) and not isinstance(value, float):
            _al_api.alAuxiliaryEffectSloti(sl, p, <ALint> value)
        elif isinstance(value, float):
            _al_api.alAuxiliaryEffectSlotf(sl, p, <ALfloat> value)
        elif isinstance(value, (tuple, list)):
            n = len(value)
            buf = <ALfloat*> calloc(n, 4)
            for i in range(n):
                buf[i] = <ALfloat> value[i]
            _al_api.alAuxiliaryEffectSlotfv(sl, p, buf)
            free(buf)
        else:
            raise TypeError(f"auxiliary_effect_slot_set: unsupported value for {pname!r}")
    finally:
        _check_al()
