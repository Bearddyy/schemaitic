# SchemAItic

AI-generated schematics and electronics design tool.

## Goals

- Turn natural-language descriptions of circuits into schematics and netlists.
- Stay interoperable with standard tools: KiCad (s-expr schematics/footprints), SPICE netlists, SVG/PNG rendering for quick review.
- Ship as a reusable skill so an AI agent can generate, review, and iterate on designs.

## Layout

```
tools/       Generator and validation scripts
examples/    Example designs (schematic + netlist pairs)
templates/   Starting points for common circuit blocks
```

## Status

Early skeleton. Stack decisions not yet made — see SKILL.md.
