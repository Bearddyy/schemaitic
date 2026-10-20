# AGENTS.md — working on SchemAItic

Instructions for AI agents (and humans) modifying this repo. The user-facing
overview is in [README.md](README.md); this file is about *how to work here*.

## Non-negotiables

1. **mypy strict is a hard gate.** `./check.sh tools tests examples` must be
   clean before committing. Everything on top of SKiDL/InSpice is annotated;
   only the audited boundary code in `nets.py`/`parts.py` may lean on `Any`.
2. **Run the full suite** before committing:
   `bash -c 'source env.sh && .venv/bin/python -m pytest tests/ -q'`
3. **Every new check needs a negative control.** A rule or design test that
   can never fail is worse than none — see `examples/broken_lpf.py` and the
   failing cases in `tests/`.
4. **Commit small and often** with imperative messages; update README and
   this file when behaviour or conventions change.
5. **Show Dan diffs/text for review before edits to his designs**;
   no AI-sounding language in user-facing prose.

## Environment

- Always `source env.sh` first (or wrap: `bash -c 'source env.sh && ...'`).
  KiCad 10 tooling needs `KICAD6..10_SYMBOL_DIR`/`_FOOTPRINT_DIR` pointing at
  `kicad-libs/` — plain `KICAD_SYMBOL_DIR` is not enough.
- Python: `.venv/bin/python` (3.14). ngspice is a system package
  (`pacman -S ngspice` / `apt install ngspice`).
- SKiDL writes scratch (`*.erc`, `*.log`, `*_sklib.py`, `*.net`) next to the
  CWD — gitignored, but clean up after probe runs; don't commit it.
- Throwaway probes go in `out/` (gitignored), never in the repo root.

## Architecture invariants

- `Schematic` subclasses implement `content(self, **params: ValueLike)`.
  Overrides MUST keep the `**params` signature (mypy override check); put
  defaults in a `DEFAULTS: dict[str, ValueLike]` class attribute and merge
  `p = {**self.DEFAULTS, **params}`.
- `build()` does a full SKiDL reset each call (sweeps rebuild repeatedly):
  never hold nets/parts across rebuilds; create them inside `content()`.
- After the build context closes, generate netlists with the **instance**
  method `self.generate_netlist(tool=...)` — the module-level function sees
  the restored empty global circuit.
- `Ground(Net)` in `nets.py` carries an audited `Pin.is_connected` patch
  because SKiDL ERC compares `type(n) == Net` exactly. Never duplicate or
  remove it.
- SKiDL nets merge by **object identity**, not name.
- `part.lib` is a `SchLib` object, not a string: check
  `getattr(p.lib, "filename", None) == "Device"`.
- SKiDL 3 has no `unwire`; rebuild a circuit to change topology.
- Simulations must not mutate the design: stimulus goes on the netlist copy
  (`nl.V("VSRC", pos, neg, ...)`); the source ref must differ from the node
  names it drives; waveform keys are lowercase net names.
- Filter physics the assertion caught once and will catch again: a cap at an
  op node sees R1||R2 (an ideal source is a dead short for AC), not R2 alone.

## Adding things

- **New rule type**: subclass `Rule` in `tools/rules.py`, implement
  `check(part) -> RuleOutcome`; optional `apply_to(part, mode)` for
  mode-dependent re-parameterisation. Add pass + fail unit tests in
  `tests/test_rules.py`.
- **New simulation type**: subclass `Simulation` (or `ACResponse`) in
  `tools/simulations.py`; populate `SimulationResult` via `res.check(...)`;
  add an end-to-end test with a negative control.
- **New custom part**: create `partslib/<name>/` with `__init__.py`, typed
  class (pins, datasheet `rules=(...)`, `spice_template`), `<NAME>.kicad_sym`,
  and `model.lib` (extension must be `.lib`/`.spice`, not `.sp`).
  `partslib/tl431/` is the reference.
- **New design**: `examples/<name>.py` with a `Schematic` subclass, a
  `build()` wrapper for the legacy stages, and `design_tests()` where a
  spec exists.

## CLI contract

`schemaitic.py <stage> <design.py>` — `info | erc | validate | netlist | sim | test`

- stdout is JSON (machine contract — keep it parseable; numpy arrays are a
  classic leak, serialise with `default=str`); progress goes to stderr.
- `--no-input` must fail closed (no `input()` ever in CI paths).
- Exit codes: 0 pass, 1 violation/error. `test` writes `out/design_tests.json`.

## Known upstream quirks

- KiCad lib sources: use **GitLab** (`gitlab.com/kicad/libraries/...`);
  GitHub mirrors are stale v4/v5 formats incompatible with SKiDL 3.x.
- InSpice warns "Newer Ngspice version that could be unsupported 47" —
  harmless; results verified against hand calculation.
- Legacy star-import sketches in `examples/` get lenient mypy treatment via
  per-module config in `mypy.ini`; new code gets no such exemption.

## Verification before "done"

1. `./check.sh tools tests examples` → `mypy: clean`
2. `.venv/bin/python -m pytest tests/ -q` → all pass (60 at time of writing)
3. Affected CLI stages re-run manually on `examples/lpf_divider.py` (must
   pass) and `examples/broken_lpf.py` (must fail with exit 1)
4. Docs updated (README/this file/SKILL.md) when scope changed; committed.
