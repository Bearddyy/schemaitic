"""Typed, object-oriented part constructors over SKiDL.

Instead of ``Part("Device", "R", value="10K")`` — where a typo in lib, part
name, or value string survives until ngspice — these subclasses pin the
library/part at class level, take values as ``Value | int | float | str``
normalised through :func:`values.to_value`, and validate constructor kwargs
immediately (fail-early ideology).

    from parts import Resistor, Capacitor, Net, Ground

    vin, vout, gnd = Net("VI"), Net("VO"), Ground("GND")
    r1 = Resistor("R1", 10e3)          # ohms
    r2 = Resistor("R2", "4.7K")        # or SI-suffixed text, parsed once
    c1 = Capacitor("C1", "100n")
    vin & r1 & vout & (r2 | c1) & gnd   # SKiDL operators work unchanged
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from skidl import Net, Part as SkidlPart

from nets import Ground  # re-export: schematics import nets from one place
from rules import Rule, attach_rules
from values import Value, ValueLike, to_value

__all__ = [
    "Capacitor",
    "Net",
    "Ground",
    "Inductor",
    "Led",
    "PartBase",
    "Resistor",
    "TwoPin",
]

# Default 0805 footprints; override per instance when the board says otherwise.
_F_FOOTPRINT = "Resistor_SMD.pretty:R_0805_2012Metric"
_C_FOOTPRINT = "Capacitor_SMD.pretty:C_0805_2012Metric"
_L_FOOTPRINT = "Inductor_SMD.pretty:L_0805_2012Metric"
_LED_FOOTPRINT = "LED_SMD.pretty:LED_0805_2012Metric"


class PartBase(SkidlPart):
    """SKiDL Part with schemaitic conventions.

    * rules keyword is consumed here and attached via attach_rules()
    * unknown kwargs raise instead of being silently set as attributes
    * value (if given) is normalised to Value and rendered SPICE-safe
    """

    _LIB = ""       # set by subclasses
    _PART = ""
    _FOOTPRINT = ""

    def __init__(
        self,
        ref: Optional[str] = None,
        value: Optional[ValueLike] = None,
        *,
        footprint: Optional[str] = None,
        rules: Tuple[Rule, ...] = (),
        datasheet: Optional[str] = None,
        **extra: Any,
    ) -> None:
        if not self._LIB:
            raise TypeError("PartBase is abstract; use Resistor/Capacitor/...")
        if extra:
            # No silent attribute-spam: an unexpected kwarg is a bug at the
            # call site (e.g. val= instead of value=).
            raise TypeError(
                f"{type(self).__name__} got unexpected kwargs {sorted(extra)}"
            )
        super().__init__(
            self._LIB,
            self._PART,
            ref=ref,
            footprint=footprint or self._FOOTPRINT,
            datasheet=datasheet or "",
        )
        if value is not None:
            self.value = to_value(value)
        else:
            self._schemaitic_value: Optional[Value] = None
        if rules:
            attach_rules(self, rules)

    # ``value`` holds a Value object in Python land but must serialise as
    # SPICE engineering notation ("4.7K") for netlists: the getter returns
    # the typed Value, the underlying SKiDL attribute keeps the string.
    @property
    def value(self) -> Any:
        v: Optional[Value] = getattr(self, "_schemaitic_value", None)
        if v is not None:
            return v
        return getattr(self, "_value", self.name)

    @value.setter
    def value(self, value: ValueLike) -> None:
        val = to_value(value)
        self._schemaitic_value = val
        self._value = val.spice()

    @value.deleter
    def value(self) -> None:
        self._schemaitic_value = None
        if hasattr(self, "_value"):
            del self._value


class TwoPin(PartBase):
    """Base for 2-pin passives: gives ``a``/``b`` pin accessors."""

    @property
    def a(self) -> Any:
        return self["1"]

    @property
    def b(self) -> Any:
        return self["2"]


class Resistor(TwoPin):
    _LIB, _PART, _FOOTPRINT = "Device", "R", _F_FOOTPRINT


class Capacitor(TwoPin):
    _LIB, _PART, _FOOTPRINT = "Device", "C", _C_FOOTPRINT


class Inductor(TwoPin):
    _LIB, _PART, _FOOTPRINT = "Device", "L", _L_FOOTPRINT


class Led(TwoPin):
    _LIB, _PART, _FOOTPRINT = "Device", "D", _LED_FOOTPRINT
