"""Tests for simulations.py: math-only helpers plus full ngspice design tests.

The simulation classes are design tests: the pass cases prove the physics,
the negative controls prove the assertions actually fire (a test that can
never fail is worse than no test).
"""

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from simulations import (  # noqa: E402
    AssertionResult,
    LowPassFilter,
    OperatingPoint,
    SimFailure,
    SimulationResult,
    TransientPulse,
    _db,
)


class TestDb:
    def test_unity_is_zero_db(self) -> None:
        assert _db(1.0) == pytest.approx(0.0)

    def test_half_power(self) -> None:
        assert _db(0.5) == pytest.approx(-6.0206, abs=1e-3)

    def test_zero_guard(self) -> None:
        assert _db(0.0) == -400.0
        assert _db(-1.0) == -400.0

    def test_reference(self) -> None:
        assert _db(2.0, ref=2.0) == pytest.approx(0.0)


class TestResult:
    def _result(self) -> SimulationResult:
        r = SimulationResult("t")
        r.check("a", 1.0, True)
        return r

    def test_empty_result_passes(self) -> None:
        # A sim with zero assertions passing by default could hide a sim
        # that never ran its checks — assert_passed must not bless that in
        # silently; callers rely on run() populating assertions.
        assert SimulationResult("empty").passed

    def test_failure_listed(self) -> None:
        r = self._result()
        r.check("b", 0.0, False, "b broke")
        assert not r.passed
        with pytest.raises(SimFailure, match="b broke"):
            r.assert_passed()

    def test_to_dict_json_safe(self) -> None:
        import json

        r = self._result()
        json.dumps(r.to_dict())  # must not raise on ndarrays etc.


class TestCutoffMath:
    """measured_cutoff is pure math — test without ngspice."""

    def _lp(self) -> LowPassFilter:
        return LowPassFilter("vo", cutoff_hz=1000.0, rejection_hz=10e3,
                             min_rejection_db=-20.0)

    def test_bracketed_crossing(self) -> None:
        # synthetic sweep: flat 0 dB until 1 kHz then -20 dB/decade
        f = [100.0, 500.0, 1000.0, 2000.0]
        g = [0.0, 0.0, -3.0, -9.5]
        assert self._lp().measured_cutoff(f, g) == pytest.approx(1000.0, rel=1e-6)

    def test_no_crossing_returns_inf(self) -> None:
        f = [10.0, 100.0]
        g = [0.0, -1.0]
        assert self._lp().measured_cutoff(f, g) == float("inf")

    def test_gain_at_interpolates(self) -> None:
        import numpy as np

        f = np.array([100.0, 10000.0])
        g = [0.0, -20.0]
        # 1 kHz is the log-midpoint of a -20 dB/decade line
        assert self._lp()._gain_at(1000.0, f, g) == pytest.approx(-10.0, abs=1e-6)


# --- End-to-end against the real divider (needs ngspice) ----------------------


def _divider_cls() -> type:
    from nets import Ground  # noqa: F401 (installs ERC patch)
    from parts import Capacitor, Resistor
    from schematic import Schematic
    from skidl import Net

    class Divider(Schematic):
        def content(self, **params: object) -> None:
            c_val = str(params.get("C", "100N"))
            vin, vout = Net("VI"), Net("VO")
            gnd = Ground("GND")
            r1 = Resistor("R1", "10K")
            r2 = Resistor("R2", "4.7K")
            c1 = Capacitor("C1", c_val)
            vin & r1 & vout & (r2 | c1[1, 2]) & gnd

    return Divider


DIVIDER_VO = 5.0 * 4.7 / 14.7  # 1.5986 V at 5 V supply


class TestDividerSims:
    @pytest.fixture(scope="class")
    def divider(self) -> object:
        d = _divider_cls()()
        d.build()
        return d

    def test_operating_point(self, divider: object) -> None:
        res = OperatingPoint(node="vo", expect_v=DIVIDER_VO, tolerance_v=0.005).run(divider)
        res.assert_passed()

    def test_operating_point_negative(self, divider: object) -> None:
        res = OperatingPoint(node="vo", expect_v=3.0, tolerance_v=0.01).run(divider)
        with pytest.raises(SimFailure, match="expected 3.0"):
            res.assert_passed()

    def test_low_pass_spec(self, divider: object) -> None:
        # cap sees R1||R2: fc = 1/(2*pi*3197*100n) ~ 497.8 Hz
        fc = 1.0 / (2.0 * math.pi * (10e3 * 4.7e3 / 14.7e3) * 100e-9)
        lp = LowPassFilter("vo", cutoff_hz=fc, rejection_hz=10e3,
                           min_rejection_db=-20.0,
                           expected_passband_db=20 * math.log10(4.7 / 14.7),
                           start=10.0, stop=1e6, points=201)
        res = lp.run(divider)
        res.assert_passed()
        assert len(res.assertions) == 3

    def test_low_pass_detects_broken_cap(self) -> None:
        # 10x capacitor moves fc a decade down; the design test MUST fail.
        d = _divider_cls()()
        d.build(C="1U")
        fc = 1.0 / (2.0 * math.pi * (10e3 * 4.7e3 / 14.7e3) * 100e-9)
        lp = LowPassFilter("vo", cutoff_hz=fc, rejection_hz=10e3,
                           min_rejection_db=-20.0, start=10.0, stop=1e6, points=201)
        res = lp.run(d)
        assert not res.passed
        with pytest.raises(SimFailure, match="cutoff"):
            res.assert_passed()

    def test_transient_plateau(self, divider: object) -> None:
        res = TransientPulse("vo", expect_final_v=DIVIDER_VO, tolerance_v=0.02).run(divider)
        res.assert_passed()
