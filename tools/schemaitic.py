#!/usr/bin/env python3
"""SchemAItic CLI: run the whole design flow from one Python circuit source.

The circuit file is the single source of truth. It must define:

    build(**params)   - construct the circuit with SKiDL (called after reset()).
                        Keyword params support sweeps (e.g. C="100N").

It may define:

    spice(circuit)    - given the InSpice Circuit object, add sources and
                        return a list of analysis dicts, e.g.:
                        [{"type": "op"},
                         {"type": "tran", "step": 1e-5, "end": 1e-2,
                          "plot": ["vi", "vo"]}]

Stages (each runs every prior stage it needs; no fixed script order):
    info    parts, nets, and sweep parameters of the circuit
    erc     electrical rules check
    validate datasheet rules attached to parts (part.rules)
    netlist KiCad netlist + SVG schematic
    sim     SPICE: convert parts, emit netlist, run ngspice, print JSON

Examples:
    schemaitic sim examples/vdivider.py
    schemaitic sim examples/vdivider.py --sweep C=1N,10N,100N,1U --plot out.png
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import types
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rules as design_rules

# KiCad library parts SKiDL can translate to SPICE automatically.
AUTO_SPICE = {
    "R": ("R", {1: "p", 2: "n"}),
    "C": ("C", {1: "p", 2: "n"}),
    "L": ("L", {1: "p", 2: "n"}),
}


def load_module(path: Path) -> types.ModuleType:
    """Execute a circuit description file and return its module namespace."""
    spec = importlib.util.spec_from_file_location("schemaitic_circuit", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load circuit file: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "build"):
        raise SystemExit(f"{path}: circuit file must define build(**params)")
    return mod


def parse_sweep(spec: str | None) -> tuple[str, list[str]] | None:
    """Parse --sweep NAME=v1,v2,... into (name, [v1, v2, ...])."""
    if spec is None:
        return None
    name, _, values = spec.partition("=")
    if not _ or not values:
        raise SystemExit('--sweep expects NAME=v1,v2,...')
    return name, values.split(",")


def build_circuit(mod: types.ModuleType, params: dict[str, Any]) -> dict[str, int]:
    """Reset SKiDL state, construct the circuit, and run ERC.

    ERC() returns None in SKiDL 3.x; results live in the ERC logger's
    counters, which ERC() resets at the start of each run. Read them
    right after the call.
    """
    from skidl import KICAD10, ERC, reset, set_default_tool
    from skidl.logger import erc_logger

    reset()
    # reset() drops tool config; the KiCad libs are the part source of truth.
    set_default_tool(KICAD10)
    mod.build(**params)
    ERC()
    return {"errors": erc_logger.error.count, "warnings": erc_logger.warning.count}


def stage_info(mod: types.ModuleType, sweep: tuple[str, list[str]] | None) -> None:
    build_circuit(mod, {})
    ckt = design_rules.default_circuit()
    print(f"parts: {len(ckt.parts)}")
    for p in ckt.parts:
        print(f"  {str(p.ref):5} {getattr(p.lib, 'filename', '?')}:{p.name} value={p.value}")
    print(f"nets:  {len(ckt.nets)}")
    for n in ckt.nets:
        print(f"  {n.name}")
    if sweep:
        print(f"sweep: {sweep[0]} in {sweep[1]}")


def stage_erc(mod: types.ModuleType) -> None:
    erc = build_circuit(mod, {})
    payload: dict[str, Any] = {"warnings": erc["warnings"], "errors": erc["errors"]}
    print(json.dumps(payload, indent=2))
    if erc["errors"]:
        sys.exit(1)


def stage_validate(mod: types.ModuleType, allow_input: bool) -> None:
    """Build the circuit, then run every part's attached rules."""
    build_circuit(mod, {})
    ckt = design_rules.default_circuit()
    outcomes = design_rules.check_all(
        list(ckt.parts), allow_input=allow_input
    )
    payload = [
        {
            "part": o.part,
            "rule": o.rule,
            "status": o.status.value,
            "detail": o.detail,
        }
        for o in outcomes
    ]
    print(json.dumps(payload, indent=2))
    if not all(o.ok for o in outcomes):
        sys.exit(1)


