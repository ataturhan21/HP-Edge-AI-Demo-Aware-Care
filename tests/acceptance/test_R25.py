"""R25 unsupported certainty (ADR-012): scoped tripwire plus local adjudication, failing closed. M08.

A test-only runtime adapter stands in for the local model so each branch is exercised through a real generation
job: it returns a chosen guidance draft and a chosen certainty-review result. Mock mode itself has no reviewer.
"""
import pytest

REQUIREMENT = "R25"

SAFE_QUESTION = "Should I ask about tests to rule out other causes?"
UNSAFE = "This rules out an emergency, so you definitely do not need care."
HEDGED = "A clinician may suggest tests to rule out other causes if needed."


def draft(**over):
    base = {
        "urgency_level": "routine_clinician", "reason_codes": ["TEST_DRAFT"],
        "outcome_title": "A primary care conversation",
        "action": {"category": "discuss_with_clinician", "text": "Book a routine appointment.",
                   "rationale": "The concern is ongoing and not severe."},
        "possible_explanation": "Several everyday factors can be involved.",
        "clinician_questions": ["What should I track before the visit?", "Is anything I do making it worse?"],
        "escalation_advice": ["If symptoms become severe, contact emergency services."],
    }
    base.update(over)
    return base


class ScriptedRuntime:
    """Returns the guidance draft, then the scripted review (a dict, or an exception to raise)."""

    def __init__(self, candidate, review=None):
        self.candidate, self.review, self.calls = candidate, review, []

    async def generate_json(self, task, prompt_version, snapshot, schema_id, timeout_s):
        self.calls.append((task, schema_id, snapshot))
        if task == "guidance":
            return self.candidate
        if isinstance(self.review, Exception):
            raise self.review
        return self.review(snapshot) if callable(self.review) else self.review

    async def health(self):
        return {"status": "ready", "provider": "zrt", "model_id": "scripted-test", "reason_code": None}

    async def manifest(self):
        return {"manifest_id": None, "adapter_version": "scripted-test", "model": None}


def safe_for_all(snapshot):
    return {"verdicts": [{"index": s["index"], "unsafe": False, "category": "none"} for s in snapshot["statements"]]}


def generate(app, api, runtime):
    app[0].state.ctx.runtime = runtime
    api.start()
    cid = api.new_case()["id"]
    job = api.to_guided(cid)
    return cid, job


def reviews(runtime):
    return [c for c in runtime.calls if c[0] == "certainty_review"]


def test_question_with_a_flagged_phrase_is_not_checked_or_reviewed(app, api):
    """Option 1 scope: the person's suggested questions are not assertions."""
    runtime = ScriptedRuntime(draft(clinician_questions=[SAFE_QUESTION, "What should I track?"]))
    cid, job = generate(app, api, runtime)
    assert job["status"] == "succeeded" and reviews(runtime) == []
    assert SAFE_QUESTION in api.ok("GET", f"/cases/{cid}/guidance", 200, "Guidance")["clinician_questions"]


def test_flagged_statement_judged_safe_is_published(app, api):
    """T-R25: a flagged phrase used in a hedged, safe way passes after the local review."""
    runtime = ScriptedRuntime(draft(possible_explanation=HEDGED), review=safe_for_all)
    cid, job = generate(app, api, runtime)
    assert job["status"] == "succeeded"
    [(_, schema, snapshot)] = reviews(runtime)
    assert schema == "CertaintyReview" and [s["text"] for s in snapshot["statements"]] == [HEDGED]
    assert api.ok("GET", f"/cases/{cid}/guidance", 200, "Guidance")["possible_explanations"][0]["text"] == HEDGED


@pytest.mark.parametrize("category", ["rules_out_risk", "definitive_diagnosis"])
def test_flagged_statement_judged_unsafe_is_rejected_without_exposing_it(app, api, category):
    """T-R25-S01/S02: an unsafe draft is rejected; the limited fallback shows no draft text."""
    runtime = ScriptedRuntime(draft(possible_explanation=UNSAFE),
                              review={"verdicts": [{"index": 0, "unsafe": True, "category": category}]})
    cid, job = generate(app, api, runtime)
    assert job["status"] == "failed" and job["error_code"] == "OUTPUT_VALIDATION_FAILED"
    r = api.req("GET", f"/cases/{cid}/guidance")
    assert r.status_code == 404 and "rules out" not in r.text  # #269: never generated
    read = api.case(cid)
    assert read["case"]["state"] == "limited" and "retry" in read["allowed_actions"]


@pytest.mark.parametrize("review", [
    RuntimeError("reviewer unavailable"),
    TimeoutError("reviewer timed out"),
    {"verdicts": []},                                                      # missing verdict
    {"verdicts": [{"index": 0, "unsafe": False, "category": "none"}] * 2},  # extra or duplicate verdict
    {"verdicts": [{"index": 5, "unsafe": False, "category": "none"}]},       # out of range
    {"verdicts": [{"index": 0, "unsafe": "no", "category": "none"}]},        # not a boolean
    {"verdicts": [{"index": 0, "unsafe": False, "category": "rules_out_risk"}]},  # contradictory
    {"verdict": "safe"},                                                    # wrong shape
    "safe",                                                                 # not an object
], ids=["unavailable", "timeout", "missing", "duplicate", "out-of-range", "not-boolean", "contradictory",
        "wrong-shape", "not-object"])
