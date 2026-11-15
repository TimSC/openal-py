"""Shared public typing aliases."""
import sys
from os import PathLike
from typing import BinaryIO, Sequence, Union

AudioFile = Union[str, PathLike[str], BinaryIO]
Vector3 = Sequence[float]

if sys.version_info >= (3, 12):
    from collections.abc import Buffer as PCMData
else:
    from typing_extensions import Buffer as PCMData

__all__ = ["AudioFile", "PCMData", "Vector3"]
