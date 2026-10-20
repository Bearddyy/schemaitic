"""Typed electrical values: a number plus an SI scale (10K, 4.7k, 100n, 1u).

Raw strings like "10K" scattered through a design are exactly the kind of
unverifiable data that silently propagates into a netlist. Value parses once,
at construction, then is an ordinary non-negative float in base units
(ohms, farads, henries) that the type checker can reason about.

Fail-early: bad text raises ValueError with the accepted grammar; NaN,
infinity and negative passives raise TypeError/ValueError at the point of
construction, not three stages later in ngspice.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Union

__all__ = ["Value", "ValueLike", "to_value", "parse_scale"]

#: Anything acceptable where an electrical value is expected.
ValueLike = Union["Value", int, float, str]

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_VALUE_RE = re.compile(rf"^(?P<num>{_NUMBER})\s*(?P<suf>[TGMKNmunpFUuµ]?)$")

_SUFFIX_MULT: dict[str, float] = {
    "T": 1e12, "t": 1e12,
    "G": 1e9, "g": 1e9,
    "M": 1e6,                      # M = mega
    "m": 1e-3,                     # m = milli (SPICE convention)
    "u": 1e-6, "µ": 1e-6, "U": 1e-6,
    "n": 1e-9, "N": 1e-9,
    "p": 1e-12, "P": 1e-12,
    "f": 1e-15, "F": 1e-15,
    "": 1.0,
    # k/K both kilo (KiCad writes K, SPICE accepts k).
    "k": 1e3, "K": 1e3,
}


@dataclass(frozen=True, slots=True)
class Value:
    """A non-negative electrical quantity in base SI units.

    ``si`` is the value in base units (ohms / farads / henries / volts...).
    Immutable so a part's value cannot drift after checks have run.
    """

    si: float

    def __post_init__(self) -> None:
        if not isinstance(self.si, (int, float)):
            raise TypeError(f"Value needs a number, got {type(self.si).__name__}")
        if isinstance(self.si, bool):
            raise TypeError("Value needs a number, got bool")
        if math.isnan(self.si) or math.isinf(self.si):
            raise ValueError(f"Value must be finite, got {self.si}")
        if self.si < 0:
            raise ValueError(f"passive values must be non-negative, got {self.si}")

    # ---- construction -------------------------------------------------

    @classmethod
    def parse(cls, text: str) -> "Value":
        """Parse '10K', '4.7k', '100n', '1u', '1e9', '3.3' ...

        Raises ValueError with the accepted grammar on anything else, so a
        typo ('10kohm', '4,7K') fails at the line that contains it.
        """
        if not isinstance(text, str):
            raise TypeError(f"Value.parse needs str, got {type(text).__name__}")
        m = _VALUE_RE.match(text.strip())
        if m is None:
            raise ValueError(
                f"cannot parse value {text!r}; expected a number with optional "
                "SI suffix: T G M K (m) u U n p f, e.g. '10K', '4.7k', '100n'"
            )
        num = float(m["num"])
        scaled = num * _SUFFIX_MULT[m["suf"]]
        return cls(scaled)

    # ---- presentation -------------------------------------------------

    def spice(self) -> str:
        """Engineering notation SPICE/KiCad accepts, e.g. 4700.0 -> '4.7K'."""
        if self.si == 0:
            return "0"
        a = abs(self.si)
        # Largest suffix that keeps the mantissa >= 1.
        bands: tuple[tuple[float, str], ...] = (
            (1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "K"),
            (1.0, ""), (1e-3, "m"), (1e-6, "U"), (1e-9, "n"),
            (1e-12, "p"), (1e-15, "F"),
        )
        for scale, suffix in bands:
            if a >= scale:
                return f"{self.si / scale:.6g}{suffix}"
        return f"{self.si:.6g}"

    def __str__(self) -> str:
        return self.spice()

    # ---- arithmetic ----------------------------------------------------

    def __mul__(self, other: Union["Value", int, float]) -> "Value":
        o = other.si if isinstance(other, Value) else other
        return Value(self.si * o)

    def __lt__(self, other: Union["Value", int, float]) -> bool:
        return self.si < (other.si if isinstance(other, Value) else other)

    def __le__(self, other: Union["Value", int, float]) -> bool:
        return self.si <= (other.si if isinstance(other, Value) else other)


def parse_scale(text: str) -> float:
    """Parse to a bare float in base units (convenience for scripts)."""
    return Value.parse(text).si


def to_value(x: Union["Value", int, float, str]) -> Value:
    """Normalise any accepted value spelling to Value; fails loudly otherwise."""
    if isinstance(x, Value):
        return x
    if isinstance(x, bool):
        raise TypeError(f"cannot use bool as an electrical value: {x!r}")
    if isinstance(x, (int, float)):
        return Value(float(x))
    if isinstance(x, str):
        return Value.parse(x)
    raise TypeError(
        f"electrical values must be Value, int, float or SI-suffixed str, "
        f"got {type(x).__name__}: {x!r}"
    )