def test_review_failures_fail_closed(app, api, review):
    """ADR-012: anything but an explicit, complete 'safe' verdict rejects the draft."""
    runtime = ScriptedRuntime(draft(outcome_title="You definitely need nothing else"), review=review)
    _, job = generate(app, api, runtime)
    assert job["status"] == "failed" and job["error_code"] == "OUTPUT_VALIDATION_FAILED"


def test_every_flagged_statement_must_be_judged_safe(app, api):
    """One unsafe verdict among several flagged statements rejects the whole draft."""
    runtime = ScriptedRuntime(
        draft(possible_explanation=HEDGED, escalation_advice=["Care is guaranteed to be unnecessary."]),
        review={"verdicts": [{"index": 0, "unsafe": False, "category": "none"},
                             {"index": 1, "unsafe": True, "category": "guaranteed_safety"}]})
    _, job = generate(app, api, runtime)
    assert job["status"] == "failed"
    assert len(reviews(runtime)[0][2]["statements"]) == 2


def test_mock_mode_has_no_reviewer_so_flagged_statements_stay_rejected(app, api):
    """Without a local model the review cannot run, so a flagged statement is rejected (conservative)."""
    from app.runtime.mock_provider import MockRuntimeAdapter
    ctx = app[0].state.ctx
    mock = MockRuntimeAdapter(ctx.fixtures)
    original = mock.generate_json

    async def flagged_guidance(task, prompt_version, snapshot, schema_id, timeout_s):
        if task == "guidance":
            out = dict(await original(task, prompt_version, snapshot, schema_id, timeout_s))
            out["possible_explanation"] = HEDGED
            return out
        return await original(task, prompt_version, snapshot, schema_id, timeout_s)

    mock.generate_json = flagged_guidance
    _, job = generate(app, api, mock)
    assert job["status"] == "failed" and job["error_code"] == "OUTPUT_VALIDATION_FAILED"


def test_unflagged_draft_needs_no_review(app, api):
    """Drafts without flagged phrases are validated as before, with no extra model call."""
    runtime = ScriptedRuntime(draft())
    _, job = generate(app, api, runtime)
    assert job["status"] == "succeeded" and reviews(runtime) == []


# --- Local generation path (#51): the same ADR-012 review on the qualified draft -----------------------------------

def test_local_path_questions_are_not_reviewed_and_flagged_statements_are():
    """ADR-012 on the local path: a question with 'rule out' is not flagged; a flagged statement is reviewed."""
    from test_R24 import ScriptedModel, local_draft, run_local
    clean = ScriptedModel(local_draft())
    run_local(clean)
    assert [c["task"] for c in clean.calls] == ["guidance"]
    flagged = local_draft(uncertainties=["Only a clinician can rule out other causes."])
    model = ScriptedModel(flagged, {"verdicts": [{"index": 0, "unsafe": False, "category": "none"}]})
    result = run_local(model)
    assert [c["task"] for c in model.calls] == ["guidance", "certainty_review"]
    assert result.reviews[0]["cleared"] and model.calls[1]["snapshot"]["statements"][0]["text"] == \
        "Only a clinician can rule out other causes."


@pytest.mark.parametrize("verdict", [
    {"verdicts": [{"index": 0, "unsafe": True, "category": "rules_out_risk"}]},
    RuntimeError("reviewer down"),
    {"verdicts": []},
], ids=["unsafe", "unavailable", "incomplete"])
def test_local_path_rejected_review_uses_the_repair_and_can_fail_closed(verdict):
    """ADR-012: an unsafe or failed review rejects the draft; the repair gets one more chance, then it fails."""
    import pytest as _pytest
    from app.modules.guidance.local import LocalGenerationFailed
    from test_R24 import ScriptedModel, local_draft, run_local
    unsafe = local_draft(outcome_title="We can rule out an emergency.")
    result = run_local(ScriptedModel(unsafe, verdict, local_draft()))
    assert [a["result"] for a in result.attempts] == ["rejected", "valid"]
    assert result.attempts[0]["codes"] == ["prohibited_certainty"]
    with _pytest.raises(LocalGenerationFailed):
        run_local(ScriptedModel(unsafe, verdict, unsafe, verdict))


# #85: medication-change commands carry no certainty phrase, so they have their own tripwires (same reviewer).
MEDICATION_COMMANDS = ["Stop taking your blood pressure tablets.", "Start taking ibuprofen 400 mg three times a day.",
                       "Double up on your inhaler when it gets bad.", "Switch to a stronger painkiller.",
                       "Come off your antidepressant this week.", "Increase the dose of your sleeping pills.",
                       # #407: dosing and change phrasings without any of the #85 substrings (the first one was
                       # published on the Nano)
                       "Stop any new medication immediately if you experience swelling, shortness of breath, or a "
                       "sudden increase in blood pressure readings.", "Stop the tablets if you feel dizzy.",
                       "Take two ibuprofen every six hours.", "Increase your amlodipine to twice a day.",
                       "Halve your metformin."]


