"""Schematic: the object that owns a design.

A design subclasses ``Schematic`` and implements ``content()``, wiring typed
parts (``parts.py``) on typed nets (``nets.py``). Everything downstream —
ERC, rule validation, KiCad netlist/SVG, and SPICE simulation — is a method
on the object, so there is no fixed script order and no module-global state
to get out of sync:

    class Divider(Schematic):
        def content(self, R_top: ValueLike = "10K") -> None:
            vin, vout = Net("VI"), Net("VO")
            gnd = Ground("GND")
            r1 = Resistor("R1", R_top)
            r2 = Resistor("R2", "4.7K")
            vin.connect(r1[1])
            vout.connect(r1[2], r2[1])
            gnd.connect(r2[2])

    d = Divider()
    d.build(R_top="4.7K")      # fresh build, ERC errors raised on the spot
    d.validate()               # Part.rules sweep over the BOM
    d.netlist(Path("out"))     # KiCad .net + .svg

``build()`` clears previous parts/nets first, so sweeps and design tests can
rebuild the same object with different parameters without leaking state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from skidl import Circuit, KICAD10, reset, set_default_tool

from . import nets  # noqa: F401  (installs the Ground/ERC compatibility patch)
from .rules import check_all
from .values import ValueLike  # re-export for design files

__all__ = ["Schematic"]


class ERCFailure(Exception):
    """ERC found errors after a build. Fail early, name the count."""


class RuleFailure(Exception):
    """Part.rules validation found violations."""


class Schematic(Circuit):
    """Circuit with an explicit, repeatable build and self-checking methods."""

    def __init__(self) -> None:
        super().__init__()
        self.name = type(self).__name__
        set_default_tool(KICAD10)

    # ---- construction -------------------------------------------------

    def content(self, **params: ValueLike) -> None:
        """Wire the design. Subclasses MUST override; run inside ``self``."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement content()"
        )

    def design_tests(self) -> list[Any]:
        """SPICE design tests (simulations.Simulation) this circuit must pass.

        Override to declare e.g. [LowPassFilter("vo", cutoff_hz=..., ...)].
        `tools/schemaitic.py test <design>` runs each and reports JSON; a
        failing assertion is a design regression (exit 1).
        """
        return []

    def build(self, **params: ValueLike) -> "Schematic":
        """(Re)build the design from scratch with the given parameters.

        A full SKiDL reset guarantees no parts, nets, or held references
        survive from a previous build (sweeps rebuild many times).
        """
        reset()
        set_default_tool(KICAD10)
        with self:
            self.content(**params)
        self.erc()
        return self

    # ---- checks --------------------------------------------------------

    def erc(self) -> dict[str, int]:
        """Run SKiDL ERC against this schematic; raise ERCFailure on errors."""
        from skidl import ERC
        from skidl.logger import erc_logger

        self.ERC()
        result = {
            "errors": erc_logger.error.count,
            "warnings": erc_logger.warning.count,
        }
        if result["errors"]:
            raise ERCFailure(
                f"{self.name}: ERC found {result['errors']} error(s), "
                f"{result['warnings']} warning(s)"
            )
        return result

    def validate(self, allow_input: bool = True) -> list[Any]:
        """Run every part's attached rules; raise RuleFailure on violations.

        Returns the full list of RuleOutcome objects (pass included) so
        callers/tests can inspect detail.
        """
        outcomes = check_all(list(self.parts), allow_input=allow_input)
        bad = [o for o in outcomes if not o.ok]
        if bad:
            detail = "; ".join(f"{o.part}/{o.rule}: {o.detail}" for o in bad)
            raise RuleFailure(f"{self.name}: {len(bad)} rule violation(s): {detail}")
        return outcomes

    # ---- outputs ---------------------------------------------------------

    def netlist(self, outdir: Path) -> Path:
        """Write the KiCad netlist into outdir and return its path."""
        outdir.mkdir(parents=True, exist_ok=True)
        net_file = outdir / f"{self.name}.net"
        # generate_netlist returns the netlist STRING; the file is written
        # via file_. (Learned the hard way — do not treat the return as path.)
        self.generate_netlist(tool=KICAD10, file_=str(net_file))
        return net_file

    def svg(self, outdir: Path) -> Path:
        """Render the schematic SVG into outdir; returns the output dir."""
        outdir.mkdir(parents=True, exist_ok=True)
        svg_dir = self.generate_svg(
            tool=KICAD10, top_name=self.name, filepath=str(outdir)
        )
        return Path(svg_dir)

    # ---- simulation seam ---------------------------------------------------

    def spice_netlist(self) -> Any:
        """Convert passives and return the InSpice netlist for simulation.

        Device-library R/C/L get SKiDL's automatic SPICE models; any other
        part must have been given a model by the design (raise loudly
        otherwise — a silently missing part invalidates every result).
        """
        from skidl import SPICE
        from skidl.pyspice import C as SC, L as SL, R as SR

        converters = {
            "R": (SR, {1: "p", 2: "n"}),
            "C": (SC, {1: "p", 2: "n"}),
            "L": (SL, {1: "p", 2: "n"}),
        }
        missing: list[str] = []
        for p in list(self.parts):
            # Custom partslib parts bring their own model + pin map.
            template_fn = getattr(p, "spice_template", None)
            if callable(template_fn):
                p.convert_for_spice(template_fn(), p.spice_pin_map())
                continue
            # Part.lib is a SchLib object; the library name is .filename.
            if getattr(p.lib, "filename", None) == "Device" and p.name in converters:
                cls, pin_map = converters[p.name]
                p.convert_for_spice(cls, pin_map)
        set_default_tool(SPICE)
        missing = [
            f"{p.ref} ({getattr(p.lib, 'filename', '?')}:{p.name})"
            for p in self.parts
            if not hasattr(p, "spice_pins")
        ]
        if missing:
            raise ValueError(
                f"{self.name}: parts without SPICE models: {missing}. "
                "Attach models in content() or exclude them from simulation."
            )
        # Instance method: after build() the context is closed, so the
        # module-level generate_netlist() would see the empty global default.
        return self.generate_netlist(tool=SPICE)
