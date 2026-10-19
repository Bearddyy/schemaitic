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
  schemaitic.py CLI: netlist | svg | validate | sim (+ sweeps)
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
