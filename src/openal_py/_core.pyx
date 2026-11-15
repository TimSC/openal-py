"""Thin Cython core: typed, error-checked wrappers over the OpenAL C API.

The actual function bodies live in the selected OpenAL shared library.
All calls go through generated _api_table trampolines, resolving symbols at
import time from the bundle, a system implementation, or OPENAL_PY_LIBRARY.

This module is deliberately un-pythonic. Build object models on top
(openal_py.source, openal_py.buffer, ...).
"""
# cython: language_level=3
from libc.stdint cimport int64_t
from libc.stddef cimport size_t
from libc.limits cimport INT_MAX
from operator import index
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


cdef inline Py_ssize_t _count(object value) except -1:
    value = index(value)
    if value < 0 or value > INT_MAX:
        raise ValueError("count must be between 0 and INT_MAX")
    return value


cdef void* _allocate(object count, size_t item_size) except NULL:
    cdef Py_ssize_t n = _count(count)
    cdef void* result
    if n > (<size_t>-1) // item_size:
        raise OverflowError("allocation size overflow")
    # A non-null allocation also makes zero-count native calls safe.
    result = calloc(max(n, 1), item_size)
    if result == NULL:
        raise MemoryError()
    return result


cdef void _vector_length(object pname, object value, Py_ssize_t expected) except *:
    if isinstance(value, (tuple, list)):
        if len(value) != expected:
            raise ValueError(f"parameter {pname!r} requires {expected} component(s)")
    elif expected != 1:
        raise ValueError(f"parameter {pname!r} requires {expected} component(s)")


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


def _load_library(path, require_devices=False):
    import os
    cdef bytes encoded = os.fsencode(path)
    return bool(_al_api.openal_py_init(encoded, require_devices))


def _init():
    """Choose a library once, before any native handles exist."""
    from openal_py._loader import initialize
    initialize(_bundled_lib_path(), _load_library)


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
    cdef ALCenum param = 0x1005
    if _al_api.alcIsExtensionPresent(NULL, b"ALC_ENUMERATE_ALL_EXT"):
        param = 0x1013
    elif not _al_api.alcIsExtensionPresent(NULL, b"ALC_ENUMERATION_EXT"):
        name = _cstr(_al_api.alcGetString(NULL, 0x1004))
        _check_alc(None)
        return [name] if name else []
    cdef const char* names = _al_api.alcGetString(NULL, param)
    _check_alc(None)
    result = []
    if names != NULL:
        while names[0] != 0:
            name_bytes = <bytes> names
            result.append(name_bytes.decode("utf-8"))
            names += len(name_bytes) + 1
    return result


def open_device(name: str | None = None) -> int:
    """Open a device. Returns the device handle (an integer)."""
    cdef ALCdevice* dev
    cdef bytes name_bytes
    cdef const ALchar* n = NULL
    if name:
        name_bytes = name.encode("utf-8")
        n = name_bytes
    dev = _al_api.alcOpenDevice(n)
    if dev == NULL:
        raise ALCError(-1)
    return <unsigned long long> dev


def close_device(device) -> None:
    if not _al_api.alcCloseDevice(_dev(device)):
        raise ALCError(0xA001)  # ALC_INVALID_DEVICE


# ---------------------------------------------------------------------------
# Contexts (ALC)
# ---------------------------------------------------------------------------

def create_context(device, attributes: dict | None = None) -> int:
    """Create a context. `attributes` maps ALC pname -> int value."""
    cdef ALCint* attrs = NULL
    cdef ALCcontext* ctx
    cdef Py_ssize_t n, i
    try:
        if attributes:
            n = len(attributes)
            attrs = <ALCint*> _allocate(2 * n + 1, sizeof(ALCint))
            for i, (k, v) in enumerate(attributes.items()):
                attrs[2 * i] = <ALCint> k
                attrs[2 * i + 1] = <ALCint> v
        ctx = _al_api.alcCreateContext(_dev(device), attrs)
    finally:
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
    cdef ALCint* buf = <ALCint*> _allocate(n, sizeof(ALCint))
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
    if not isinstance(value, (int, float, bool)):
        value = tuple(value)
    _vector_length(pname, value, 6 if pname == 0x100F else (3 if pname in (0x1004, 0x1006) else 1))
    cdef ALenum p = <ALenum> pname
    cdef ALfloat buf6[6]
    cdef int64_t i
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
    _check_al()


