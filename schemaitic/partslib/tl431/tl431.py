"""TL431 programmable shunt reference — pins, rules, and SPICE model in one place.

Digitised once from the datasheet (TI SLVS14B): symbol (TL431.kicad_sym),
simulation model (model.lib), and the electrical rules that must hold in any
design using it. Designs just say ``u = TL431(ref="U1")``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ...parts import PartBase
from ...rules import GroundedRule, Rule

_HERE = Path(__file__).resolve().parent
SYMBOL = _HERE / "TL431.kicad_sym"
MODEL = _HERE / "model.lib"


class TL431(PartBase):
    """Three-terminal shunt regulator (cathode / anode / reference)."""

    _LIB = str(SYMBOL)
    _PART = "TL431"
    _FOOTPRINT = "Package_TO_SOT_SMD.pretty:SOT-23"

    # Datasheet-derived rules, applied wherever the part is used.
    BASE_RULES: tuple[Rule, ...] = (
        GroundedRule(2, description="ANODE must be at ground (shunt reference)"),
    )

    #: KiCad pin number -> subckt node name in model.lib (order matters!).
    SPICE_PIN_MAP: Dict[int, str] = {1: "CATHODE", 2: "ANODE", 3: "REFERENCE"}

    def __init__(
        self,
        ref: Optional[str] = None,
        value: Optional[str] = None,
        *,
        footprint: Optional[str] = None,
        rules: tuple[Rule, ...] = (),
    ) -> None:
        super().__init__(
            ref,
            value,
            footprint=footprint,
            rules=tuple(self.BASE_RULES) + tuple(rules),
            datasheet="https://www.ti.com/lit/ds/symlink/tl431.pdf",
        )

    # -- simulation seam --------------------------------------------------

    def spice_template(self) -> Any:
        """TEMPLATE part from the folder's SPICE model, for convert_for_spice."""
        from skidl import SPICE, TEMPLATE, Part

        return Part(str(MODEL), "TL431", tool=SPICE, dest=TEMPLATE)

    def spice_pin_map(self) -> Dict[int, str]:
        return dict(self.SPICE_PIN_MAP)
