"""SchemAItic: typed, object-oriented electronics design on SKiDL.

One import surface for designs — SKiDL primitives are re-exported here so
design files never need `from skidl import ...` or sys.path edits:

    from schemaitic import Ground, Net, Resistor, Capacitor, Schematic
    from schemaitic.rules import GroundedRule, PullRule
    from schemaitic.simulations import LowPassFilter, OperatingPoint

Submodules stay granular (`schemaitic.values`, `schemaitic.nets`, ...) for
tooling; this root only re-exports what a design actually writes against.
"""

from __future__ import annotations

# SKiDL primitives, exposed through our namespace: the package boundary is
# schemaitic.*, so designs never import skidl directly. (List verified
# against skidl 3.0 - not every doc'd name exists at top level.)
from skidl import (
    KICAD10,
    SPICE,
    TEMPLATE,
    Circuit,
    ERC,
    Net,
    Part,
    Pin,
    bus,
    config,
    search_footprints,
    search_parts,
)

from .values import Value, ValueLike, parse_scale, to_value
from .nets import Ground
from .rules import (
    GroundedRule,
    LambdaRule,
    ManualRule,
    ModeRule,
    NoConnectRule,
    PinOnNetRule,
    PullRule,
    PullState,
    Rule,
    RuleOutcome,
    RuleStatus,
    attach_rules,
    check_all,
    effective_rules,
)
from .parts import (
    Capacitor,
    Inductor,
    Led,
    PartBase,
    Resistor,
)
from .schematic import ERCFailure, RuleFailure, Schematic
from .simulations import (
    ACResponse,
    AssertionResult,
    LowPassFilter,
    OperatingPoint,
    SimFailure,
    Simulation,
    SimulationResult,
    TransientPulse,
)

__version__ = "0.1.0"

__all__ = [
    # SKiDL re-exports
    "Circuit",
    "ERC",
    "KICAD10",
    "Net",
    "Part",
    "Pin",
    "SPICE",
    "TEMPLATE",
    "bus",
    "config",
    "search_footprints",
    "search_parts",
    # values
    "Value",
    "ValueLike",
    "parse_scale",
    "to_value",
    # nets
    "Ground",
    # rules
    "GroundedRule",
    "LambdaRule",
    "ManualRule",
    "ModeRule",
    "NoConnectRule",
    "PinOnNetRule",
    "PullRule",
    "PullState",
    "Rule",
    "RuleOutcome",
    "RuleStatus",
    "attach_rules",
    "check_all",
    "effective_rules",
    # parts
    "Capacitor",
    "Inductor",
    "Led",
    "PartBase",
    "Resistor",
    # schematic
    "ERCFailure",
    "RuleFailure",
    "Schematic",
    # simulations
    "ACResponse",
    "AssertionResult",
    "LowPassFilter",
    "OperatingPoint",
    "SimFailure",
    "Simulation",
    "SimulationResult",
    "TransientPulse",
]
