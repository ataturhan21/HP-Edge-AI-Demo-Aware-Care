"""M05 red-flag screen of the person's own words (R15, R17; ADR-003 amendment 2, #79).

The approved red-flag checklist relies on the person ticking a box. With `general-adult-3` the local model also reads
what the person wrote (the concern and every answer) before any guidance is generated, and returns only the IDs of
approved red flags those words describe as present now. A match routes the case to urgent help exactly as a ticked
box does; nothing the model writes is shown. Any failure (unavailable, timeout, invalid output) fails closed: no
guidance is published.

The screen is its own task and prompt, so the qualified guidance prompt (`guidance-local-1`) is unchanged. Only the
approved red-flag wording and the person's words go to the local runtime; nothing leaves the device or is logged.

#387: the person's words include the free text they typed into the profile (A02 relevant history, current medications
and reported allergies). The guidance model reads the same text as confirmed facts, so an overdose or a suicide attempt
written there is screened exactly like one written in the concern: at creation, on an edit that changes it, and before
guidance. #583: so is context a client sends under any other kind (the A02 form sends none), which the guidance model
also reads.

#389 (`red-flag-screen-2`): a carer's words count too. An acute sign happening now in someone the person cares for or
is with, when the words ask for help for them, routes to urgent help like the person's own; another person's past
illness, family history or a sign that is only background to the writer's own concern does not.
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from app.modules.safety.pathway import URGENT_LEVELS, Pathway
from app.modules.safety.service import RED_FLAGS_KIND

TASK, PROMPT_VERSION, SCHEMA_ID = "red_flag_screen", "red-flag-screen-2", "RedFlagScreen"
# #389: red-flag-screen-2 also counts an acute sign happening now, or just now, in someone the person cares for or is
# with when the words ask for help for them (the concern check accepts concerns about someone they care for), and
# keeps another person's past illness, family history or background out. The rest of red-flag-screen-1 stays,
# including "When you are unsure ..., count it" (#390: narrowing it for terse concerns lost urgent items on the Nano).
# Re-qualified on both devices (ADR-002): evidence/model-qualification/2026-10-22-red-flag-screen-2/README.md.
# The examples name "吐血" (vomiting blood): the first Fury run graded it as coughing up blood. Previous:
# red-flag-screen-1, sha256 8dfbd461....
INSTRUCTIONS = (
    "You screen a person's own words for urgent warning signs. Below are approved warning signs, each with an id. "
    "Decide which of them the words describe as present now or recently for this person, or for someone they care for "
    "or are with when the words ask about that person (for example a child, partner, parent or friend). Count another "
    "person's sign only when it is happening to them now or has just happened and the words ask for help for them. Do "
    "not count a sign the person denies (for example \"no chest pain\"), describes as long past and resolved, or as "
    "hypothetical or only asks about for next time. Do not count another person's sign that is only background to the "
    "writer's own concern, such as their worry, sleep or own risk, or another person's past illness, long-standing "
    "condition or family history (for example \"my brother had a fit at school years ago\", \"my colleague collapsed "
    "at work and now I can't stop worrying\" or \"what should I do if my mum collapses?\"). Count a sign that is "
    "described in different, everyday words (for example \"blood streaks in my phlegm\" is coughing up blood, \"numb "
    "between my legs\" is numbness around the groin, \"threw up something like coffee grounds\" or \"吐血\" is vomiting "
    "blood, \"I bring up every sip of water\" is being unable to keep fluids down, and \"kms\" is a thought of "
    "suicide). When you are unsure whether a described symptom matches a sign, count it. Return only JSON: "
    "{\"present\": [<ids>]}, using only the listed ids, and an empty list when no sign is described."
)
PROMPT_SHA256 = hashlib.sha256(INSTRUCTIONS.encode("utf-8")).hexdigest()
URGENT_ORDER = ["urgent_clinician", "emergency"]  # increasing urgency of a matched red flag


class RedFlagDescribed(Exception):
    """The person's words describe an approved red flag: no guidance; the case goes to urgent help."""

    def __init__(self, ids: list[str], level: str):
        super().__init__(level)
        self.ids, self.level = ids, level


class ScreenFailed(RuntimeError):
    """Content-free failure: the caller fails closed (no guidance). #550: `cause` says why, content-free: the adapter's
    typed result (`timeout`, `model_unavailable`, `model_output_invalid`), `invalid_output` (JSON that is not
    `{"present": [approved ids]}`, such as the `{}` a thinking model answered) or `no_time_left`."""

    def __init__(self, code: str, cause: str | None = None):
        super().__init__(code)
        self.code = code
        self.cause = cause

    @property
    def detail(self) -> list[str]:
        """The job's content-free reason (attempt 0 is the screen before any draft): `0:RED_FLAG_SCREEN_INVALID/invalid_output`."""
        return [f"0:{self.code}" + (f"/{self.cause}" if self.cause else "")]


