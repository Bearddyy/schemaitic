"""Pytest configuration: set KiCad lib paths for bare-`pytest` runs.

Tests that instantiate SKiDL parts need KICAD{6..10}_SYMBOL_DIR/FOOTPRINT_DIR
(the same exports env.sh provides), so they can run without sourcing anything.
The schemaitic package itself is installed (pip install -e .), so no sys.path
hacks live here or in any test.
"""

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

LIBS = REPO / "kicad-libs"
for _v in range(6, 11):
    os.environ.setdefault(f"KICAD{_v}_SYMBOL_DIR", str(LIBS / "symbols"))
    os.environ.setdefault(f"KICAD{_v}_FOOTPRINT_DIR", str(LIBS / "footprints"))
