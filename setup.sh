#!/usr/bin/env bash
# SchemAItic deployment script: creates the venv, installs dependencies,
# and fetches the KiCad symbol/footprint libraries SKiDL needs.
#
# Usage:  ./setup.sh            (from the repo root)
# Then:   source env.sh && .venv/bin/python examples/divider.py
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
LIBS="$REPO/kicad-libs"

echo "==> Python venv at $REPO/.venv"
if [ ! -x "$REPO/.venv/bin/python" ]; then
  "$PYTHON" -m venv "$REPO/.venv"
fi
"$REPO/.venv/bin/pip" install --upgrade pip -q
"$REPO/.venv/bin/pip" install -q skidl schematizer

# KiCad 6+ stores stock libraries as .kicad_symdir directories of .kicad_sym
# files; SKiDL 3.x reads that format. The authoritative, current libraries are
# on GitLab (the GitHub mirrors are stale v4/v5 .lib files - do not use them).
echo "==> KiCad libraries"
mkdir -p "$LIBS"
clone_lib() {
  local name="$1" url="$2"
  if [ ! -d "$LIBS/$name/.git" ]; then
    git clone --depth 1 "$url" "$LIBS/$name"
  else
    echo "    $name already present, skipping clone"
  fi
}
clone_lib symbols    https://gitlab.com/kicad/libraries/kicad-symbols
clone_lib footprints https://gitlab.com/kicad/libraries/kicad-footprints

echo "==> Smoke test"
cd "$REPO/examples"
# shellcheck disable=SC1091
source "$REPO/env.sh"
"$REPO/.venv/bin/python" divider.py > /dev/null 2>&1 \
  && echo "    divider.py OK (netlist + SVG generated)" \
  || { echo "    smoke test FAILED - run examples/divider.py manually"; exit 1; }

echo "Done. Usage: source env.sh && .venv/bin/python <script>.py"