def listener_get(pname, n: int = 1):
    expected = 6 if pname == 0x100F else (3 if pname in (0x1004, 0x1006) else 1)
    if n != expected:
        raise ValueError(f"parameter requires {expected} component(s)")
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
    cdef int64_t count = _count(n)
    cdef ALuint* arr = <ALuint*> _allocate(count, sizeof(ALuint))
    try:
        _al_api.alGenSources(count, arr)
        _check_al()
        return [arr[i] for i in range(count)]
    finally:
        free(arr)


def delete_sources(sources) -> None:
    cdef int64_t n = len(sources)
    cdef int64_t i
    cdef ALuint* arr = <ALuint*> _allocate(n, sizeof(ALuint))
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


def source_rewind(source) -> None:
    _al_api.alSourceRewind(<ALuint> source)
    _check_al()


def source_set(source, pname, value) -> None:
    """Set a source parameter: scalar float/int, or 1/3-tuple."""
    if not isinstance(value, (int, float, bool)):
        value = tuple(value)
    _vector_length(pname, value, 3 if pname in (0x1004, 0x1005, 0x1006, 0x20006) else 1)
    cdef ALuint s = <ALuint> source
    cdef ALenum p = <ALenum> pname
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
    _check_al()


def source_get(source, pname, n: int = 1):
    """Get a source parameter (1 -> float, 3 -> tuple)."""
    cdef ALuint s = <ALuint> source
    cdef ALenum p = <ALenum> pname
    if n not in (1, 3):
        raise ValueError("n must be 1 or 3")
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
    cdef ALuint* arr = <ALuint*> _allocate(n, sizeof(ALuint))
    try:
        for i in range(n):
            arr[i] = <ALuint> buffers[i]
        _al_api.alSourceQueueBuffers(<ALuint> source, <ALsizei> n, arr)
        _check_al()
    finally:
        free(arr)


def source_unqueue_buffers(source, n: int) -> list:
    cdef int64_t i
    cdef ALuint* arr = <ALuint*> _allocate(n, sizeof(ALuint))
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
    cdef int64_t count = _count(n)
    cdef ALuint* arr = <ALuint*> _allocate(count, sizeof(ALuint))
    try:
        _al_api.alGenBuffers(count, arr)
        _check_al()
        return [arr[i] for i in range(count)]
    finally:
        free(arr)


def delete_buffers(buffers) -> None:
    cdef int64_t n = len(buffers)
    cdef int64_t i
    cdef ALuint* arr = <ALuint*> _allocate(n, sizeof(ALuint))
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
    cdef int64_t size = _count(len(data))
    if frequency <= 0 or frequency > INT_MAX:
        raise ValueError("frequency must be between 1 and INT_MAX")
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

cdef void _require_symbol(bytes name, object device=None) except *:
    if not _al_api.openal_py_has_symbol(name, _dev(device)):
        raise NotImplementedError(f"loaded OpenAL does not provide {name.decode('ascii')}")


def gen_effects(n: int = 1) -> list:
    _require_symbol(b"alGenEffects")
    cdef int64_t count = _count(n)
    cdef ALuint* arr = <ALuint*> _allocate(count, sizeof(ALuint))
    try:
        _al_api.alGenEffects(count, arr)
        _check_al()
        return [arr[i] for i in range(count)]
    finally:
        free(arr)


