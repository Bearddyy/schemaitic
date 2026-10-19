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
    "PullState",
    "PullRule",
    "NoConnectRule",
    "PinOnNetRule",
    "LambdaRule",
    "ManualRule",
    "ModeRule",
    "attach_rules",
    "get_rules",
    "effective_rules",
    "check_part",
    "check_all",
    "lib_name",
    "get_pin",
    "GROUND_NET_PATTERN",
    "RAIL_NET_PATTERN",
]

# A pin reference within a part: pin number ("1", 2) or pin name ("GND").
PinRef = str | int

# Net names that count as ground-like: GND, VSS, EARTH, CHASSIS, analog/digital
# variants, with optional digits (GND1, AGND2, ...).
GROUND_NET_PATTERN: re.Pattern[str] = re.compile(
    r"^(A?V?(SS|DD0?G)?|GND\d?|AGND\d?|DGND\d?|PGND\d?|EARTH|CHASSIS)$",
    re.IGNORECASE,
)

# Conventional positive-rail names used to accept hard-strap-high: VCC, VDD,
# V5, VIN, VBAT, 3V3, 1V8, P3V3 ... (anything clearly not a signal net).
RAIL_NET_PATTERN: re.Pattern[str] = re.compile(
    r"^(P?V\d?CC?\d?|VDD\d?|VIN\d?|VCC\d?|VBAT\d?|VREF\d?|P?\d+V\d+|\d+V\d*)$",
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


def pin_nets(pin: PinLike) -> list[Any]:
    """The net objects a pin is attached to (empty if unconnected).

    Returns the live Net objects so rules can test type (Ground) rather
    than only spelling; untyped upstream, hence Any.
    """
    return list(pin.nets)


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

    def apply_to(self, part: object, mode: str | None) -> "Rule | None":
        """Resolve this rule for a part's declared mode.

        Returns the rule to actually check (possibly re-parameterised for
        the mode, e.g. a PullRule that requires LOW when mode='shutdown'),
        or None to drop the rule entirely in that mode. Default: mode has
        no effect, check as-is.
        """
        return self

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
        description: str | None = None,
    ) -> None:
        self.pin_ref = pin
        self.predicate = predicate or (lambda n: bool(GROUND_NET_PATTERN.match(n)))
        super().__init__(description or f"pin {pin} must be grounded")

    def check(self, part: object) -> None:
        pin = get_pin(part, self.pin_ref)
        nets = pin_nets(pin)
        if not nets:
            raise RuleViolation(f"pin {self.pin_ref} is unconnected (needs a ground net)")
        # Type-first: schemaitic.net.Ground marks ground by TYPE.
        if any(getattr(n, "ground", False) for n in nets):
            return
        # Spelling fallback for plain SKiDL nets (GND/VSS/... convention).
        names = [str(n.name) for n in nets]
        if not any(self.predicate(n) for n in names):
            raise RuleViolation(
                f"pin {self.pin_ref} is on net(s) {names}, none ground-like"
            )


class PullState(Enum):
    """How a configuration/strap pin may be terminated, per datasheet."""

    HIGH = "high"        # pulled to a positive rail through a resistor
    LOW = "low"          # pulled to ground through a resistor
    FLOATING = "floating"  # datasheet allows leaving it unconnected