# #387: the profile fields the person types in their own words (A02), with the label the source is screened under.
PROFILE_TEXT = {"history": "Relevant history", "medications": "Current medications", "allergies": "Reported allergies"}
# #583: the context kinds whose value the server checks itself, so they carry no free text: the checklist (its ticked
# approved IDs route by themselves), the age (a whole number from 18 to 130) and the allergy status (one of three
# values). Every other client kind (the contract allows any) reaches the guidance model as a confirmed fact labelled
# with its kind, so it is screened as "<kind>: <value>". The server's own fact namespaces (answers, record facts and
# fixture signals) are not context: answers are screened as answers, the others are not the person's words.
STRUCTURED_KINDS = {RED_FLAGS_KIND, "age_years", "allergy_status"}
SERVER_KIND_PREFIXES = ("answer:", "fixture:", "record:")
OTHER_DETAIL = "Other detail"


def _field(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def _context_text(value: Any) -> str:
    """A context value as words: a list joined, true/false as JSON writes them, null as unknown."""
    if isinstance(value, list):
        return ", ".join(map(str, value))
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def profile_words(items: list[Any]) -> list[dict[str, str]]:
    """#387: the profile free text the person typed (relevant history, current medications, reported allergies), from
    stored facts or from the context of a create or edit request. Blank or unknown fields carry nothing to screen.
    #583: and every other client context kind with its value, as the guidance model reads it."""
    words = []
    for item in items:
        kind, value = _field(item, "kind"), _field(item, "value")
        if kind in PROFILE_TEXT:
            if isinstance(value, str) and value.strip():
                words.append({"source": PROFILE_TEXT[kind], "text": value})
        elif (isinstance(kind, str) and kind not in STRUCTURED_KINDS and not kind.startswith(SERVER_KIND_PREFIXES)
              and _field(item, "provenance") in {None, "user", "profile"}):
            words.append({"source": OTHER_DETAIL, "text": f"{kind}: {_context_text(value)}"})
    return words


def person_words(concern: str, facts: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The concern, the profile free text (#387) and every answered question, as the person gave them. Unknown answers
    carry nothing to screen."""
    words = [{"source": "concern", "text": concern}, *profile_words(facts)]
    for f in facts:
        if not f["kind"].startswith("answer:") or f["value"] is None:
            continue
        value = ", ".join(map(str, f["value"])) if isinstance(f["value"], list) else str(f["value"])
        words.append({"source": f["original_text"] or "answer", "text": value})
    return words


def snapshot(pathway: Pathway, words: list[dict[str, str]]) -> dict[str, Any]:
    return {"instructions": INSTRUCTIONS,
            "warning_signs": [{"id": i, "text": f["text"]} for i, f in pathway.red_flags.items()],
            "person_words": words}


def accept(output: Any, pathway: Pathway) -> list[str]:
    """The matched IDs, or ScreenFailed for anything but `{"present": [distinct approved ids]}`."""
    present = output.get("present") if isinstance(output, dict) and set(output) == {"present"} else None
    if (not isinstance(present, list) or len(set(map(str, present))) != len(present)
            or any(not isinstance(i, str) or i not in pathway.red_flags for i in present)):
        raise ScreenFailed("RED_FLAG_SCREEN_INVALID", "invalid_output")
    return sorted(present)


def highest_level(pathway: Pathway, ids: list[str]) -> str:
    levels = [pathway.red_flags[i]["level"] for i in ids]
    assert levels and all(level in URGENT_LEVELS for level in levels)
    return max(levels, key=URGENT_ORDER.index)


def ticked_level(pathway: Pathway | None, ids: list[str] | None) -> str | None:
    """The reviewed level of ticked checklist items (#153: recorded on the case with its urgent state)."""
    return highest_level(pathway, ids) if pathway is not None and ids else None


def screen_concern(ctx, concern: str, context: list[Any] | None = None) -> tuple[list[str], str | None]:
    """#153 (ADR-003 amendment 3): screen the concern when a case is created or its concern is edited, so a written
    emergency interrupts intake at once instead of after the questions. #387: with the profile free text of `context`
    (the request's or the stored profile context), screened on creation and on an edit that changes it.

    Returns (matched IDs, deferral code). Runs only in local mode with a reviewed pathway that has the screen. A screen
    that fails or does not answer in time defers: intake continues, and the screen before guidance, which reads the
    concern again with every answer, still runs and fails closed. It can only route a case to urgent help sooner."""
    pathway = ctx.pathway
    if ctx.settings.mode == "mock" or pathway is None or not pathway.active() or not pathway.red_flag_screen:
        return [], None
    try:
        words = [{"source": "concern", "text": concern}, *profile_words(context or [])]
        return asyncio.run(screen(ctx.runtime, pathway, words, ctx.settings.concern_screen_timeout_seconds)), None
    except ScreenFailed as failed:
        return [], failed.code


async def screen(runtime, pathway: Pathway, words: list[dict[str, str]], timeout_s: float) -> list[str]:
    """Run the screen through the runtime adapter; fail closed on any error."""
    if timeout_s <= 0:
        raise ScreenFailed("RED_FLAG_SCREEN_UNAVAILABLE", "no_time_left")
    try:
        output = await runtime.generate_json(TASK, PROMPT_VERSION, snapshot(pathway, words), SCHEMA_ID, timeout_s)
    except Exception as exc:  # transport, timeout or non-JSON output
        raise ScreenFailed("RED_FLAG_SCREEN_UNAVAILABLE",
                           str(getattr(exc, "code", "GENERATION_FAILED")).lower()) from exc
    return accept(output, pathway)
