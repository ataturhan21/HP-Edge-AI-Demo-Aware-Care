"""R09 an accepted clinical edit creates revision n+1; old guidance, matches and exports are not current. M03."""
from test_R03 import SEARCH

REQUIREMENT = "R09"


def guided_with_artifacts(api):
    api.start()
    cid = api.new_case()["id"]
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    search = api.ok("POST", f"/cases/{cid}/provider-search", 200, "ProviderSearchResult",
                    json={"expected_revision": rev, "criteria": SEARCH})
    job = api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                 json={"expected_revision": rev, "user_reviewed": True})
    # #267: a card is read with the search it is opened from.
    return (cid, rev, f'{search["matches"][0]["provider_id"]}?search_id={search["id"]}',
            api.wait_job(job["id"])["result_id"])


def test_concern_edit_invalidates_every_dependent_output(api):
    cid, rev, provider, export = guided_with_artifacts(api)
    edited = api.ok("PATCH", f"/cases/{cid}", 200, "Case", json={"expected_revision": rev, "concern": "Edited."})
    assert edited["revision"] == rev + 1 and edited["state"] == "intake" and edited["latest_guidance_id"] is None
    assert api.req("GET", f"/cases/{cid}/guidance").status_code == 409
    assert api.req("GET", f"/cases/{cid}/providers/{provider}").status_code in {404, 409}
    assert api.req("GET", f"/exports/{export}/download").status_code in {404, 409}
    r = api.req("POST", f"/cases/{cid}/exports", key=True, json={"expected_revision": rev + 1, "user_reviewed": True})
    assert r.status_code == 409


def test_context_edit_keeps_answers_and_invalidates_outputs(api):
    cid, rev, _, _ = guided_with_artifacts(api)
    answers_before = [f for f in api.case(cid)["case"]["confirmed_context"] if f["kind"].startswith("answer:")]
    api.ok("PATCH", f"/cases/{cid}", 200, "Case", json={"expected_revision": rev, "confirmed_context": [
        {"kind": "age_years", "value": 40, "units": None, "origin": "user", "profile_revision": None}]})
    after = api.case(cid)["case"]["confirmed_context"]
    assert [f["id"] for f in after if f["kind"].startswith("answer:")] == [f["id"] for f in answers_before]
    assert {f["kind"]: f["value"] for f in after}["age_years"] == 40
    assert api.req("GET", f"/cases/{cid}/guidance").status_code == 409


def test_answer_edit_after_guidance_is_a_clinical_edit(api):
    cid, rev, _, _ = guided_with_artifacts(api)
    qid = next(f["source_id"] for f in api.case(cid)["case"]["confirmed_context"] if f["kind"] == "answer:Q02")
    saved = api.ok("PUT", f"/cases/{cid}/answers/{qid}", 200, "SaveAnswerResponse",
                   json={"expected_revision": rev, "status": "unknown", "value": None})
    assert saved["case_revision"] == rev + 1
    read = api.case(cid)
    assert read["case"]["issued_slots"] == 10 and read["case"]["state"] == "intake"
    assert api.req("GET", f"/cases/{cid}/guidance").status_code == 409


def test_clinical_edit_makes_every_revision_n_artifact_non_current(app, api):
    """T-R09-S01: revision n questions, guidance, matches and exports cannot be presented as current after n+1."""
    cid, rev, provider, export = guided_with_artifacts(api)
    old_q = next(f["source_id"] for f in api.case(cid)["case"]["confirmed_context"] if f["kind"] == "answer:Q01")
    edited = api.ok("PATCH", f"/cases/{cid}", 200, "Case", json={"expected_revision": rev, "concern": "Edited."})
    assert edited["revision"] == rev + 1 and edited["state"] == "intake"
    assert edited["reviewed_revision"] is None and edited["latest_guidance_id"] is None
    # A question answered for revision n cannot be answered as current with the old revision.
    r = api.req("PUT", f"/cases/{cid}/answers/{old_q}", json={"expected_revision": rev, "status": "unknown",
                                                               "value": None})
    assert r.status_code == 409
    assert api.req("GET", f"/cases/{cid}/guidance").status_code == 409
    assert api.req("GET", f"/cases/{cid}/providers/{provider}").status_code in {404, 409}
    assert api.req("POST", f"/cases/{cid}/provider-search",
                   json={"expected_revision": rev + 1, "criteria": SEARCH}).status_code == 409
    assert api.req("GET", f"/exports/{export}/download").status_code in {404, 409}
    assert api.req("POST", f"/cases/{cid}/exports", key=True,
                   json={"expected_revision": rev + 1, "user_reviewed": True}).status_code == 409
    # Back in intake: applicable checks run again before a new review.
    assert "next_question" in api.case(cid)["allowed_actions"]