@pytest.mark.parametrize("command", MEDICATION_COMMANDS)
def test_a_medication_change_command_is_reviewed_and_rejected_when_unsafe(app, api, command):
    def unsafe_rx(snapshot):
        return {"verdicts": [{"index": s["index"], "unsafe": s["text"] == command,
                              "category": "prescription_change" if s["text"] == command else "none"}
                             for s in snapshot["statements"]]}
    runtime = ScriptedRuntime(draft(action={"category": "discuss_with_clinician", "text": command,
                                            "rationale": "It may help."}), unsafe_rx)
    cid, job = generate(app, api, runtime)
    assert job["status"] == "failed"
    [review] = reviews(runtime)
    assert command in [s["text"] for s in review[2]["statements"]]
    assert command not in str(api.case(cid))


def test_a_mention_of_medications_is_reviewed_and_published_when_judged_safe(app, api):
    from app.modules.guidance.service import flagged_statements
    mention = "Bring a list of your medications to the appointment."
    assert flagged_statements([mention]) == [mention]
    runtime = ScriptedRuntime(draft(action={"category": "discuss_with_clinician", "text": mention,
                                            "rationale": "It helps the clinician."}), safe_for_all)
    cid, job = generate(app, api, runtime)
    assert job["status"] == "succeeded" and len(reviews(runtime)) == 1


def test_everyday_statements_without_a_tripwire_are_not_reviewed():
    from app.modules.guidance.service import flagged_statements
    plain = ["Keep a short symptom diary.", "Book a routine appointment.", "Rest and drink fluids.",
             "What should I track before the visit?", "Switch to an anti-dandruff shampoo with zinc pyrithione.",
             "Switch to a softer pillow.", "Continue using the salicylic acid face wash.",
             # #407: everyday self-care that the widened tripwire must not send to the reviewer
             "Apply a fragrance-free moisturizer to your forearms twice daily.", "Reduce your screen time before bed.",
             "Take short breaks during long screen sessions.", "Stop the activity if the pain gets worse.",
             "Take a short walk every day.", "Increase your fluid intake.", "Stop using any new skin products.",
             "Change position every few hours.", "Take a lukewarm shower instead of a hot one."]
    assert flagged_statements(plain) == []


def test_a_medication_instruction_is_rejected_on_the_local_path_even_when_the_reviewer_clears_it():
    """#407: the Nano's reviewer cleared "Stop any new medication immediately if ..." 3 of 3 times (a conditional use);
    the local validator rejects an instruction to change a medicine or a dose itself and names it in the repair."""
    from app.modules.guidance import local
    from test_R24 import ScriptedModel, local_draft, local_inputs, run_local
    stop = MEDICATION_COMMANDS[6]
    unsafe = local_draft(escalation_advice=[stop])
    assert local.check_draft(local_inputs(), unsafe) == ["medication_change"]
    model = ScriptedModel(unsafe, local_draft())  # no reviewer call is needed for the rejected draft
    result = run_local(model)
    assert [a["result"] for a in result.attempts] == ["rejected", "valid"]
    assert result.attempts[0]["codes"] == ["medication_change"]
    assert [c["task"] for c in model.calls] == ["guidance", "guidance"]
    errors = model.calls[1]["snapshot"]["repair"]["previous_output_errors"]
    assert any(e.startswith("medication_change: escalation_advice[0] ") for e in errors)
    assert not any("swelling" in e for e in errors)  # paths only, no case text


# #491: the Nano's real outputs for the QA's G08 inputs (synthetic), captured on the device at temperature 0.
G08_NANO = "evidence/clinical-review/2026-10-23-g08-repair/nano-g08-outputs.json"


def g08_nano():
    import json
    from conftest import ROOT
    return json.loads((ROOT / G08_NANO).read_text())


class ReplayedNano:
    """Replays the Nano's recorded outputs: attempt 1, then the repair the model wrote for the exact repair message it
    was given (`repair_errors_<tag>` -> `repair_<tag>`: an earlier message or the current one), then its certainty
    review (`certainty_review_<tag>` of that repair, else `certainty_review_after`)."""

    def __init__(self, fx):
        self.fx, self.calls, self.tag = fx, [], None

    async def generate_json(self, task, prompt_version, snapshot, schema_id, timeout_s):
        self.calls.append({"task": task, "snapshot": snapshot})
        if task == "certainty_review":
            return self.fx.get(f"certainty_review_{self.tag}", self.fx.get("certainty_review_after"))
        repair = snapshot.get("repair")
        if repair is None:
            return self.fx["attempt_1"]
        tags = [k.removeprefix("repair_errors_") for k, v in self.fx.items()
                if k.startswith("repair_errors_") and v == repair["previous_output_errors"]]
        assert tags, "no recorded output for this repair"
        self.tag = tags[0]
        return self.fx[f"repair_{self.tag}"]


