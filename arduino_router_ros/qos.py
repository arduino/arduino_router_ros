from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from rclpy.qos import (
    QoSProfile,
    QoSHistoryPolicy,
    QoSReliabilityPolicy,
    QoSDurabilityPolicy,
)


@dataclass(frozen=True)
class QoSDecodeResult:
    qos: QoSProfile
    warnings: tuple[str, ...] = ()


# Numeric codes -> rclpy enums (aligned with common RMW policy numeric values used in bridges)
_HISTORY = {
    10: QoSHistoryPolicy.KEEP_LAST,
    20: QoSHistoryPolicy.KEEP_ALL,
    30: QoSHistoryPolicy.SYSTEM_DEFAULT,
    40: QoSHistoryPolicy.UNKNOWN,
}

_RELIABILITY = {
    10: QoSReliabilityPolicy.BEST_EFFORT,
    20: QoSReliabilityPolicy.RELIABLE,
    30: QoSReliabilityPolicy.SYSTEM_DEFAULT,
    40: QoSReliabilityPolicy.BEST_AVAILABLE,  # Jazzy: available
    50: QoSReliabilityPolicy.UNKNOWN,
}

_DURABILITY = {
    10: QoSDurabilityPolicy.VOLATILE,
    20: QoSDurabilityPolicy.TRANSIENT_LOCAL,
    30: QoSDurabilityPolicy.SYSTEM_DEFAULT,
    40: QoSDurabilityPolicy.BEST_AVAILABLE,  # Jazzy: available
    50: QoSDurabilityPolicy.UNKNOWN,
}


def qos_from_dict(d: Mapping[str, Any], *, strict: bool = False) -> QoSDecodeResult:
    """
    Expected keys: 'history', 'depth', 'reliability', 'durability' (ints).

    strict=False:
      - missing keys default to SYSTEM_DEFAULT (depth defaults to 10)
      - unknown numeric codes fall back to SYSTEM_DEFAULT (and emit warnings)

    strict=True:
      - missing keys raise KeyError
      - unknown codes raise ValueError
    """
    if not isinstance(d, Mapping):
        raise TypeError(f"Expected a mapping/dict, got {type(d).__name__}")

    warnings: list[str] = []

    def get_int(key: str, default: int) -> int:
        if key not in d:
            if strict:
                raise KeyError(f"Missing key '{key}' in QoS dict")
            warnings.append(f"Missing '{key}', defaulting to {default}")
            return default
        v = d[key]
        if isinstance(v, bool) or not isinstance(v, int):
            raise TypeError(f"QoS field '{key}' must be int, got {type(v).__name__}")
        return v

    history_code = get_int("history", 30)
    depth = get_int("depth", 10)
    reliability_code = get_int("reliability", 30)
    durability_code = get_int("durability", 30)

    if depth < 0:
        raise ValueError(f"QoS depth must be >= 0, got {depth}")

    def map_code(kind: str, code: int, table: dict[int, Any], default_enum: Any) -> Any:
        if code in table:
            return table[code]
        msg = f"Unknown QoS {kind} code {code}"
        if strict:
            raise ValueError(msg)
        warnings.append(msg + f"; using {default_enum}")
        return default_enum

    history = map_code("history", history_code, _HISTORY, QoSHistoryPolicy.SYSTEM_DEFAULT)
    reliability = map_code(
        "reliability", reliability_code, _RELIABILITY, QoSReliabilityPolicy.SYSTEM_DEFAULT
    )
    durability = map_code(
        "durability", durability_code, _DURABILITY, QoSDurabilityPolicy.SYSTEM_DEFAULT
    )

    qos = QoSProfile(
        history=history,
        depth=depth,
        reliability=reliability,
        durability=durability,
    )
    return QoSDecodeResult(qos=qos, warnings=tuple(warnings))


def qos_profile(d: Mapping[str, Any], *, strict: bool = False) -> QoSProfile:
    """Convenience: return only the QoSProfile."""
    return qos_from_dict(d, strict=strict).qos