# #273 (QA 2026-10-19): revision and state are checked before any model call.

def test_a_stale_or_urgent_state_edit_is_refused_before_any_model_call(local):
    from conftest import NO_RED_FLAGS, red_flags
    api, model, _ = local
    case = api.new_case(context=[NO_RED_FLAGS])
    calls = len(model.calls)
    model.concern = {"health_concern": False}  # would refuse the text with 422 if it were asked
    stale = api.req("PATCH", f"/cases/{case['id']}", json={"expected_revision": case["revision"] + 5,
                                                          "concern": "asdf qwer zxcv"})
    assert stale.status_code == 409 and stale.json()["code"] == "REVISION_CONFLICT"
    assert len(model.calls) == calls
    urgent = api.new_case(context=[red_flags("RF04")])
    calls = len(model.calls)
    r = api.req("PATCH", f"/cases/{urgent['id']}", json={"expected_revision": urgent["revision"],
                                                        "concern": "asdf qwer zxcv"})
    assert r.status_code == 409 and r.json()["code"] == "STATE_CONFLICT"
    assert len(model.calls) == calls
    # A current, editable edit still runs both checks.
    model.concern = {"health_concern": True}
    api.ok("PATCH", f"/cases/{case['id']}", 200, "Case", json={"expected_revision": case["revision"],
                                                               "concern": "Headaches and now dizziness."})
    assert [c["task"] for c in model.calls[calls:]] == ["red_flag_screen", "concern_check"]


def test_a_concern_saved_unchanged_is_not_a_clinical_edit(api):
    """#411: saving the concern unchanged on review changes nothing: same revision, the review state and its
    confirmation stay; a changed concern is still a clinical edit."""
    api.start()
    case = api.new_case("Headaches after long workdays.")
    api.answer_all(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    reviewed = api.ok("POST", f"/cases/{case['id']}/review", 200, "Case",
                      json={"expected_revision": rev, "facts_confirmed": True})
    for concern in ("Headaches after long workdays.", "  Headaches after long workdays.  "):
        same = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                      json={"expected_revision": reviewed["revision"], "concern": concern})
        assert (same["revision"], same["state"], same["reviewed_revision"]) == (
            reviewed["revision"], "reviewed", reviewed["revision"])
    edited = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                    json={"expected_revision": reviewed["revision"], "concern": "Headaches after long days."})
    assert (edited["revision"], edited["state"]) == (reviewed["revision"] + 1, "intake")


def test_a_changed_answer_keeps_its_place_in_question_order(api):
    """#449: the answers are listed in question (slot) order, also after an earlier answer was changed."""
    api.start()
    case = api.new_case()
    api.answer_all(case["id"])
    facts = api.case(case["id"])["case"]["confirmed_context"]
    first = next(f for f in facts if f["kind"].startswith("answer:"))
    rev = api.case(case["id"])["case"]["revision"]
    api.ok("PUT", f"/cases/{case['id']}/answers/{first['source_id']}", 200, "SaveAnswerResponse",
           json={"expected_revision": rev, "status": "skipped", "value": None})
    after = [f for f in api.case(case["id"])["case"]["confirmed_context"] if f["kind"].startswith("answer:")]
    assert after[0]["source_id"] == first["source_id"] and after[0]["value"] is None
    with api.c.app.state.ctx.db.read() as conn:  # type: ignore[attr-defined]
        slots = {r["id"]: r["slot"] for r in conn.execute("SELECT id, slot FROM questions WHERE case_id=?",
                                                          (case["id"],))}
    order = [slots[f["source_id"]] for f in after]
    assert order == sorted(order) and len(order) > 1
