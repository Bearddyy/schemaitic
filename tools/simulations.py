"""Design tests in SPICE: simulations that take a Schematic, instrument it,
run, and ASSERT behaviour — a failing sim is a design bug, not a suggestion.

Philosophy (mirrors rules.py): a Simulation encodes what the circuit must do
(e.g. "low-pass: -20 dB at 10 kHz"), not how to draw it. Simulations receive
the circuit under test (dependency injection) and know nothing about which
design they run against, so the same test travels across designs and sweeps.

    class DividerLowPass(FilterLowPassTest):
        cutoff_hz = 338.0            # 1/(2*pi*R2*C) for 4.7K || 100n

    sim = DividerLowPass(node="vo", stop=1e6)
    result = sim.run(divider_schematic)
    result.assert_passed()           # raises SimulationFailure

InSpice notes (proven on this box):
- Sources are injected on the NETLIST object, e.g. nl.V("source","VI","GND",
  ac_value=1 @ u_V). For PULSE: dc_value = None, tran_value = "PULSE(...)".
- Waveform node keys are lowercase net names.
- AC: wf.frequency + complex wf[node]; DC: wf.<source>_src; TRAN: wf.time.
"""

from __future__ import annotations

import abc
import math
from dataclasses import dataclass, field
from typing import Any, Sequence

__all__ = [
    "AssertionResult",
    "SimFailure",
    "SimulationResult",
    "Simulation",
    "OperatingPoint",
    "ACResponse",
    "LowPassFilter",
    "TransientPulse",
]


class SimFailure(AssertionError):
    """A simulation expectation was violated (design regression)."""


@dataclass(frozen=True)
class AssertionResult:
    """One check: name, measured value, pass/fail, human detail."""

    name: str
    actual: float
    passed: bool
    detail: str = ""


@dataclass
class SimulationResult:
    """Measured quantities plus the assertions evaluated against them."""

    sim_name: str
    quantities: dict[str, float] = field(default_factory=dict)
    assertions: list[AssertionResult] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    def check(self, name: str, actual: float, passed: bool, detail: str = "") -> None:
        self.assertions.append(AssertionResult(name, actual, passed, detail))

    @property
    def passed(self) -> bool:
        return all(a.passed for a in self.assertions)

    def assert_passed(self) -> None:
        """Raise SimFailure listing every violated expectation."""
        bad = [a for a in self.assertions if not a.passed]
        if bad:
            lines = "; ".join(f"{a.name}: {a.detail or 'failed'}" for a in bad)
            raise SimFailure(f"{self.sim_name}: {len(bad)} assertion(s) failed -> {lines}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sim": self.sim_name,
            "passed": self.passed,
            "quantities": self.quantities,
            "assertions": [
                {"name": a.name, "actual": a.actual, "passed": a.passed, "detail": a.detail}
                for a in self.assertions
            ],
        }


def _db(mag: float, ref: float = 1.0) -> float:
    """Magnitude ratio in dB, guarding against log(0)."""
    if mag <= 0.0:
        return -400.0
    return 20.0 * math.log10(mag / ref)


class Simulation(abc.ABC):
    """Base: instrument -> run -> measure -> assert, against a Schematic.

    Subclasses implement ``run(schematic) -> SimulationResult``. The schematic
    arrives fully built (and validated); sims must not modify its parts, only
    attach stimulus to the netlist copy.
    """

    #: Override per simulation so failure messages name the test.
    name: str = "simulation"

    @staticmethod
    def _simulator(schematic: Any, source: str, node_pos: str, node_neg: str, kind: str) -> Any:
        """SPICE-netlist + stimulus + Simulator, shared by all sim types.

        kind: "ac" (1 V amplitude) or "pulse" (0->amp pulse, given via args).
        """
        from InSpice import Simulator
        from InSpice.Unit import u_V

        nl = schematic.spice_netlist()
        if kind == "ac":
            nl.V("VSRC", node_pos, node_neg, ac_value=1 @ u_V)
        elif kind == "pulse":
            raise NotImplementedError  # callers build pulse sources themselves
        else:  # dc sweep source
            nl.V(source, node_pos, node_neg, dc_value=1 @ u_V)
        return Simulator.factory().simulation(nl, temperature=25, nominal_temperature=25)

    @abc.abstractmethod
    def run(self, schematic: Any) -> SimulationResult:
        """Execute against the given Schematic; never mutate it."""
        raise NotImplementedError


