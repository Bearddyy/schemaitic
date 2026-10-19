---
name: schemaitic
description: Generate and review AI-designed electronic schematics with SchemAItic.
---

# SchemAItic — AI schematic & electronics design

Repo: `~/repos/schemaitic`

## When to use

- Dan asks for a circuit schematic, netlist, component selection, or circuit review.
- Dan asks to extend the SchemAItic tooling itself.

## Workflow

1. Capture the requirement (inputs, outputs, voltages, currents, constraints).
2. Draft the design as text first (component list + netlist) and show Dan before rendering.
3. Emit standard formats where possible: KiCad schematic s-exprs, SPICE netlists, SVG for review.
4. Validate: ERC-style sanity checks (pins connected, no floating inputs, rail voltages consistent) before declaring done.

## Conventions

- Prefer tool-interoperable standard formats over custom ones.
- Show diffs/text for review before committing.
- Keep every design in `examples/` with its generated artifacts side by side.

## Stack (decided Oct 2026)

- SKiDL 3.0 + schematizer (pip) in `.venv`.
- KiCad symbol/footprint libs cloned from **GitLab** (`gitlab.com/kicad/libraries/kicad-symbols|kicad-footprints`) into `kicad-libs/` — the GitHub mirrors are stale v4/v5 `.lib` format and do NOT work with SKiDL 3.x (it needs KiCad 6+ `.kicad_sym`/`.kicad_symdir`).
- `source env.sh` before running (sets `KICAD6..10_SYMBOL_DIR`/`KICAD{6..10}_FOOTPRINT_DIR`; plain `KICAD_SYMBOL_DIR` is not enough).
- Deploy elsewhere: `./setup.sh` (venv + pip + libs + smoke test).
- Outputs: `generate_netlist(tool=KICAD10)` -> .net, `generate_svg(tool=KICAD10, top_name=...)` -> .svg. Both kwargs-only.

## Open decisions

- Rendering review workflow (SVG placement is randomized per run — keep outputs you like).
- Part library search strategy (`search_parts_in_libs` vs. curated subset).
