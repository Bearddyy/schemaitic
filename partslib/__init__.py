"""SchemAItic parts library: custom parts defined once, reused everywhere.

Each custom part lives in its own folder::

    partslib/
        tl431/
            __init__.py      # exports the part class(es)
            tl431.py         # Python class: pins, rules, footprint, model wiring
            TL431.kicad_sym  # KiCad symbol (SKiDL needs a real lib file)
            model.lib        # SPICE .subckt used for simulation

The class is the single definition: schematics import it for structure/ERC/
rules, and simulation finds its SPICE model through ``spice_template()`` /
``spice_pin_map()`` — so a part datasheet gets digitised once (pins + rules
from the datasheet, model from the vendor) and every design inherits all of it.

Passives that need no customisation (plain R/C/L) do NOT belong here —
they come from the standard KiCad Device lib via ``tools/parts.py``.
"""

from __future__ import annotations

from pathlib import Path

#: Repo root -> tools on sys.path so partslib modules can import parts/rules
#: even when a design file imported partslib directly.
_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parent / "tools"
import sys

if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from partslib.tl431 import TL431  # noqa: E402

__all__ = ["TL431"]
