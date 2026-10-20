"""Voltage divider with an optional cap across the bottom resistor —
reference design: typed parts, datasheet rules, ground as a type,
and SPICE design tests declaring the spec.

    schemaitic validate examples/lpf_divider.py --no-input
    schemaitic test examples/lpf_divider.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from skidl import Net  # noqa: E402

from nets import Ground  # noqa: E402
from parts import Capacitor, Resistor  # noqa: E402
from rules import GroundedRule  # noqa: E402
from schematic import Schematic  # noqa: E402
from simulations import LowPassFilter, OperatingPoint, Simulation  # noqa: E402
from values import ValueLike  # noqa: E402

R_TOP_OHM = 10e3
R_BOT_OHM = 4.7e3
SUPPLY_V = 5.0


class LpfDivider(Schematic):
    """VI --10K-- VO --4.7K-- GND with C across R2 (2nd-order-free LPF)."""

    #: Design parameters with defaults (read in content/design_tests).
    DEFAULTS: dict[str, ValueLike] = {"R_top": "10K", "R_bot": "4.7K", "C": "100N"}

    def content(self, **params: ValueLike) -> None:
        p = {**self.DEFAULTS, **params}
        vin, vout = Net("VI"), Net("VO")
        gnd = Ground("GND")
        r1 = Resistor("R1", p["R_top"])
        r2 = Resistor("R2", p["R_bot"], rules=(GroundedRule(2),))  # bottom -> GND
        c1 = Capacitor("C1", p["C"], rules=(GroundedRule(2),))
        vin & r1 & vout & (r2 | c1[1, 2]) & gnd
        self.resolved = p

    def design_tests(self) -> list[Simulation]:
        from values import to_value

        p = getattr(self, "resolved", dict(self.DEFAULTS))
        r_bot = float(to_value(p["R_bot"]).si)
        cap = float(to_value(p["C"]).si)
        # The cap charges through R1||R2 (source is ideal, so R1 is in parallel
        # with the 0-ohm supply for AC): fc = 1 / (2*pi*(R1||R2)*C).
        fc = 1.0 / (2.0 * math.pi * (R_TOP_OHM * r_bot / (R_TOP_OHM + r_bot)) * cap)
        divider_db = 20.0 * math.log10(r_bot / (R_TOP_OHM + r_bot))
        return [
            OperatingPoint(node="vo", expect_v=SUPPLY_V * r_bot / (R_TOP_OHM + r_bot),
                           tolerance_v=0.005),
            LowPassFilter("vo", cutoff_hz=fc, rejection_hz=10e3,
                          min_rejection_db=-20.0,
                          expected_passband_db=divider_db,
                          start=10.0, stop=1e6, points=201),
        ]


# Legacy function-style entry point so the older stages keep working.
def build(**params: ValueLike) -> None:
    LpfDivider().build(**params)