def test_g08_nano_outputs_carry_a_stop_instruction_that_the_validator_rejects():
    """#491 / #407: both drafts the Nano's model wrote under the v0.15.0-demo.1 repair tell the person to stop taking
    ibuprofen ("Stop taking ibuprofen ... if ..."), a medication change the validator must keep rejecting."""
    from app.modules.guidance import local
    from app.modules.guidance.service import medication_instruction
    fx = g08_nano()
    inputs = local.LocalInputs(**fx["inputs"])
    for key in ("attempt_1", "repair_before"):
        draft = local.restore_ids(inputs, fx[key])
        assert "medication_change" in local.check_draft(inputs, draft)
        assert [p for p, t in local.located_statements(draft) if medication_instruction(t)] == ["escalation_advice[0]"]
    after = local.restore_ids(inputs, fx["repair_after"])
    assert local.check_draft(inputs, after) == []
    assert not any(medication_instruction(t) for t in local.statements(after))


# #500: the same inputs in both context orders (the red-flag checklist first, as the v0.15.0 and v0.15.1 device checks
# sent them, or the medications first, as #491 measured), with the Nano's recorded repair under the v0.15.1-demo.1
# (#491) message and under the #500 message.
G08_ORDER_NANO = "evidence/clinical-review/2026-10-23-g08-order/nano-g08-order-outputs.json"


def g08_order_nano(order):
    import json
    from conftest import ROOT
    return json.loads((ROOT / G08_ORDER_NANO).read_text())[order]


@pytest.mark.parametrize("order", ["checklist_first", "profile_first"])
def test_g08_order_nano_drafts_that_the_validator_must_reject(order):
    """#500 / #407: attempt 1 tells the person to stop a medicine in either order ("Stop any new medication immediately
    if ...", "Stop taking ibuprofen and seek medical attention if ..."); with the checklist first, the repair under the
    #491 message kept "Stop any new medication if ...". The validator rejects them all; the #500 repairs are valid."""
    from app.modules.guidance import local
    from app.modules.guidance.service import medication_instruction
    fx = g08_order_nano(order)
    inputs = local.LocalInputs(**fx["inputs"])
    for key in ("attempt_1", *(("repair_before",) if order == "checklist_first" else ())):
        draft = local.restore_ids(inputs, fx[key])
        assert "medication_change" in local.check_draft(inputs, draft)
        assert [p for p, t in local.located_statements(draft) if medication_instruction(t)] == ["escalation_advice[0]"]
    after = local.restore_ids(inputs, fx["repair_after"])
    assert local.check_draft(inputs, after) == []
    assert not any(medication_instruction(t) for t in local.statements(after))


@pytest.mark.parametrize("order", ["checklist_first", "profile_first"])
def test_g08_on_the_nano_publishes_in_either_context_order(order):
    """#500 (#491): the repair is a new generation that never sees the rejected draft, so a path alone named a sentence
    the model could not see. With the checklist first, the Nano failed 5 of 5 times: told to delete "that medicine
    instruction" from escalation_advice[0], it wrote "Stop any new medication if ..." again. The repair now quotes the
    instruction's own words and gives the rewrite; replaying the model's recorded answers, both orders publish without
    any medicine instruction (on the previous message, the checklist-first order fails closed)."""
    from app.modules.guidance import local
    from app.modules.guidance.service import medication_instruction
    from test_R24 import run_local
    fx = g08_order_nano(order)
    model = ReplayedNano(fx)
    result = run_local(model, inputs=local.LocalInputs(**fx["inputs"]))
    assert [a["result"] for a in result.attempts] == ["rejected", "valid"]
    assert [c["task"] for c in model.calls] == ["guidance", "guidance", "certainty_review"]
    assert not any(medication_instruction(t) for t in local.statements(result.draft))
    errors = model.calls[1]["snapshot"]["repair"]["previous_output_errors"]
    quoted = {"checklist_first": "stop any new medication", "profile_first": "stop taking ibuprofen"}[order]
    med = [e for e in errors if e.startswith("medication_change: escalation_advice[0] ")]
    assert med and f'says "{quoted}"' in med[0] and "If ..., seek medical advice promptly." in med[0]
    # Only the instruction's words are quoted: never the warning signs, the rest of the statement or a case fact.
    assert not any(w in e.lower() for e in errors for w in ("swelling", "shortness", "chest pain", "lisinopril", "knee"))


# #543: the same G08 inputs with the checklist first, after #514 reworded two intake questions. The Nano's attempt 1
# changed: it is rejected only for "the user" in a rationale, and the repair, told only that, wrote "Stop any new
# medication if ..." (main 79d1c89: 0 of 5 published). Recorded on the Nano before and after the fix.
G08_THIRD_PERSON_NANO = "evidence/clinical-review/2026-10-26-g08-third-person/nano-g08-third-person-outputs.json"


def g08_third_person_nano():
    import json
    from conftest import ROOT
    return json.loads((ROOT / G08_THIRD_PERSON_NANO).read_text())["checklist_first"]


def test_g08_since_514_attempt_1_is_third_person_and_its_old_repair_a_medicine_instruction():
    """#543: attempt 1 has no medicine instruction, only "the user" in actions[2].rationale; the repair written under the
    earlier message tells the person to stop a medicine, which the validator must keep rejecting."""
    from app.modules.guidance import local
    from app.modules.guidance.service import medication_instruction
    fx = g08_third_person_nano()
    inputs = local.LocalInputs(**fx["inputs"])
    first = local.restore_ids(inputs, fx["attempt_1"])
    assert local.check_draft(inputs, first) == ["third_person"]
    assert local.rejections(first, ["third_person"], []) == ["third_person@actions[2].rationale"]
    before = local.restore_ids(inputs, fx["repair_before"])
    assert "medication_change" in local.check_draft(inputs, before)
    assert [t for t in local.statements(before) if medication_instruction(t)] == [
        "Stop any new medication if you experience swelling or shortness of breath."]


