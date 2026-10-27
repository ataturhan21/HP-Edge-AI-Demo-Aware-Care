"""R14 stop with explicit limits: unresolved gaps remove self-care reassurance. M04/M05/M08.

Mock fixtures define no reviewed critical fields, so every unanswered issued slot
is treated as a gap (ADR-008). Assertions use the real API and guidance worker.
"""
REQUIREMENT = "R14"


def answer_with(api, case_id: str, status_for) -> None:
    rev = api.case(case_id)["case"]["revision"]
    while True:
        nq = api.ok("POST", f"/cases/{case_id}/questions/next", 200, "NextQuestionResponse", key=True,
                    json={"expected_revision": rev})
        if nq["kind"] == "review_required":
            return
        q = nq["question"]
        status = status_for(q)
        value = None
        if status == "answered":
            value = {"single_choice": lambda: q["choices"][0]["id"], "multiple_choice": lambda: [q["choices"][0]["id"]],
                     "text": lambda: "No changes yet.", "scale": lambda: 4}[q["response_type"]]()
        rev = api.ok("PUT", f"/cases/{case_id}/answers/{q['id']}", 200, "SaveAnswerResponse",
                     json={"expected_revision": rev, "status": status, "value": value})["case_revision"]


def generate(api, case_id: str) -> dict:
    rev = api.case(case_id)["case"]["revision"]
    api.ok("POST", f"/cases/{case_id}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    job = api.ok("POST", f"/cases/{case_id}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    assert api.wait_job(job["id"])["status"] == "succeeded"
    return api.ok("GET", f"/cases/{case_id}/guidance", 200, "Guidance")


def test_review_required_lists_unresolved_gaps(api):
    api.start()
    case = api.new_case()
    rev = api.case(case["id"])["case"]["revision"]
    for i in range(10):
        q = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                   json={"expected_revision": rev})["question"]
        rev = api.ok("PUT", f"/cases/{case['id']}/answers/{q['id']}", 200, "SaveAnswerResponse",
                     json={"expected_revision": rev, "status": "unknown" if i % 2 else "skipped",
                           "value": None})["case_revision"]
    done = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                  json={"expected_revision": rev})
    assert done["kind"] == "review_required" and len(done["unresolved_gaps"]) == 10


def test_all_unanswered_gives_undetermined_limited_information(api):
    api.start()
    case = api.new_case()
    answer_with(api, case["id"], lambda q: "skipped")
    g = generate(api, case["id"])
    assert g["urgency"]["level"] == "undetermined"
    assert "LIMITED_INFORMATION" in g["urgency"]["reason_codes"]
    assert g["actions"][0]["category"] == "discuss_with_clinician"
    assert g["uncertainties"][0].startswith("Limited information")
    assert sum(u.startswith("Not answered:") for u in g["uncertainties"]) == 10


def test_partial_gaps_are_flagged_without_self_care(api):
    api.start()
    case = api.new_case()
    answer_with(api, case["id"], lambda q: "unknown" if q["template_id"] in {"Q02", "Q06"} else "answered")
    g = generate(api, case["id"])
    assert "LIMITED_INFORMATION" in g["urgency"]["reason_codes"]
    assert g["urgency"]["level"] != "self_care_candidate"
    assert sum(u.startswith("Not answered:") for u in g["uncertainties"]) == 2


def test_complete_answers_have_no_limited_flag(api):
    api.start()
    case = api.new_case()
    api.to_guided(case["id"])
    g = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")
    assert "LIMITED_INFORMATION" not in g["urgency"]["reason_codes"]
    assert g["urgency"]["level"] == "routine_clinician"


def test_self_care_candidate_is_never_reassuring_with_gaps():
    from app.modules.safety.service import apply_information_limits
    candidate = {"urgency_level": "self_care_candidate", "reason_codes": ["X"], "outcome_title": "t",
                 "action": {"category": "self_care", "text": "t", "rationale": "r"}}
    out = apply_information_limits(candidate, answered=3, gaps=1)
    assert out["urgency_level"] == "routine_clinician" and out["action"]["category"] == "discuss_with_clinician"
    assert apply_information_limits(candidate, answered=4, gaps=0) is candidate
    # Never lowers urgency.
    urgent = {**candidate, "urgency_level": "urgent_clinician"}
    assert apply_information_limits(urgent, answered=2, gaps=2)["urgency_level"] == "urgent_clinician"


# #55 connected acceptance with the reviewed pathway (local mode, scripted model; ADR-003).

