"""Pytest configuration: make tools/ importable and set KiCad lib paths.

Tests that instantiate SKiDL parts need KICAD{6..10}_SYMBOL_DIR/FOOTPRINT_DIR
(the same exports env.sh provides), so they can run via bare `pytest` without
sourcing anything first.
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

LIBS = REPO / "kicad-libs"
for _v in range(6, 11):
    os.environ.setdefault(f"KICAD{_v}_SYMBOL_DIR", str(LIBS / "symbols"))
    os.environ.setdefault(f"KICAD{_v}_FOOTPRINT_DIR", str(LIBS / "footprints"))
