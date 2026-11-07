from __future__ import annotations

import json
import math
from typing import Any


def _reject_constant(value: str) -> None:
    raise ValueError(f"JSON no finito: {value}")


def _parse_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"JSON no finito: {value}")
    return parsed


def strict_loads(value: str | bytes | bytearray) -> Any:
    return json.loads(value, parse_constant=_reject_constant, parse_float=_parse_float)
