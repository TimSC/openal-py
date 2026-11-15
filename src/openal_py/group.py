"""Batch playback commands for sources sharing one context."""
from __future__ import annotations
from typing import TYPE_CHECKING, Iterable, Iterator, Literal

from openal_py import _core
from openal_py._errors import ContextMismatchError

if TYPE_CHECKING:
    from openal_py.context import Context
    from openal_py.source import Source


class SourceGroup:
    """A retained collection of sources, without independent native ownership."""

    def __init__(self, context: Context, sources: Iterable[Source]):
        from openal_py.source import Source
        self._context = context
        self._sources = tuple(sources)
        for source in self._sources:
            if not isinstance(source, Source):
                raise TypeError('group entries must be Source objects')
            if source.context is not context:
                raise ContextMismatchError('source belongs to another context')
        if len({id(source) for source in self._sources}) != len(self._sources):
            raise ValueError('a source may appear only once in a group')

    @property
    def context(self) -> Context:
        return self._context

    @property
    def sources(self) -> tuple[Source, ...]:
        return self._sources

    def _command(self, operation: Literal['play', 'pause', 'stop', 'rewind']) -> None:
        self.context._require_current()
        handles = []
        for source in self.sources:
            source._require_current()
            assert source.handle is not None
            handles.append(source.handle)
        _core.source_batch(handles, operation)

    def play(self) -> None:
        self._command('play')

    def pause(self) -> None:
        self._command('pause')

    def stop(self) -> None:
        self._command('stop')

    def rewind(self) -> None:
        self._command('rewind')

    def __iter__(self) -> Iterator[Source]:
        return iter(self.sources)

    def __len__(self) -> int:
        return len(self.sources)