def test_g08_checklist_first_publishes_again_because_the_repair_restates_the_medicine_rule():
    """#543: in a case that lists the person's medications, a repair that is not already about medication_change
    restates the medicine rule. Replaying the Nano's recorded answers, G08 (checklist first) publishes with no medicine
    instruction; under the earlier message the recorded repair fails closed."""
    from app.modules.guidance import local
    from app.modules.guidance.service import medication_instruction
    from test_R24 import run_local
    fx = g08_third_person_nano()
    model = ReplayedNano(fx)
    result = run_local(model, inputs=local.LocalInputs(**fx["inputs"]))
    assert [a["result"] for a in result.attempts] == ["rejected", "valid"] and model.tag == "after"
    errors = model.calls[1]["snapshot"]["repair"]["previous_output_errors"]
    assert errors[-1] == f"keep: {local.NO_MEDICINE_ACTION}"
    assert not any(medication_instruction(t) for t in local.statements(result.draft))
    # No case text in the repair: the rule and the place only.
    assert not any(w in e.lower() for e in errors for w in ("swelling", "lisinopril", "knee", "ibuprofen"))


def test_the_medicine_rule_is_restated_only_for_a_case_that_lists_medications():
    """#543: the Quick flows and the journeys carry no medications entry, so their repair messages stay exactly as they
    were (restating the rule there changed the C30 journey's repair on the Nano and failed it closed); a repair already
    about medication_change names the statement instead."""
    from app.modules.guidance import local
    fx = g08_third_person_nano()
    inputs = local.LocalInputs(**fx["inputs"])
    assert local.lists_medications(inputs)
    meds = next(f for f in inputs.facts if f["question"] == "Current medications")
    for answer in ("unknown", "", None):
        facts = [f if f is not meds else {**f, "answer": answer} for f in inputs.facts]
        assert not local.lists_medications(local.LocalInputs(**{**fx["inputs"], "facts": facts}))
    assert not local.lists_medications(local.LocalInputs(**selfcare_nano("selfcare")["inputs"]))
    # The #500 checklist-first case: attempt 1 is a medicine instruction, so its repair names it and adds no reminder.
    order = g08_order_nano("checklist_first")
    from test_R24 import run_local
    model = ReplayedNano(order)
    run_local(model, inputs=local.LocalInputs(**order["inputs"]))
    errors = model.calls[1]["snapshot"]["repair"]["previous_output_errors"]
    assert not any(e.startswith("keep: tell the person no medicine action") for e in errors)


@pytest.mark.parametrize(("statement", "quoted"), [
    (MEDICATION_COMMANDS[6], "stop any new medication"), ("If you feel dizzy, stop the tablets.", "stop the tablets"),
    ("Take two ibuprofen every six hours.", "take two ibuprofen"),
    ("Increase your amlodipine to twice a day.", "increase your amlodipine to twice"),
    ("Halve your metformin.", "halve your"),
    ("Rest your knee; stop taking ibuprofen and take two paracetamol tablets.", "stop taking ibuprofen\", \"take two paracetamol"),
])
def test_the_medication_repair_quotes_only_the_instruction_words(statement, quoted):
    """#500: the repair names the statement's place and quotes the matched instruction words (the model's own), and
    nothing else of the statement; a conditional instruction gets the "If ..., seek medical advice promptly." rewrite,
    one without a condition the plain "say instead when to seek medical advice"."""
    from app.modules.guidance import local
    from test_R24 import local_draft
    problems = local.medication_change_problems(local_draft(escalation_advice=[statement]))
    assert len(problems) == 1
    assert problems[0].startswith(f'escalation_advice[0] says "{quoted}", a medicine instruction; rewrite escalation_advice[0] ')
    conditional = "if " in statement.lower()
    assert ("If ..., seek medical advice promptly." in problems[0]) == conditional
    assert ("says instead when to seek medical advice" in problems[0]) == (not conditional)
    rest = problems[0].split(", a medicine instruction; ")[1]
    assert not any(w in rest for w in ("dizzy", "six hours", "a day", "metformin", "rest your knee", "paracetamol"))


@pytest.mark.parametrize("statement", MEDICATION_COMMANDS[6:] + ["If you feel dizzy, stop the tablets.",
                                                                 "Stop taking your blood pressure tablets."])
def test_medication_instructions_are_recognised(statement):
    from app.modules.guidance.service import medication_instruction
    assert medication_instruction(statement)


@pytest.mark.parametrize("statement", [
    "Do not stop your medication without speaking to a clinician.",
    "Keep taking your usual medicines as prescribed unless a clinician tells you otherwise.",
    "Take paracetamol as directed on the packet if you need pain relief.",
    "Bring a list of your medications to the appointment.", "Ask a pharmacist before you start taking anything new.",
    "Tell the clinician if you have recently had to stop taking a medicine.",
    "Mention any recent dose changes to the clinician.", "Stop using any new skin products.",
    "Apply a fragrance-free moisturizer twice daily."])