def delete_effects(effects) -> None:
    _require_symbol(b"alDeleteEffects")
    cdef int64_t n = len(effects)
    cdef int64_t i
    cdef ALuint* arr = <ALuint*> _allocate(n, sizeof(ALuint))
    try:
        for i in range(n):
            arr[i] = <ALuint> effects[i]
        _al_api.alDeleteEffects(<ALsizei> n, arr)
        _check_al()
    finally:
        free(arr)


def effect_set(effect, pname, value) -> None:
    """Set an effect parameter: scalar float/int, or a float list."""
    _require_symbol(b"alGetEffecti")
    _require_symbol(b"alEffecti")
    _require_symbol(b"alEffectf")
    _require_symbol(b"alEffectfv")
    cdef ALuint e = <ALuint> effect
    cdef ALenum p = <ALenum> pname
    cdef ALfloat* buf = NULL
    cdef int64_t n, i
    cdef ALint effect_type
    expected = 1
    if pname in (0x000B, 0x000E):
        _al_api.alGetEffecti(e, 0x8001, &effect_type)
        _check_al()
        if effect_type == 0x8000:  # AL_EFFECT_EAXREVERB
            expected = 3
    _vector_length(pname, value, expected)
    try:
        if isinstance(value, (int, bool)) and not isinstance(value, float):
            _al_api.alEffecti(e, p, <ALint> value)
        elif isinstance(value, float):
            _al_api.alEffectf(e, p, <ALfloat> value)
        elif isinstance(value, (tuple, list)):
            n = len(value)
            buf = <ALfloat*> _allocate(n, sizeof(ALfloat))
            for i in range(n):
                buf[i] = <ALfloat> value[i]
            _al_api.alEffectfv(e, p, buf)
        else:
            raise TypeError(f"effect_set: unsupported value for {pname!r}")
    finally:
        free(buf)
    _check_al()


def gen_filters(n: int = 1) -> list:
    _require_symbol(b"alGenFilters")
    cdef int64_t count = _count(n)
    cdef ALuint* arr = <ALuint*> _allocate(count, sizeof(ALuint))
    try:
        _al_api.alGenFilters(count, arr)
        _check_al()
        return [arr[i] for i in range(count)]
    finally:
        free(arr)


def delete_filters(filters) -> None:
    _require_symbol(b"alDeleteFilters")
    cdef int64_t n = len(filters)
    cdef int64_t i
    cdef ALuint* arr = <ALuint*> _allocate(n, sizeof(ALuint))
    try:
        for i in range(n):
            arr[i] = <ALuint> filters[i]
        _al_api.alDeleteFilters(<ALsizei> n, arr)
        _check_al()
    finally:
        free(arr)


def filter_set(f, pname, value) -> None:
    """Set a filter parameter: scalar float/int, or a float list."""
    _require_symbol(b"alFilteri")
    _require_symbol(b"alFilterf")
    _require_symbol(b"alFilterfv")
    cdef ALuint flt = <ALuint> f
    cdef ALenum p = <ALenum> pname
    cdef ALfloat* buf = NULL
    cdef int64_t n, i
    _vector_length(pname, value, 1)
    try:
        if isinstance(value, (int, bool)) and not isinstance(value, float):
            _al_api.alFilteri(flt, p, <ALint> value)
        elif isinstance(value, float):
            _al_api.alFilterf(flt, p, <ALfloat> value)
        elif isinstance(value, (tuple, list)):
            n = len(value)
            buf = <ALfloat*> _allocate(n, sizeof(ALfloat))
            for i in range(n):
                buf[i] = <ALfloat> value[i]
            _al_api.alFilterfv(flt, p, buf)
        else:
            raise TypeError(f"filter_set: unsupported value for {pname!r}")
    finally:
        free(buf)
    _check_al()


