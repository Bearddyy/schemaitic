"""Grounded nets as a type: Ground(Net) with ``net.ground is True``.

Making ground a *type* instead of a naming convention means rules check
``isinstance(net, Ground)`` / ``net.ground`` instead of regex-matching names,
and mypy can see the intent where the object is constructed. SKiDL itself has
no ground subclass (ground is just a Net named GND), so we add ours and
install one audited compatibility patch: SKiDL's ``Pin.is_connected``
compares ``type(n) == Net`` exactly and would reject any subclass as
"connected to something strange" during ERC.

Import this module (anything that builds schematics does) to activate both.
"""

from __future__ import annotations

import re
from typing import Any

from skidl import Net

__all__ = ["Ground", "is_ground_net"]

# Naming fallback so plain strings/SKiDL nets still validate: GND, VSS,
# EARTH, CHASSIS, AGND/DGND, STAR_GND ...
_GROUND_NAME_RE = re.compile(r"(?:\b|[_\-])(?:gnd|ground|vss|earth|chassis)(?:\b|[_\-])|^gnd$|^vss$", re.IGNORECASE)


class Ground(Net):
    """A net that IS ground by type, not by spelling.

    Everything connected to it is ground: SKiDL keeps the same object when
    nets merge through components (verified against SKiDL 3.0), so the
    ``ground`` property survives the whole chain.
    """

    @property
    def ground(self) -> bool:
        """Always True; exists so generic Net-handling code can ask."""
        return True


def is_ground_net(net: Any) -> bool:
    """True for Ground instances and conventionally-named ground nets.

    Accepts Any because pin.nets may yield SKiDL Net objects (untyped
    upstream); anything with a truthy ``ground`` attribute or a ground-like
    name qualifies so hand-written SKiDL examples stay valid.
    """
    if getattr(net, "ground", False):
        return True
    name = getattr(net, "name", "")
    return bool(_GROUND_NAME_RE.search(str(name)))


# ---------------------------------------------------------------------------
# Audited compatibility patch (see module docstring). Idempotent.
# ---------------------------------------------------------------------------

def _install_erc_compatibility() -> None:
    import skidl.pin as spin
    from skidl.net import NCNet

    original = spin.Pin.is_connected
    if getattr(original, "_schemaitic_ground_patch", False):
        return

    def is_connected(self: Any) -> bool:
        if not self.nets:
            return False
        net_types = {type(n) for n in self.nets}
        if net_types == {NCNet}:
            return False
        # Tolerate Net subclasses (Ground); delegate genuinely odd types.
        if all(issubclass(t, (Net, NCNet)) for t in net_types):
            return True
        return bool(original(self))

    is_connected._schemaitic_ground_patch = True  # type: ignore[attr-defined]
    spin.Pin.is_connected = is_connected


_install_erc_compatibility()
