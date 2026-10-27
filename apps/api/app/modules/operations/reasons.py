"""#550: a failed job's reason in plain words (`Job.error_reason`), for the presenter and the logs view.

Built only from the job's content-free `error_code` and `error_detail` (#538: rule codes, categories and places such as
`2:prohibited_certainty/rules_out_risk@claims[1].text`), so it never holds case or model text. The words name what the
local checks rejected and where, e.g. "The first draft was rejected: a statement was judged to rule out a risk (a stated
fact or explanation). The repair was rejected: a statement called the person "the user" (an action's reason). Nothing
was published." A job without a known reason gets None.
"""
from __future__ import annotations

import re

ATTEMPT = {0: "The warning-sign check before the draft", 1: "The first draft", 2: "The repair"}
RULE = {
    "schema": "it did not match the required format",
    "urgency_lowered": "it lowered the reviewed urgency",
    "unsupported_self_care": "it offered self-care that the reviewed urgency does not allow",
    "self_care_action_without_decision": "it gave a self-care step that the reviewed urgency does not allow",
    "self_care_when_undetermined": "it gave a self-care step although it was unsure of the urgency",
    "urgent_without_seek_care": "an urgent result had no step to seek care",
    "urgent_level_without_seek_care": "it raised the urgency but gave no step to seek care",
    "self_care_when_urgent": "it raised the urgency but gave a self-care step",
    "gaps_not_disclosed": "it did not list the unanswered questions",
    "no_possible_explanation": "it gave no possible explanation",
    "invalid_ids": "it cited facts that are not in the case",
    "invented_url_or_provider": "it named a web address or a doctor",
    "prohibited_certainty": "a statement was judged to claim unsupported certainty",
    "third_person": 'a statement called the person "the user" or "the patient"',
    "medication_change": "a statement told the person what to do with a medicine",
}
CERTAINTY = {
    "definitive_diagnosis": "a statement was judged to state a diagnosis",
    "rules_out_risk": "a statement was judged to rule out a risk",
    "guaranteed_safety": "a statement was judged to promise that something is safe",
    "prescription_change": "a statement was judged to change a medicine",
    "numeric_diagnostic_confidence": "a statement was judged to give a percentage for a diagnosis",
    "unclear": "the certainty reviewer did not clear a statement",
    "unreviewed": "the certainty reviewer could not check a statement",
}
PLACE = {"outcome_title": "the title", "actions": "an action", "rationale": "an action's reason",
         "claims": "a stated fact or explanation", "escalation_advice": "the advice on when to get help",
         "uncertainties": "the limits", "clinician_questions": "the questions for a clinician"}
# Results of an attempt (or a check) that produced no usable answer, and job codes without a detail.
RESULT = {
    "TIMEOUT": "the local AI did not answer in time",
    "DEADLINE_EXCEEDED": "the time limit for one consultation ran out",
    "MODEL_UNAVAILABLE": "the local AI could not be reached",
    "RUNTIME_UNAVAILABLE": "the local AI could not be reached",
    "MODEL_OUTPUT_INVALID": "the AI's answer was not valid JSON (cut off, or thinking text instead of an answer)",
    "GENERATION_FAILED": "the local AI call failed",
}
SCREEN_CAUSE = {
    "invalid_output": "the AI answered something other than a list of warning signs (a model that thinks first "
                      "answers this way when the server leaves thinking on)",
    "no_time_left": "no time was left for it",
}
CODE = {
    **RESULT,
    "OUTPUT_VALIDATION_FAILED": "The AI's answer did not pass the checks. Nothing was published.",
    "RED_FLAG_SCREEN_UNAVAILABLE": "The warning-sign check did not answer, so no guidance was made.",
    "RED_FLAG_SCREEN_INVALID": "The warning-sign check gave an unusable answer, so no guidance was made.",
    "PREPARE_TIMEOUT": "The guidance did not finish in time.",
    "QUEUE_FULL": "The device was busy with other guidance.",
    "SERVICE_LIMITED": "Guidance was unavailable on the device.",
    "INTERRUPTED": "The service restarted while it ran.",
    "QUICK_ANSWER_INVALID": "A synthetic answer did not fit the reviewed question.",
}
_ITEM = re.compile(r"^(\d+):([A-Za-z_]+)(?:/([a-z_]+))?(?:@([A-Za-z0-9_.\[\]]+))?$")


def _place(path: str | None) -> str:
    if not path:
        return ""
    head = path.split("[")[0].split(".")[0]
    words = PLACE.get("rationale" if path.endswith(".rationale") else head)
    return f" ({words})" if words else ""


def _words(rule: str, sub: str | None, attempt: int) -> str:
    if attempt == 0 and rule.startswith("RED_FLAG_SCREEN"):
        cause = SCREEN_CAUSE.get(sub or "") or RESULT.get((sub or "").upper()) or "it failed"
        return cause
    if rule == "prohibited_certainty" and sub:
        return CERTAINTY.get(sub, RULE[rule])
    return RULE.get(rule) or RESULT.get(rule) or rule.replace("_", " ").lower()


def error_reason(error_code: str | None, detail: list[str] | None) -> str | None:
    """Plain words for a failed job (see the module docstring); None when there is nothing to say."""
    by_attempt: dict[int, list[str]] = {}
    for item in detail or []:
        m = _ITEM.match(item) if isinstance(item, str) else None
        if not m:
            continue
        attempt, rule, sub, path = int(m[1]), m[2], m[3], m[4]
        text = _words(rule, sub, attempt) + _place(path)
        if text not in by_attempt.setdefault(attempt, []):
            by_attempt[attempt].append(text)
    if by_attempt:
        parts = []
        for attempt, texts in sorted(by_attempt.items()):
            who = ATTEMPT.get(attempt, f"Attempt {attempt}")
            verb = "failed" if attempt == 0 else "was rejected"
            parts.append(f"{who} {verb}: {'; '.join(texts[:4])}{'; and more' if len(texts) > 4 else ''}.")
        return " ".join(parts) + " Nothing was published."
    if error_code in CODE:
        text = CODE[error_code]
        return text if text.endswith(".") else text[0].upper() + text[1:] + ". Nothing was published."
    return None