class PullRule(Rule):
    """A strap/config pin's termination: pulled high, pulled low, floating.

    Datasheets commonly say e.g. "MODE: pull high with >10k for function A,
    pull low with 10k for function B, leave floating for function C". One
    rule captures the set of allowed states:

        PullRule("MODE", {PullState.HIGH, PullState.LOW, PullState.FLOATING})
        PullRule(8, {PullState.LOW}, max_ohms=10e3)   # datasheet value limit

    A pull is satisfied when the pin shares a net with a resistor whose far
    end lands on a rail (ground-like for LOW, non-ground for HIGH). Direct
    rail connection (hard strap) also passes; a pin wired straight to the
    *opposite* rail fails. FLOATING passes only with no connection.
    """

    def __init__(
        self,
        pin: PinRef,
        states: Iterable[PullState],
        *,
        max_ohms: float | None = None,
        min_ohms: float | None = None,
        description: str | None = None,
    ) -> None:
        self.pin_ref = pin
        self.states = frozenset(states)
        if not self.states:
            raise ValueError("PullRule needs at least one allowed state")
        self.max_ohms = max_ohms
        self.min_ohms = min_ohms
        super().__init__(
            description
            or f"pin {pin} termination in "
            + "/".join(sorted(s.value for s in self.states))
        )

    # --- helpers ---------------------------------------------------------

    @staticmethod
    def _net_objs_are_ground(nets: list[Any]) -> bool:
        if any(getattr(n, "ground", False) for n in nets):
            return True
        return all(
            GROUND_NET_PATTERN.match(str(getattr(n, "name", ""))) for n in nets
        )

    @staticmethod
    def _resistor_value(part: Any) -> float | None:
        """Ohms of a resistor part, or None if not a resolvable resistor."""
        if getattr(part, "name", None) != "R":
            return None
        val = getattr(part, "value", None)
        if val is None:
            return None
        si = getattr(val, "si", None)  # schemaitic Value
        if si is not None:
            return float(si)
        from values import Value  # plain string values from SKiDL libs

        try:
            return Value.parse(str(val)).si
        except (ValueError, TypeError):
            return None

    def _check_ohms(self, ohms: float) -> None:
        if self.max_ohms is not None and ohms > self.max_ohms:
            raise RuleViolation(
                f"pull resistor is {ohms:g} ohm, datasheet allows at most "
                f"{self.max_ohms:g} ohm"
            )
        if self.min_ohms is not None and ohms < self.min_ohms:
            raise RuleViolation(
                f"pull resistor is {ohms:g} ohm, datasheet requires at least "
                f"{self.min_ohms:g} ohm"
            )

    # --- check -------------------------------------------------------------

    def check(self, part: object) -> None:
        pin = get_pin(part, self.pin_ref)
        own_nets = pin_nets(pin)

        if not own_nets:
            if PullState.FLOATING in self.states:
                return
            raise RuleViolation(
                f"pin {self.pin_ref} is floating; datasheet requires a "
                + "/".join(sorted(s.value for s in self.states)) + " strap"
            )

        own_names = {str(n.name) for n in own_nets}
        # Parts sharing a net with this pin, via the pins of those nets.
        candidates: list[Any] = []
        for net in own_nets:
            get_pins = getattr(net, "get_pins", None)
            if get_pins is None:
                continue
            for other in get_pins():
                cand_part = getattr(other, "part", None)
                if cand_part is not None and cand_part is not part:
                    candidates.append(cand_part)

        found: list[str] = []
        for cand in candidates:
            # Hard strap: resistor of 0 ohm is effectively direct wiring.
            ohms = self._resistor_value(cand)
            if ohms is None:
                continue
            own_ids = {id(n) for n in own_nets}
            far_nets: list[Any] = []
            for cpin in cand.pins:
                cn = pin_nets(cpin)
                # skip the pin that attaches the resistor to *this* pin's nets
                if any(id(n) in own_ids for n in cn):
                    continue
                far_nets.extend(cn)
            # Dangling resistor (both ends on this pin's own net, or the far
            # end unconnected) is not a pull.
            if not far_nets or all(id(n) in own_ids for n in far_nets):
                continue
            low = self._net_objs_are_ground(far_nets)
            high = all(
                RAIL_NET_PATTERN.match(str(n.name)) for n in far_nets
            )
            if (low and PullState.LOW in self.states) or (
                high and PullState.HIGH in self.states
            ):
                self._check_ohms(ohms)
                found.append(
                    f"{ohms:g} ohm pull to "
                    + ",".join(sorted(str(n.name) for n in far_nets))
                    + f" ({'low' if low else 'high'})"
                )

        if found:
            return

        # No valid resistor pull. A hard strap (direct rail connection) is
        # only accepted when the rail is recognisable: ground-like counts as
        # LOW, a conventional power-rail name counts as HIGH. Anything else
        # (a signal net, an ambiguous name) FAILS — we refuse to guess which
        # rail an unnamed net sits on.
        if own_nets:
            if self._net_objs_are_ground(own_nets):
                if PullState.LOW in self.states:
                    return
                direct = "low"
            elif all(RAIL_NET_PATTERN.match(nm) for nm in own_names):
                if PullState.HIGH in self.states:
                    return
                direct = "high"
            else:
                raise RuleViolation(
                    f"pin {self.pin_ref} is on "
                    + ",".join(sorted(own_names))
                    + " with no pull resistor to a rail; allowed: "
                    + "/".join(sorted(s.value for s in self.states))
                )
            raise RuleViolation(
                f"pin {self.pin_ref} is hard-tied ({direct}) to "
                + ",".join(sorted(own_names))
                + "; allowed: "
                + "/".join(sorted(s.value for s in self.states))
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


class ModeRule(Rule):
    """Declares and verifies the operating mode a part is strapped into.

    A part picks its function with strap pins (MODE, SHDN, ADDR...). The
    design declares the intended mode once at construction; this rule then:

    1. verifies the strap pin's termination matches the mode's requirement
       (its PullRule-style check), and
    2. *switches the rule set*: mode_rules maps each mode to the extra rules
       that mode implies, so downstream rules only apply in the right mode.

        u1 = SomeChip(ref="U1", mode="sleep")
        attach_rules(u1, [
            ModeRule(
                "MODE",
                mode_requirements={
                    "run":   {PullState.FLOATING},
                    "sleep": {PullState.LOW},
                },
                mode_rules={
                    # extra rules that only apply in 'sleep'
                    "sleep": [GroundedRule("SHDN")],
                    # 'run' adds none
                },
            ),
        ])

    Rules returned via mode_rules are resolved (and recursively mode-resolved)
    by effective_rules(); the ModeRule itself still checks the strap pin.
    """

    def __init__(
        self,
        pin: PinRef,
        mode_requirements: dict[str, "PullState | frozenset[PullState]"],
        mode_rules: dict[str, Sequence["Rule"]] | None = None,
        *,
        description: str | None = None,
    ) -> None:
        self.pin_ref = pin
        # normalise values to frozensets
        self.mode_requirements: dict[str, frozenset[PullState]] = {
            m: (s if isinstance(s, frozenset) else frozenset({s}))
            for m, s in mode_requirements.items()
        }
        self.mode_rules: dict[str, tuple[Rule, ...]] = {
            m: tuple(rs) for m, rs in (mode_rules or {}).items()
        }
        super().__init__(
            description or f"pin {pin} mode strap ({'/'.join(sorted(self.mode_requirements))})"
        )

    def pull_rule_for(self, mode: str) -> "PullRule":
        return PullRule(self.pin_ref, self.mode_requirements[mode])

    def check(self, part: object) -> None:
        mode = getattr(part, "mode", None)
        if mode is None:
            raise NeedsHuman(
                f"which mode is this part strapped for? one of "
                f"{sorted(self.mode_requirements)} (pass mode=... at construction)"
            )
        if mode not in self.mode_requirements:
            raise RuleViolation(
                f"declared mode {mode!r} is not one of {sorted(self.mode_requirements)}"
            )
        # verify the strap termination matches the declared mode
        self.pull_rule_for(mode).check(part)

    def extra_rules_for(self, part: object) -> tuple[Rule, ...]:
        """Rules implied by the part's declared mode (empty if none)."""
        mode = getattr(part, "mode", None)
        if mode is None:
            return ()
        return self.mode_rules.get(str(mode), ())


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



def effective_rules(part: object) -> tuple[Rule, ...]:
    """Rules to actually check for a part, after mode resolution.

    Each attached rule gets a chance to re-parameterise or drop itself for
    the part's declared mode via Rule.apply_to(); ModeRules additionally
    inject the extra rules their mode implies (resolved recursively, with a
    depth guard so a misconfigured rule set can't loop forever).
    """
    rules = get_rules(part)
    mode = getattr(part, "mode", None)
    out: list[Rule] = []
    seen_modes: set[tuple[int, str]] = set()

    def resolve(rs: Sequence[Rule], depth: int) -> None:
        if depth > 8:
            raise RuntimeError("rule resolution too deep — cyclic mode_rules?")
        for rule in rs:
            if isinstance(rule, ModeRule):
                m = str(mode)
                key = (id(rule), m)
                if key in seen_modes:
                    continue  # already injected this mode's extras
                seen_modes.add(key)
                out.append(rule)  # the strap check itself
                resolve(rule.extra_rules_for(part), depth + 1)
            else:
                applied = rule.apply_to(part, mode)
                if applied is not None:
                    out.append(applied)

    resolve(rules, 0)
    return tuple(out)


# --- Runners --------------------------------------------------------------------


def check_part(
    part: object,
    rules: Sequence[Rule] | None = None,
    *,
    allow_input: bool = True,
) -> list[RuleOutcome]:
    """Check one part against its attached rules (or an explicit list).

    Without an explicit list, rules go through effective_rules() first so
    mode-declared parts get their mode-resolved / mode-implied rule set.
    """
    effective = tuple(rules) if rules is not None else effective_rules(part)
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
