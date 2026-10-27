"""R21 approved evidence only (M07; ADR-004): without a valid local corpus, guidance discloses the limit and never
substitutes unreviewed sources or invented citations.

#55 connected acceptance with the reviewed pathway (local mode, scripted model). ADR-004 records no approved corpus
for the demo, so T-R21-S01 (retrieval over a mixed corpus) cannot be met and is recorded as not applicable.
"""
REQUIREMENT = "R21"


def test_without_a_corpus_the_published_result_discloses_the_evidence_limit(local):
    """T-R21-S02: the result explains the evidence limitation and carries no evidence or citation. Since ADR-015 its
    possible explanations come from general medical knowledge, labeled as such, never as a sourced claim."""
    import json
    from conftest import NO_RED_FLAGS
    api, _, _ = local
    case = api.new_case(context=[NO_RED_FLAGS])
    assert api.to_guided(case["id"])["status"] == "succeeded"
    g = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")
    assert g["corpus_version"] == "none-no-approved-corpus"
    from app.modules.guidance.service import GENERAL_KNOWLEDGE_LIMIT
    assert GENERAL_KNOWLEDGE_LIMIT in g["uncertainties"]
    assert all(c["evidence_ids"] == [] for c in g["claims"]) and all(a["evidence_ids"] == [] for a in g["actions"])
    clinical = [c for c in g["claims"] if c["kind"] == "clinical"]
    assert clinical and all(c["validation_status"] == "general_knowledge" for c in clinical)
    assert g["possible_explanations"] == clinical
    assert "http" not in json.dumps(g).lower()


def test_mock_guidance_calls_its_explanation_scripted_never_general_medical_knowledge(api):
    """#456 (P-12): mock mode's possible explanation is a scripted fixture sentence; its limit says so (A07 "Limits of
    this result", the A12 preview and the PDF read it), and never claims general medical knowledge. Local mode keeps
    GENERAL_KNOWLEDGE_LIMIT (the test above)."""
    from app.modules.guidance.service import GENERAL_KNOWLEDGE_LIMIT, SCRIPTED_EXPLANATION_LIMIT
    api.start()
    case = api.new_case()
    assert api.to_guided(case["id"])["status"] == "succeeded"
    g = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")
    assert g["model_manifest_id"].startswith("mock-")
    assert SCRIPTED_EXPLANATION_LIMIT in g["uncertainties"] and GENERAL_KNOWLEDGE_LIMIT not in g["uncertainties"]
    assert not any("general medical knowledge" in u.lower() for u in g["uncertainties"])
    assert [c["text"].startswith("Scripted illustrative explanation") for c in g["possible_explanations"]] == [True]


def test_a_draft_with_an_invented_citation_or_link_is_never_published(local):
    """T-R21-S02: a clinical claim with an invented evidence ID, or an unreviewed web link, is rejected (one repair,
    then fail closed); no unreviewed page or invented citation reaches the person."""
    from conftest import NO_RED_FLAGS
    api, model, application = local
    model.override = {
        "claims": [{"text": "Tension headaches come from muscle strain.", "kind": "clinical", "fact_ids": [],
                    "evidence_ids": ["99999999-9999-4999-8999-999999999999"]}],
        "actions": [{"text": "Read https://example.org/headache-cures for advice.", "category": "discuss_with_clinician",
                     "rationale": "More information.", "evidence_ids": []}]}
    case = api.new_case(context=[NO_RED_FLAGS])
    job = api.to_guided(case["id"])
    assert job["status"] == "failed" and job["result_id"] is None
    assert len([c for c in model.calls if c["task"] == "guidance"]) == 2  # the draft and its single repair
    read = api.case(case["id"])
    assert read["case"]["state"] == "limited" and "retry" in read["allowed_actions"]
    assert api.req("GET", f"/cases/{case['id']}/guidance").status_code in (404, 409)
    with application.state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM guidance").fetchone()[0] == 0


def test_a_draft_without_a_possible_explanation_is_repaired_once_then_fails_closed(local):
    """ADR-015: a result never comes without a possible explanation. A draft with none is sent back once with the
    error; if the repair still has none, nothing is published (never a blank or mock result)."""
    from conftest import NO_RED_FLAGS
    api, model, application = local
    model.override = {"claims": []}
    case = api.new_case(context=[NO_RED_FLAGS])
    job = api.to_guided(case["id"])
    calls = [c for c in model.calls if c["task"] == "guidance"]
    assert job["status"] == "failed" and job["result_id"] is None and len(calls) == 2
    from app.modules.guidance.local import REPAIR_HINTS
    assert f"validation: {REPAIR_HINTS['no_possible_explanation']}" in calls[1]["snapshot"]["repair"]["previous_output_errors"]
    with application.state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM guidance").fetchone()[0] == 0


def test_a_repaired_draft_with_a_possible_explanation_is_published(local):
    """ADR-015: the single repair that adds a possible explanation publishes it as general medical knowledge."""
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    snapshot = {"case": {"reviewed_urgency_decision": "self_care_candidate",
                         "confirmed_facts": [{"id": "11111111-1111-4111-8111-111111111111", "answer": "a"}]}}
    model.outputs = [{**model.draft(snapshot), "claims": []}]
    case = api.new_case(context=[NO_RED_FLAGS])
    assert api.to_guided(case["id"])["status"] == "succeeded"
    assert len([c for c in model.calls if c["task"] == "guidance"]) == 2
    g = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")
    assert [c["validation_status"] for c in g["possible_explanations"]] == ["general_knowledge"]
