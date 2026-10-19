#!/usr/bin/env bash
# SchemAItic workflow gate: type-check before anything else may run.
# Usage: ./check.sh [files...]   (default: tools/)
set -euo pipefail
cd "$(dirname "$0")"
TARGETS=("${@:-tools}")
.venv/bin/mypy --config-file mypy.ini "${TARGETS[@]}"
echo "mypy: clean"
