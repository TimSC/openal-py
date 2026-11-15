"""Select one OpenAL implementation before any device handles are created."""
from __future__ import annotations

import ctypes.util
import os
import sys
from typing import Callable


def system_libraries() -> list[str]:
    """Platform loader names, with the system's discovered library first."""
    if sys.platform == "win32":
        names = ["OpenAL32.dll", "openal.dll"]
    elif sys.platform == "darwin":
        names = ["libopenal.1.dylib", "/System/Library/Frameworks/OpenAL.framework/OpenAL"]
    else:
        names = ["libopenal.so.1", "libopenal.so"]
    discovered = ctypes.util.find_library("OpenAL" if sys.platform == "darwin" else "openal")
    return list(dict.fromkeys(([discovered] if discovered else []) + names))


def initialize(bundled_path: str | bytes, load: Callable[[str, bool], bool]) -> None:
    """Prefer a bundle with playback devices, then system OpenAL.

    An explicit override is authoritative. If neither implementation detects
    devices, a loadable library is still useful for headless/loopback work.
    ``load`` must only commit its function table after successful validation.
    """
    override = os.environ.get("OPENAL_PY_LIBRARY")
    if override:
        if load(override, False):
            return
        raise ImportError(f"openal_py: failed to initialize OPENAL_PY_LIBRARY={override!r}")

    bundled = os.fsdecode(bundled_path)
    has_bundle = os.path.isfile(bundled)
    attempted = []
    if has_bundle:
        attempted.append(bundled)
        if load(bundled, True):
            return
    for candidate in system_libraries():
        attempted.append(candidate)
        if load(candidate, False):
            return
    if has_bundle and load(bundled, False):
        return
    raise ImportError(
        "openal_py: no usable OpenAL library found; tried " + ", ".join(attempted)
        + ". Install system OpenAL or set OPENAL_PY_LIBRARY to its path."
    )