def test_mentions_and_everyday_self_care_are_not_medication_instructions(statement):
    from app.modules.guidance.service import medication_instruction
    assert not medication_instruction(statement)

# #55 connected acceptance with the reviewed pathway (local mode, scripted model and reviewer; ADR-003, ADR-012).

def test_local_unsafe_certainty_is_rejected_and_only_the_reviewed_fallback_is_shown(local):
    """T-R25-S01: a draft with a definitive diagnosis, guaranteed safety or a prescription change is rejected (after
    its single repair) and no draft text is exposed; the case shows the reviewed limited fallback state."""
    import json
    from conftest import NO_RED_FLAGS
    api, model, application = local
    for phrase, category in (("You have a migraine.", "definitive_diagnosis"),
                             ("This is guaranteed to be harmless.", "guaranteed_safety"),
                             ("Stop taking your blood pressure tablets.", "prescription_change")):
        model.calls.clear()
        model.override = {"outcome_title": phrase}
        model.unsafe_phrases, model.unsafe_category = (phrase,), category
        case = api.new_case(context=[NO_RED_FLAGS])
        job = api.to_guided(case["id"])
        assert job["status"] == "failed" and job["result_id"] is None, phrase
        assert len([c for c in model.calls if c["task"] == "guidance"]) == 2, phrase
        read = api.case(case["id"])
        assert read["case"]["state"] == "limited" and "retry" in read["allowed_actions"]
        assert phrase not in json.dumps(read) and phrase not in json.dumps(job)
    with application.state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM guidance").fetchone()[0] == 0
        assert not [r for r in conn.execute("SELECT * FROM events") if "migraine" in json.dumps(list(r))]


def test_local_model_cannot_relax_the_reviewed_level_or_add_numeric_confidence(local):
    """T-R25-S02: when the reviewed decision requires a clinician (gaps), a self-care draft is refused; a numeric
    diagnostic confidence is caught by the certainty review; the published level never drops below the decision."""
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    model.level = "self_care_candidate"  # the model tries to lower the reviewed routine decision
    case = api.new_case(context=[NO_RED_FLAGS])
    rev = case["revision"]
    first = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                   json={"expected_revision": rev})["question"]
    api.ok("PUT", f"/cases/{case['id']}/answers/{first['id']}", 200, "SaveAnswerResponse",
           json={"expected_revision": rev, "status": "unknown", "value": None})
    job = api.to_guided(case["id"])
    assert job["status"] == "failed"  # the lowered draft and its repair were both refused
    calls = [c for c in model.calls if c["task"] == "guidance"]
    assert calls[0]["snapshot"]["case"]["reviewed_urgency_decision"] == "routine_clinician" and len(calls) == 2
    # A numeric diagnostic confidence is a certainty tripwire the reviewer judges unsafe.
    model.calls.clear()
    model.level = None
    phrase = "There is a 90% chance this is tension headache."
    model.override = {"outcome_title": phrase}
    model.unsafe_phrases, model.unsafe_category = (phrase,), "numeric_diagnostic_confidence"
    second = api.new_case(context=[NO_RED_FLAGS])
    assert api.to_guided(second["id"])["status"] == "failed"
    assert [c for c in model.calls if c["task"] == "certainty_review"]


# #538: the Nano's real outputs (synthetic) for the presenter's Self-care Quick flow scenario and QA app-05's
# sore-throat answer set. Attempt 1 restates the checklist answer as "You have no urgent warning signs ..."; the
# "you have" tripwire sends it to the reviewer, which judges it a diagnosis or a ruled-out risk. The generic repair named
# nothing, so the model wrote the same claim again (and drifted to "The user ..."): 5 of 5 self-care runs failed closed.
SELFCARE_NANO = "evidence/clinical-review/2026-10-26-selfcare-certainty/nano-selfcare-outputs.json"


def selfcare_nano(case):
    import json
    from conftest import ROOT
    return json.loads((ROOT / SELFCARE_NANO).read_text())[case]


class ReplayedSelfcare:
    """Attempt 1 and its recorded review, then the repair recorded for the exact error list it is given (before or
    after #538), then that repair's recorded review. `force` replays that repair whatever the errors are."""

    def __init__(self, fx, force=None):
        self.fx, self.force, self.calls, self.tag = fx, force, [], None

    async def generate_json(self, task, prompt_version, snapshot, schema_id, timeout_s):
        self.calls.append({"task": task, "snapshot": snapshot})
        if task == "certainty_review":
            review = self.fx["certainty_review_1"] if self.tag is None else self.fx[f"certainty_review_{self.tag}"]
            assert [s["text"] for s in snapshot["statements"]] == [s["text"] for s in review["statements"]]
            return review["output"]
        repair = snapshot.get("repair")
        if repair is None:
            return self.fx["attempt_1"]
        self.tag = self.force or next((t for t in ("before", "after")
                                       if repair["previous_output_errors"] == self.fx[f"repair_errors_{t}"]), None)
        assert self.tag, "no recorded output for this repair"
        return self.fx[f"repair_{self.tag}"]