class OperatingPoint(Simulation):
    """DC operating point; optionally assert node voltages."""

    name = "operating_point"

    def __init__(self, *, node: str = "vo", expect_v: float | None = None,
                 tolerance_v: float = 0.01, source: str = "VI",
                 supply_v: float = 5.0) -> None:
        self.node = node.lower()
        self.expect_v = expect_v
        self.tolerance_v = tolerance_v
        self.source = source
        self.supply_v = supply_v

    def run(self, schematic: Any) -> SimulationResult:
        from InSpice import Simulator
        from InSpice.Unit import u_V

        nl = schematic.spice_netlist()
        # Source ref must differ from the node it drives (InSpice keys both).
        nl.V("VSRC", self.source, "GND", self.supply_v @ u_V)
        sim = Simulator.factory().simulation(nl, temperature=25, nominal_temperature=25)
        op = sim.operating_point()
        nodes = {str(n.name).lower(): float(n[0]) for n in op.nodes.values()}
        res = SimulationResult(self.name, quantities={f"{k}_v": v for k, v in nodes.items()})
        vo = nodes.get(self.node)
        if vo is None:
            raise KeyError(f"node '{self.node}' not in op result: {sorted(nodes)}")
        if self.expect_v is not None:
            ok = abs(vo - self.expect_v) <= self.tolerance_v
            res.check(
                f"{self.node}=={self.expect_v}V",
                vo, ok,
                f"{self.node}={vo:.4f} V, expected {self.expect_v} ±{self.tolerance_v} V",
            )
        return res


class ACResponse(Simulation):
    """AC sweep: returns frequency/complex waveforms for subclass measurement."""

    name = "ac_response"

    def __init__(self, node: str = "vo", *, start: float = 10.0, stop: float = 1e6,
                 points: int = 101, variation: str = "dec", source: str = "VI") -> None:
        self.node = node.lower()
        self.start = start
        self.stop = stop
        self.points = points
        self.variation = variation
        self.source = source

    def sweep(self, schematic: Any) -> tuple[Any, Any]:
        """(frequency ndarray Hz, node complex ndarray) — 1 V stimulus."""
        import numpy as np

        sim = self._simulator(schematic, self.source, self.source, "GND", "ac")
        wf = sim.ac(
            variation=self.variation,
            number_of_points=self.points,
            start_frequency=self.start,
            stop_frequency=self.stop,
        )
        return (
            np.asarray(wf.frequency, dtype=float),
            np.asarray(wf[self.node], dtype=complex),
        )

    def run(self, schematic: Any) -> SimulationResult:
        f, vo = self.sweep(schematic)
        mags = [_db(abs(v)) for v in vo]
        return SimulationResult(
            self.name,
            quantities={"passband_db": mags[0], "stopband_db": mags[-1]},
            extras={"freq_hz": f, "gain_db": mags},
        )


