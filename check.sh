#!/usr/bin/env bash
# SchemAItic workflow gate: type-check before anything else may run.
# Usage: ./check.sh [files...]   (default: schemaitic/)
set -euo pipefail
cd "$(dirname "$0")"
TARGETS=("${@:-schemaitic}")
.venv/bin/mypy --config-file mypy.ini "${TARGETS[@]}"
echo "mypy: clean"