@pytest.mark.parametrize("case", ["selfcare", "sore_throat"])
def test_the_nano_restates_the_checklist_as_you_have_no_urgent_warning_signs_and_the_reviewer_rejects_it(case):
    from app.modules.guidance import local
    from app.modules.guidance.service import tripped
    fx = selfcare_nano(case)
    inputs = local.LocalInputs(**fx["inputs"])
    draft = local.restore_ids(inputs, fx["attempt_1"])
    assert local.check_draft(inputs, draft) == []  # the deterministic rules pass; only the review rejects it
    flagged = [p for p, t in local.located_statements(draft) if tripped(t)]
    assert flagged == {"selfcare": ["claims[0].text", "claims[1].text"], "sore_throat": ["claims[0].text"]}[case]
    assert any(t.startswith("You have no urgent warning signs") for t in local.statements(draft))
    assert all(v["unsafe"] for v in fx["certainty_review_1"]["output"]["verdicts"])


@pytest.mark.parametrize("case", ["selfcare", "sore_throat"])
def test_the_certainty_repair_names_the_statement_and_how_to_rewrite_it_so_the_nano_publishes(case):
    """#538: replaying the Nano's recorded answers, the repair now names each statement the reviewer did not clear, its
    tripwire words and what to write instead ("You reported ..."), and restates rule 10; the model's repair is valid
    and publishes. With the earlier generic message the recorded repair fails closed (5 of 5 on the Nano)."""
    from app.modules.guidance import local
    from app.modules.guidance.service import tripped
    from test_R24 import run_local
    fx = selfcare_nano(case)
    model = ReplayedSelfcare(fx)
    result = run_local(model, inputs=local.LocalInputs(**fx["inputs"]))
    assert [a["result"] for a in result.attempts] == ["rejected", "valid"] and model.tag == "after"
    errors = model.calls[2]["snapshot"]["repair"]["previous_output_errors"]
    named = [e for e in errors if e.startswith("prohibited_certainty: ")]
    expected = {"selfcare": [("claims[0].text", "you have mild neck stiffness that", "to state a diagnosis"),
                             ("claims[1].text", "you have no urgent warning signs", "to rule out a risk")],
                "sore_throat": [("claims[0].text", "you have no urgent warning signs", "to state a diagnosis")]}
    assert len(named) == len(expected[case])
    for message, (path, words, judged) in zip(named, expected[case]):
        assert message.startswith(f'prohibited_certainty: {path} says "{words}", judged {judged}; rewrite {path} as a '
                                  'report ("You reported')
    assert errors[-1].startswith('keep: address the person as "you" in every statement')
    # Only the tripwire words are quoted, never the rest of the statement or another case fact.
    assert not any(w in e.lower() for e in errors for w in ("turn your head", "improving", "high fever", "breathing"))
    published = local.statements(result.draft)
    assert not any(tripped(t) for t in published) and not any(t.startswith("You have") for t in published)
    assert result.attempts[0]["rejections"] == [f"prohibited_certainty/{v['category']}@{p}" for v, p in zip(
        fx["certainty_review_1"]["output"]["verdicts"], [p for p, *_ in expected[case]])]


@pytest.mark.parametrize(("case", "detail"), [
    ("selfcare", ["1:prohibited_certainty/definitive_diagnosis@claims[0].text",
                  "1:prohibited_certainty/rules_out_risk@claims[1].text",
                  "2:prohibited_certainty/definitive_diagnosis@claims[0].text"]),
    ("sore_throat", ["1:prohibited_certainty/definitive_diagnosis@claims[0].text",
                     "2:third_person@actions[2].rationale"]),
])
def test_a_failed_generation_says_which_rule_rejected_which_statement_content_free(case, detail):
    """#538: the Nano's drafts under the earlier repair, as recorded: the failure carries each attempt's rule codes and
    places, never text."""
    import json
    from app.modules.guidance import local
    from test_R24 import run_local
    fx = selfcare_nano(case)
    with pytest.raises(local.LocalGenerationFailed) as failed:
        run_local(ReplayedSelfcare(fx, force="before"), inputs=local.LocalInputs(**fx["inputs"]))
    assert local.rejection_detail(failed.value.attempts) == detail
    words = {w.lower().strip('.,"') for t in local.statements(fx["attempt_1"]) + local.statements(fx["repair_before"])
             for w in t.split() if len(w) > 4}
    assert not words & set(json.dumps(detail).lower().replace("@", " ").replace(".", " ").replace("/", " ").split())


@pytest.mark.parametrize(("verdict", "unsafe"), [
    ({"verdicts": [{"index": 0, "unsafe": False, "category": "none"},
                   {"index": 1, "unsafe": True, "category": "rules_out_risk"}]}, {1: "rules_out_risk"}),
    ({"verdicts": [{"index": 0, "unsafe": True, "category": "made_up"}]}, {0: "unclear", 1: "unclear"}),
    ({"verdicts": []}, {0: "unclear", 1: "unclear"}),
    ("not a verdict", {0: "unclear", 1: "unclear"}),
    ({"verdicts": [{"index": 0, "unsafe": False, "category": "none"},
                   {"index": 0, "unsafe": False, "category": "none"}]}, {1: "unclear"}),
])
def test_the_unsafe_statements_of_a_rejected_review(verdict, unsafe):
    from app.modules.guidance.local import review_unsafe
    assert review_unsafe(verdict, 2) == unsafe