def gen_auxiliary_effect_slots(n: int = 1) -> list:
    _require_symbol(b"alGenAuxiliaryEffectSlots")
    cdef int64_t count = _count(n)
    cdef ALuint* arr = <ALuint*> _allocate(count, sizeof(ALuint))
    try:
        _al_api.alGenAuxiliaryEffectSlots(count, arr)
        _check_al()
        return [arr[i] for i in range(count)]
    finally:
        free(arr)


def delete_auxiliary_effect_slots(slots) -> None:
    _require_symbol(b"alDeleteAuxiliaryEffectSlots")
    cdef int64_t n = len(slots)
    cdef int64_t i
    cdef ALuint* arr = <ALuint*> _allocate(n, sizeof(ALuint))
    try:
        for i in range(n):
            arr[i] = <ALuint> slots[i]
        _al_api.alDeleteAuxiliaryEffectSlots(<ALsizei> n, arr)
        _check_al()
    finally:
        free(arr)


def auxiliary_effect_slot_set(slot, pname, value) -> None:
    """Set an auxiliary effect slot parameter: scalar float/int, or a float list."""
    _require_symbol(b"alAuxiliaryEffectSloti")
    _require_symbol(b"alAuxiliaryEffectSlotf")
    _require_symbol(b"alAuxiliaryEffectSlotfv")
    cdef ALuint sl = <ALuint> slot
    cdef ALenum p = <ALenum> pname
    cdef ALfloat* buf = NULL
    cdef int64_t n, i
    _vector_length(pname, value, 1)
    try:
        if isinstance(value, (int, bool)) and not isinstance(value, float):
            _al_api.alAuxiliaryEffectSloti(sl, p, <ALint> value)
        elif isinstance(value, float):
            _al_api.alAuxiliaryEffectSlotf(sl, p, <ALfloat> value)
        elif isinstance(value, (tuple, list)):
            n = len(value)
            buf = <ALfloat*> _allocate(n, sizeof(ALfloat))
            for i in range(n):
                buf[i] = <ALfloat> value[i]
            _al_api.alAuxiliaryEffectSlotfv(sl, p, buf)
        else:
            raise TypeError(f"auxiliary_effect_slot_set: unsupported value for {pname!r}")
    finally:
        free(buf)
    _check_al()


# Remaining core operations and optional extensions. All allocations use counts
# checked before narrowing to native integer types.

def enum_value(name: str, device=None, alc=False) -> int:
    cdef bytes encoded = name.encode('ascii')
    cdef int value
    if alc:
        value = _al_api.alcGetEnumValue(_dev(device), encoded)
        _check_alc(device)
    else:
        value = _al_api.alGetEnumValue(encoded)
        _check_al()
    return value


def function_address(name: str, device=None, alc=False):
    cdef bytes encoded = name.encode('ascii')
    cdef void* address
    if alc:
        address = _al_api.alcGetProcAddress(_dev(device), encoded)
        _check_alc(device)
    else:
        address = _al_api.alGetProcAddress(encoded)
        _check_al()
    return <size_t>address if address != NULL else None


def capability(pname, enabled=None):
    if enabled is None:
        result = bool(_al_api.alIsEnabled(pname))
    elif enabled:
        _al_api.alEnable(pname)
        result = None
    else:
        _al_api.alDisable(pname)
        result = None
    _check_al()
    return result


def global_parameter(pname, kind='float'):
    if kind == 'float':
        result = float(_al_api.alGetFloat(pname))
    elif kind == 'double':
        result = float(_al_api.alGetDouble(pname))
    elif kind == 'int':
        result = int(_al_api.alGetInteger(pname))
    elif kind == 'bool':
        result = bool(_al_api.alGetBoolean(pname))
    else:
        raise ValueError('kind must be float, double, int, or bool')
    _check_al()
    return result


