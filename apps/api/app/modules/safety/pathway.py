"""M05 reviewed pathway package loader (R12, R14-R17; ADR-003).

Loads the enabled package listed in content/pathways/registry.json: pathway.json (contract `Pathway`), the approved
question templates and the approved red-flag checklist. The API image has no spec/, so this module checks the
structure it relies on; tests validate pathway.json against spec/contracts/Pathway.schema.json.

A malformed package fails startup. An expired or unapproved package loads but is not active, so local mode stays
limited and generateGuidance refuses it; ticked red flags are still honored, because routing to urgent help is the
safe direction.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

URGENT_LEVELS = ("emergency", "urgent_clinician")


class PathwayError(RuntimeError):
    pass


@dataclass(frozen=True)
class Pathway:
    id: str
    version: str
    enabled: bool
    approved: bool
    review_date: datetime
    expires_at: datetime
    questions: dict[str, dict[str, Any]]   # template_id -> approved template
    question_order: tuple[str, ...]        # eligible templates in issue order (R12)
    red_flags: dict[str, dict[str, str]]   # RF id -> {"level", "text"}
    messages: dict[str, str]               # urgency level -> approved urgent message
    # ADR-003 amendment (general-adult-2): when the model answers "undetermined" for a case that reached it, publish
    # at this clinician floor without self-care advice instead of repairing toward self-care. None keeps the v1 rule.
    undetermined_floor: str | None = None
    # ADR-003 amendment 2 (general-adult-3): screen the person's own words for red flags before guidance.
    red_flag_screen: bool = False

    def active(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return self.enabled and self.approved and self.review_date <= now < self.expires_at


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PathwayError(f"pathway file {path.name} unreadable") from exc


def _when(value: Any, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PathwayError(f"pathway {name} is not a date-time") from exc
    if parsed.tzinfo is None:
        raise PathwayError(f"pathway {name} has no time zone")
    return parsed


def load_package(directory: Path, entry: dict[str, Any]) -> Pathway:
    doc = _read(directory / entry["pathway"])
    questions_doc = _read(directory / entry["questions"])
    flags_doc = _read(directory / entry["red_flags"])
    if doc.get("version") != entry.get("version") or doc.get("id") != entry.get("id"):
        raise PathwayError("registry entry does not match pathway.json")
    templates = {q["template_id"]: q for q in questions_doc["questions"]}
    order = tuple(q["template_id"] for q in sorted(doc["eligible_questions"],
                                                   key=lambda q: (-q["urgency_priority"], q["template_id"])))
    if not order or any(t not in templates for t in order):
        raise PathwayError("an eligible question has no approved template")
    if doc["stop_rules"].get("max_issued_slots") != 10:
        raise PathwayError("the 10 issued-slot rule must stay")
    flags = {f["id"]: {"level": f["level"], "text": f["text"]} for f in flags_doc["red_flags"]}
    rules = {r["id"]: r["urgency_level"] for r in doc["urgent_rules"]}
    if rules != {k: v["level"] for k, v in flags.items()}:
        raise PathwayError("urgent_rules and the red-flag checklist disagree")
    if any(level not in URGENT_LEVELS for level in rules.values()):
        raise PathwayError("a red flag must route to emergency or urgent_clinician")
    messages = flags_doc["messages"]
    if set(messages) != set(URGENT_LEVELS) or not all(isinstance(m, str) and m for m in messages.values()):
        raise PathwayError("both urgent messages are required")
    reviewers = doc.get("reviewers") or []
    floor, red_flag_screen = None, False
    if entry.get("policy"):
        policy = _read(directory / entry["policy"])
        floor = policy.get("undetermined_floor")
        if floor not in ("routine_clinician", "urgent_clinician"):
            raise PathwayError("undetermined_floor must be routine_clinician or urgent_clinician")
        red_flag_screen = policy.get("red_flag_screen", False)
        if not isinstance(red_flag_screen, bool):
            raise PathwayError("red_flag_screen must be true or false")
    return Pathway(
        id=doc["id"], version=doc["version"], enabled=doc.get("enabled") is True,
        approved=bool(reviewers) and all(r.get("decision") == "approved" for r in reviewers),
        review_date=_when(doc["review_date"], "review_date"), expires_at=_when(doc["expires_at"], "expires_at"),
        questions=templates, question_order=order, red_flags=flags, messages=dict(messages),
        undetermined_floor=floor, red_flag_screen=red_flag_screen,
    )


def load_registry(directory: Path) -> Pathway | None:
    """The enabled package, or None when the registry enables none. This build serves at most one."""
    registry = _read(directory / "registry.json")
    enabled = registry.get("enabled_pathways") or []
    if not enabled:
        return None
    if len(enabled) != 1:
        raise PathwayError("this build serves exactly one enabled pathway")
    entry = next((p for p in registry.get("packages", []) if p.get("version") == enabled[0]), None)
    if entry is None:
        raise PathwayError("the enabled pathway has no package entry")
    try:
        return load_package(directory, entry)
    except (KeyError, TypeError) as exc:
        raise PathwayError("pathway package is malformed") from exc
