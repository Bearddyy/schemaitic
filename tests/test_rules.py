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
    NeedsHuman,
    NoConnectRule,
    PinOnNetRule,
    RuleOutcome,
    RuleStatus,
    RuleViolation,
    attach_rules,
    check_all,
    check_part,
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


class TestCheckAll:
    def test_bom_sweep(self) -> None:
        p1 = make_part({"1|GND": ["GND"]})
        attach_rules(p1, [GroundedRule(1)])
        p2 = make_part({"1|GND": ["SIG"]})
        attach_rules(p2, [GroundedRule(1)])
        outcomes: list[RuleOutcome] = check_all([p1, p2], allow_input=False)
        assert [o.status for o in outcomes] == [RuleStatus.PASS, RuleStatus.FAIL]
