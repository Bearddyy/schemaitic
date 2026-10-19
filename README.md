# SchemAItic

Python-single-source electronics design: schematics, netlists, validation,
and SPICE simulation from one typed, object-oriented circuit description.

## Workflow

Everything runs from the Python description; each stage chains the steps it
needs, so there is no fixed script ordering to remember:

```
build circuit -> ERC -> rules validation -> KiCad netlist/SVG -> SPICE netlist -> ngspice
```

```bash
source env.sh                                   # KiCad lib paths
./check.sh                                      # mypy --strict gate
.venv/bin/python -m pytest tests/ -q            # unit + CLI tests
.venv/bin/python tools/schemaitic.py validate examples/rules_demo.py --no-input
.venv/bin/python tools/schemaitic.py sim examples/vdivider.py --sweep C=1N,10N,100N,1U --plot out/sweep.png
```

## Layout

```
tools/        Typed core + CLI
  values.py     Value: typed electrical values (10K, 4.7k, 100n parse to SI floats)
  nets.py       Ground: ground-like nets as a TYPE (.ground), not a naming convention
  parts.py      Resistor/Capacitor/Inductor/Led with typed values and rules= kwargs
  rules.py      Rule engine: GroundedRule, PullRule, ModeRule, NoConnectRule, ...
  schematic.py  Schematic: owns a design; build/erc/validate/netlist/svg/spice_netlist
  simulations.py Design tests: OperatingPoint, LowPassFilter, TransientPulse
  schemaitic.py CLI: netlist | svg | validate | sim | test (+ sweeps)
partslib/     Reusable custom parts, defined once, shared across designs
  <part>/       python class (pins, rules, spice_template) + .kicad_sym + model.lib
examples/     Example designs
tests/        pytest suite (rules engine + CLI end-to-end)
templates/    Starting points for common circuit blocks
```

## Rules

Every part carries `part.rules`: datasheet-derived checks that run on every
`validate` and can fail the build before hardware exists.

- `GroundedRule(pin)` — pin must land on a ground net (type-checked via
  `Ground`, name-pattern fallback for plain SKiDL nets).
- `PullRule(pin, {HIGH, LOW, FLOATING}, max_ohms=...)` — strap termination:
  resistor to a rail, hard strap, or intentionally floating; resistor value
  bounds enforced.
- `ModeRule(pin, mode_requirements, mode_rules)` — declare the operating mode
  at construction (`SomeChip(ref="U1", mode="sleep")`); the rule verifies the
  strap pin matches the mode AND injects the extra rules that mode implies, so
  downstream rules change with the part's configuration.
- `NoConnectRule`, `PinOnNetRule`, `LambdaRule`, `ManualRule` (prompts; fails
  closed with `--no-input`).

New rule types extend `Rule`; `Rule.apply_to(part, mode)` lets any rule
re-parameterise or drop itself per mode at check time.

## Parts library

Digitise a part once in `partslib/<name>/`: a Python class with typed pins,
rules extracted from the datasheet, and SPICE model metadata; plus the
`.kicad_sym` symbol and a `.lib` SPICE subckt. Designs import the class and
get symbol, sim model, and rule checks automatically. `partslib/tl431/` is
the reference implementation.

## Simulation as design tests

`tools/simulations.py` turns SPICE into assertions. A `Simulation` receives a
built `Schematic` (dependency injection), attaches stimulus to the netlist
copy, runs ngspice, measures, and asserts — a failing sim is a design
regression, not a suggestion.

- `OperatingPoint(node, expect_v=...)` — DC bias within tolerance.
- `LowPassFilter(node, cutoff_hz=, rejection_hz=, min_rejection_db=)` —
  measured -3 dB cutoff (log-interpolated) within tolerance, stopband
  rejection met, optional passband-gain check.
- `TransientPulse(node, expect_final_v=...)` — PULSE stimulus, plateau check.
- Subclass `ACResponse`/`Simulation` for your own analyses.

Declare the spec next to the circuit:

```python
class LpfDivider(Schematic):
    def design_tests(self) -> list[Simulation]:
        return [OperatingPoint(...), LowPassFilter(...)]
```

Then `tools/schemaitic.py test examples/lpf_divider.py` runs them and exits 1
on any violation (`out/design_tests.json` has the per-assertion detail).
`examples/broken_lpf.py` is the negative control: same spec, 10x capacitor,
must fail.

## Stack

- [SKiDL 3.x](https://github.com/devbisme/skidl) — circuit description, KiCad
  netlist, SVG (via schematizer), SPICE conversion.
- [InSpice](https://github.com/inryu112/InSpice) + ngspice — AC/transient sims
  from the same Python source.
- KiCad symbol/footprint libs cloned from GitLab (see `setup.sh`).
- mypy --strict is a hard gate (`check.sh`, wired into `setup.sh`).

## Setup

`./setup.sh` creates the venv, installs deps, clones the KiCad libraries,
runs the type gate and tests. ngspice needs the system package
(`pacman -S ngspice`); setup warns if it is missing.
