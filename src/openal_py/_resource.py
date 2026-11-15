"""Shared ownership and lifecycle for context-bound AL handles."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, TypeVar

from openal_py import _finalize
from openal_py._errors import ResourceClosedError

if TYPE_CHECKING:
    from openal_py.context import Context

_R = TypeVar('_R', bound='ContextResource')


class ContextResource:
    """Private base: finalizers retain state/handles, never their wrapper.

    Subclasses supply native deletion and optional post-close bookkeeping.
    Failed native deletion leaves ownership, references, and finalizer armed.
    """

    def _initialize_resource(self, context: Context, handle: int,
                             delete: Callable[[list[int]], None], *, owned: bool = True,
                             label: str | None = None) -> None:
        self._context = context
        self._handle: int | None = handle
        self._owned = owned
        self._delete = delete
        self._label = label or type(self).__name__.lower()
        self._retained: list[object] = []
        self._finalizer = (_finalize.register(self, context._state, handle, delete, self._retained)
                           if owned else None)

    @property
    def context(self) -> Context:
        return self._context

    @property
    def closed(self) -> bool:
        return self._handle is None or self.context.closed

    @property
    def handle(self) -> int | None:
        return None if self.closed else self._handle

    def _require_current(self) -> None:
        if self.closed:
            raise ResourceClosedError(f'{self._label} has been closed/deleted or its context closed')
        self.context._require_current()

    def close(self) -> None:
        if self._handle is None:
            return
        handle = self._handle
        if self._owned:
            _finalize.release(self.context._state, handle, self._delete, self._retained)
        # Commit release before Python bookkeeping: a failing subclass hook
        # must never leave a finalizer armed for an already-deleted native name.
        self._handle = None
        if self._finalizer is not None:
            self._finalizer.detach()
        try:
            self._after_close(handle)
        finally:
            self._retained.clear()

    def _after_close(self, handle: int) -> None:
        """Subclass bookkeeping after successful native release (or context closure)."""

    def __enter__(self: _R) -> _R:
        self._require_current()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f'{type(self).__name__}(handle={self.handle}, closed={self.closed})'