def source_batch(sources, operation):
    cdef Py_ssize_t n = _count(len(sources))
    cdef ALuint* handles = <ALuint*>_allocate(n, sizeof(ALuint))
    try:
        for i in range(n):
            handles[i] = sources[i]
        if operation == 'play':
            _al_api.alSourcePlayv(n, handles)
        elif operation == 'pause':
            _al_api.alSourcePausev(n, handles)
        elif operation == 'stop':
            _al_api.alSourceStopv(n, handles)
        elif operation == 'rewind':
            _al_api.alSourceRewindv(n, handles)
        else:
            raise ValueError('invalid batch operation')
        _check_al()
    finally:
        free(handles)


def object_parameter(kind, handle, pname, integer=False):
    """Query core object parameters with arity determined by their AL enum."""
    cdef ALint ints[6]
    cdef ALfloat floats[6]
    cdef int n = 1
    allowed = {
        'listener': {0x1004, 0x1006, 0x100A, 0x100F, 0x20004},
        'source': {0x202, 0x1001, 0x1002, 0x1003, 0x1004, 0x1005, 0x1006, 0x1007,
                   0x1009, 0x100A, 0x100D, 0x100E, 0x1010, 0x1015, 0x1016,
                   0x1020, 0x1021, 0x1022, 0x1023, 0x1024, 0x1025, 0x1026, 0x1027,
                   0x20007, 0x20008, 0x20009, 0x2000A, 0x2000B, 0x2000C},
        'buffer': {0x2001, 0x2002, 0x2003, 0x2004, 0x2015},
    }
    if kind not in allowed or pname not in allowed[kind]:
        raise ValueError('parameter has no registered safe output shape')
    if kind == 'listener':
        n = 6 if pname == 0x100f else (3 if pname in (0x1004, 0x1006) else 1)
        if integer:
            _al_api.alGetListeneriv(pname, ints)
        else:
            _al_api.alGetListenerfv(pname, floats)
    elif kind == 'source':
        n = 3 if pname in (0x1004, 0x1005, 0x1006) else 1
        if integer:
            _al_api.alGetSourceiv(handle, pname, ints)
        else:
            _al_api.alGetSourcefv(handle, pname, floats)
    elif kind == 'buffer':
        n = 2 if pname == 0x2015 else 1  # AL_LOOP_POINTS_SOFT
        if integer:
            _al_api.alGetBufferiv(handle, pname, ints)
        else:
            _al_api.alGetBufferfv(handle, pname, floats)
    else:
        raise ValueError('invalid object kind')
    _check_al()
    return (ints[0] if integer else floats[0]) if n == 1 else tuple(
        ints[i] if integer else floats[i] for i in range(n))


def buffer_set(buffer, pname, value):
    cdef ALint points[2]
    cdef ALuint h = buffer
    cdef ALenum p = pname
    if pname == 0x2015:  # AL_LOOP_POINTS_SOFT
        _vector_length(pname, value, 2)
        points[0], points[1] = index(value[0]), index(value[1])
        _al_api.alBufferiv(h, p, points)
    elif isinstance(value, (int, bool)):
        _al_api.alBufferi(h, p, value)
    elif isinstance(value, float):
        _al_api.alBufferf(h, p, value)
    else:
        raise TypeError('buffer parameter requires a scalar or loop point pair')
    _check_al()


def capture_devices():
    cdef const char* names = _al_api.alcGetString(NULL, 0x310)
    _check_alc(None)
    result = []
    if names != NULL:
        while names[0]:
            name = <bytes>names
            result.append(name.decode('utf-8'))
            names += len(name) + 1
    return result


# Capture's native API cannot query its frame size. Remember the validated
# format at open time; callers cannot provide a smaller output allocation.
_capture_sizes = {}


