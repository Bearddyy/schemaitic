"""Typed electronics design-rule checks that travel with the parts they check.

Philosophy: fail early. A rule attached at part-creation time (ideally
extracted from the datasheet alongside the symbol) is validated on every
``validate`` run, so violations surface at design time, not on the bench.

Parts carry ``part.rules``: a tuple of :class:`Rule` instances. The validate
stage walks every part in the circuit and calls ``rule.run(part)``. Rules that
cannot be checked automatically raise :class:`NeedsHuman`, which the runner
turns into an interactive prompt (or a hard failure with ``--no-input``).

SKiDL ships no type stubs, so this module defines the structural contracts
(:class:`PinLike`, :class:`PartLike`, :class:`NetLike`) it requires. Call
sites are checked against those protocols by mypy --strict, and the runtime
accessors (:func:`lib_name`, :func:`get_pin`) fail fast with clear messages
when handed the wrong kind of object.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable, Literal, Protocol, Sequence, runtime_checkable

__all__ = [
    "CircuitLike",
    "default_circuit",
    "Rule",
    "RuleOutcome",
    "RuleStatus",
    "RuleViolation",
    "NeedsHuman",
    "GroundedRule",
    "NoConnectRule",
    "PinOnNetRule",
    "LambdaRule",
    "ManualRule",
    "attach_rules",
    "get_rules",
    "check_part",
    "check_all",
    "lib_name",
    "get_pin",
    "GROUND_NET_PATTERN",
]

# A pin reference within a part: pin number ("1", 2) or pin name ("GND").
PinRef = str | int

# Net names that count as ground-like: GND, VSS, EARTH, CHASSIS, analog/digital
# variants, with optional digits (GND1, AGND2, ...).
GROUND_NET_PATTERN: re.Pattern[str] = re.compile(
    r"^(A?V?(SS|DD0?G)?|GND\d?|AGND\d?|DGND\d?|PGND\d?|EARTH|CHASSIS)$",
    re.IGNORECASE,
)


# --- Structural contracts over SKiDL objects (untyped upstream) -------------


@runtime_checkable
class NetLike(Protocol):
    """What a rule needs from a SKiDL Net."""

    @property
    def name(self) -> str: ...


@runtime_checkable
class PinLike(Protocol):
    """What a rule needs from a SKiDL Pin."""

    @property
    def name(self) -> str: ...

    @property
    def num(self) -> str: ...

    @property
    def nets(self) -> Sequence[Any]: ...


@runtime_checkable
class PartLike(Protocol):
    """What a rule needs from a SKiDL Part."""

    @property
    def pins(self) -> Sequence[Any]: ...


@runtime_checkable
class CircuitLike(Protocol):
    """What the stages need from a SKiDL Circuit."""

    @property
    def parts(self) -> list[Any]: ...

    @property
    def nets(self) -> list[Any]: ...


def default_circuit() -> CircuitLike:
    """The circuit SKiDL is currently building.

    SKiDL 3.x injects this onto ``builtins`` at import
    (skidl/skidl.py: ``builtins.default_circuit = Circuit()``), which no
    type checker can see. This function is the single audited boundary
    for that hack; everything downstream sees CircuitLike.
    """
    import builtins

    ckt: object = getattr(builtins, "default_circuit", None)
    if not isinstance(ckt, CircuitLike):  # runtime_checkable: parts/nets attrs
        raise TypeError(
            "builtins.default_circuit missing or not circuit-like - did "
            "'import skidl' happen?"
        )
    return ckt


# --- Fast-failing accessors --------------------------------------------------


def lib_name(part: object) -> str:
    """Return the symbol-library name of a SKiDL part.

    SKiDL 3.x stores the library as a ``SchLib`` OBJECT on ``part.lib``; the
    name is its ``filename``. Comparing ``part.lib == "Device"`` silently
    compares an object to a str and is always False — this accessor exists so
    that mistake cannot be repeated.
    """
    lib: object = getattr(part, "lib", None)
    filename: object = getattr(lib, "filename", None)
    if not isinstance(filename, str):
        raise TypeError(
            f"part {part!r} has no string part.lib.filename "
            f"(got {type(lib).__name__}.filename={filename!r}); "
            "rules require KiCad-tool parts"
        )
    return filename


def get_pin(part: object, ref: PinRef) -> PinLike:
    """Look a pin up by number or name; fail loudly if it does not exist.

    A rule naming a pin that isn't on the symbol is itself a design error
    (e.g. datasheet revision changed the pinout), so this raises rather than
    returning ``None``.
    """
    if not isinstance(part, PartLike):  # runtime_checkable Protocol: pins attr
        raise TypeError(f"{part!r} does not look like a part (no .pins)")
    pins: Sequence[Any] = part.pins
    key: str = str(ref)
    for pin_obj in pins:
        pin: PinLike = pin_obj
        if str(pin.num) == key or pin.name == key:
            return pin
    available = sorted(f"{p.num}({p.name})" for p in pins)
    raise KeyError(f"part {part!r} has no pin {ref!r}; pins: {available}")


def pin_net_names(pin: PinLike) -> list[str]:
    """Names of the nets a pin is attached to (empty if unconnected)."""
    return [str(n.name) for n in pin.nets]


# --- Rule machinery -----------------------------------------------------------


class RuleStatus(Enum):
    """Outcome of evaluating one rule against one part."""

    PASS = "pass"
    FAIL = "fail"
    MANUAL_PASS = "manual_pass"
    MANUAL_FAIL = "manual_fail"


class RuleViolation(AssertionError):
    """Raised by a rule when the part violates it. Message explains the fix."""


class NeedsHuman(Exception):
    """Raised by a rule that cannot be checked automatically.

    The message becomes the prompt shown to the engineer; the runner records
    MANUAL_PASS / MANUAL_FAIL from the answer. ``--no-input`` turns it into a
    hard failure so automated pipelines never hang.
    """


@dataclass(frozen=True)
class RuleOutcome:
    """Result of one rule against one part."""

    part: str
    rule: str
    status: RuleStatus
    detail: str = ""

    @property
    def ok(self) -> bool:
        """True when the rule passed (including a human confirming a manual check)."""
        return self.status in (RuleStatus.PASS, RuleStatus.MANUAL_PASS)


class Rule:
    """Base class: a datasheet-derived constraint checked against a part.

    Subclasses implement :meth:`check`, raising :class:`RuleViolation` for a
    failed automated check or :class:`NeedsHuman` to request a human. Always
    invoke via :meth:`run`, which handles prompts and produces the outcome.
    """

    def __init__(self, description: str) -> None:
        self.description = description

    def check(self, part: object) -> None:
        """Automated check. Raise RuleViolation or NeedsHuman; return to pass."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement check() or override run()"
        )

    def run(self, part: object, *, allow_input: bool = True) -> RuleOutcome:
        """Evaluate the rule, prompting a human when the rule asks for one."""
        part_name = str(getattr(part, "ref", part))
        try:
            self.check(part)
        except RuleViolation as exc:
            return RuleOutcome(part_name, self.description, RuleStatus.FAIL, str(exc))
        except NeedsHuman as exc:
            if not allow_input:
                return RuleOutcome(
                    part_name, self.description, RuleStatus.MANUAL_FAIL,
                    f"needs human check (no input allowed): {exc}",
                )
            answer = input(f"[{part_name}] {exc} (y/N) ").strip().lower()
            passed = answer in ("y", "yes")
            return RuleOutcome(
                part_name, self.description,
                RuleStatus.MANUAL_PASS if passed else RuleStatus.MANUAL_FAIL,
                "confirmed by engineer" if passed else "rejected by engineer",
            )
        return RuleOutcome(part_name, self.description, RuleStatus.PASS)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.description!r})"


