"""R08 case revisions: stale writes conflict; edits invalidate review and derived results. M03."""

REQUIREMENT = "R08"


def test_stale_expected_revision_returns_conflict_with_current(api):
    api.start()
    case = api.new_case()
    api.ok("PATCH", f"/cases/{case['id']}", 200, "Case", json={"expected_revision": 1, "concern": "Updated text"})
    r = api.req("PATCH", f"/cases/{case['id']}", json={"expected_revision": 1, "concern": "Other text"})
    assert r.status_code == 409 and r.json()["code"] == "REVISION_CONFLICT"
    assert r.json()["current_revision"] == 2
    assert api.case(case["id"])["case"]["concern"] == "Updated text"


def test_edit_after_guidance_invalidates_guidance_and_returns_to_intake(api):
    api.start()
    case = api.new_case()
    assert api.to_guided(case["id"])["status"] == "succeeded"
    read = api.case(case["id"])
    rev = read["case"]["revision"]
    edited = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case", json={"expected_revision": rev, "concern": "Changed"})
    assert edited["state"] == "intake" and edited["revision"] == rev + 1
    assert edited["reviewed_revision"] is None and edited["latest_guidance_id"] is None
    assert api.req("GET", f"/cases/{case['id']}/guidance").status_code == 409


def test_client_cannot_post_state_or_slots(api):
    api.start()
    case = api.new_case()
    r = api.req("PATCH", f"/cases/{case['id']}", json={"expected_revision": 1, "state": "guided"})
    assert r.status_code == 422


def _urgent_case(api):
    from test_R15 import TRIGGER, first_question
    api.start()
    case = api.new_case()
    q1, rev = first_question(api, case["id"])
    api.ok("PUT", f"/cases/{case['id']}/answers/{q1['id']}", 200, "SaveAnswerResponse",
           json={"expected_revision": rev, "status": "answered", "value": TRIGGER})
    return case["id"]


def test_urgent_case_refuses_routine_work_and_overrides_but_keeps_permitted_paths(api):
    """T-R08-S01."""
    from test_R03 import SEARCH
    cid = _urgent_case(api)
    rev = api.case(cid)["case"]["revision"]
    for method, path, kw in (("POST", f"/cases/{cid}/guidance", {"key": True, "json": {"expected_revision": rev}}),
                             ("POST", f"/cases/{cid}/provider-search", {"json": {"expected_revision": rev,
                                                                                 "criteria": SEARCH}})):
        r = api.req(method, path, **kw)
        assert r.status_code == 409 and r.json()["code"] == "STATE_CONFLICT", (path, r.text[:120])
    nq = api.req("POST", f"/cases/{cid}/questions/next", key=True, json={"expected_revision": rev})
    assert nq.status_code == 409
    for override in ({"expected_revision": rev, "state": "intake"}, {"expected_revision": rev, "issued_slots": 0},
                     {"expected_revision": rev, "urgent": False}):
        assert api.req("PATCH", f"/cases/{cid}", json=override).status_code == 422, override
    read = api.case(cid)
    assert read["case"]["state"] == "urgent" and read["case"]["revision"] == rev and read["case"]["issued_slots"] == 1
    assert "view_urgent" in read["allowed_actions"] and "next_question" not in read["allowed_actions"]
    assert [c["id"] for c in api.ok("GET", "/cases", 200, "CaseList")["items"]] == [cid]   # owned history
    api.ok("DELETE", f"/cases/{cid}?expected_revision={rev}", 202, "DeletionAccepted")  # deletion permitted
    assert api.req("GET", f"/cases/{cid}").status_code == 404


def test_stale_or_illegal_mutation_on_a_reviewed_case_preserves_revision_and_answers(api):
    """T-R08-S02."""
    api.start()
    cid = api.new_case()["id"]
    api.answer_all(cid)
    rev = api.case(cid)["case"]["revision"]
    api.ok("POST", f"/cases/{cid}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    before = api.case(cid)["case"]
    answers = sorted((f["kind"], str(f["value"])) for f in before["confirmed_context"] if f["kind"].startswith("answer:"))
    assert before["state"] == "reviewed" and len(answers) == 10
    stale = api.req("PATCH", f"/cases/{cid}", json={"expected_revision": rev - 1, "concern": "Overwrite"})
    assert stale.status_code == 409 and stale.json()["code"] == "REVISION_CONFLICT"
    qid = next(f["source_id"] for f in before["confirmed_context"] if f["kind"] == "answer:Q01")
    stale_answer = api.req("PUT", f"/cases/{cid}/answers/{qid}", json={"expected_revision": rev - 1,
                                                                       "status": "unknown", "value": None})
    assert stale_answer.status_code == 409
    illegal = api.req("POST", f"/cases/{cid}/questions/next", key=True, json={"expected_revision": rev})
    assert illegal.status_code == 409 and illegal.json()["code"] == "STATE_CONFLICT"
    after = api.case(cid)["case"]
    assert after["revision"] == before["revision"] and after["state"] == "reviewed" and after["concern"] == before["concern"]
    assert sorted((f["kind"], str(f["value"])) for f in after["confirmed_context"] if f["kind"].startswith("answer:")) == answers