def capture_open(name, sample_rate, format, buffer_frames):
    cdef int rate = _count(sample_rate)
    cdef int frames = _count(buffer_frames)
    if rate == 0 or frames == 0:
        raise ValueError('sample_rate and buffer_frames must be positive')
    sizes = {0x1100: 1, 0x1101: 2, 0x1102: 2, 0x1103: 4}
    if format not in sizes:
        raise ValueError('capture requires a mono/stereo 8/16-bit format')
    cdef bytes encoded
    cdef const char* n = NULL
    if name is not None:
        encoded = name.encode('utf-8')
        n = encoded
    cdef ALCdevice* device = _al_api.alcCaptureOpenDevice(n, rate, format, frames)
    if device == NULL:
        _check_alc(None)
        raise ALCError(-1)
    handle = <size_t>device
    try:
        _capture_sizes[handle] = sizes[format]
    except BaseException:
        _al_api.alcCaptureCloseDevice(device)
        raise
    return handle


def capture_close(device):
    if not _al_api.alcCaptureCloseDevice(_dev(device)):
        raise ALCError(0xA001)
    _capture_sizes.pop(device, None)


def capture_start(device):
    _al_api.alcCaptureStart(_dev(device))
    _check_alc(device)


def capture_stop(device):
    _al_api.alcCaptureStop(_dev(device))
    _check_alc(device)


def capture_available(device):
    return get_integer(device, 0x312)


def capture_read(device, frames):
    cdef int n = _count(frames)
    if device not in _capture_sizes:
        raise ValueError('capture device was not opened by this binding')
    if n > capture_available(device):
        raise ValueError('requested more capture frames than available')
    cdef Py_ssize_t size = _count(n * _capture_sizes[device])
    cdef char* data = <char*>_allocate(size, sizeof(char))
    try:
        if n:
            _al_api.alcCaptureSamples(_dev(device), data, n)
            _check_alc(device)
        return data[:size]
    finally:
        free(data)


def loopback_open(name=None):
    _require_symbol(b'alcLoopbackOpenDeviceSOFT')
    cdef bytes encoded
    cdef const char* n = NULL
    if name is not None:
        encoded = name.encode('utf-8')
        n = encoded
    cdef ALCdevice* device = _al_api.alcLoopbackOpenDeviceSOFT(n)
    if device == NULL:
        _check_alc(None)
        raise ALCError(-1)
    return <size_t>device


def loopback_supported(device, sample_rate, channels, sample_type):
    _require_symbol(b'alcIsRenderFormatSupportedSOFT', device)
    cdef int rate = _count(sample_rate)
    result = bool(_al_api.alcIsRenderFormatSupportedSOFT(_dev(device), rate, channels, sample_type))
    _check_alc(device)
    return result


def loopback_render(device, frames):
    _require_symbol(b'alcRenderSamplesSOFT', device)
    cdef int n = _count(frames)
    channels = get_integer(device, 0x1990)
    sample_type = get_integer(device, 0x1991)
    channel_sizes = {0x1500: 1, 0x1501: 2, 0x1503: 4, 0x1504: 6, 0x1505: 7, 0x1506: 8}
    sample_sizes = {0x1400: 1, 0x1401: 1, 0x1402: 2, 0x1403: 2, 0x1404: 4, 0x1405: 4, 0x1406: 4}
    if channels not in channel_sizes or sample_type not in sample_sizes:
        raise ValueError('unsupported loopback output layout')
    cdef Py_ssize_t size = _count(n * channel_sizes[channels] * sample_sizes[sample_type])
    cdef char* data = <char*>_allocate(size, sizeof(char))
    try:
        if n:
            _al_api.alcRenderSamplesSOFT(_dev(device), data, n)
            _check_alc(device)
        return data[:size]
    finally:
        free(data)


def device_reset(device, attributes, name=None, reopen=False):
    _require_symbol(b'alcReopenDeviceSOFT' if reopen else b'alcResetDeviceSOFT', device)
    cdef ALCint* attrs = <ALCint*>_allocate(2 * len(attributes) + 1, sizeof(ALCint))
    cdef bytes encoded
    cdef const char* n = NULL
    cdef bint ok
    try:
        for i, (key, value) in enumerate(attributes.items()):
            attrs[2*i], attrs[2*i+1] = key, value
        if name is not None:
            encoded = name.encode('utf-8')
            n = encoded
        if reopen:
            ok = _al_api.alcReopenDeviceSOFT(_dev(device), n, attrs)
        else:
            ok = _al_api.alcResetDeviceSOFT(_dev(device), attrs)
        _check_alc(device)
        if not ok:
            raise ALCError(-1)
    finally:
        free(attrs)


