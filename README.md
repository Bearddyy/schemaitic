# SchemAItic

Electronics design where the circuit is Python. One typed, object-oriented
description is the single source of truth for:

- **Schematics** — KiCad netlists and SVG drawings
- **Validation** — ERC plus datasheet-derived rules (grounding, pull
  straps, mode-dependent constraints) that fail the build before hardware exists
- **Simulation** — SPICE runs that assert design specs (cutoff frequency,
  DC bias, rejection) like unit tests do for software

## A design looks like this

```python
class LpfDivider(Schematic):
    """VI --10K-- VO --4.7K-- GND with C across R2."""

    DEFAULTS: dict[str, ValueLike] = {"R_top": "10K", "R_bot": "4.7K", "C": "100N"}

    def content(self, **params: ValueLike) -> None:
        p = {**self.DEFAULTS, **params}
        vin, vout = Net("VI"), Net("VO")
        gnd = Ground("GND")
        r1 = Resistor("R1", p["R_top"])
        r2 = Resistor("R2", p["R_bot"], rules=(GroundedRule(2),))
        c1 = Capacitor("C1", p["C"], rules=(GroundedRule(2),))
        vin & r1 & vout & (r2 | c1[1, 2]) & gnd

    def design_tests(self) -> list[Simulation]:
        # cap sees R1||R2: fc = 1/(2*pi*(R1||R2)*C)
        fc = 1.0 / (2 * math.pi * (10e3 * 4.7e3 / 14.7e3) * 100e-9)
        return [
            OperatingPoint(node="vo", expect_v=1.5986, tolerance_v=0.005),
            LowPassFilter("vo", cutoff_hz=fc, rejection_hz=10e3,
                          min_rejection_db=-20.0),
        ]
```

Values are typed (`"10K"`, `"100n"`, `10e3` — garbage raises at construction),
ground is a *type* (`Ground`), and the circuit's spec ships with it: change
the capacitor to the wrong value and `schemaitic test` fails with
`cutoff~498Hz: measured 51.6 Hz`.

## Quick start

```bash
git clone <this repo> && cd schemaitic
./setup.sh                    # venv, deps (editable install), KiCad libs, gates
source env.sh                 # KiCad library paths for this shell
source .venv/bin/activate     # brings in the `schemaitic` command

# the stages (each chains whatever it needs)
schemaitic validate examples/lpf_divider.py --no-input
schemaitic test examples/lpf_divider.py
schemaitic sim examples/vdivider.py --sweep C=1N,10N,100N,1U --plot out/sweep.png
schemaitic netlist examples/lpf_divider.py
```

Pipeline: `build circuit -> ERC -> rules -> KiCad netlist/SVG -> SPICE -> ngspice`

Requirements: Python 3.12+ (3.14 used here) and ngspice
(`pacman -S ngspice` / `apt install ngspice`); setup warns if missing.

## Layout

```
schemaitic/          The Python package (pip install -e .; import from anywhere)
  __init__.py          Public API: re-exports SKiDL primitives + everything below
  values.py            Value: typed electrical values (10K, 4.7k, 100n -> SI floats)
  nets.py              Ground: ground-like nets as a TYPE, not a naming convention
  parts.py             Resistor/Capacitor/Inductor/Led: typed values, rules= kwarg
  rules.py             Rule engine: GroundedRule, PullRule, ModeRule, NoConnectRule...
  schematic.py         Schematic: owns a design; build/erc/validate/netlist/svg/spice
  simulations.py       Design tests: OperatingPoint, ACResponse, LowPassFilter, TransientPulse
  cli.py               CLI stages: info | erc | validate | netlist | sim | test
  partslib/            Custom parts, digitised once, reused across designs
    <part>/              python class (pins, rules, spice_template) + .kicad_sym + model.lib
examples/          Example designs (lpf_divider = reference; broken_lpf = negative control)
tests/             pytest suite: rules engine, simulations, CLI end-to-end
templates/         Starting points for common circuit blocks
```

Designs import only the package — never `skidl` directly, never path hacks:

```python
from schemaitic import Ground, Net, Resistor, Capacitor, Schematic
from schemaitic.rules import GroundedRule
from schemaitic.simulations import LowPassFilter
```

## Rules engine

Every part carries `part.rules` — checks extracted from the datasheet when
the part was digitised, run on every `validate`:

| Rule | Checks |
| --- | --- |
| `GroundedRule(pin)` | pin lands on a ground net (`Ground` type first, name fallback) |
| `PullRule(pin, {HIGH, LOW, FLOATING}, max_ohms=)` | strap termination: resistor to rail/ground within value bounds, hard strap on recognisable rails, or intentionally floating |
| `ModeRule(pin, mode_requirements, mode_rules)` | part declares `mode=` at construction; strap must match the mode, and the mode's extra rules are injected at check time |
| `NoConnectRule` / `PinOnNetRule` | NC pins unused; pin on a named net |
| `ManualRule` | human check via prompt; fails closed with `--no-input` (CI-safe) |

New rule types extend `Rule`; `Rule.apply_to(part, mode)` lets any rule
re-parameterise or drop itself per mode.

## Simulation as design tests

A `Simulation` receives a built `Schematic` (dependency injection), attaches
stimulus to the netlist copy, runs ngspice, measures, and asserts. A failing
sim is a design regression, not a suggestion:

- `OperatingPoint(node, expect_v=...)` — DC bias within tolerance
- `LowPassFilter(node, cutoff_hz=, rejection_hz=, min_rejection_db=, expected_passband_db=)` — measured -3 dB cutoff (log-interpolated), stopband rejection, passband gain
- `TransientPulse(node, expect_final_v=...)` — PULSE stimulus, plateau check
- Subclass `ACResponse` / `Simulation` for your own analyses

`schemaitic test <design>` runs the tests declared in `design_tests()`,
writes `out/design_tests.json`, exits 1 on any violation.
`examples/broken_lpf.py` must fail — it guards that the assertions actually fire.

## Parts library

Digitise a part once in `schemaitic/partslib/<name>/`: Python class with typed pins,
datasheet rules, and SPICE model metadata, plus the `.kicad_sym` symbol and
a `.lib` subckt. Designs import the class and get symbol, sim model, and
rule checks automatically. `schemaitic/partslib/tl431/` is the reference implementation.

## Quality gates

- `./check.sh` — mypy strict over `schemaitic/ tests/ examples/`; hard gate, wired
  into `setup.sh`
- `.venv/bin/python -m pytest tests/ -q` — 60 tests incl. CLI subprocess
  end-to-end and negative controls
- Ideology: fail early and loudly — bad values, wrong types, broken specs
  raise at construction/check time, never silently downstream

## Stack

- [SKiDL 3.x](https://github.com/devbisme/skidl) — circuit description, KiCad
  netlist, SVG (via schematizer), SPICE conversion
- [InSpice](https://github.com/inryu112/InSpice) + ngspice — AC/transient
  sims from the same Python source
- KiCad symbol/footprint libraries cloned from
  [GitLab](https://gitlab.com/kicad/libraries) (GitHub mirrors are stale)

For AI agents working in this repo: see [AGENTS.md](AGENTS.md).
