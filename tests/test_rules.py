"""Unit tests for the rules engine - run with .venv/bin/pytest.

These encode the fail-early ideology: wrong-shaped input raises immediately,
violations are reported with actionable detail, manual rules never silently
pass in CI mode.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pytest

from rules import (
    GroundedRule,
    LambdaRule,
    ManualRule,
    ModeRule,
    NeedsHuman,
    NoConnectRule,
    PinOnNetRule,
    PullRule,
    PullState,
    RuleOutcome,
    RuleStatus,
    RuleViolation,
    attach_rules,
    check_all,
    check_part,
    effective_rules,
    get_pin,
    get_rules,
    lib_name,
)


def make_part(pin_specs: dict[str, list[str]]) -> SimpleNamespace:
    """Fake part: pin_specs maps 'num|name' -> net names (empty = floating)."""
    pins = [
        SimpleNamespace(
            num=key.split("|")[0],
            name=key.split("|")[1],
            nets=[SimpleNamespace(name=n) for n in nets],
        )
        for key, nets in pin_specs.items()
    ]
    return SimpleNamespace(ref="T1", pins=pins, lib=SimpleNamespace(filename="Device"))


class TestAccessors:
    def test_lib_name_reads_schlib_filename(self) -> None:
        assert lib_name(make_part({})) == "Device"

    def test_lib_name_rejects_str_lib(self) -> None:
        # The original bug: a str-valued (or missing) lib must raise, not
        # silently compare unequal as object-vs-str did.
        with pytest.raises(TypeError):
            lib_name(SimpleNamespace(lib="Device"))

    def test_get_pin_by_num_and_name(self) -> None:
        part = make_part({"1|VCC": ["3V3"], "2|GND": ["GND"]})
        assert get_pin(part, 1).name == "VCC"
        assert get_pin(part, "GND").num == "2"

    def test_get_pin_missing_lists_alternatives(self) -> None:
        part = make_part({"1|VCC": []})
        with pytest.raises(KeyError, match="pins"):
            get_pin(part, 9)


class TestRules:
    def test_grounded_pass_fail_detail(self) -> None:
        ok = GroundedRule("GND").run(make_part({"2|GND": ["GND"]}))
        bad = GroundedRule("GND").run(make_part({"2|GND": ["SIG"]}))
        floating = GroundedRule("GND").run(make_part({"2|GND": []}))
        assert ok.status is RuleStatus.PASS
        assert bad.status is RuleStatus.FAIL and "none ground-like" in bad.detail
        assert floating.status is RuleStatus.FAIL and "unconnected" in floating.detail

    def test_grounded_custom_predicate(self) -> None:
        rule = GroundedRule(1, predicate=lambda n: n == "STAR_GND")
        assert rule.run(make_part({"1|X": ["STAR_GND"]})).ok
        assert not rule.run(make_part({"1|X": ["GND"]})).ok

    def test_no_connect(self) -> None:
        rule = NoConnectRule(3)
        assert rule.run(make_part({"3|NC": []})).ok
        assert not rule.run(make_part({"3|NC": ["SIG"]})).ok

    def test_pin_on_net_pattern(self) -> None:
        rule = PinOnNetRule(1, r"(VCC|VIN)\d*")
        assert rule.run(make_part({"1|S": ["VCC"]})).ok
        assert not rule.run(make_part({"1|S": ["VI"]})).ok

    def test_lambda_rule(self) -> None:
        rule = LambdaRule("value is set", lambda p: bool(getattr(p, "value", "")))
        assert rule.run(SimpleNamespace(ref="R1", value="10K")).ok
        assert not rule.run(SimpleNamespace(ref="R1", value="")).ok

    def test_manual_rule_prompts_and_records(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda *_: "y")
        out = ManualRule("clearance ok?").run(make_part({}))
        assert out.status is RuleStatus.MANUAL_PASS

    def test_manual_rule_fails_closed_in_ci(self) -> None:
        out = ManualRule("clearance ok?").run(make_part({}), allow_input=False)
        assert out.status is RuleStatus.MANUAL_FAIL
        assert not out.ok

    def test_rule_base_class_is_abstract(self) -> None:
        from rules import Rule

        with pytest.raises(NotImplementedError):
            Rule("nothing").check(make_part({}))


class TestAttachment:
    def test_attach_and_get(self) -> None:
        part = make_part({"1|GND": ["GND"]})
        attach_rules(part, [GroundedRule(1)])
        attach_rules(part, [ManualRule("extra")])  # merges
        assert len(get_rules(part)) == 2
        assert check_part(part, allow_input=False)[0].ok

    def test_attach_rejects_non_rules(self) -> None:
        part = make_part({})
        with pytest.raises(TypeError):
            attach_rules(part, ["ground pin 1"])  # type: ignore[list-item]

    def test_get_rules_rejects_garbage(self) -> None:
        part = make_part({})
        part.rules = "oops"
        with pytest.raises(TypeError):
            get_rules(part)


# --- PullRule / ModeRule ------------------------------------------------------


class NetGraph:
    """Minimal SKiDL-shaped net graph for strap tests.

    Wires pins to nets by object; nets expose get_pins() like SKiDL does, so
    PullRule's resistor-on-net traversal runs for real against the fake.
    """

    def __init__(self) -> None:
        self.parts: list[SimpleNamespace] = []

    def net(self, name: str, ground: bool = False) -> SimpleNamespace:
        pins: list[SimpleNamespace] = []
        return SimpleNamespace(
            name=name,
            ground=ground,
            pins=pins,
            get_pins=lambda: list(pins),
        )

    def pin(self, num: str, name: str) -> SimpleNamespace:
        return SimpleNamespace(num=num, name=name, nets=[])

    def wire(self, net: SimpleNamespace, *pins: SimpleNamespace) -> None:
        for pin in pins:
            pin.nets.append(net)
            net.pins.append(pin)

    def part(self, ref: str, pins: list[SimpleNamespace], part_name: str = "CHIP") -> SimpleNamespace:
        p = SimpleNamespace(
            ref=ref, name=part_name, pins=pins, lib=SimpleNamespace(filename="Device")
        )
        for pin in pins:
            pin.part = p
        self.parts.append(p)
        return p

    def resistor(self, ref: str, value: str) -> SimpleNamespace:
        r = self.part(ref, [self.pin("1", ""), self.pin("2", "")], part_name="R")
        r.value = value  # plain string value; PullRule parses via values.Value
        return r


def strap_setup(pull_ohms: str | None, far_net: str) -> tuple[SimpleNamespace, NetGraph]:
    """Chip MODE pin pulled via resistor to a named net (GND / 3V3 / SIG)."""
    g = NetGraph()
    mode = g.net("MODE")
    far = {"GND": g.net("GND", ground=True), "3V3": g.net("3V3"), "SIG": g.net("SIG")}[far_net]
    chip = g.part("U1", [g.pin("1", "MODE")])
    g.wire(mode, chip.pins[0])
    if pull_ohms is not None:
        r = g.resistor("R1", pull_ohms)
        g.wire(mode, r.pins[0])
        g.wire(far, r.pins[1])
    return chip, g


class TestPullRule:
    def test_pull_low_via_resistor_passes(self) -> None:
        chip, _ = strap_setup("10K", "GND")
        PullRule("MODE", {PullState.LOW}).check(chip)  # no raise

    def test_pull_high_via_resistor_passes(self) -> None:
        chip, _ = strap_setup("4.7K", "3V3")
        PullRule("MODE", {PullState.HIGH}).check(chip)

    def test_wrong_direction_fails(self) -> None:
        chip, _ = strap_setup("10K", "GND")
        with pytest.raises(RuleViolation, match="allowed: high"):
            PullRule("MODE", {PullState.HIGH}).check(chip)

    def test_floating_passes_only_when_allowed(self) -> None:
        g = NetGraph()
        chip = g.part("U1", [g.pin("1", "MODE")])
        PullRule("MODE", {PullState.FLOATING}).check(chip)
        with pytest.raises(RuleViolation, match="floating"):
            PullRule("MODE", {PullState.LOW}).check(chip)

    def test_three_state_accepts_all(self) -> None:
        states = {PullState.HIGH, PullState.LOW, PullState.FLOATING}
        floating_chip = NetGraph().part("U1", [NetGraph().pin("1", "MODE")])
        PullRule("MODE", states).check(floating_chip)
        low, _ = strap_setup("10K", "GND")
        PullRule("MODE", states).check(low)
        high, _ = strap_setup("10K", "3V3")
        PullRule("MODE", states).check(high)

    def test_max_ohms_enforced(self) -> None:
        chip, _ = strap_setup("100K", "3V3")
        with pytest.raises(RuleViolation, match="at most"):
            PullRule("MODE", {PullState.HIGH}, max_ohms=10e3).check(chip)
        PullRule("MODE", {PullState.HIGH}, max_ohms=100e3).check(chip)

    def test_hard_strap_to_rail_accepted(self) -> None:
        g = NetGraph()
        chip = g.part("U1", [g.pin("1", "MODE")])
        g.wire(g.net("GND", ground=True), chip.pins[0])
        PullRule("MODE", {PullState.LOW}).check(chip)

    def test_ambiguous_net_without_pull_fails(self) -> None:
        # pin wired straight to a signal net: refuse to guess, must fail
        g = NetGraph()
        chip = g.part("U1", [g.pin("1", "MODE")])
        g.wire(g.net("SOME_SIG"), chip.pins[0])
        with pytest.raises(RuleViolation, match="no pull resistor"):
            PullRule("MODE", {PullState.LOW, PullState.HIGH}).check(chip)

    def test_empty_states_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError):
            PullRule("MODE", set())


class TestModeRule:
    def _chip(self, mode: str | None) -> tuple[SimpleNamespace, NetGraph]:
        chip, _ = strap_setup("10K", "GND")
        chip.mode = mode
        return chip, NetGraph()

    def _rule(self) -> ModeRule:
        return ModeRule(
            "MODE",
            mode_requirements={"run": PullState.HIGH, "sleep": PullState.LOW},
            mode_rules={
                "sleep": [LambdaRule("sleep-only rule", lambda part: True)]
            },
        )

    def test_declared_mode_extras_included(self) -> None:
        chip, _ = self._chip("sleep")
        attach_rules(chip, [self._rule()])
        descs = [r.description for r in effective_rules(chip)]
        assert any("sleep-only" in d for d in descs)

    def test_other_mode_extras_excluded(self) -> None:
        chip, _ = self._chip("run")
        attach_rules(chip, [self._rule()])
        descs = [r.description for r in effective_rules(chip)]
        assert not any("sleep-only" in d for d in descs)

    def test_strap_mismatch_fails(self) -> None:
        # MODE pulled LOW but declared run (requires HIGH)
        chip, _ = self._chip("run")
        with pytest.raises(RuleViolation):
            self._rule().check(chip)

    def test_strap_match_passes(self) -> None:
        chip, _ = self._chip("sleep")
        self._rule().check(chip)

    def test_no_mode_prompts_human(self) -> None:
        chip, _ = self._chip(None)
        with pytest.raises(NeedsHuman, match="which mode"):
            self._rule().check(chip)

    def test_unknown_mode_fails(self) -> None:
        chip, _ = self._chip("hypersleep")
        with pytest.raises(RuleViolation, match="not one of"):
            self._rule().check(chip)

    def test_check_part_uses_effective_rules(self) -> None:
        chip, _ = self._chip("sleep")
        attach_rules(chip, [self._rule()])
        outcomes = check_part(chip, allow_input=False)
        assert all(o.ok for o in outcomes)
        assert len(outcomes) == 2  # strap check + sleep-only extra



class TestCheckAll:
    def test_bom_sweep(self) -> None:
        p1 = make_part({"1|GND": ["GND"]})
        attach_rules(p1, [GroundedRule(1)])
        p2 = make_part({"1|GND": ["SIG"]})
        attach_rules(p2, [GroundedRule(1)])
        outcomes: list[RuleOutcome] = check_all([p1, p2], allow_input=False)
        assert [o.status for o in outcomes] == [RuleStatus.PASS, RuleStatus.FAIL]
