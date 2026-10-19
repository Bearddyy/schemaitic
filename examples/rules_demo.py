"""Demo of the validate stage: datasheet rules attached to parts.

Shows the three outcomes the runner can produce:
  - PASS        automated rule satisfied (R1's body has no rules; C1 grounded OK)
  - FAIL        automated rule violated (U1's exposed pad left floating)
  - MANUAL_*    rule needs a human (heatsink clearance prompt)

Run:
    tools/schemaitic.py validate examples/rules_demo.py          # prompts
    tools/schemaitic.py validate examples/rules_demo.py --no-input  # CI mode
"""

import sys
from pathlib import Path

# Circuit files are loaded from anywhere; make tools/rules.py importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from skidl import Net, Part

from rules import (
    GroundedRule,
    ManualRule,
    NoConnectRule,
    PinOnNetRule,
    attach_rules,
)


def build() -> None:
    """Fake sensor U1 with a ground pin, an NC pin, a floating pad, plus passives."""
    vin, sig, gnd = Net("VI"), Net("SIG"), Net("GND")

    # A generic 4-pin IC built from the Device library symbol.
    u1 = Part("Device", "R_Potentiometer", ref_prefix="U", tag="U1")
    u1.value = "SENSOR-XYZ"
    # Rules an agent would extract from the datasheet:
    attach_rules(
        u1,
        [
            # pin 2 (wiper) is VSS on this part -> must be ground-like
            GroundedRule(2),
            # pin 3 is flagged NC in the datasheet -> must stay floating
            NoConnectRule(3),
            # pin 1 is the supply pin -> must sit on a power-like net
            PinOnNetRule(1, r"(VCC|VIN|VBUS|PWR)\d*"),
            # cannot be checked from netlist data at all -> prompt
            ManualRule(
                "datasheet: keep 5 mm clearance over pins 1-4 for the "
                "heatsink; is the layout clear?"
            ),
        ],
    )

    r1 = Part("Device", "R", tag="R1")
    r1.value = "10K"

    # VI -> U1(1..2) gives pin1=VI (fails the power-net rule below since
    # VI is not power-like), pin2=GND via r1 keeps GroundedRule honest.
    vin & u1[1]
    u1[2] & r1 & gnd
    # pin 3 deliberately left connected to SIG -> violates NoConnectRule.
    u1[3] & sig

    # A clean part: cap from SIG to GND, no rules attached -> nothing to fail.
    c1 = Part("Device", "C", tag="C1")
    c1.value = "100N"
    attach_rules(c1, [GroundedRule(2)])
    sig & c1[1]
    c1[2] & gnd
