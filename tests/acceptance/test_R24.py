"""R24/R25/R27 reviewed-revision guidance: publish only current, validated output. M08."""

import json

import pytest

REQUIREMENT = "R24"


def test_guidance_requires_confirmed_review_of_current_revision(api):
    api.start()
    case = api.new_case()
    api.answer_all(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    r = api.req("POST", f"/cases/{case['id']}/guidance", key=True, json={"expected_revision": rev})
    assert r.status_code == 409 and r.json()["code"] == "STATE_CONFLICT"


def test_published_guidance_is_contract_valid_and_labels_unsourced_explanations(api):
    api.start()
    case = api.new_case()
    job = api.to_guided(case["id"])
    assert job["status"] == "succeeded" and job["result_type"] == "guidance"
    g = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")
    assert g["id"] == job["result_id"] and g["status"] == "complete"
    for claim in g["claims"]:
        assert claim["validation_status"] in {"supported", "suppressed", "general_knowledge"}
        if claim["kind"] == "clinical":  # ADR-015: no corpus, so a labeled general-knowledge explanation
            assert claim["validation_status"] == "general_knowledge" and claim["evidence_ids"] == []
    assert g["possible_explanations"], "a result never comes without a possible explanation (ADR-015)"
    sources = api.ok("GET", f"/cases/{case['id']}/sources", 200, "CaseSources")
    assert sources["evidence"] == []
    read = api.case(case["id"])
    assert read["case"]["state"] == "guided" and "search_providers" in read["allowed_actions"]


def test_idempotent_generation_returns_same_job(api):
    api.start()
    case = api.new_case()
    api.answer_all(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    api.ok("POST", f"/cases/{case['id']}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    headers = {"Idempotency-Key": "same-key-123456"}
    j1 = api.ok("POST", f"/cases/{case['id']}/guidance", 202, "Job", headers=headers, json={"expected_revision": rev})
    j2 = api.ok("POST", f"/cases/{case['id']}/guidance", 202, "Job", headers=headers, json={"expected_revision": rev})
    assert j1["id"] == j2["id"]
    api.wait_job(j1["id"])


def test_edit_during_generation_marks_job_stale(app, api):
    import threading
    ctx = app[0].state.ctx
    gate = threading.Event()
    original = ctx.runtime.generate_json

    async def slow(*args, **kwargs):
        gate.wait(5)
        return await original(*args, **kwargs)

    ctx.runtime.generate_json = slow
    api.start()
    case = api.new_case()
    api.answer_all(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    api.ok("POST", f"/cases/{case['id']}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    job = api.ok("POST", f"/cases/{case['id']}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    api.ok("PATCH", f"/cases/{case['id']}", 200, "Case", json={"expected_revision": rev, "concern": "Edited"})
    gate.set()
    final = api.wait_job(job["id"])
    assert final["status"] == "stale" and final["result_id"] is None
    assert api.case(case["id"])["case"]["latest_guidance_id"] is None


# --- Local generation path for the qualified model (#51; app.modules.guidance.local) -----------------------------
# A scripted runtime stands in for the model; the inputs are synthetic and the decision is a labeled test oracle.

FACT_A, FACT_B = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
PASSAGE = "33333333-3333-4333-8333-333333333333"


def local_inputs(level="routine_clinician", evidence=True, unknown=False, corpus=None):
    from app.modules.guidance.local import LocalInputs
    return LocalInputs(
        case_id="44444444-4444-4444-8444-444444444444", input_revision=3,
        concern="Recurring headaches after long workdays (synthetic).",
        facts=[{"id": FACT_A, "question": "When did this concern begin?", "answer": "One to four weeks ago"},
               {"id": FACT_B, "question": "Has the pattern changed?", "answer": None if unknown else "Improving"}],
        decision={"level": level, "reason_codes": ["SYNTHETIC_TEST_ORACLE"], "rule_version": "test-rules-1",
                  "pathway_id": "test-pathway"},
        evidence=[{"id": PASSAGE, "text": "Synthetic test passage about keeping a symptom diary."}] if evidence else [],
        corpus_version=corpus)


def local_draft(**over):
    draft = {
        "urgency_level": "routine_clinician", "reason_codes": ["PATTERN_STABLE"],
        "outcome_title": "A routine conversation with a clinician",
        "actions": [{"text": "Book a routine appointment.", "category": "discuss_with_clinician",
                     "rationale": "The concern is ongoing.", "evidence_ids": []}],
        "claims": [{"text": "The headaches began one to four weeks ago.", "kind": "case_fact", "fact_ids": [FACT_A],
                    "evidence_ids": []},
                   {"text": "A symptom diary can help the visit.", "kind": "clinical", "fact_ids": [],
                    "evidence_ids": [PASSAGE]}],
        "clinician_questions": ["What should I track?", "Could tests rule out other causes?"],
        "escalation_advice": ["If symptoms become severe, seek care promptly."],
        "uncertainties": [],
    }
    draft.update(over)
    return draft


class ScriptedModel:
    """Returns scripted outputs in order (dicts, or exceptions to raise); records every call."""

    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []

    async def generate_json(self, task, prompt_version, snapshot, schema_id, timeout_s):
        self.calls.append({"task": task, "prompt_version": prompt_version, "schema_id": schema_id,
                           "snapshot": snapshot, "timeout_s": timeout_s})
        out = self.outputs.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


def run_local(model, inputs=None, deadline_s=60.0):
    import asyncio
    from app.modules.guidance import local
    return asyncio.run(local.generate(model, inputs or local_inputs(), deadline_s))


def test_local_path_uses_the_qualified_prompt_and_schema_and_publishes_contract_valid_guidance():
    """R24: the app's local path sends the qualified prompt and draft schema, and maps to a valid Guidance."""
    import hashlib
    from app.modules.guidance import local
    from conftest import validate
    model = ScriptedModel(local_draft())
    result = run_local(model)
    [call] = model.calls
    assert (call["task"], call["prompt_version"], call["schema_id"]) == ("guidance", local.PROMPT_VERSION,
                                                                         "GuidanceDraft")
    assert call["snapshot"]["instructions"] == local.INSTRUCTIONS
    assert hashlib.sha256(local.INSTRUCTIONS.encode()).hexdigest() == local.PROMPT_SHA256
    assert call["snapshot"]["case"]["reviewed_urgency_decision"] == "routine_clinician"
    # #199: the facts reach the model under short aliases, mapped back to the real ids before any check.
    assert [f["id"] for f in call["snapshot"]["case"]["confirmed_facts"]] == ["F1", "F2"]
    assert local.aliases(local_inputs()) == {"F1": FACT_A, "F2": FACT_B, "E1": PASSAGE}
    published = local.to_guidance(local_inputs(), result.draft, manifest_id="qwen3.6-35b-a3b-fp8@95a723d0-2026-10-15",
                                  created_at="2026-10-15T12:00:00Z")
    validate("Guidance", published)
    status = {c["kind"]: c["validation_status"] for c in published["claims"]}
    assert status == {"case_fact": "supported", "clinical": "general_knowledge"}  # no approved corpus (ADR-015)
    assert published["possible_explanations"] == [c for c in published["claims"] if c["kind"] == "clinical"]
    assert all(c["evidence_ids"] == [] for c in published["possible_explanations"])  # never presented as sourced
    assert published["urgency"]["rule_version"] == "test-rules-1" and published["corpus_version"] == \
        "none-no-approved-corpus"


def test_local_mapping_supports_claims_only_with_references():
    """R24: a case-fact claim without fact references is suppressed; a clinical claim is supported only with an
    approved corpus, and otherwise published as general medical knowledge without its evidence ids (ADR-015)."""
    from app.modules.guidance import local
    draft = local_draft(claims=[
        {"text": "The concern was described today.", "kind": "case_fact", "fact_ids": [], "evidence_ids": []},
        {"text": "A diary can help.", "kind": "clinical", "fact_ids": [], "evidence_ids": [PASSAGE]}])
    with_corpus = local.to_guidance(local_inputs(corpus="corpus-test-1"), draft, manifest_id="m",
                                    created_at="2026-10-15T12:00:00Z")
    without = local.to_guidance(local_inputs(), draft, manifest_id="m", created_at="2026-10-15T12:00:00Z")
    assert [c["validation_status"] for c in with_corpus["claims"]] == ["suppressed", "supported"]
    assert [c["validation_status"] for c in without["claims"]] == ["suppressed", "general_knowledge"]
    assert without["claims"][1]["evidence_ids"] == [] and with_corpus["claims"][1]["evidence_ids"] == [PASSAGE]


def test_shipped_draft_schema_matches_the_spec():
    """The GuidanceDraft schema shipped with the app is exactly the one derived from the spec's Action and Claim."""
    import json
    from conftest import ROOT
    from app.modules.guidance import local
    derived = local.derive_draft_schema(json.loads((ROOT / "spec/api/openapi.json").read_text()))
    assert local.draft_schema() == derived, "regenerate guidance_draft.schema.json from spec/api/openapi.json"


# Local mode through the API (ADR-003): the reviewed pathway's decision, the qualified path, a contract-valid result.

def test_local_generation_publishes_contract_valid_guidance_with_the_pathway_decision(local):
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    case = api.new_case(context=[NO_RED_FLAGS])
    job = api.to_guided(case["id"])
    assert job["status"] == "succeeded", job
    g = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")
    assert g["urgency"]["rule_version"] == "general-adult-4" and g["urgency"]["pathway_id"] == "general-adult"
    assert g["urgency"]["level"] == "self_care_candidate" and "NO_RED_FLAG" in g["urgency"]["reason_codes"]
    assert g["model_manifest_id"] == "test-model@local-test" and g["corpus_version"] == "none-no-approved-corpus"
    from app.modules.guidance.service import GENERAL_KNOWLEDGE_LIMIT
    assert GENERAL_KNOWLEDGE_LIMIT in g["uncertainties"]
    assert [c["validation_status"] for c in g["possible_explanations"]] == ["general_knowledge"]
    [call] = [c for c in model.calls if c["task"] == "guidance"]
    assert (call["prompt_version"], call["schema_id"]) == ("guidance-local-5", "GuidanceDraft")
    snap = call["snapshot"]["case"]
    assert snap["reviewed_urgency_decision"] == "self_care_candidate"
    assert snap["concern"] == "Recurring headaches after long workdays."
    questions = [f["question"] for f in snap["confirmed_facts"]]
    assert questions[0] == "Urgent warning signs checklist" and "When did this concern begin?" in questions
    assert call["snapshot"]["evidence"] == []
    assert all(c["validation_status"] == "supported" for c in g["claims"] if c["kind"] == "case_fact")
    assert not g["case_summary"].startswith("Synthetic demo result")


def test_local_unanswered_questions_remove_self_care_from_the_decision(local):
    """R14 with the reviewed pathway: gaps make the starting decision routine, so the model cannot offer self-care."""
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    case = api.new_case(context=[NO_RED_FLAGS])
    rev = case["revision"]
    first = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                   json={"expected_revision": rev})["question"]
    rev = api.ok("PUT", f"/cases/{case['id']}/answers/{first['id']}", 200, "SaveAnswerResponse",
                 json={"expected_revision": rev, "status": "unknown", "value": None})["case_revision"]
    api.answer_all(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    api.ok("POST", f"/cases/{case['id']}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    job = api.ok("POST", f"/cases/{case['id']}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    assert api.wait_job(job["id"])["status"] == "succeeded"
    g = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")
    [call] = [c for c in model.calls if c["task"] == "guidance"]
    assert call["snapshot"]["case"]["reviewed_urgency_decision"] == "routine_clinician"
    assert g["urgency"]["level"] == "routine_clinician" and "LIMITED_INFORMATION" in g["urgency"]["reason_codes"]
    assert all(a["category"] != "self_care" for a in g["actions"])


# ADR-003 amendment (general-adult-2 onward, option 1a): when the model is unsure, publish at the clinician floor.

def test_an_unsure_model_is_published_at_the_clinician_floor_without_a_repair(local):
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    model.level = "undetermined"  # with discuss_with_clinician actions only (the drafts observed for B03-B08)
    case = api.new_case(context=[NO_RED_FLAGS])
    assert api.to_guided(case["id"])["status"] == "succeeded"
    g = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")
    assert g["urgency"]["level"] == "routine_clinician"
    assert "MODEL_UNCERTAIN_CLINICIAN_FLOOR" in g["urgency"]["reason_codes"]
    assert all(a["category"] != "self_care" for a in g["actions"])
    assert len([c for c in model.calls if c["task"] == "guidance"]) == 1  # no repair toward self-care


def test_self_care_advice_while_unsure_is_repaired_once(local):
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    unsure = {"urgency_level": "undetermined", "actions": [
        {"text": "Rest at home.", "category": "self_care", "rationale": "r", "evidence_ids": []}]}
    model.outputs = [{**model.draft({"case": {"reviewed_urgency_decision": "self_care_candidate",
                                               "confirmed_facts": [{"id": "11111111-1111-4111-8111-111111111111",
                                                                    "answer": "a"}]}}), **unsure}]
    case = api.new_case(context=[NO_RED_FLAGS])
    assert api.to_guided(case["id"])["status"] == "succeeded"
    calls = [c for c in model.calls if c["task"] == "guidance"]
    assert len(calls) == 2
    assert any("no self_care action" in e for e in calls[1]["snapshot"]["repair"]["previous_output_errors"])


def test_the_floor_follows_the_pathway_and_never_lowers_a_decision():
    """Unit level: without a floor (general-adult-1, the qualification harness) undetermined is still repaired; with
    one, the published level is the higher of the floor and the decision."""
    from app.modules.guidance import local
    from test_R24 import local_draft, local_inputs
    no_floor = local_inputs(level="self_care_candidate", evidence=False)
    explanation = {"text": "This is often linked to everyday factors.", "kind": "clinical", "fact_ids": [],
                   "evidence_ids": []}
    unsure = local_draft(urgency_level="undetermined", claims=[explanation], actions=[
        {"text": "See a clinician.", "category": "discuss_with_clinician", "rationale": "r", "evidence_ids": []}])
    assert local.check_draft(no_floor, unsure) == ["urgency_lowered"]
    with_floor = local.LocalInputs(**{**no_floor.__dict__, "decision": {**no_floor.decision,
                                                                       "undetermined_floor": "routine_clinician"}})
    assert local.check_draft(with_floor, unsure) == []
    assert local.published_level(with_floor, unsure) == "routine_clinician"
    routine = local.LocalInputs(**{**with_floor.__dict__, "decision": {**with_floor.decision, "level": "routine_clinician"}})
    assert local.published_level(routine, unsure) == "routine_clinician"
    assert local.published_level(with_floor, local_draft(urgency_level="urgent_clinician")) == "urgent_clinician"


def test_a_draft_without_a_clinical_claim_names_the_missing_explanation():
    """ADR-015 (#105): `no_possible_explanation` is a validation error with its own repair hint, with or without
    evidence; a hedged explanation without evidence passes."""
    from app.modules.guidance import local
    case_facts_only = local_draft(claims=local_draft()["claims"][:1])
    for evidence in (True, False):
        assert "no_possible_explanation" in local.check_draft(local_inputs(evidence=evidence), case_facts_only)
    assert "no_possible_explanation" in local.REPAIR_HINTS
    general = local_draft(claims=[*local_draft()["claims"][:1],
                                  {"text": "Headaches like these are often linked to eye strain.", "kind": "clinical",
                                   "fact_ids": [], "evidence_ids": []}])
    assert local.check_draft(local_inputs(evidence=False), general) == []


def test_the_contract_allows_general_knowledge_only_for_unsourced_clinical_claims():
    """Claim.schema.json: `general_knowledge` is for clinical claims with no evidence ids; nothing else may use it."""
    import pytest
    from conftest import validate
    base = {"id": "55555555-5555-4555-8555-555555555555", "text": "Often linked to eye strain.", "kind": "clinical",
            "fact_ids": [], "evidence_ids": [], "validation_status": "general_knowledge"}
    validate("Claim", base)
    for bad in ({"kind": "case_fact"}, {"evidence_ids": [PASSAGE]}):
        with pytest.raises(AssertionError, match="contract violation"):
            validate("Claim", {**base, **bad})


def test_the_prompt_carries_no_topic_example_the_model_could_copy():
    """#110: `guidance-local-2` gave a headache example in rule 5, and the model repeated it for unrelated concerns
    (nausea, low mood, a rash). The prompt names no symptom or cause, and ties explanations to the described concern."""
    import re
    from app.modules.guidance import local
    rule5 = local.INSTRUCTIONS.split("\n5. ")[1].split("\n6. ")[0]
    assert not re.search(r"headache|screen|eye strain|muscle tension|posture", rule5, re.I)
    assert "for the concern THIS person described" in " ".join(rule5.split())
    assert "Never bring in symptoms, activities or causes unrelated to the described concern." in " ".join(rule5.split())


def test_the_model_manifest_records_the_prompt_the_app_sends():
    """#110: `infra/model-manifest.json` names the prompt version and SHA-256 the local path actually sends."""
    import json
    from conftest import ROOT
    from app.modules.guidance import local
    generation = json.loads((ROOT / "infra/model-manifest.json").read_text())["generation"]
    assert (generation["prompt_version"], generation["prompt_sha256"]) == (local.PROMPT_VERSION, local.PROMPT_SHA256)


def test_the_fury_manifest_records_the_same_prompt_and_the_nanos_model():
    """ADR-018: the ZGX Fury runs the same app prompt. #646 (ADR-018 amendment, 2026-10-28): on the Nano's model at the
    Nano's pinned revision, by the owner's decision, so its manifest claims no qualification on the Fury."""
    import json
    from conftest import ROOT
    from app.modules.guidance import local
    fury = json.loads((ROOT / "infra/fury/model-manifest.json").read_text())
    nano = json.loads((ROOT / "infra/model-manifest.json").read_text())
    assert (fury["generation"]["prompt_version"], fury["generation"]["prompt_sha256"]) == (local.PROMPT_VERSION,
                                                                                             local.PROMPT_SHA256)
    assert fury["model"] == nano["model"]
    assert fury["model"]["served_model_id"] == "qwen3.6-35b-a3b-fp8"
    assert fury["qualification"]["runtime_requalifications"] == []
    assert not any(fury["validation"][k] for k in fury["validation"] if k.endswith(("_passed", "_verified")))
    assert fury["qualification"]["previous_model"]["served_model_id"] == "qwen3.8-flash-next-fp8"
    assert fury["model"]["license_reviewed"] is True


# --- #199: short id aliases ------------------------------------------------------------------------------------------
def test_the_snapshot_uses_id_aliases_with_the_instructions_unchanged():
    """#199: facts and evidence carry `F`/`E` aliases and the model-facing schema expects aliases. The qualified
    instructions are byte-for-byte unchanged, and nothing else is added to the snapshot."""
    import json
    from app.modules.guidance import local
    snap = local.snapshot(local_inputs())
    assert snap["instructions"] == local.INSTRUCTIONS
    assert set(snap) == {"instructions", "output_schema", "case", "evidence"}
    assert [e["id"] for e in snap["evidence"]] == ["E1"]
    text = json.dumps(snap)
    assert FACT_A not in text and FACT_B not in text and PASSAGE not in text  # no UUID reaches the model
    props = snap["output_schema"]["properties"]
    assert props["claims"]["items"]["properties"]["fact_ids"]["items"]["pattern"] == "^F[1-9][0-9]*$"
    assert props["actions"]["items"]["properties"]["evidence_ids"]["items"]["pattern"] == "^E[1-9][0-9]*$"
    assert local.draft_schema()["properties"]["claims"]["items"]["properties"]["fact_ids"]["items"]["format"] == "uuid"


def test_a_draft_citing_aliases_is_published_with_the_real_ids():
    """#199: aliases in fact_ids and evidence_ids come back as the input's UUIDs; the claim is supported."""
    from app.modules.guidance import local
    model = ScriptedModel(local_draft(
        claims=[{"text": "The headaches began one to four weeks ago.", "kind": "case_fact", "fact_ids": ["F1", "F2"],
                 "evidence_ids": []},
                {"text": "A symptom diary can help the visit.", "kind": "clinical", "fact_ids": [],
                 "evidence_ids": ["E1"]}]))
    result = run_local(model)
    assert [a["result"] for a in result.attempts] == ["valid"]
    assert result.draft["claims"][0]["fact_ids"] == [FACT_A, FACT_B]
    assert result.draft["claims"][1]["evidence_ids"] == [PASSAGE]
    published = local.to_guidance(local_inputs(), result.draft, manifest_id="m", created_at="2026-10-15T12:00:00Z")
    assert published["claims"][0]["validation_status"] == "supported"


def test_an_unknown_alias_is_rejected_and_the_repair_names_it():
    """#199: an alias that is not in the input stays as written, fails the unchanged id validation, and the single
    repair says which path holds an id that is not from the input."""
    model = ScriptedModel(local_draft(claims=[{"text": "The headaches began recently.", "kind": "case_fact",
                                               "fact_ids": ["F9"], "evidence_ids": []},
                                              {"text": "Stress is often linked to headaches.", "kind": "clinical",
                                               "fact_ids": [], "evidence_ids": []}]),
                          local_draft())
    result = run_local(model)
    assert [a["result"] for a in result.attempts] == ["rejected", "valid"]
    errors = model.calls[1]["snapshot"]["repair"]["previous_output_errors"]
    assert any("claims[0].fact_ids[0] is not an id from the input" in e for e in errors)
    assert "F9" not in str(result.draft)


def test_restoring_ids_leaves_malformed_drafts_to_the_validator():
    """#199: the mapping never raises and invents no structure beyond the fields the model's schema leaves out (#551:
    an empty reason_codes, and empty evidence_ids when no evidence was supplied); validation still decides."""
    from app.modules.guidance import local
    inputs = local_inputs()
    assert local.restore_ids(inputs, ["not", "an", "object"]) == ["not", "an", "object"]
    assert local.restore_ids(inputs, {"claims": "text"}) == {"claims": "text", "reason_codes": []}
    odd = {"claims": [{"fact_ids": ["F1", 7, None, "E1"]}, "row"], "actions": [{"evidence_ids": ["E1", "F1"]}]}
    assert local.restore_ids(inputs, odd) == {"claims": [{"fact_ids": [FACT_A, 7, None, "E1"]}, "row"],
                                              "actions": [{"evidence_ids": [PASSAGE, "F1"]}], "reason_codes": []}
    bare = local.restore_ids(local_inputs(evidence=False), {"claims": [{"fact_ids": ["F1"]}], "reason_codes": ["X"]})
    assert bare == {"claims": [{"fact_ids": [FACT_A], "evidence_ids": []}], "reason_codes": ["X"]}


# #154 (ADR-015 amendment 2, prompt guidance-local-4): every statement addresses the person as "you" (rule 10). A concern
# that describes no health matter is refused at case creation instead (test_R16, cases/concern_check.py).


def test_the_prompt_keeps_the_second_person_rule_and_since_550_reports_case_facts_in_short_drafts():
    """#154: rule 10 addresses the person as "you". #550/#551 (guidance-local-5): rule 5 asks case-fact claims to report
    what the person said, never "You have ..." (the R25 tripwire the self-care first draft always hit), and rule 9 keeps
    drafts short; the other rules are unchanged."""
    from app.modules.guidance import local
    assert local.PROMPT_VERSION == "guidance-local-5"
    head, rule10 = local.INSTRUCTIONS.split("\n10. ")
    assert rule10 == 'Address the person as "you".'
    rule5 = " ".join(head.split("\n5. ")[1].split("\n6. ")[0].split())
    assert 'report what the person said ("You reported ...", "You said ..."), never "You have ..."' in rule5
    rule9 = " ".join(head.split("\n9. ")[1].split())
    assert rule9 == ("Keep it short: at most 3 actions, at most 4 claims (1 to 2 clinical), 2 to 3 clinician questions, "
                     "1 to 2 escalation items; every text is one short sentence.")


def test_third_person_statements_are_repaired_and_the_persons_own_questions_are_not_checked():
    from app.modules.guidance import local
    inputs = local_inputs()
    for field, value in (("outcome_title", "The user reports headaches after work."),
                         ("claims", [*local_draft()["claims"][:1], {"text": "The patient may have eye strain.",
                                                                     "kind": "clinical", "fact_ids": [],
                                                                     "evidence_ids": [PASSAGE]}])):
        assert "third_person" in local.check_draft(inputs, local_draft(**{field: value})), field
    own = local_draft(clinician_questions=["What should the patient track?", "When should I come back?"])
    assert local.check_draft(inputs, own) == []
    assert "third_person" in local.REPAIR_HINTS
    model = ScriptedModel(local_draft(outcome_title="This user should see a clinician."), local_draft())
    result = run_local(model)
    assert [a["result"] for a in result.attempts] == ["rejected", "valid"]
    assert result.attempts[0]["codes"] == ["third_person"]
    assert any("address them as" in e for e in model.calls[1]["snapshot"]["repair"]["previous_output_errors"])


def test_guidance_and_sources_never_generated_are_404_and_stale_ones_409(api):
    """#269: getGuidance and getCaseSources answered 409 for a case whose guidance was never generated."""
    api.start()
    case = api.new_case()
    for path in ("guidance", "sources"):
        r = api.req("GET", f"/cases/{case['id']}/{path}")
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND", path
    api.to_guided(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    api.ok("GET", f"/cases/{case['id']}/sources", 200, "CaseSources")
    api.ok("PATCH", f"/cases/{case['id']}", 200, "Case", json={"expected_revision": rev, "concern": "Edited."})
    for path in ("guidance", "sources"):  # generated for an earlier version: not current
        r = api.req("GET", f"/cases/{case['id']}/{path}")
        assert r.status_code == 409 and r.json()["code"] == "STATE_CONFLICT", path


# --- #391 (R24): the level agrees with the result's own next steps --------------------------------------------------
# A self-care draft whose own next steps send the person to a clinician is published at the routine clinician level
# (never lower); conditional safety-netting ("If it gets worse, contact a clinician") stays self-care.

HEARTBURN_STEP = ("Schedule an appointment with a primary care clinician or gastroenterologist to evaluate your worsening "
                  "symptoms.")
HEARTBURN_RATIONALE = ("Unintentional weight loss and dysphagia are significant details that require professional "
                       "assessment.")
SENDS_TO_CLINICIAN = [HEARTBURN_STEP, "Schedule an appointment with a primary care provider to discuss your headache "
                      "pattern.", "Schedule a routine appointment to discuss coping strategies for emotional distress.",
                      "Book an appointment with your GP.", "See a doctor about the rash.",
                      "Consider booking a visit with a dermatologist.", "Ask your clinician about checking iron levels.",
                      "Use an antacid as needed and book an appointment with your GP to discuss the swallowing.",
                      "You should see a clinician for an assessment of the unsteadiness.",
                      "Seek medical advice about your persistent cough.",
                      "Book an appointment with your GP to check if the mole has changed."]
STAYS_SELF_CARE = ["If it gets worse, contact a clinician.", "See a clinician if it does not improve within two weeks.",
                   "Seek medical attention if the skin becomes infected.", "Should the pain persist, see a doctor.",
                   "Write down questions about your skin condition to discuss with your clinician.",
                   "Prepare questions to discuss with your clinician at your next visit.",
                   "Make a list of questions to discuss with your clinician.",
                   "Make sure to bring your symptom diary to your appointment.",
                   "Keep a symptom diary to share with your clinician.", "Ask a pharmacist about a suitable emollient.",
                   "Contact your doctor before starting any new medicine.", "Have questions ready to ask your doctor.",
                   "Apply a fragrance-free moisturizer twice daily.", "Get plenty of rest and drink fluids."]


def _self_care_draft(text="Rest and keep a short symptom diary.", rationale="It helps you see the pattern.",
                     **over):
    return local_draft(**{"urgency_level": "self_care_candidate", "outcome_title": "Self-care for this concern",
                          "actions": [{"text": text, "category": "self_care", "rationale": rationale,
                                       "evidence_ids": []}], **over})


@pytest.mark.parametrize("step", SENDS_TO_CLINICIAN)
def test_a_next_step_that_sends_you_to_a_clinician_is_recognised(step):
    from app.modules.guidance import local
    assert local.sends_to_clinician(step)


@pytest.mark.parametrize("step", STAYS_SELF_CARE)
def test_safety_netting_and_preparation_are_not_a_clinician_next_step(step):
    from app.modules.guidance import local
    assert not local.sends_to_clinician(step) and not local.needs_assessment(step)


def test_a_self_care_result_that_sends_you_to_a_clinician_is_published_at_the_routine_level():
    """#391: the Nano heartburn result: self-care badge above "Schedule an appointment ..." and a rationale that the
    symptoms "require professional assessment"."""
    from app.modules.guidance import local
    from app.modules.guidance.service import CLINICIAN_STEP_REASON
    from conftest import validate
    inputs = local_inputs(level="self_care_candidate")
    for draft in (_self_care_draft(text=HEARTBURN_STEP, rationale=HEARTBURN_RATIONALE),
                  _self_care_draft(rationale=HEARTBURN_RATIONALE),
                  _self_care_draft(outcome_title="See a doctor about your heartburn")):
        assert local.check_draft(inputs, draft) == []
        published = local.to_guidance(inputs, draft, manifest_id="m", created_at="2026-10-22T12:00:00Z")
        validate("Guidance", published)
        assert published["urgency"]["level"] == "routine_clinician"
        assert CLINICIAN_STEP_REASON in published["urgency"]["reason_codes"]
        assert [a["text"] for a in published["actions"]] == [a["text"] for a in draft["actions"]]


def test_self_care_with_conditional_escalation_stays_self_care_and_no_level_is_lowered():
    from app.modules.guidance import local
    from app.modules.guidance.service import CLINICIAN_STEP_REASON
    inputs = local_inputs(level="self_care_candidate")
    draft = _self_care_draft(escalation_advice=["If it gets worse, contact a clinician."],
                             actions=[{"text": t, "category": "self_care", "rationale": "It may help.",
                                       "evidence_ids": []} for t in STAYS_SELF_CARE[:3]])
    published = local.to_guidance(inputs, draft, manifest_id="m", created_at="2026-10-22T12:00:00Z")
    assert published["urgency"]["level"] == "self_care_candidate"
    assert CLINICIAN_STEP_REASON not in published["urgency"]["reason_codes"]
    for level in ("routine_clinician", "urgent_clinician", "emergency"):
        draft = local_draft(urgency_level=level, actions=[{"text": HEARTBURN_STEP, "category": "seek_care",
                                                           "rationale": "r", "evidence_ids": []}])
        published = local.to_guidance(local_inputs(level=level), draft, manifest_id="m", created_at="2026-10-22T12:00Z")
        assert published["urgency"]["level"] == level
        assert CLINICIAN_STEP_REASON not in published["urgency"]["reason_codes"]


def test_the_raised_level_is_what_the_guidance_and_the_summary_show(local):
    """#391 through the app: A07 (getGuidance) and the summary PDF show the raised level, and a content-free event
    records that the level was raised."""
    from conftest import NO_RED_FLAGS
    from test_R32 import A07_LEVELS, export, pdf_lines
    api, model, application = local
    model.override = {"actions": [{"text": HEARTBURN_STEP, "category": "discuss_with_clinician",
                                   "rationale": HEARTBURN_RATIONALE, "evidence_ids": []}]}
    case = api.new_case(concern="Heartburn after meals for six weeks.", context=[NO_RED_FLAGS])
    assert api.to_guided(case["id"])["status"] == "succeeded"
    [call] = [c for c in model.calls if c["task"] == "guidance"]
    assert call["snapshot"]["case"]["reviewed_urgency_decision"] == "self_care_candidate"
    g = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")
    assert g["urgency"]["level"] == "routine_clinician"
    assert "CLINICIAN_NEXT_STEP_RAISED_LEVEL" in g["urgency"]["reason_codes"]
    lines = pdf_lines(api.req("GET", f"/exports/{export(api, case['id'])['result_id']}/download").content)
    assert lines[lines.index("Suggested level of care (AI-generated, check with a clinician)") + 1] == \
        A07_LEVELS["routine_clinician"]
    with application.state.ctx.db.read() as conn:
        events = [tuple(r) for r in conn.execute("SELECT kind, status, error_code FROM events")]
    assert ("guidance_level_raised", "succeeded", "CLINICIAN_NEXT_STEP_RAISED_LEVEL") in events


# --- #393: the Nano rejected an ordinary dry-skin draft twice for a third-person rationale ---------------------------
# Replayed on the Nano (synthetic dry-skin case, 3 of 3): attempt 1 and its repair both said in actions[2].rationale
# "The user explicitly requested ...", because the generic hint did not say which statement. The repair now names it.

class _FixesOnlyWhatIsNamed:
    """Repeats the third-person draft until the repair names the statement's place, as the Nano's model did."""

    def __init__(self, draft, path, fixed):
        self.draft, self.path, self.fixed, self.calls = draft, path, fixed, []

    async def generate_json(self, task, prompt_version, snapshot, schema_id, timeout_s):
        self.calls.append(snapshot)
        errors = (snapshot.get("repair") or {}).get("previous_output_errors", [])
        return self.fixed if any(self.path in e for e in errors) else self.draft


def test_a_third_person_rationale_is_repaired_once_its_place_is_named():
    from app.modules.guidance import local
    rejected = local_draft(actions=[
        {"text": "Book a routine appointment.", "category": "discuss_with_clinician", "rationale": "It is ongoing.",
         "evidence_ids": []},
        {"text": "Keep a short symptom diary.", "category": "discuss_with_clinician", "rationale": "It shows the "
         "pattern.", "evidence_ids": []},
        {"text": "Prepare questions about your skin symptoms to discuss with your clinician at your next visit.",
         "category": "discuss_with_clinician", "evidence_ids": [],
         "rationale": "The user explicitly requested to discuss the concern with a clinician to understand it better."}])
    assert local.check_draft(local_inputs(), rejected) == ["third_person"]
    model = _FixesOnlyWhatIsNamed(rejected, "actions[2].rationale", local_draft())
    result = run_local(model)
    assert [a["result"] for a in result.attempts] == ["rejected", "valid"]
    errors = model.calls[1]["repair"]["previous_output_errors"]
    assert any(e.startswith("third_person: actions[2].rationale ") for e in errors)
    assert "explicitly requested" not in json.dumps(errors)  # paths only, no case text


# --- #448 (R04): limits never invent allergies -----------------------------------------------------------------------

def test_allergy_limits_are_dropped_unless_allergies_were_reported():
    from app.modules.guidance import local
    written = ["The specific cause of your allergies remains unknown.", "The duration is unclear."]
    assert local.allergy_limits(written, "unknown") == ["The duration is unclear.", local.ALLERGIES_NOT_RECORDED]
    assert local.allergy_limits(written, "none_reported") == ["The duration is unclear."]
    assert local.allergy_limits(written, "reported") == written
    assert local.allergy_limits(written, None) == written  # the qualification harness: no profile status
    assert local.allergy_limits(["The duration is unclear."], "unknown") == ["The duration is unclear."]


@pytest.mark.parametrize("profile,shown", [
    ([], ["Allergies were not recorded."]),
    ([{"kind": "allergy_status", "value": "none_reported", "units": None, "origin": "user", "profile_revision": None}],
     []),
    ([{"kind": "allergy_status", "value": "reported", "units": None, "origin": "user", "profile_revision": None},
      {"kind": "allergies", "value": "Penicillin", "units": None, "origin": "user", "profile_revision": None}],
     ["The specific nature of your allergies is unknown."]),
], ids=["unknown", "none-reported", "reported"])
def test_published_limits_never_invent_allergies(local, profile, shown):
    """#448: the presenter flow, G04 and G09 showed "The specific nature of your allergies is unknown." with no allergy
    reported. A07, the summary and the PDF all list these limits (Guidance.uncertainties)."""
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    model.override = {"uncertainties": ["The specific nature of your allergies is unknown.",
                                        "Some details were not answered."]}
    case = api.new_case(context=[*profile, NO_RED_FLAGS])
    assert api.to_guided(case["id"])["status"] == "succeeded"
    limits = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")["uncertainties"]
    assert [u for u in limits if "llerg" in u] == shown
    assert "Some details were not answered." in limits


# --- #582: a level the model raised to urgent or emergency carries the urgent action, never self-care ---------------
# The checks compared the actions with the reviewed decision only, so a self-care or routine decision raised by the
# model to emergency published "Rest and keep a symptom diary." (self_care) as the only emergency action.

SELF_CARE_ONLY = [{"text": "Rest and keep a symptom diary.", "category": "self_care", "rationale": "It may help.",
                   "evidence_ids": []}]
ROUTINE_ONLY = [{"text": "Book a routine appointment.", "category": "discuss_with_clinician",
                 "rationale": "The concern is ongoing.", "evidence_ids": []}]
SEEK_CARE = [{"text": "Get urgent medical help now.", "category": "seek_care", "rationale": "This needs prompt care.",
              "evidence_ids": []}]


@pytest.mark.parametrize("decision", ["self_care_candidate", "routine_clinician"])
@pytest.mark.parametrize("raised", ["urgent_clinician", "emergency"])
def test_a_raised_urgent_level_needs_the_urgent_action_and_no_self_care(decision, raised):
    from app.modules.guidance import local
    inputs = local_inputs(level=decision)
    for actions in (SELF_CARE_ONLY, ROUTINE_ONLY, [*SEEK_CARE, *SELF_CARE_ONLY]):
        codes = local.check_draft(inputs, local_draft(urgency_level=raised, actions=actions))
        if "seek_care" not in {a["category"] for a in actions}:
            assert "urgent_level_without_seek_care" in codes, actions
        if any(a["category"] == "self_care" for a in actions):
            assert {"self_care_when_urgent", "self_care_action_without_decision"} & set(codes), actions
        assert all(c in local.REPAIR_HINTS for c in codes)
    assert local.check_draft(inputs, local_draft(urgency_level=raised, actions=SEEK_CARE)) == []
    # an urgent decision keeps its own rule and hint, unchanged
    assert local.check_draft(local_inputs(level=raised), local_draft(urgency_level=raised, actions=ROUTINE_ONLY)) \
        == ["urgent_without_seek_care"]


@pytest.mark.parametrize("raised", ["urgent_clinician", "emergency"])
@pytest.mark.parametrize("actions", [SELF_CARE_ONLY, ROUTINE_ONLY], ids=["self_care", "routine"])
def test_a_model_raised_emergency_without_its_action_fails_closed(local, raised, actions):
    """#582 through the app: the repair says what is missing; when it is still missing nothing is published."""
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    model.override = {"urgency_level": raised, "actions": actions}
    case = api.new_case("Mild headache", [NO_RED_FLAGS])
    job = api.to_guided(case["id"])
    assert job["status"] == "failed" and job["result_id"] is None, job
    assert api.req("GET", f"/cases/{case['id']}/guidance").status_code in {404, 409}
    calls = [c for c in model.calls if c["task"] == "guidance"]
    assert len(calls) == 2
    assert any("seek_care" in e for e in calls[1]["snapshot"]["repair"]["previous_output_errors"])


def test_a_model_raised_emergency_publishes_once_the_repair_gives_the_urgent_action(local):
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    built, drafts = model.draft, iter([SELF_CARE_ONLY, SEEK_CARE])  # the first draft, then the repair
    model.draft = lambda snapshot: {**built(snapshot), "urgency_level": "emergency", "actions": next(drafts)}
    case = api.new_case("Mild headache", [NO_RED_FLAGS])
    job = api.to_guided(case["id"])
    assert job["status"] == "succeeded", job
    calls = [c for c in model.calls if c["task"] == "guidance"]
    assert calls[0]["snapshot"]["case"]["reviewed_urgency_decision"] == "self_care_candidate"
    assert any("seek_care" in e for e in calls[1]["snapshot"]["repair"]["previous_output_errors"])
    g = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")
    assert g["urgency"]["level"] == "emergency"
    assert {a["category"] for a in g["actions"]} == {"seek_care"}
