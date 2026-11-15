"""Shared parameter and timing types."""
from __future__ import annotations
from enum import IntEnum
from typing import Literal, NamedTuple, Union
from openal_py._constants import AL, ALC

Parameter = Union[int, str]
ParameterValue = Union[float, int, tuple[float, ...], tuple[int, ...]]
NumericKind = Literal['float', 'double', 'int', 'bool']


def resolve(namespace: type, parameter: Parameter) -> int:
    if isinstance(parameter, str):
        value: int = getattr(namespace, parameter)
        return value
    return int(parameter)


class DistanceModel(IntEnum):
    NONE = AL.AL_NONE
    INVERSE = AL.AL_INVERSE_DISTANCE
    INVERSE_CLAMPED = AL.AL_INVERSE_DISTANCE_CLAMPED
    LINEAR = AL.AL_LINEAR_DISTANCE
    LINEAR_CLAMPED = AL.AL_LINEAR_DISTANCE_CLAMPED
    EXPONENT = AL.AL_EXPONENT_DISTANCE
    EXPONENT_CLAMPED = AL.AL_EXPONENT_DISTANCE_CLAMPED


class HRTFStatus(IntEnum):
    DISABLED = ALC.ALC_HRTF_DISABLED_SOFT
    ENABLED = ALC.ALC_HRTF_ENABLED_SOFT
    DENIED = ALC.ALC_HRTF_DENIED_SOFT
    REQUIRED = ALC.ALC_HRTF_REQUIRED_SOFT
    HEADPHONES_DETECTED = ALC.ALC_HRTF_HEADPHONES_DETECTED_SOFT
    UNSUPPORTED_FORMAT = ALC.ALC_HRTF_UNSUPPORTED_FORMAT_SOFT


class DeviceTiming(NamedTuple):
    clock_ns: int
    latency_ns: int


class PlaybackLatency(NamedTuple):
    offset_seconds: float
    latency_seconds: float
