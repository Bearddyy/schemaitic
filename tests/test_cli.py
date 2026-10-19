"""End-to-end tests for the schemaitic CLI stages.

These guard the bug classes that cost real debugging time:
  - parts silently dropping out of the SPICE netlist (TEMPLATE / lib-str)
  - validate must exit non-zero on any rule violation, zero when clean
  - JSON stdout must stay parseable (the ndarray leak)
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
VENV_PY = REPO / ".venv" / "bin" / "python"
CLI = REPO / "tools" / "schemaitic.py"

needs_ngspice = pytest.mark.skipif(
    shutil.which("ngspice") is None, reason="ngspice not installed"
)


def run_cli(*args: str, expect_exit: int = 0) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [str(VENV_PY), str(CLI), *args],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=REPO,
    )
    assert proc.returncode == expect_exit, (
        f"exit {proc.returncode} != {expect_exit}\nstderr tail:\n{proc.stderr[-2000:]}"
    )
    return proc


def tran_max(run: dict[str, Any], probe: str = "vo") -> float:
    """Peak value of a transient probe from a summarized sim run.

    Uses max, not final: the PULSE source is back at 0 V at the end of the
    10 ms window, so both vi and vo finish at 0 in every run.
    """
    tran = [a for a in run["analyses"] if a["type"] == "tran"][-1]
    return float(tran["nodes"][probe]["max"])


class TestValidateStage:
    def test_clean_circuit_exits_zero(self) -> None:
        # The plain divider has no rules attached -> nothing to violate.
        run_cli("validate", "examples/vdivider.py", "--no-input")

    def test_violations_exit_one_and_report_detail(self) -> None:
        proc = run_cli(
            "validate", "examples/rules_demo.py", "--no-input", expect_exit=1
        )
        outcomes: list[dict[str, Any]] = json.loads(proc.stdout)
        by_status = {o["status"] for o in outcomes}
        assert "fail" in by_status and "pass" in by_status
        grounded = next(o for o in outcomes if "grounded" in o["rule"])
        # Regression: detail must name the offending net, not just 'failed'.
        assert "none ground-like" in grounded["detail"]

    def test_manual_rule_fails_closed_without_input(self) -> None:
        proc = run_cli(
            "validate", "examples/rules_demo.py", "--no-input", expect_exit=1
        )
        outcomes = json.loads(proc.stdout)
        manual = [o for o in outcomes if o["status"].startswith("manual")]
        assert manual and all(o["status"] == "manual_fail" for o in manual)


class TestSimStage:
    @needs_ngspice
    def test_sweep_plot_and_summary(self, tmp_path: Path) -> None:
        plot = tmp_path / "sweep.png"
        proc = run_cli(
            "sim", "examples/vdivider.py", "--sweep", "C=100N,1U",
            "--plot", str(plot),
        )
        # stdout must be pure JSON (nothing may leak into it, ndarray or else).
        runs = json.loads(proc.stdout)
        assert [r["sweep_label"] for r in runs] == ["C=100N", "C=1U"]
        assert plot.exists() and plot.stat().st_size > 1000

    @needs_ngspice
    def test_capacitor_reaches_netlist_and_physics(self) -> None:
        """The 1U case must charge slowly: VO stays well below the DC divider
        output 1.5986 V at the end of the 5 ms pulse (tau = 3.2 ms). A dropped
        capacitor would settle instantly at 1.5986 - this is the regression
        lock for the silent-TEMPLATE-drop bug."""
        proc = run_cli("sim", "examples/vdivider.py", "--sweep", "C=1U")
        (run,) = json.loads(proc.stdout)
        vo_peak = tran_max(run)
        # tau=3.2ms -> peak ~1.264 V, not the instant 1.5986 V of a missing cap.
        assert vo_peak < 1.45, f"cap missing? VO peak {vo_peak}"

    @needs_ngspice
    def test_no_capacitor_settles_at_divider_voltage(self) -> None:
        """Counterpart lock: without C the divider must reach 1.5986 V,
        proving the 1U assertion above measures the cap, not a broken sim."""
        proc = run_cli("sim", "examples/vdivider.py")
        (run,) = json.loads(proc.stdout)
        assert abs(tran_max(run) - 1.5986) < 0.01

    @needs_ngspice
    def test_json_stays_serialisable_with_plot(self, tmp_path: Path) -> None:
        # Regression: t_s ndarrays used to leak into the JSON summary.
        plot = tmp_path / "p.png"
        proc = run_cli(
            "sim", "examples/vdivider.py", "--sweep", "C=1N", "--plot", str(plot)
        )
        json.loads(proc.stdout)  # raises if numpy leaked


class TestNetlistStage:
    def test_kicad_netlist_contains_capacitor(self, tmp_path: Path) -> None:
        # NOTE: netlist stage builds with no params, so it uses the plain
        # divider; C only appears via sim sweep. Assert resistors present.
        run_cli("netlist", "examples/vdivider.py", "--outdir", str(tmp_path))
        nets = list(tmp_path.glob("*.net"))
        assert nets, f"no .net written to {tmp_path}"
        text = nets[0].read_text()
        assert '(lib "Device")' in text
        assert '"R1"' in text and '"R2"' in text


class TestDesignTestStage:
    @needs_ngspice
    def test_healthy_lpf_passes(self) -> None:
        proc = run_cli("test", "examples/lpf_divider.py")
        payload = json.loads(proc.stdout)  # last stdout line must be JSON
        assert payload["passed"] is True
        assert all(t["passed"] for t in payload["tests"])

    @needs_ngspice
    def test_broken_cap_fails_exit1(self) -> None:
        # 10x cap moves the cutoff: the SPICE design test must fail the stage.
        proc = run_cli("test", "examples/broken_lpf.py", expect_exit=1)
        payload = json.loads(proc.stdout)
        assert payload["passed"] is False
        assert any(not t["passed"] for t in payload["tests"])

    def test_function_design_without_class_fails_fast(self) -> None:
        proc = run_cli("test", "examples/vdivider.py", expect_exit=1)
        assert "Schematic subclass" in proc.stderr


class TestArgParsing:
    def test_bad_sweep_spec_fails_fast(self) -> None:
        # SystemExit -> exit 1 with the message on stderr.
        proc = run_cli(
            "sim", "examples/vdivider.py", "--sweep", "noequals", expect_exit=1
        )
        assert "--sweep" in proc.stderr

    def test_missing_circuit_file_fails_fast(self) -> None:
        proc = run_cli("info", "examples/does_not_exist.py", expect_exit=1)
        assert proc.stderr  # must explain itself