def device_pause(device, paused):
    if paused:
        _require_symbol(b'alcDevicePauseSOFT', device)
        _al_api.alcDevicePauseSOFT(_dev(device))
    else:
        _require_symbol(b'alcDeviceResumeSOFT', device)
        _al_api.alcDeviceResumeSOFT(_dev(device))
    _check_alc(device)


def device_string_index(device, pname, item):
    _require_symbol(b'alcGetStringiSOFT', device)
    cdef int i = _count(item)
    result = _cstr(_al_api.alcGetStringiSOFT(_dev(device), pname, i))
    _check_alc(device)
    return result


def device_timing(device):
    _require_symbol(b'alcGetInteger64vSOFT', device)
    cdef _al_api.ALCint64SOFT values[2]
    _al_api.alcGetInteger64vSOFT(_dev(device), 0x1602, 2, values)
    _check_alc(device)
    return (values[0], values[1])


def source_latency(source):
    _require_symbol(b'alGetSourcedvSOFT')
    cdef _al_api.ALdouble values[2]
    _al_api.alGetSourcedvSOFT(source, 0x1201, values)
    _check_al()
    return (values[0], values[1])


def defer_updates(defer):
    if defer:
        _require_symbol(b'alDeferUpdatesSOFT')
        _al_api.alDeferUpdatesSOFT()
    else:
        _require_symbol(b'alProcessUpdatesSOFT')
        _al_api.alProcessUpdatesSOFT()
    _check_al()


def efx_is(kind, handle):
    if kind == 'effect':
        _require_symbol(b'alIsEffect')
        result = bool(_al_api.alIsEffect(handle))
    elif kind == 'filter':
        _require_symbol(b'alIsFilter')
        result = bool(_al_api.alIsFilter(handle))
    elif kind == 'slot':
        _require_symbol(b'alIsAuxiliaryEffectSlot')
        result = bool(_al_api.alIsAuxiliaryEffectSlot(handle))
    else:
        raise ValueError('invalid EFX kind')
    _check_al()
    return result


def efx_get(kind, handle, pname, integer=False):
    cdef ALint value = 0
    cdef ALfloat values[3]
    cdef int n = 1
    if kind == 'effect':
        if integer:
            _require_symbol(b'alGetEffecti')
            _al_api.alGetEffecti(handle, pname, &value)
        else:
            _require_symbol(b'alGetEffectfv')
            if pname in (0xB, 0xE):
                _require_symbol(b'alGetEffecti')
                _al_api.alGetEffecti(handle, 0x8001, &value)
                _check_al()
                if value == 0x8000:
                    n = 3
            _al_api.alGetEffectfv(handle, pname, values)
    elif kind == 'filter':
        if integer:
            _require_symbol(b'alGetFilteri')
            _al_api.alGetFilteri(handle, pname, &value)
        else:
            _require_symbol(b'alGetFilterf')
            _al_api.alGetFilterf(handle, pname, &values[0])
    elif kind == 'slot':
        if integer:
            _require_symbol(b'alGetAuxiliaryEffectSloti')
            _al_api.alGetAuxiliaryEffectSloti(handle, pname, &value)
        else:
            _require_symbol(b'alGetAuxiliaryEffectSlotf')
            _al_api.alGetAuxiliaryEffectSlotf(handle, pname, &values[0])
    else:
        raise ValueError('invalid EFX kind')
    _check_al()
    return value if integer else (values[0] if n == 1 else tuple(values[i] for i in range(n)))
