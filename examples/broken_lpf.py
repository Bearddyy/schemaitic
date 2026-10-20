"""Negative control for `schemaitic test`: the LPF with a 10x-too-big cap.

Same spec as lpf_divider (fc ~498 Hz) but C defaults to 1U, moving the real
cutoff to ~50 Hz — the design test must fail and the CLI must exit 1.
Kept self-contained (no sibling imports) so type-checking resolves cleanly.
"""

from __future__ import annotations

import math

from schemaitic import (
    Capacitor,
    Ground,
    LowPassFilter,
    Net,
    OperatingPoint,
    Resistor,
    Schematic,
    Simulation,
    ValueLike,
)

R_TOP_OHM = 10e3
R_BOT_OHM = 4.7e3
SUPPLY_V = 5.0


class BrokenLpf(Schematic):
    """Correct topology, wrong capacitor: violates the filter spec."""

    DEFAULTS: dict[str, ValueLike] = {"R_top": "10K", "R_bot": "4.7K", "C": "1U"}

    def content(self, **params: ValueLike) -> None:
        p = {**self.DEFAULTS, **params}
        vin, vout = Net("VI"), Net("VO")
        gnd = Ground("GND")
        r1 = Resistor("R1", p["R_top"])
        r2 = Resistor("R2", p["R_bot"])
        c1 = Capacitor("C1", p["C"])
        # Each net lists the pins that live on it.
        vin.connect(r1[1])
        vout.connect(r1[2], r2[1], c1[1])
        gnd.connect(r2[2], c1[2])

    def design_tests(self) -> list[Simulation]:
        # Spec for the HEALTHY filter (C=100n); this build has C=1U.
        fc = 1.0 / (
            2.0 * math.pi * (R_TOP_OHM * R_BOT_OHM / (R_TOP_OHM + R_BOT_OHM)) * 100e-9
        )
        return [
            OperatingPoint(
                node="vo",
                expect_v=SUPPLY_V * R_BOT_OHM / (R_TOP_OHM + R_BOT_OHM),
                tolerance_v=0.005,
            ),
            LowPassFilter(
                "vo",
                cutoff_hz=fc,
                rejection_hz=10e3,
                min_rejection_db=-20.0,
                start=10.0,
                stop=1e6,
                points=201,
            ),
        ]


def build(**params: ValueLike) -> None:
    BrokenLpf().build(**params)