def stage_netlist(mod: types.ModuleType, outdir: Path) -> None:
    from skidl import KICAD10, generate_netlist, generate_svg

    build_circuit(mod, {})
    outdir.mkdir(parents=True, exist_ok=True)
    net_file = outdir / "design.net"
    # generate_netlist returns the netlist STRING (and writes it to file_);
    # it is not a path, despite the variable name it used to be given.
    generate_netlist(tool=KICAD10, file_=str(net_file))
    svg_dir = generate_svg(tool=KICAD10, top_name="design", filepath=str(outdir))
    print(json.dumps({"netlist": str(net_file), "svg_dir": str(svg_dir)}))


def run_spice(mod: types.ModuleType, params: dict[str, Any]) -> dict[str, Any]:
    """One full SPICE pass: build, convert, netlist, simulate, collect."""
    import numpy as np

    from skidl import KICAD10, SPICE, generate_netlist, set_default_tool

    erc = build_circuit(mod, params)

    # Auto-convert plain Device passives; anything else needs a model hook.
    ckt = design_rules.default_circuit()
    from skidl.pyspice import C as SC, L as SL, R as SR

    converters = {"R": SR, "C": SC, "L": SL}
    for p in list(ckt.parts):
        # Part.lib is a SchLib object in SKiDL 3.x; the lib name is .filename.
        if getattr(p.lib, "filename", None) == "Device" and p.name in AUTO_SPICE:
            spice_cls, pin_map = AUTO_SPICE[p.name]
            p.convert_for_spice(converters[spice_cls], pin_map)

    set_default_tool(SPICE)
    # convert_for_spice() tags parts with `spice_pins` in place (it does NOT
    # change part.tool), so unconverted parts are the ones lacking it.
    unmapped = [
        f"{p.ref} ({getattr(p.lib, 'filename', '?')}:{p.name})"
        for p in ckt.parts
        if not hasattr(p, "spice_pins")
    ]
    circuit = generate_netlist()
    if not hasattr(mod, "spice"):
        raise SystemExit(
            "circuit file must define spice(circuit) to add sources and "
            "return analyses"
        )
    analyses_spec = mod.spice(circuit) or []
    if not analyses_spec:
        raise SystemExit("spice(circuit) returned no analyses")

    from InSpice import Simulator

    sim = Simulator.factory().simulation(circuit, temperature=25, nominal_temperature=25)
    results: list[dict[str, Any]] = []
    for spec in analyses_spec:
        kind = spec["type"]
        if kind == "op":
            analysis = sim.operating_point()
            # Each Node in analysis.nodes indexes its own value with [0].
            nodes = {str(n.name).lower(): float(n[0]) for n in analysis.nodes.values()}
            results.append({"type": "op", "nodes": nodes})
        elif kind == "tran":
            wf = sim.transient(step_time=spec["step"], end_time=spec["end"])
            t = np.asarray(wf.time, dtype=float)
            series: dict[str, dict[str, Any]] = {}
            for probe in spec.get("plot", []):
                v = np.asarray(wf[probe], dtype=float)
                series[probe] = {
                    "t_s": t,
                    "values": v,
                    "max": float(v.max()),
                    "final": float(v[-1]),
                }
            results.append({"type": "tran", "step": spec["step"], "end": spec["end"], "nodes": series})
        else:
            raise SystemExit(f"unknown analysis type: {kind}")

    return {"params": params, "erc_errors": erc["errors"], "unmapped_parts": unmapped, "analyses": results}


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe summary (waveform arrays replaced by stats + CSV path)."""
    out = dict(result)
    analyses = []
    for a_orig in result["analyses"]:
        a = {k: v for k, v in a_orig.items() if not k.startswith("_series_")}
        if a["type"] == "tran":
            nodes = {}
            for name, d in a["nodes"].items():
                nodes[name] = {k: v for k, v in d.items() if k not in ("values", "t_s")} | {
                    "n_points": len(d["values"])
                }
                a_orig["_series_" + name] = d  # kept for plotting, stripped from JSON
            a["nodes"] = nodes
        analyses.append(a)
    out["analyses"] = analyses
    return out


def stage_sim(mod: types.ModuleType, sweep: tuple[str, list[str]] | None, plot: Path | None) -> None:
    runs: list[dict[str, Any]] = []
    series_for_plot: list[tuple[str, Any, Any]] = []  # (label, t, values)

    if sweep:
        name, values = sweep
        for v in values:
            res = run_spice(mod, {name: v})
            res["sweep_label"] = f"{name}={v}"
            runs.append(res)
    else:
        res = run_spice(mod, {})
        res["sweep_label"] = "base"
        runs.append(res)

    json_runs = []
    for res in runs:
        s = summarize(res)
        json_runs.append(s)
        if plot:
            for a in res["analyses"]:
                if a["type"] != "tran":
                    continue
                for probe, d in a["nodes"].items():
                    series_for_plot.append(
                        (f"{res['sweep_label']} \u2192 {probe}", d["t_s"], d["values"])
                    )

    print(json.dumps(json_runs, indent=2))

    if plot and series_for_plot:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig = plt.figure()
        for label, t, v in series_for_plot:
            plt.plot(t * 1000, v, label=label)
        plt.xlabel("Time (ms)")
        plt.ylabel("Value")
        plt.legend(fontsize=8)
        fig.savefig(plot, bbox_inches="tight")
        print(f"plot: {plot}", file=sys.stderr)


def stage_test(mod: types.ModuleType, outdir: Path) -> None:
    """Run SPICE design tests declared by the design (Schematic.design_tests).

    A failing assertion means the circuit no longer meets its spec -> exit 1.
    Works with OO designs (Schematic subclasses); function-style build()
    designs must migrate to declare tests on the class.
    """
    from schematic import Schematic

    cls: type[Schematic] | None = None
    for value in vars(mod).values():
        if (isinstance(value, type) and issubclass(value, Schematic)
                and value is not Schematic
                and getattr(value, "__module__", None) == mod.__name__):
            cls = value
            break
    if cls is None:
        raise SystemExit(
            f"{mod.__file__}: design must define a Schematic subclass "
            "with design_tests()"
        )
    design = cls()
    design.build()
    tests = design.design_tests()
    if not tests:
        raise SystemExit(f"{cls.__name__}.design_tests() declared no tests")

    results: list[dict[str, Any]] = []
    failed = 0
    for sim in tests:
        try:
            res = sim.run(design)
            entry = res.to_dict()
            if not res.passed:
                failed += 1
        except Exception as exc:  # a crashing sim is also a failure
            entry = {"sim": getattr(sim, "name", "?"), "passed": False,
                     "error": f"{type(exc).__name__}: {exc}"}
            failed += 1
        results.append(entry)

    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / "design_tests.json"
    out_path.write_text(json.dumps(
        {"design": cls.__name__, "passed": failed == 0, "tests": results},
        indent=2, default=str,
    ))
    print(json.dumps({"passed": failed == 0, "design": cls.__name__,
                      "tests": [{"sim": r["sim"], "passed": r["passed"]}
                                for r in results]}))
    if failed:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="schemaitic", description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=["info", "erc", "validate", "netlist", "sim", "test"])
    parser.add_argument("circuit", type=Path, help="Python circuit description")
    parser.add_argument("--sweep", help="parameter sweep, e.g. C=1N,10N,100N,1U")
    parser.add_argument("--plot", type=Path, help="PNG output for sim waveforms")
    parser.add_argument("--outdir", type=Path, default=Path("out"), help="output directory")
    parser.add_argument(
        "--no-input", action="store_true",
        help="never prompt for manual rules; uncheckable rules fail instead",
    )
    args = parser.parse_args(argv)

    mod = load_module(args.circuit)
    sweep = parse_sweep(args.sweep)

    if args.stage == "info":
        stage_info(mod, sweep)
    elif args.stage == "erc":
        stage_erc(mod)
    elif args.stage == "validate":
        stage_validate(mod, allow_input=not args.no_input)
    elif args.stage == "netlist":
        stage_netlist(mod, args.outdir)
    elif args.stage == "sim":
        stage_sim(mod, sweep, args.plot)
    elif args.stage == "test":
        stage_test(mod, args.outdir)


if __name__ == "__main__":
    main()