# --- Concrete rules -----------------------------------------------------------


class GroundedRule(Rule):
    """The given pin must be attached to a ground-like net.

    Ground-like names match :data:`GROUND_NET_PATTERN`, or a custom
    ``predicate`` overrides the name matching entirely (e.g. to require a
    specific star-ground net).
    """

    def __init__(
        self,
        pin: PinRef,
        *,
        predicate: Callable[[str], bool] | None = None,
    ) -> None:
        self.pin_ref = pin
        self.predicate = predicate or (lambda n: bool(GROUND_NET_PATTERN.match(n)))
        super().__init__(f"pin {pin} must be grounded")

    def check(self, part: object) -> None:
        pin = get_pin(part, self.pin_ref)
        names = pin_net_names(pin)
        if not names:
            raise RuleViolation(f"pin {self.pin_ref} is unconnected (needs a ground net)")
        if not any(self.predicate(n) for n in names):
            raise RuleViolation(
                f"pin {self.pin_ref} is on net(s) {names}, none ground-like"
            )


class NoConnectRule(Rule):
    """The given pin must be explicitly unconnected / marked NC."""

    def __init__(self, pin: PinRef) -> None:
        self.pin_ref = pin
        super().__init__(f"pin {pin} must be no-connect")

    def check(self, part: object) -> None:
        pin = get_pin(part, self.pin_ref)
        if pin_net_names(pin):
            raise RuleViolation(
                f"pin {self.pin_ref} is connected to {pin_net_names(pin)}, "
                "but the datasheet says leave it floating"
            )


