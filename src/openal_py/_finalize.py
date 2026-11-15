"""Weakref-based C-handle cleanup without reference cycles.

``weakref.finalize(obj, callback)`` fires only *after* ``obj`` is dead, so the
callback can't touch the object.  A bound method (``obj._delete``) would also
keep ``obj`` alive forever.  So each owning object registers its raw C handle
(an int, not the object) plus the low-level delete callable; the finalizer
releases the C handle directly once the Python wrapper is gone.
"""
from __future__ import annotations

import weakref


def register(obj, handle, delete) -> None:
    """Release *handle* (via ``delete([handle])``) when *obj* is collected.

    *delete* is the low-level core function (e.g. ``_core.delete_buffers``).
    Safe to call repeatedly; the finalizer fires at most once.
    """
    if handle is None:
        return

    def _release() -> None:
        try:
            delete([handle])
        except Exception:
            pass

    weakref.finalize(obj, _release)
