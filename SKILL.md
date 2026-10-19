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

## Open decisions

- Core generation stack (KiCad Python API vs. custom s-expr emitter vs. netlist-only).
- Rendering path for quick visual review.
- Part library source (KiCad libraries vs. a curated subset).
