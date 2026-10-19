"""Voltage divider with an optional cap across the bottom resistor.

Single source of truth for SchemAItic: build() makes the circuit,
spice() adds the stimulus and picks analyses. Run via:

    tools/schemaitic.py sim examples/vdivider.py --sweep C=1N,10N,100N,1U --plot out.png
"""

from skidl import TEMPLATE, Net, Part

R_TOP = "10K"
R_BOT = "4.7K"


def build(C: str | None = None) -> None:
    """Divider VI -> R1 -> VO -> R2 -> GND; C (if given) parallels R2."""
    vin, vout, gnd = Net("VI"), Net("VO"), Net("GND")

    r1, r2 = 2 * Part(
        "Device", "R", dest=TEMPLATE,
        footprint="Resistor_SMD.pretty:R_0805_2012Metric",
    )
    r1.value, r2.value = R_TOP, R_BOT
    r1.tag, r2.tag = "R1", "R2"

    if C is None:
        vin & r1 & vout & r2 & gnd
    else:
        # NOTE: no dest=TEMPLATE here - a lone TEMPLATE part is never
        # instantiated and silently drops out of the netlist.
        c1 = Part(
            "Device", "C",
            footprint="Capacitor_SMD.pretty:C_0805_2012Metric",
        )
        c1.value, c1.tag = C, "C1"
        vin & r1 & vout & (r2 | c1[1, 2]) & gnd


def spice(circuit) -> list[dict]:
    """Pulse stimulus on VI; DC op point plus a 10 ms transient."""
    from InSpice.Unit import u_V

    src = circuit.V("source", "VI", "GND", 0 @ u_V)
    src.dc_value = None
    src.tran_value = "PULSE(0 5 0 1n 1n 5m 10m)"
    return [
        {"type": "op"},
        {"type": "tran", "step": 5e-6, "end": 10e-3, "plot": ["vi", "vo"]},
    ]