def test_local_reviewed_pathway_stops_at_ten_names_every_gap_and_never_reassures(local):
    """T-R14-S02: critical answers unknown at slot 10. No eleventh prompt, review names every gap, and the permitted
    result is limited without a self-care conclusion. Generation needs a current review first (T-R14-S01)."""
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    case = api.new_case(context=[NO_RED_FLAGS])
    answer_with(api, case["id"], lambda q: "unknown")
    read = api.case(case["id"])
    assert (read["case"]["issued_slots"], read["case"]["state"]) == (10, "review")
    rev = read["case"]["revision"]
    again = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                   json={"expected_revision": rev})
    assert again["kind"] == "review_required" and len(again["unresolved_gaps"]) == 10
    assert all(g.startswith("Not answered: ") for g in again["unresolved_gaps"])
    assert api.case(case["id"])["case"]["issued_slots"] == 10  # no eleventh prompt
    assert "generate_guidance" not in read["allowed_actions"]
    early = api.req("POST", f"/cases/{case['id']}/guidance", key=True, json={"expected_revision": rev})
    assert early.status_code == 409  # review of the current revision comes first
    g = generate(api, case["id"])
    assert "LIMITED_INFORMATION" in g["urgency"]["reason_codes"]
    assert g["urgency"]["level"] != "self_care_candidate"
    assert all(a["category"] != "self_care" for a in g["actions"])
    assert sum(u.startswith("Not answered:") for u in g["uncertainties"]) == 10
    [call] = [c for c in model.calls if c["task"] == "guidance"]
    assert call["snapshot"]["case"]["reviewed_urgency_decision"] == "undetermined"


def test_local_complete_answers_reach_review_after_the_last_reviewed_question(local):
    """T-R14-S01 (clauses): once every reviewed question is answered, continuation returns review with no further
    question, and generation waits for the review of the current revision."""
    from conftest import NO_RED_FLAGS
    api, _, _ = local
    case = api.new_case(context=[NO_RED_FLAGS])
    done = api.answer_all(case["id"])
    assert done["kind"] == "review_required" and done["unresolved_gaps"] == []
    read = api.case(case["id"])
    assert read["case"]["state"] == "review" and "generate_guidance" not in read["allowed_actions"]
    rev = read["case"]["revision"]
    assert api.req("POST", f"/cases/{case['id']}/guidance", key=True, json={"expected_revision": rev}).status_code == 409
    api.ok("POST", f"/cases/{case['id']}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    assert "generate_guidance" in api.case(case["id"])["allowed_actions"]


# #268 (QA 2026-10-19): confirmed record facts are not answered intake questions.

def test_confirmed_record_facts_are_not_counted_as_answered_questions(api):
    from records_helpers import records, upload_ok
    api.start()
    cid = api.new_case()["id"]
    upload_ok(api, cid)
    facts = records(api, cid)["facts"]
    rev = api.case(cid)["case"]["revision"]
    rev = api.ok("PATCH", f"/cases/{cid}/facts/{facts[0]['id']}", 200, "FactReviewResponse",
                 json={"expected_revision": rev, "action": "confirm"})["case_revision"]
    if len(facts) > 1:  # a record fact corrected to unknown is not an unanswered intake question either
        api.ok("PATCH", f"/cases/{cid}/facts/{facts[1]['id']}", 200, "FactReviewResponse",
               json={"expected_revision": rev, "action": "correct", "corrected_value": {"value": None, "units": None}})
    assert api.to_guided(cid)["status"] == "succeeded"
    g = api.ok("GET", f"/cases/{cid}/guidance", 200, "Guidance")
    answers = [f["id"] for f in api.case(cid)["case"]["confirmed_context"] if f["kind"].startswith("answer:")]
    claim = next(c for c in g["claims"] if c["kind"] == "case_fact")
    assert claim["text"] == "You answered 10 intake question(s) in this synthetic demo."
    assert claim["fact_ids"] == answers
    assert not [u for u in g["uncertainties"] if u.startswith("Not answered:")]
    assert "LIMITED_INFORMATION" not in g["urgency"]["reason_codes"]


def test_local_decision_counts_only_intake_answers(local):
    """In local mode a confirmed record fact with an unknown value used to count as an unanswered question, which
    changed the R14 decision (self-care reassurance removed)."""
    import uuid
    from conftest import NO_RED_FLAGS
    api, model, application = local
    case = api.new_case(context=[NO_RED_FLAGS])
    with application.state.ctx.db.tx() as conn:
        conn.execute("INSERT INTO facts (id, case_id, kind, value_json, units, provenance, source_id, page, status, "
                     "original_text, confirmed_at) VALUES (?,?,?,?,NULL,'document',?,1,'confirmed',?,?)",
                     (str(uuid.uuid4()), case["id"], "record:medications", "null", str(uuid.uuid4()),
                      "Synthetic record line", "2026-10-19T00:00:00Z"))
    assert api.to_guided(case["id"])["status"] == "succeeded"
    guidance_call = next(c for c in model.calls if c["task"] == "guidance")
    decision = guidance_call["snapshot"]["case"]["reviewed_urgency_decision"]
    assert decision == "self_care_candidate", decision
    g = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")
    assert "LIMITED_INFORMATION" not in g["urgency"]["reason_codes"]