class PinOnNetRule(Rule):
    """The given pin must be attached to a net whose name matches ``pattern``."""

    def __init__(self, pin: PinRef, pattern: str) -> None:
        self.pin_ref = pin
        self.pattern = re.compile(pattern)
        super().__init__(f"pin {pin} must be on net /{pattern}/")

    def check(self, part: object) -> None:
        pin = get_pin(part, self.pin_ref)
        names = pin_net_names(pin)
        if not any(self.pattern.match(n) for n in names):
            raise RuleViolation(
                f"pin {self.pin_ref} is on net(s) {names}, expected /{self.pattern.pattern}/"
            )


class LambdaRule(Rule):
    """Ad-hoc rule from a predicate.

    The predicate returns True to pass, False to fail, raises RuleViolation
    with a custom message, or NeedsHuman to escalate to the engineer.
    """

    def __init__(
        self,
        description: str,
        predicate: Callable[[object], bool] | None = None,
    ) -> None:
        self.predicate = predicate
        super().__init__(description)

    def check(self, part: object) -> None:
        if self.predicate is None:
            raise NeedsHuman(self.description)
        if self.predicate(part) is not True:
            raise RuleViolation(self.description)


class ManualRule(Rule):
    """A rule that cannot be automated (mechanical fit, thermal path, ...)."""

    def __init__(self, prompt: str) -> None:
        super().__init__(prompt)

    def check(self, part: object) -> None:
        raise NeedsHuman(self.description)


# --- Attaching rules to parts --------------------------------------------------


_RULES_ATTR = "rules"


def attach_rules(part: Any, rules: Iterable[Rule]) -> tuple[Rule, ...]:
    """Attach rules to a part and return the tuple now stored on it.

    ``part.rules`` must be a tuple of Rule — assigning anything else raises
    immediately (fail early on typos like a single bare Rule).
    """
    for rule in rules:
        if not isinstance(rule, Rule):
            raise TypeError(
                f"part.rules accepts Rule instances only, got {type(rule).__name__}"
            )
    merged: tuple[Rule, ...] = tuple(getattr(part, _RULES_ATTR, ())) + tuple(rules)
    part.rules = merged
    return merged


def get_rules(part: object) -> tuple[Rule, ...]:
    """Rules attached to a part (empty tuple if none). Validates the type."""
    rules: object = getattr(part, _RULES_ATTR, ())
    if not isinstance(rules, tuple) or not all(isinstance(r, Rule) for r in rules):
        raise TypeError(
            f"part {part!r} has a non-Rule .rules attribute ({type(rules).__name__}); "
            "use attach_rules() to set it"
        )
    return tuple(rules)


# --- Runners --------------------------------------------------------------------


def check_part(
    part: object,
    rules: Sequence[Rule] | None = None,
    *,
    allow_input: bool = True,
) -> list[RuleOutcome]:
    """Check one part against its attached rules (or an explicit list)."""
    effective = tuple(rules) if rules is not None else get_rules(part)
    return [rule.run(part, allow_input=allow_input) for rule in effective]


def check_all(
    parts: Iterable[object],
    *,
    allow_input: bool = True,
) -> list[RuleOutcome]:
    """Check every part on the BOM against its rules."""
    outcomes: list[RuleOutcome] = []
    for part in parts:
        outcomes.extend(check_part(part, allow_input=allow_input))
    return outcomes