def test_an_unavailable_review_marks_every_flagged_statement_unreviewed():
    from app.modules.guidance import local
    from test_R24 import ScriptedModel, local_draft, run_local
    unsafe = local_draft(outcome_title="We can rule out an emergency.")
    with pytest.raises(local.LocalGenerationFailed) as failed:
        run_local(ScriptedModel(unsafe, RuntimeError("down"), unsafe, RuntimeError("down")))
    assert local.rejection_detail(failed.value.attempts) == ["1:prohibited_certainty/unreviewed@outcome_title",
                                                            "2:prohibited_certainty/unreviewed@outcome_title"]


@pytest.mark.parametrize(("statement", "spans"), [
    ("You have no urgent warning signs and can turn your head fully.", ["you have no urgent warning signs"]),
    ("There is a 40% chance; it is definitely fine.", ["40% chance", "definitely fine"]),
    ("This rules out an emergency, so you definitely do not need care.", ["definitely do not need care"]),
    ("Stop taking your tablets (all of them).", ["stop taking your tablets"]),
])
def test_the_tripwire_spans_are_the_matched_words_to_the_end_of_their_clause(statement, spans):
    from app.modules.guidance.service import tripwire_spans
    assert tripwire_spans(statement) == spans


# ------------------------------------------------------------------ #550/#551: the Self-care first draft publishes

SPEED_NANO = "evidence/clinical-review/2026-10-26-selfcare-speed/nano-outputs.json"


def speed_nano(key):
    import json
    from conftest import ROOT
    return json.loads((ROOT / SPEED_NANO).read_text())[key]


def test_the_nanos_guidance_local_5_self_care_draft_publishes_first_time_without_a_review():
    """#550/#551: under guidance-local-5 the Nano's Self-care attempt 1 reports the checklist ("You reported ...") and,
    with short-ids-2, carries no evidence_ids and no reason_codes (439 instead of 650 output tokens). It publishes with
    no certainty review and no repair: one model call instead of four (8.1 s instead of 22.5 s on the Nano). Before, the
    same output failed the draft schema and needed the repair."""
    from app.modules.guidance import local
    from app.modules.guidance.service import tripped
    from test_R24 import ScriptedModel, run_local
    fx = speed_nano("selfcare")
    raw = fx["attempt_1"]
    assert "reason_codes" not in raw and not any("evidence_ids" in r for r in raw["actions"] + raw["claims"])
    model = ScriptedModel(raw)
    inputs = local.LocalInputs(**fx["inputs"])
    result = run_local(model, inputs=inputs)
    assert [a["result"] for a in result.attempts] == ["valid"]
    assert [c["task"] for c in model.calls] == ["guidance"]  # no certainty review, no repair
    assert result.draft["reason_codes"] == [] and all(r["evidence_ids"] == [] for r in result.draft["claims"])
    assert not any(tripped(t) for t in local.statements(result.draft))
    snap = model.calls[0]["snapshot"]["output_schema"]
    assert "reason_codes" not in snap["properties"] and "evidence_ids" not in snap["properties"]["claims"]["items"][
        "properties"]
    guidance = local.to_guidance(inputs, result.draft, manifest_id="m", created_at="2026-10-26T00:00:00Z")
    assert guidance["urgency"]["level"] == "self_care_candidate"
    assert guidance["urgency"]["reason_codes"] == inputs.decision["reason_codes"]


def test_with_evidence_the_model_still_sees_and_cites_evidence_ids():
    from app.modules.guidance import local
    from test_R24 import local_inputs
    schema = local.snapshot(local_inputs(evidence=True))["output_schema"]
    assert "evidence_ids" in schema["properties"]["claims"]["items"]["properties"]
    assert "evidence_ids" not in local.snapshot(local_inputs(evidence=False))["output_schema"]["properties"]["claims"][
        "items"]["properties"]


@pytest.mark.parametrize(("statement", "trips"), [
    # the Nano's statements under guidance-local-5 that the reviewer cleared (app-05's sore throat), now not sent
    *[(s["text"], False) for s in speed_nano("sore_throat_review")["statements"]],
    ("Ask about any concerns you have.", False),
    # still sent: "you have" as the service's own assertion, also next to a report
    ("You have no urgent warning signs.", True),
    ("You reported that you have a cough, and you have a fever.", True),
    ("You said that you have been resting; you have strep throat.", True),
    ("You reported no warning signs, so we can rule out an emergency.", True),
])
def test_an_attributed_you_have_is_no_tripwire_but_an_assertion_still_is(statement, trips):
    """#551: "You reported that you have ..." and "questions you have" assert nothing; the reviewer cleared them on the
    Nano (1.3 s per review). Any other "you have" still goes to the reviewer."""
    from app.modules.guidance.service import tripped, tripwire_spans
    assert tripped(statement) is trips
    assert bool(tripwire_spans(statement)) is trips
    if "reported" in statement or "questions" in statement:
        assert all(v["unsafe"] is False for v in speed_nano("sore_throat_review")["output"]["verdicts"])
