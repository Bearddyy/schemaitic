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
- InSpice + ngspice for sims; AC results: `wf.frequency`, complex `wf["vo"]` for dB assertions.

## Typed OO layer (Oct 2026)

- `schemaitic/values.py` `Value`: typed electrical values; construct with `10e3`, `"10K"`, `"100n"`; `.si` float, `.spice()` engineering string. Garbage raises at construction.
- `schemaitic/nets.py` `Ground(Net)`: ground as a TYPE (`.ground` property). SKiDL ERC compares `type(n) == Net` exactly, so nets.py carries an audited `Pin.is_connected` compat patch — never duplicate it.
- `schemaitic/parts.py`: `Resistor("R1", "10K", footprint=..., rules=(...), mode=...)`; unknown kwargs rejected; `mode=` declares operating mode (see ModeRule).
- `schemaitic/schematic.py` `Schematic(Circuit)`: subclass implements `content()`, call `build(**params)` (full reset each rebuild — fresh nets inside the context; never reuse held nets across rebuilds). `erc()`/`validate()` raise on failure; `spice_netlist()` converts Device passives plus partslib parts carrying `spice_template`. Must call the *instance* `generate_netlist(tool=SPICE)` — the module-level function sees the empty global circuit after the context closes.
- `schemaitic/partslib/<name>/`: custom part defined once — python class (pins, datasheet rules, `spice_template`) + `.kicad_sym` + `model.lib` (suffix must be `.lib`/`.spice`, not `.sp`).

## Rules engine

- Part carries `part.rules` (tuple of `Rule`); `attach_rules()` merges and type-checks.
- `GroundedRule` (type-first via `Ground`), `PullRule(pin, {HIGH|LOW|FLOATING}, max_ohms=)` strap termination incl. resistor bounds, hard-strap accepted only on recognisable rails, `NoConnectRule`, `PinOnNetRule`, `LambdaRule`, `ManualRule` (input(); fails closed `--no-input`).
- `ModeRule(pin, mode_requirements, mode_rules)`: part declares `mode=` at construction; rule checks strap termination matches the mode and injects mode-implied extra rules. `effective_rules(part)` resolves; `check_part` uses it. Any rule can re-parameterise per mode via `Rule.apply_to(part, mode)`.

## Simulation design tests (Oct 2026)

- `schemaitic/simulations.py`: `Simulation.run(schematic) -> SimulationResult`; `result.assert_passed()` raises `SimFailure`. Built-ins: `OperatingPoint`, `ACResponse`, `LowPassFilter` (cutoff/rejection/passband assertions), `TransientPulse`.
- Designs declare `design_tests() -> list[Simulation]`; CLI stage `test` discovers the module-local `Schematic` subclass, runs the tests, writes `out/design_tests.json`, exit 1 on violation. Negative control: `examples/broken_lpf.py` must FAIL.
- InSpice gotchas (proven): inject sources on the NETLIST object (`nl.V("VSRC", pos, neg, ac_value=1 @ u_V)`); source ref must differ from node names it drives (InSpice keys both). Waveform node keys are LOWERCASE net names. PULSE: `src.dc_value = None; src.tran_value = "PULSE(...)"`.
- Physics the assertion caught: filter cap sees R1||R2 (ideal source is 0 ohms AC), not R2 alone — fc = 1/(2 pi (R1||R2) C).
- `content()` overrides must keep the base `**params: ValueLike` signature (mypy strict override check); use a `DEFAULTS: dict[str, ValueLike]` class attr merged with params.

## Open decisions

- Rendering review workflow (SVG placement is randomized per run — keep outputs you like).
- Part library search strategy (`search_parts_in_libs` vs. curated subset).
