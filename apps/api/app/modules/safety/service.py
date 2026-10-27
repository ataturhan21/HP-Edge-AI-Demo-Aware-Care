"""M05 scope and urgency gates (R14-R17).

- **Red flags (ADR-003, both modes):** the approved checklist arrives as the structured `red_flags` context answer (a
  list of RF IDs; an empty list means "none of these apply"). Any ticked item routes the case to urgent before intake
  or guidance. Free text is never evaluated.
- **Local mode:** needs the enabled, unexpired reviewed pathway and a checklist answer. Without either the case is
  limited, because urgency could not be assessed (R17). With no red flag, the starting urgency is the reviewed policy
  (a) `self_care_candidate`, reduced by R14 information limits; the model may raise it, never lower it.
- **Mock mode:** routes by the explicit synthetic fixture scenario or the explicit A05 fixture trigger, plus ticked
  red flags.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.errors import ApiError
from app.modules.safety.pathway import Pathway

MOCK_RULE_VERSION = "mock-fixture-1.0.0"
MOCK_PATHWAY_ID = "mock-synthetic-pathway"
# Reserved structured fixture trigger for the urgent scenario's alternate trigger
# ("Simulate urgent answer" on A05, ADR-008). Sent as the one-element list value of
# an answered saveAnswer. No question type accepts it as a real answer, it is not
# free text, and it is honored only in mock mode (local mode rejects it as invalid).
MOCK_URGENT_TRIGGER = "fixture:urgent-signal"
# Fact kind of a synthetic urgent signal: recorded by the A05 trigger and, in a scripted
# record sample, assigned by the fixture extraction (never derived from user text).
URGENT_SIGNAL_KIND = "fixture:urgent_signal"
LIMITED_INFORMATION = "LIMITED_INFORMATION"
RED_FLAGS_KIND = "red_flags"
NO_RED_FLAG = "NO_RED_FLAG"


@dataclass(frozen=True)
class GateDecision:
    state: str  # intake | urgent | limited
    limited_reason: str | None = None


def red_flag_answer(items: list[Any]) -> list[str] | None:
    """The checklist answer among ConfirmedContextWrite items: the ticked IDs, or None when it was not answered."""
    item = next((i for i in items if i.kind == RED_FLAGS_KIND), None)
    return None if item is None else item.value


def check_red_flags(value: Any, pathway: Pathway | None) -> None:
    """Reject anything but distinct, approved red-flag IDs (an empty list is the explicit "none apply")."""
    known = pathway.red_flags if pathway is not None else {}
    if (not isinstance(value, list) or len(set(value)) != len(value)
            or any(not isinstance(v, str) or v not in known for v in value)):
        raise ApiError(422, "VALIDATION_FAILED", "Choose the warning signs that apply, or none of them.",
                       field_errors=[{"field": "confirmed_context.red_flags", "code": "invalid",
                                      "message": "Use the approved checklist items only."}])


def initial_gate(mode: str, scenario_id: str, pathway: Pathway | None = None,
                 red_flags: list[str] | None = None) -> GateDecision:
    if red_flags:
        return GateDecision("urgent")
    if mode != "mock":
        if pathway is None or not pathway.active():
            return GateDecision("limited", "no_reviewed_pathway")
        if red_flags is None:
            return GateDecision("limited", "urgency_not_assessed")
        return GateDecision("intake")
    if scenario_id == "urgent":
        return GateDecision("urgent")
    if scenario_id == "unsupported":
        return GateDecision("limited", "unsupported_scope")
    return GateDecision("intake")


def urgency_decision(pathway: Pathway, answered: int, gaps: int) -> dict[str, Any]:
    """The reviewed starting decision for an unflagged local case (policy (a)), with the R14 information limits.

    Unanswered questions remove self-care reassurance; no answers at all leave the level undetermined.
    """
    level, codes = "self_care_candidate", [NO_RED_FLAG]
    if gaps:
        level = "undetermined" if answered == 0 else "routine_clinician"
        codes.append(LIMITED_INFORMATION)
    decision = {"level": level, "reason_codes": codes, "rule_version": pathway.version, "pathway_id": pathway.id}
    if pathway.undetermined_floor:
        decision["undetermined_floor"] = pathway.undetermined_floor
    return decision


def is_urgent_fixture_trigger(mode: str, status: str, value: Any) -> bool:
    """Urgency recheck after every answer (R15). Mock: explicit fixture trigger only."""
    return mode == "mock" and status == "answered" and value == [MOCK_URGENT_TRIGGER]


def is_urgent_record_fixture(mode: str, kind: str) -> bool:
    """Urgency recheck when a record fact is confirmed or corrected (R15). Mock: fixture fact kind only."""
    return mode == "mock" and kind == URGENT_SIGNAL_KIND


def apply_information_limits(candidate: dict[str, Any], answered: int, gaps: int) -> dict[str, Any]:
    """R14: unresolved gaps prevent reassuring self-care output; no answers means undetermined.

    The fixture pack defines no reviewed required/critical fields, so every
    unanswered issued slot is treated conservatively as a gap. This never lowers
    urgency; it only removes reassurance and records the limitation.
    """
    if gaps == 0:
        return candidate
    out = {**candidate, "reason_codes": [*candidate["reason_codes"], LIMITED_INFORMATION]}
    if answered == 0:
        out.update(
            urgency_level="undetermined",
            outcome_title="Limited information",
            action={"category": "discuss_with_clinician",
                    "text": "Discuss this concern with a clinician; there was not enough information for a result.",
                    "rationale": "No intake questions were answered, so no level of care was suggested."},
        )
    elif out["urgency_level"] == "self_care_candidate":
        out.update(
            urgency_level="routine_clinician",
            action={"category": "discuss_with_clinician",
                    "text": "Discuss this concern with a clinician before relying on self-care.",
                    "rationale": "Some questions were not answered, so self-care reassurance is not shown."},
        )
    return out


def routine_blocked(state: str) -> bool:
    """Urgent and limited cases never expose routine guidance, ranking or export."""
    return state in {"urgent", "limited"}