class LowPassFilter(ACResponse):
    """Design test: an RC/active low-pass keeps its cutoff and rejection.

    Subclass or instantiate with the spec the filter MUST meet:

        LowPassFilter("vo", cutoff_hz=338.0, rejection_hz=10e3, min_rejection_db=-20)

    Assertions:
    - measured -3 dB cutoff within ``cutoff_tolerance`` (relative) of spec;
    - gain at ``rejection_hz`` at or below ``min_rejection_db`` relative to
      the passband (first sweep point);
    - passband gain consistent with ``expected_passband_db`` when given
      (catches e.g. a wrong divider ratio silently changing DC gain).
    """

    name = "low_pass_filter"

    def __init__(self, node: str = "vo", *, cutoff_hz: float,
                 rejection_hz: float, min_rejection_db: float,
                 cutoff_tolerance: float = 0.15,
                 expected_passband_db: float | None = None, **kw: Any) -> None:
        super().__init__(node, **kw)
        self.cutoff_hz = cutoff_hz
        self.rejection_hz = rejection_hz
        self.min_rejection_db = min_rejection_db
        self.cutoff_tolerance = cutoff_tolerance
        self.expected_passband_db = expected_passband_db

    def _gain_at(self, freq: float, f: Any, gain_db: Sequence[float]) -> float:
        """Linear-interpolated gain (dB) at freq on the log-frequency sweep."""
        import numpy as np

        lf = math.log10(freq)
        xs = np.log10(f)
        return float(np.interp(lf, xs, gain_db))

    def measured_cutoff(self, f: Any, gain_db: Sequence[float]) -> float:
        """First frequency where gain drops 3 dB below the passband edge.

        Log-frequency linear interpolation between the two sweep points that
        bracket the -3 dB crossing; inf if the sweep never crosses (filter
        cutoff above the stop frequency — also a reportable failure).
        """
        import numpy as np

        edge = gain_db[0]
        target = edge - 3.0
        lf = np.log10(np.asarray(f, dtype=float))
        prev_lf, prev_g = float(lf[0]), gain_db[0]
        for x_lf, g in zip(lf, gain_db):
            if g <= target:
                frac = (prev_g - target) / max(prev_g - g, 1e-12)
                return float(10.0 ** (prev_lf + frac * (float(x_lf) - prev_lf)))
            prev_lf, prev_g = float(x_lf), g
        return float("inf")  # never crossed: no cutoff inside sweep

    def run(self, schematic: Any) -> SimulationResult:
        import numpy as np

        f, vo = self.sweep(schematic)
        mags_db = [20.0 * math.log10(abs(v)) if abs(v) > 0 else -400.0 for v in vo]
        pass_db = mags_db[0]
        rel = [m - pass_db for m in mags_db]

        res = SimulationResult(
            self.name,
            quantities={"passband_db": pass_db},
            extras={"freq_hz": f, "gain_db": mags_db},
        )
        cut = self.measured_cutoff(f, mags_db)
        rel_err = abs(cut - self.cutoff_hz) / self.cutoff_hz
        res.check(
            f"cutoff~{self.cutoff_hz:g}Hz",
            cut,
            rel_err <= self.cutoff_tolerance,
            f"measured cutoff {cut:.4g} Hz vs spec {self.cutoff_hz:.4g} Hz "
            f"({rel_err * 100:.0f}% off, tol {self.cutoff_tolerance * 100:.0f}%)",
        )
        rej = self._gain_at(self.rejection_hz, f, rel)
        res.check(
            f"<={self.min_rejection_db:g}dB@{self.rejection_hz:g}Hz",
            rej,
            rej <= self.min_rejection_db,
            f"gain at {self.rejection_hz:.3g} Hz is {rej:.2f} dB, need <= "
            f"{self.min_rejection_db} dB",
        )
        if self.expected_passband_db is not None:
            ok = abs(pass_db - self.expected_passband_db) <= 0.5
            res.check(
                f"passband~{self.expected_passband_db:g}dB",
                pass_db, ok,
                f"passband {pass_db:.2f} dB, expected {self.expected_passband_db} ±0.5",
            )
        return res


class TransientPulse(Simulation):
    """PULSE stimulus transient; measures settle value / rise on a node."""

    name = "transient_pulse"

    def __init__(self, node: str = "vo", *, supply_v: float = 5.0,
                 pulse_width_s: float = 5e-3, stop_s: float = 10e-3,
                 step_s: float = 5e-6, source: str = "VI",
                 expect_final_v: float | None = None, tolerance_v: float = 0.02) -> None:
        self.node = node.lower()
        self.supply_v = supply_v
        self.pulse_width_s = pulse_width_s
        self.stop_s = stop_s
        self.step_s = step_s
        self.source = source
        self.expect_final_v = expect_final_v
        self.tolerance_v = tolerance_v

    def run(self, schematic: Any) -> SimulationResult:
        import numpy as np
        from InSpice import Simulator

        nl = schematic.spice_netlist()
        src = nl.V("VSRC", self.source, "GND")
        src.dc_value = None
        src.tran_value = (
            f"PULSE(0 {self.supply_v:g} 0 1n 1n "
            f"{self.pulse_width_s:g} {2 * self.pulse_width_s:g})"
        )
        sim = Simulator.factory().simulation(nl, temperature=25, nominal_temperature=25)
        wf = sim.transient(step_time=self.step_s, end_time=self.stop_s)
        t = np.asarray(wf.time, dtype=float)
        v = np.asarray(wf[self.node], dtype=float)
        # value at end of the high phase (just before the pulse falls)
        plateau_idx = int(np.searchsorted(t, self.pulse_width_s, side="left") - 1)
        plateau = float(v[max(plateau_idx, 0)])
        res = SimulationResult(
            self.name,
            quantities={"plateau_v": plateau, "final_v": float(v[-1]),
                        "peak_v": float(v.max())},
            extras={"t_s": t, "node": self.node, "values": v},
        )
        if self.expect_final_v is not None:
            ok = abs(plateau - self.expect_final_v) <= self.tolerance_v
            res.check(
                f"plateau~{self.expect_final_v:g}V",
                plateau, ok,
                f"{self.node} plateau {plateau:.4f} V, expected "
                f"{self.expect_final_v} ±{self.tolerance_v} V",
            )
        return res
