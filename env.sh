# Source this before running SKiDL scripts:  source env.sh  (bash/sh)
# SKiDL 3.x looks for version-specific vars (KICAD6..KICAD10).
LIBS="$HOME/repos/schemaitic/kicad-libs"
for v in 6 7 8 9 10; do
  export KICAD${v}_SYMBOL_DIR="$LIBS/symbols"
  export KICAD${v}_FOOTPRINT_DIR="$LIBS/footprints"
done
export KICAD_SYMBOL_DIR="$LIBS/symbols"
export KICAD_FOOTPRINT_DIR="$LIBS/footprints"
