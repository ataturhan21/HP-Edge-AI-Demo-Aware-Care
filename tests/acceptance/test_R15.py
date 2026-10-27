"""R15/R17 urgent and limited fixture branches block routine work. M05.

Scenario selection uses the presenter loadScenario path with a presenter session
created through the (simulated) presenter gateway (ADR-005 option A).
"""

import json

import pytest

from conftest import concern_screens_only

REQUIREMENT = "R15"


def load(presenter, scenario: str) -> dict:
    return presenter.ok("POST", f"/presenter/scenarios/{scenario}/load", 201, "ScenarioLoaded", key=True,
                        json={"reset": True})


def case_state(app, case_id: str) -> str:
    with app[0].state.ctx.db.read() as conn:
        return conn.execute("SELECT state FROM cases WHERE id=?", (case_id,)).fetchone()["state"]


def test_urgent_scenario_interrupts_before_intake(app, presenter):
    loaded = load(presenter, "urgent")
    assert loaded["synthetic"] is True and case_state(app, loaded["case_id"]) == "urgent"


def test_unsupported_scenario_is_limited(app, presenter):
    loaded = load(presenter, "unsupported")
    assert case_state(app, loaded["case_id"]) == "limited"


def test_urgent_case_blocks_questions_guidance_and_ranking(app, presenter):
    from app.core.security import SessionInfo
    from app.core.errors import ApiError
    from app.modules.intake import service as intake
    from app.modules.guidance import service as guidance
    loaded = load(presenter, "urgent")
    s = loaded["session"]
    session = SessionInfo(id=s["id"], actor_id=s["actor_id"], mode="guest", role="patient",
                          consent_version=s["consent_version"], consent_at=s["consent_at"], adult_eligible=True,
                          created_at=s["created_at"], last_seen_at=s["last_seen_at"], expires_at=s["expires_at"],
                          csrf_token="x")
    ctx = app[0].state.ctx
    for call in (lambda: intake.next_question(ctx, session, loaded["case_id"], 1, "key-12345678"),
                 lambda: guidance.start_generation(ctx, session, loaded["case_id"], 1, "key-87654321"),
                 lambda: guidance.get_guidance(ctx, session, loaded["case_id"])):
        try:
            call()
        except ApiError as err:
            assert err.status in (404, 409)  # #269: guidance never generated is 404
        else:
            raise AssertionError("urgent case allowed routine work")


def test_reset_purges_previous_demo_before_new_load(app, presenter):
    first = load(presenter, "routine")
    load(presenter, "selfcare")
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT 1 FROM cases WHERE id=?", (first["case_id"],)).fetchone() is None


def test_guest_cannot_reach_presenter_operations(api):
    api.start()
    for path in ("/presenter/runtime", "/presenter/controls"):
        assert api.req("GET", path).status_code == 403
    assert api.req("POST", "/presenter/reset", key=True).status_code == 403


# --- Urgent at answer (patient path, ADR-008 explicit fixture trigger) -----------------------------

TRIGGER = ["fixture:urgent-signal"]
SEARCH = {"location": {"location_id": None, "city": "Dallas", "region": "TX", "postal_code": None},
          "radius_miles": 25, "specialty_ids": ["primary_care"], "exact_plan_id": None,
          "required_verified_plan": False, "visit_type": "in_person", "language": None, "required_language": False,
          "ranked_preferences": []}


def first_question(api, case_id: str) -> tuple[dict, int]:
    rev = api.case(case_id)["case"]["revision"]
    nq = api.ok("POST", f"/cases/{case_id}/questions/next", 200, "NextQuestionResponse", key=True,
                json={"expected_revision": rev})
    return nq["question"], rev


def test_urgent_signal_at_answer_interrupts_intake_and_keeps_slot(api):
    api.start()
    case = api.new_case()
    q1, rev = first_question(api, case["id"])
    saved = api.ok("PUT", f"/cases/{case['id']}/answers/{q1['id']}", 200, "SaveAnswerResponse",
                   json={"expected_revision": rev, "status": "answered", "value": q1["choices"][0]["id"]})
    nq = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                json={"expected_revision": saved["case_revision"]})
    urgent = api.ok("PUT", f"/cases/{case['id']}/answers/{nq['question']['id']}", 200, "SaveAnswerResponse",
                    json={"expected_revision": saved["case_revision"], "status": "answered", "value": TRIGGER})
    assert urgent["next_action"] == "urgent" and urgent["case_revision"] == saved["case_revision"] + 1
    read = api.case(case["id"])
    assert read["case"]["state"] == "urgent"
    assert read["case"]["issued_slots"] == 2  # the interrupted prompt keeps its slot (R11)
    assert "next_question" not in read["allowed_actions"] and "view_urgent" in read["allowed_actions"]
    # The trigger is never stored as an answer value.
    assert not any(f["value"] == TRIGGER for f in read["case"]["confirmed_context"])


def test_urgent_case_blocks_next_question_guidance_search_and_export_over_api(api):
    api.start()
    case = api.new_case()
    q1, rev = first_question(api, case["id"])
    api.ok("PUT", f"/cases/{case['id']}/answers/{q1['id']}", 200, "SaveAnswerResponse",
           json={"expected_revision": rev, "status": "answered", "value": TRIGGER})
    rev = api.case(case["id"])["case"]["revision"]
    blocked = [
        api.req("POST", f"/cases/{case['id']}/questions/next", key=True, json={"expected_revision": rev}),
        api.req("POST", f"/cases/{case['id']}/review", json={"expected_revision": rev, "facts_confirmed": True}),
        api.req("POST", f"/cases/{case['id']}/guidance", key=True, json={"expected_revision": rev}),
        api.req("GET", f"/cases/{case['id']}/guidance"),
        api.req("POST", f"/cases/{case['id']}/provider-search", json={"expected_revision": rev, "criteria": SEARCH}),
        api.req("POST", f"/cases/{case['id']}/exports", key=True,
                json={"expected_revision": rev, "user_reviewed": True}),
    ]
    # #269: guidance was never generated, so getGuidance is 404; every other routine action is a 409.
    assert [r.status_code for r in blocked] == [409, 409, 409, 404, 409, 409], [(r.status_code, r.text[:80])
                                                                                 for r in blocked]
    with api.c.app.state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM guidance").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind IN ('guidance','export')").fetchone()[0] == 0


def test_urgent_trigger_after_guidance_is_not_accepted_as_answer(api):
    """The fixture trigger only acts during intake; elsewhere it is an invalid answer, never stored."""
    api.start()
    case = api.new_case()
    api.to_guided(case["id"])
    read = api.case(case["id"])
    qid = next(f["source_id"] for f in read["case"]["confirmed_context"] if f["kind"] == "answer:Q01")
    r = api.req("PUT", f"/cases/{case['id']}/answers/{qid}",
                json={"expected_revision": read["case"]["revision"], "status": "answered", "value": TRIGGER})
    assert r.status_code == 422 and r.json()["code"] == "ANSWER_INVALID"
    assert api.case(case["id"])["case"]["state"] == "guided"


def test_urgent_trigger_is_inert_in_local_mode():
    from app.modules.safety.service import is_urgent_fixture_trigger
    assert is_urgent_fixture_trigger("mock", "answered", TRIGGER)
    assert not is_urgent_fixture_trigger("local", "answered", TRIGGER)
    assert not is_urgent_fixture_trigger("mock", "answered", "fixture:urgent-signal")  # free text never triggers
    assert not is_urgent_fixture_trigger("mock", "skipped", None)


# ADR-003 red-flag checklist (RF01-RF16): structured, reviewed urgent signals at concern entry and on edit.

def _package():
    import json
    from conftest import ROOT
    registry = json.loads((ROOT / "content/pathways/registry.json").read_text())
    [version] = registry["enabled_pathways"]
    return json.loads((ROOT / "content/pathways" / version / "red-flags.json").read_text())


def test_a_ticked_red_flag_routes_to_urgent_before_any_question(api):
    from conftest import red_flags
    api.start()
    case = api.new_case(context=[red_flags("RF04")])
    assert case["state"] == "urgent" and case["issued_slots"] == 0
    read = api.case(case["id"])
    assert read["allowed_actions"] == ["view_urgent", "view_history", "delete"]
    r = api.req("POST", f"/cases/{case['id']}/questions/next", key=True, json={"expected_revision": case["revision"]})
    assert r.status_code == 409


def test_none_of_these_apply_continues_to_intake_and_is_kept_as_a_fact(api):
    from conftest import NO_RED_FLAGS
    api.start()
    case = api.new_case(context=[NO_RED_FLAGS])
    assert case["state"] == "intake"
    [fact] = [f for f in case["confirmed_context"] if f["kind"] == "red_flags"]
    assert fact["value"] == [] and fact["provenance"] == "user"


def test_a_ticked_red_flag_routes_to_urgent_even_without_a_concern(api):
    """#392 (R15): a ticked reviewed warning sign routes to urgent help at once, whatever else is missing; a concern
    that was not written is stored empty. Without a ticked sign the concern stays required."""
    from conftest import NO_RED_FLAGS, red_flags
    api.start()
    for concern in ("", "   ", "\u200b\u00ad"):
        case = api.new_case(concern=concern, context=[red_flags("RF01")])
        assert (case["state"], case["concern"], case["urgent_level"], case["issued_slots"]) == (
            "urgent", "", "emergency", 0), repr(concern)
        assert api.case(case["id"])["allowed_actions"] == ["view_urgent", "view_history", "delete"]
    assert api.new_case(concern="", context=[red_flags("RF15")])["urgent_level"] == "urgent_clinician"
    for context in ([NO_RED_FLAGS], [], [red_flags("RF99")]):
        r = api.req("POST", "/cases", key=True, json={"concern": "", "confirmed_context": context})
        assert r.status_code == 422, context
        assert r.json()["field_errors"][0]["field"] in {"concern", "confirmed_context.red_flags"}
    assert len(api.ok("GET", "/cases", 200, None)["items"]) == 4


def test_local_ticked_red_flag_without_a_concern_is_urgent_with_no_model_call(local):
    """#392 in local mode: the ticked sign decides at once; nothing is screened or checked by the model."""
    from conftest import red_flags
    api, model, _ = local
    case = api.new_case(concern=" ", context=[red_flags("RF06")])
    assert (case["state"], case["concern"], case["urgent_level"]) == ("urgent", "", "emergency")
    assert model.calls == []


def test_unknown_or_repeated_red_flag_ids_are_rejected_without_a_case(api):
    from conftest import red_flags
    api.start()
    for bad in (red_flags("RF99"), red_flags("RF01", "RF01"), {**red_flags(), "value": "RF01"},
                {**red_flags(), "value": True}):
        r = api.req("POST", "/cases", key=True, json={"concern": "A fictional concern.", "confirmed_context": [bad]})
        assert r.status_code == 422, bad
        assert r.json()["field_errors"][0]["field"] == "confirmed_context.red_flags"
    assert api.ok("GET", "/cases", 200, None)["items"] == []


def test_every_level_routes_to_urgent(api):
    """Both reviewed levels interrupt: RF01-RF14 and RF19 are emergency, RF15-RF18 urgent clinician (RF17-RF19: amendment)."""
    from conftest import red_flags
    api.start()
    for flag in _package()["red_flags"]:
        assert api.new_case(context=[red_flags(flag["id"])])["state"] == "urgent", flag["id"]


def test_ticking_a_red_flag_on_edit_interrupts_and_invalidates_the_result(api):
    from conftest import NO_RED_FLAGS, red_flags
    api.start()
    case = api.new_case(context=[NO_RED_FLAGS])
    assert api.to_guided(case["id"])["status"] == "succeeded"
    rev = api.case(case["id"])["case"]["revision"]
    edited = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                    json={"expected_revision": rev, "confirmed_context": [red_flags("RF11")]})
    assert edited["state"] == "urgent" and edited["revision"] == rev + 1 and edited["latest_guidance_id"] is None
    r = api.req("GET", f"/cases/{case['id']}/guidance")
    assert r.status_code == 409


def test_an_edit_without_the_checklist_keeps_its_answer(api):
    from conftest import NO_RED_FLAGS
    api.start()
    case = api.new_case(context=[NO_RED_FLAGS])
    age = {"kind": "age_years", "value": 40, "units": "years", "origin": "user", "profile_revision": None}
    edited = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                    json={"expected_revision": case["revision"], "confirmed_context": [age]})
    kinds = {f["kind"] for f in edited["confirmed_context"]}
    assert edited["state"] == "intake" and {"red_flags", "age_years"} <= kinds


def test_the_web_checklist_matches_the_reviewed_package():
    """The A03 checklist ships in the web bundle; it must be the approved wording, levels and messages verbatim."""
    import json
    import re
    from conftest import ROOT
    package = _package()
    source = (ROOT / "apps/web/src/components/RedFlags.tsx").read_text()
    data = json.loads(re.search(r"/\* reviewed-package:begin \*/(.*?)/\* reviewed-package:end \*/", source,
                                re.S).group(1))
    assert data == {k: package[k] for k in ("prompt", "none_label", "messages", "red_flags")}


# ADR-003 amendment 2 (general-adult-3, #79): a red flag described in the person's own words, without a ticked box.
# Before any guidance, the local model screens the concern and every answer against RF01-RF19; a match routes the case
# to urgent help like a ticked box, and any screen failure fails closed (no guidance).

def _screen_calls(model) -> list[dict]:
    return [c for c in model.calls if c["task"] == "red_flag_screen"]


def _events(application, operation: str) -> list[tuple]:
    with application.state.ctx.db.read() as conn:
        return [tuple(r) for r in conn.execute(
            "SELECT kind, status, error_code FROM events WHERE operation_id=? ORDER BY rowid", (operation,))]


def test_the_screen_reads_the_concern_and_answers_against_the_approved_red_flags_before_guidance(local):
    from conftest import NO_RED_FLAGS
    from app.modules.safety import screen
    api, model, application = local
    case = api.new_case(concern="Cough for a week with some blood streaks in my phlegm.", context=[NO_RED_FLAGS])
    job = api.to_guided(case["id"])
    assert job["status"] == "succeeded", job  # no red flag found: guidance as before
    # #153: the screen runs at creation (with the #154 concern check), then again first before guidance.
    assert [c["task"] for c in model.calls][:4] == ["red_flag_screen", "concern_check", "red_flag_screen", "guidance"]
    creation, call = _screen_calls(model)
    assert creation["snapshot"]["person_words"] == [
        {"source": "concern", "text": "Cough for a week with some blood streaks in my phlegm."}]
    assert (call["prompt_version"], call["schema_id"]) == ("red-flag-screen-2", "RedFlagScreen")
    snap = call["snapshot"]
    assert snap["instructions"] == screen.INSTRUCTIONS
    package = _package()
    assert snap["warning_signs"] == [{"id": f["id"], "text": f["text"]} for f in package["red_flags"]]
    words = snap["person_words"]
    assert words[0] == {"source": "concern", "text": "Cough for a week with some blood streaks in my phlegm."}
    answered = [f for f in api.case(case["id"])["case"]["confirmed_context"] if f["kind"].startswith("answer:")]
    assert len(words) == 1 + len(answered) and all(w["text"] for w in words)
    assert set(snap) == {"instructions", "warning_signs", "person_words"}  # nothing else about the case


def test_a_described_emergency_red_flag_routes_to_urgent_without_guidance(local):
    from conftest import NO_RED_FLAGS
    api, model, application = local
    case = api.new_case(concern="Back pain and now I cannot start to pee.", context=[NO_RED_FLAGS])
    model.screen = {"present": ["RF19"]}  # found before guidance (the creation-time screen is tested below, #153)
    job = api.to_guided(case["id"])
    assert (job["status"], job["error_code"], job["result_id"]) == ("failed", "RED_FLAG_DESCRIBED_EMERGENCY", None)
    assert not [c for c in model.calls if c["task"] == "guidance"]  # nothing the model writes is generated or shown
    read = api.case(case["id"])
    assert read["case"]["state"] == "urgent"
    assert read["allowed_actions"] == ["view_urgent", "view_history", "delete"]
    assert api.req("GET", f"/cases/{case['id']}/guidance").status_code in (404, 409)
    r = api.req("POST", f"/cases/{case['id']}/questions/next", key=True,
                json={"expected_revision": read["case"]["revision"]})
    assert r.status_code == 409
    events = _events(application, "generateGuidance")
    assert ("urgent_interrupt", "urgent", "RED_FLAG_DESCRIBED") in events  # #275: no level in events
    assert not [e for e in events if e[0] in ("guidance_published", "guidance_failed")]


def test_the_highest_described_level_wins_and_urgent_clinician_alone_is_reported_as_such(local):
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    first = api.new_case(context=[NO_RED_FLAGS])
    model.screen = {"present": ["RF17"]}
    assert api.to_guided(first["id"])["error_code"] == "RED_FLAG_DESCRIBED_URGENT_CLINICIAN"
    model.screen = {"present": []}
    second = api.new_case(context=[NO_RED_FLAGS])
    model.screen = {"present": ["RF17", "RF04"]}
    assert api.to_guided(second["id"])["error_code"] == "RED_FLAG_DESCRIBED_EMERGENCY"
    assert {api.case(c["id"])["case"]["state"] for c in (first, second)} == {"urgent"}


def test_an_invalid_screen_answer_fails_closed_with_no_guidance(local):
    from conftest import NO_RED_FLAGS
    api, model, application = local
    for bad in ({"present": ["RF99"]}, {"present": ["RF04", "RF04"]}, {"present": "RF04"}, {"present": [4]},
                {"present": [], "note": "x"}, {"flags": []}, ["RF04"]):
        model.calls.clear()
        model.screen = bad
        case = api.new_case(context=[NO_RED_FLAGS])
        job = api.to_guided(case["id"])
        assert (job["status"], job["error_code"]) == ("failed", "RED_FLAG_SCREEN_INVALID"), bad
        assert not [c for c in model.calls if c["task"] == "guidance"], bad
        read = api.case(case["id"])
        assert read["case"]["state"] == "limited" and "retry" in read["allowed_actions"], bad
    assert ("guidance_failed", "failed", "RED_FLAG_SCREEN_INVALID") in _events(application, "generateGuidance")


def test_an_unavailable_screen_fails_closed_and_retry_screens_again(local):
    from conftest import NO_RED_FLAGS
    from app.runtime.zrt_provider import RuntimeTransportError
    api, model, _ = local
    model.screen = RuntimeTransportError("MODEL_UNAVAILABLE")
    case = api.new_case(context=[NO_RED_FLAGS])
    job = api.to_guided(case["id"])
    assert (job["status"], job["error_code"]) == ("failed", "RED_FLAG_SCREEN_UNAVAILABLE")
    assert not [c for c in model.calls if c["task"] == "guidance"]
    assert api.case(case["id"])["case"]["state"] == "limited"
    model.screen = {"present": ["RF04"]}  # the retry is screened again; this time a red flag is described
    job = api.to_guided(case["id"])
    assert job["error_code"] == "RED_FLAG_DESCRIBED_EMERGENCY" and api.case(case["id"])["case"]["state"] == "urgent"


def test_a_pathway_without_the_screen_does_not_call_it(local):
    from dataclasses import replace
    from conftest import NO_RED_FLAGS
    api, model, application = local
    ctx = application.state.ctx
    ctx.pathway = replace(ctx.pathway, red_flag_screen=False)  # general-adult-2 behaviour
    model.screen = {"present": ["RF04"]}
    case = api.new_case(context=[NO_RED_FLAGS])
    assert api.to_guided(case["id"])["status"] == "succeeded"
    assert not _screen_calls(model)


def test_the_screen_accepts_only_distinct_approved_ids_and_grades_by_the_package():
    import pytest
    from conftest import ROOT
    from app.modules.safety import screen
    from app.modules.safety.pathway import load_registry
    pathway = load_registry(ROOT / "content/pathways")
    assert pathway.red_flag_screen is True
    assert screen.accept({"present": []}, pathway) == []
    assert screen.accept({"present": ["RF19", "RF01"]}, pathway) == ["RF01", "RF19"]
    for bad in (None, {}, {"present": None}, {"present": ["rf01"]}, {"present": ["RF01"], "extra": 1}):
        with pytest.raises(screen.ScreenFailed):
            screen.accept(bad, pathway)
    levels = {f["id"]: f["level"] for f in _package()["red_flags"]}
    for i, level in levels.items():
        assert screen.highest_level(pathway, [i]) == level
    assert screen.highest_level(pathway, ["RF15", "RF16"]) == "urgent_clinician"
    words = screen.person_words("my concern", [
        {"kind": "answer:Q01", "value": "2 days", "original_text": "How long?"},
        {"kind": "answer:Q02", "value": None, "original_text": "Unknown?"},
        {"kind": "answer:Q03", "value": ["a", "b"], "original_text": "Which?"},
        {"kind": "red_flags", "value": [], "original_text": None}])
    assert words == [{"source": "concern", "text": "my concern"}, {"source": "How long?", "text": "2 days"},
                     {"source": "Which?", "text": "a, b"}]


def test_an_invalid_screen_setting_fails_startup(tmp_path):
    import json
    import shutil
    import pytest
    from dataclasses import replace
    from app.config import load_settings
    from app.main import create_app
    from app.modules.safety.pathway import PathwayError
    from conftest import ROOT
    from fastapi.testclient import TestClient
    broken = tmp_path / "pathways"
    shutil.copytree(ROOT / "content/pathways", broken)
    [enabled] = json.loads((broken / "registry.json").read_text())["enabled_pathways"]
    policy = json.loads((broken / enabled / "policy.json").read_text())
    policy["red_flag_screen"] = "yes"
    (broken / enabled / "policy.json").write_text(json.dumps(policy))
    settings = replace(load_settings(), mode="local", data_dir=tmp_path / "d", pathways_dir=broken)
    with pytest.raises(PathwayError):
        with TestClient(create_app(settings)):
            pass


# #55 connected acceptance with the reviewed pathway (local mode, scripted model; ADR-003).

def test_local_red_flag_at_concern_blocks_every_routine_action_and_never_reaches_the_model(local):
    """T-R15-S01: a reviewed red flag at the initial concern selects urgent help before intake; routine intake,
    guidance, doctor ranking and export stay blocked."""
    from conftest import red_flags
    api, model, application = local
    case = api.new_case(context=[red_flags("RF04")])
    assert (case["state"], case["issued_slots"]) == ("urgent", 0)
    assert api.case(case["id"])["allowed_actions"] == ["view_urgent", "view_history", "delete"]
    rev = case["revision"]
    blocked = [
        api.req("POST", f"/cases/{case['id']}/questions/next", key=True, json={"expected_revision": rev}),
        api.req("POST", f"/cases/{case['id']}/review", json={"expected_revision": rev, "facts_confirmed": True}),
        api.req("POST", f"/cases/{case['id']}/guidance", key=True, json={"expected_revision": rev}),
        api.req("GET", f"/cases/{case['id']}/guidance"),
        api.req("POST", f"/cases/{case['id']}/provider-search", json={"expected_revision": rev, "criteria": SEARCH}),
        api.req("POST", f"/cases/{case['id']}/exports", key=True, json={"expected_revision": rev, "user_reviewed": True}),
    ]
    # #269: guidance was never generated, so getGuidance is 404; every other routine action is a 409.
    assert [r.status_code for r in blocked] == [409, 409, 409, 404, 409, 409], [(r.status_code, r.text[:80])
                                                                                 for r in blocked]
    assert model.calls == []
    with application.state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_local_red_flag_in_an_answer_is_rechecked_before_guidance(local):
    """T-R15-S02, answer channel: a red flag written only in an answer is screened before the next routine action
    (guidance), routes to urgent help, and no model prose is generated or shown."""
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    case = api.new_case(concern="A chest cold for a week.", context=[NO_RED_FLAGS])
    model.screen = {"present": ["RF17"]}  # the answer, not the concern, describes the red flag
    rev = case["revision"]
    while True:
        nq = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                    json={"expected_revision": rev})
        if nq["kind"] == "review_required":
            break
        q = nq["question"]
        value = {"single_choice": lambda: q["choices"][0]["id"], "multiple_choice": lambda: [q["choices"][0]["id"]],
                 "text": lambda: "I have been coughing up blood since yesterday.", "scale": lambda: 4}[q["response_type"]]()
        rev = api.ok("PUT", f"/cases/{case['id']}/answers/{q['id']}", 200, "SaveAnswerResponse",
                     json={"expected_revision": rev, "status": "answered", "value": value})["case_revision"]
    rev = api.case(case["id"])["case"]["revision"]
    api.ok("POST", f"/cases/{case['id']}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    job = api.wait_job(api.ok("POST", f"/cases/{case['id']}/guidance", 202, "Job", key=True,
                              json={"expected_revision": rev})["id"])
    assert (job["status"], job["error_code"]) == ("failed", "RED_FLAG_DESCRIBED_URGENT_CLINICIAN")
    call = [c for c in model.calls if c["task"] == "red_flag_screen"][-1]
    assert "I have been coughing up blood since yesterday." in [w["text"] for w in call["snapshot"]["person_words"]]
    assert not [c for c in model.calls if c["task"] == "guidance"]
    assert api.case(case["id"])["case"]["state"] == "urgent"


def test_local_red_flag_ticked_on_an_edit_is_rechecked_and_recorded_with_a_new_revision(local):
    """T-R15-S02, clinical-edit channel: ticking a reviewed red flag on an edit routes to urgent help before the next
    routine action, records the ticked IDs with the new input revision, and blocks the reviewed generation."""
    from conftest import NO_RED_FLAGS, red_flags
    api, model, _ = local
    case = api.new_case(context=[NO_RED_FLAGS])
    api.answer_all(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    api.ok("POST", f"/cases/{case['id']}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    edited = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                    json={"expected_revision": rev, "confirmed_context": [red_flags("RF19")]})
    assert edited["state"] == "urgent" and edited["revision"] > rev
    [flags] = [f for f in edited["confirmed_context"] if f["kind"] == "red_flags"]
    assert flags["value"] == ["RF19"]
    r = api.req("POST", f"/cases/{case['id']}/guidance", key=True, json={"expected_revision": edited["revision"]})
    assert r.status_code == 409
    assert edited["urgent_level"] == "emergency"  # #153: the case records the ticked item's reviewed level
    assert concern_screens_only(model)  # #153: the concern was screened when the case was created; nothing else


def test_local_mode_has_no_record_input_channel_until_a_reviewed_extractor_exists(local):
    """T-R15-S02, record channel: local mode refuses record uploads, so no record fact can bypass the urgency check
    (the mock record channel is asserted by test_R20::test_confirming_or_correcting_a_record_fact_reruns_the_urgency_check)."""
    from conftest import NO_RED_FLAGS
    from records_helpers import SAMPLE, upload
    api, model, application = local
    case = api.new_case(context=[NO_RED_FLAGS])
    r = upload(api, case["id"], SAMPLE)
    assert r.status_code == 503 and r.json()["code"] == "SERVICE_LIMITED"
    with application.state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM facts WHERE provenance='document'").fetchone()[0] == 0
    assert concern_screens_only(model)  # #153: the concern was screened when the case was created; nothing else


# #153 (ADR-003 amendment 3): the red-flag screen also reads the concern when the case is created, and again when the
# concern is edited, so a written emergency interrupts intake at once instead of after the questions. A screen failure
# there defers to the screen before guidance, which still fails closed.

def _case_row(application, case_id: str):
    with application.state.ctx.db.read() as conn:
        return conn.execute("SELECT state, urgent_level, issued_slots FROM cases WHERE id=?", (case_id,)).fetchone()


def test_a_written_emergency_interrupts_intake_when_the_case_is_created(local):
    from conftest import NO_RED_FLAGS
    api, model, application = local
    model.screen = {"present": ["RF04"]}
    case = api.new_case(concern="Crushing chest pain spreading to my left arm.", context=[NO_RED_FLAGS])
    assert (case["state"], case["urgent_level"], case["issued_slots"]) == ("urgent", "emergency", 0)
    [call] = _screen_calls(model)
    assert call["snapshot"]["person_words"] == [{"source": "concern",
                                                 "text": "Crushing chest pain spreading to my left arm."}]
    assert [c["task"] for c in model.calls] == ["red_flag_screen"]  # no question, no guidance, nothing shown
    read = api.case(case["id"])
    assert read["allowed_actions"] == ["view_urgent", "view_history", "delete"]
    r = api.req("POST", f"/cases/{case['id']}/questions/next", key=True, json={"expected_revision": case["revision"]})
    assert r.status_code == 409
    events = _events(application, "createCase")
    assert ("case_created", "urgent", None) in events
    assert ("urgent_interrupt", "urgent", "RED_FLAG_DESCRIBED") in events  # #275: no level in events


def test_a_written_urgent_clinician_sign_is_recorded_at_its_reviewed_level(local):
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    model.screen = {"present": ["RF17"]}
    case = api.new_case(concern="I coughed up some blood this morning.", context=[NO_RED_FLAGS])
    assert (case["state"], case["urgent_level"]) == ("urgent", "urgent_clinician")
    model.screen = {"present": ["RF17", "RF04"]}
    assert api.new_case(context=[NO_RED_FLAGS])["urgent_level"] == "emergency"  # the highest level wins


def test_a_failed_concern_screen_defers_to_the_screen_before_guidance(local):
    from conftest import NO_RED_FLAGS
    from app.runtime.zrt_provider import RuntimeTransportError
    api, model, application = local
    for failure, code in ((RuntimeTransportError("MODEL_UNAVAILABLE"), "RED_FLAG_SCREEN_UNAVAILABLE"),
                          ({"present": ["RF99"]}, "RED_FLAG_SCREEN_INVALID")):
        model.screen = failure
        case = api.new_case(context=[NO_RED_FLAGS])
        assert (case["state"], case["urgent_level"]) == ("intake", None), code  # intake continues
        assert ("concern_screen_deferred", "deferred", code) in _events(application, "createCase")
        model.screen = {"present": ["RF19"]}  # the screen before guidance still runs and still routes
        job = api.to_guided(case["id"])
        assert job["error_code"] == "RED_FLAG_DESCRIBED_EMERGENCY", code
        assert _case_row(application, case["id"])["urgent_level"] == "emergency"  # recorded on that route too


def test_no_concern_screen_runs_when_a_box_is_ticked_or_the_checklist_is_unanswered(local):
    from conftest import red_flags
    api, model, _ = local
    ticked = api.new_case(context=[red_flags("RF17")])
    assert (ticked["state"], ticked["urgent_level"]) == ("urgent", "urgent_clinician")
    unanswered = api.new_case(context=[])
    assert unanswered["state"] == "limited" and unanswered["urgent_level"] is None
    assert model.calls == []


def test_no_concern_screen_runs_in_mock_mode_or_without_the_reviewed_screen(local, app):
    from dataclasses import replace
    from conftest import NO_RED_FLAGS
    from app.modules.safety import screen
    api, model, application = local
    ctx = application.state.ctx
    ctx.pathway = replace(ctx.pathway, red_flag_screen=False)
    model.screen = {"present": ["RF04"]}
    assert api.new_case(context=[NO_RED_FLAGS])["state"] == "intake"
    assert not _screen_calls(model)  # (the #154 concern check is separate and still runs)
    assert screen.screen_concern(app[0].state.ctx, "Crushing chest pain.") == ([], None)  # mock mode: never read


def test_an_edited_concern_is_screened_again_and_an_unchanged_one_is_not(local):
    from conftest import NO_RED_FLAGS
    api, model, application = local
    case = api.new_case(concern="A mild headache since Monday.", context=[NO_RED_FLAGS])
    assert case["state"] == "intake" and len(_screen_calls(model)) == 1
    same = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                  json={"expected_revision": case["revision"], "concern": "A mild headache since Monday."})
    assert same["state"] == "intake" and len(_screen_calls(model)) == 1  # unchanged concern: not screened again
    model.screen = {"present": ["RF02"]}
    edited = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                    json={"expected_revision": same["revision"],
                          "concern": "Now the worst headache of my life, it came on suddenly."})
    assert (edited["state"], edited["urgent_level"], edited["revision"]) == ("urgent", "emergency", same["revision"] + 1)
    assert _screen_calls(model)[-1]["snapshot"]["person_words"][0]["text"].startswith("Now the worst headache")
    assert ("urgent_interrupt", "urgent", "RED_FLAG_DESCRIBED") in _events(application, "editCase")  # #275


def test_a_failed_screen_of_an_edited_concern_keeps_intake_and_is_recorded(local):
    from conftest import NO_RED_FLAGS
    from app.runtime.zrt_provider import RuntimeTransportError
    api, model, application = local
    case = api.new_case(context=[NO_RED_FLAGS])
    model.screen = RuntimeTransportError("MODEL_UNAVAILABLE")
    edited = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                    json={"expected_revision": case["revision"], "concern": "A different concern now."})
    assert edited["state"] == "intake"
    assert ("concern_screen_deferred", "deferred", "RED_FLAG_SCREEN_UNAVAILABLE") in _events(application, "editCase")


# --- #87 (T-R15-S02): the matched rule IDs are recorded with the input revision ----------------------------------------
def _recorded(application, case_id: str):
    import json
    with application.state.ctx.db.read() as conn:
        row = conn.execute("SELECT state, urgent_level, urgent_rule_ids, urgent_revision, revision FROM cases WHERE id=?",
                           (case_id,)).fetchone()
    return row["state"], row["urgent_level"], json.loads(row["urgent_rule_ids"] or "null"), row["urgent_revision"], \
        row["revision"]


def test_the_ids_the_screen_matches_before_guidance_are_recorded_with_the_input_revision(local):
    """T-R15-S02: the screen's matched IDs (not only their level) are stored with the revision they were matched at."""
    from conftest import NO_RED_FLAGS
    api, model, application = local
    case = api.new_case(concern="Back pain and now I cannot start to pee.", context=[NO_RED_FLAGS])
    model.screen = {"present": ["RF19", "RF17"]}
    job = api.to_guided(case["id"])
    assert job["error_code"] == "RED_FLAG_DESCRIBED_EMERGENCY"
    state, level, ids, revision, current = _recorded(application, case["id"])
    assert (state, level, ids) == ("urgent", "emergency", ["RF17", "RF19"])
    assert revision == job["input_revision"] == current


def test_ids_written_in_the_concern_or_ticked_are_recorded_at_creation_and_on_an_edit(local):
    from conftest import NO_RED_FLAGS, red_flags
    api, model, application = local
    model.screen = {"present": ["RF04"]}
    written = api.new_case(concern="Crushing chest pain spreading to my left arm.", context=[NO_RED_FLAGS])
    assert _recorded(application, written["id"])[:4] == ("urgent", "emergency", ["RF04"], 1)
    ticked = api.new_case(context=[red_flags("RF11", "RF02")])
    assert _recorded(application, ticked["id"])[2:4] == (["RF02", "RF11"], 1)
    model.screen = {"present": []}
    plain = api.new_case(concern="A mild headache since Monday.", context=[NO_RED_FLAGS])
    assert _recorded(application, plain["id"])[1:4] == (None, None, None)  # nothing matched, nothing recorded
    model.screen = {"present": ["RF02"]}
    edited = api.ok("PATCH", f"/cases/{plain['id']}", 200, "Case",
                    json={"expected_revision": plain["revision"], "concern": "Sudden weakness down one side."})
    state, level, ids, revision, current = _recorded(application, plain["id"])
    assert (state, ids) == ("urgent", ["RF02"]) and revision == current == edited["revision"] == plain["revision"] + 1


def test_recorded_ids_are_never_shown_or_written_to_events(local):
    """The record is internal: the person sees only the level's approved message, and events stay content-free."""
    from conftest import NO_RED_FLAGS
    api, model, application = local
    model.screen = {"present": ["RF04"]}
    case = api.new_case(concern="Crushing chest pain spreading to my left arm.", context=[NO_RED_FLAGS])
    read = api.case(case["id"])["case"]
    assert "urgent_rule_ids" not in read and "urgent_revision" not in read and "RF04" not in str(read)
    with application.state.ctx.db.read() as conn:
        assert not [r for r in conn.execute("SELECT * FROM events") if "RF04" in str(tuple(r))]


# --- #387 (ADR-003 amendment 5): the free text the person typed into the profile (A02 relevant history, current
# medications, reported allergies) is screened with the concern, at creation, on an edit that changes it and before
# guidance, so an overdose or a suicide attempt written there routes to urgent help like one written in the concern.
OVERDOSE = "I took 30 of my sleeping tablets about an hour ago."
SUICIDE = "I tried to kill myself last week and I still have those thoughts every day."


def _profile(kind: str, value) -> dict:
    return {"kind": kind, "value": value, "units": None, "origin": "user", "profile_revision": None}


def _screen_matching(phrase: str, rf: str):
    """A scripted screen that finds `rf` only when `phrase` is among the words it is given."""
    return lambda words: {"present": [rf] if any(phrase in w["text"] for w in words) else []}


@pytest.mark.parametrize("kind,label,text,concern,rf", [
    ("medications", "Current medications", OVERDOSE, "I feel sick and a bit sleepy.", "RF20"),
    ("history", "Relevant history", SUICIDE, "I can't sleep at night.", "RF11"),
], ids=["overdose-in-medications", "suicide-attempt-in-history"])
def test_a_red_flag_written_in_the_profile_routes_to_urgent_help_when_the_case_is_created(local, kind, label, text,
                                                                                       concern, rf):
    from conftest import NO_RED_FLAGS
    api, model, application = local
    model.screen = _screen_matching(text, rf)
    case = api.new_case(concern=concern, context=[_profile("age_years", 41), _profile(kind, text), NO_RED_FLAGS])
    assert (case["state"], case["urgent_level"], case["issued_slots"]) == ("urgent", "emergency", 0)
    [call] = _screen_calls(model)
    assert call["snapshot"]["person_words"] == [{"source": "concern", "text": concern}, {"source": label, "text": text}]
    assert [c["task"] for c in model.calls] == ["red_flag_screen"]  # no question, no guidance, nothing shown
    assert api.case(case["id"])["allowed_actions"] == ["view_urgent", "view_history", "delete"]
    assert _recorded(application, case["id"])[:4] == ("urgent", "emergency", [rf], 1)
    assert ("urgent_interrupt", "urgent", "RED_FLAG_DESCRIBED") in _events(application, "createCase")


def test_the_screen_before_guidance_reads_the_profile_free_text_with_the_concern_and_answers(local):
    from conftest import NO_RED_FLAGS
    from app.runtime.zrt_provider import RuntimeTransportError
    api, model, _ = local
    model.screen = RuntimeTransportError("MODEL_UNAVAILABLE")  # the creation-time screen defers
    case = api.new_case(concern="I feel sick and a bit sleepy.",
                        context=[_profile("medications", OVERDOSE), NO_RED_FLAGS])
    assert case["state"] == "intake"
    model.screen = _screen_matching(OVERDOSE, "RF20")
    job = api.to_guided(case["id"])
    assert (job["status"], job["error_code"]) == ("failed", "RED_FLAG_DESCRIBED_EMERGENCY")
    assert not [c for c in model.calls if c["task"] == "guidance"]
    words = _screen_calls(model)[-1]["snapshot"]["person_words"]
    assert words[:2] == [{"source": "concern", "text": "I feel sick and a bit sleepy."},
                         {"source": "Current medications", "text": OVERDOSE}]
    answered = [f for f in api.case(case["id"])["case"]["confirmed_context"] if f["kind"].startswith("answer:")]
    assert len(words) == 2 + len(answered)
    assert api.case(case["id"])["case"]["state"] == "urgent"


def test_an_edit_that_changes_the_profile_free_text_is_screened_and_an_unchanged_one_is_not(local):
    from conftest import NO_RED_FLAGS
    api, model, application = local
    model.screen = _screen_matching(OVERDOSE, "RF20")
    usual = _profile("medications", "Lisinopril 10 mg once a day.")
    case = api.new_case(concern="I feel sick and a bit sleepy.", context=[usual, NO_RED_FLAGS])
    assert case["state"] == "intake" and len(_screen_calls(model)) == 1
    checks = len([c for c in model.calls if c["task"] == "concern_check"])
    same = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                  json={"expected_revision": case["revision"], "confirmed_context": [usual, _profile("age_years", 41)]})
    assert same["state"] == "intake" and len(_screen_calls(model)) == 1  # the profile text did not change
    edited = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                    json={"expected_revision": same["revision"], "confirmed_context": [_profile("medications", OVERDOSE)]})
    assert (edited["state"], edited["urgent_level"], edited["revision"]) == ("urgent", "emergency", same["revision"] + 1)
    assert _screen_calls(model)[-1]["snapshot"]["person_words"] == [
        {"source": "concern", "text": "I feel sick and a bit sleepy."}, {"source": "Current medications", "text": OVERDOSE}]
    assert len([c for c in model.calls if c["task"] == "concern_check"]) == checks  # the concern did not change
    assert ("urgent_interrupt", "urgent", "RED_FLAG_DESCRIBED") in _events(application, "editCase")


def test_profile_words_are_the_typed_profile_text_only():
    from app.modules.cases.schemas import ConfirmedContextWrite
    from app.modules.safety import screen
    facts = [{"kind": "red_flags", "value": [], "original_text": None},
             {"kind": "age_years", "value": 41, "original_text": None},
             {"kind": "history", "value": "Asthma since childhood.", "original_text": None},
             {"kind": "medications", "value": None, "original_text": None},
             {"kind": "allergy_status", "value": "reported", "original_text": None},
             {"kind": "allergies", "value": "Penicillin", "original_text": None},
             {"kind": "record:medications", "value": "Synthetic record line", "original_text": "Record"},
             {"kind": "answer:Q05", "value": "Rest and water.", "original_text": "What have you already tried?"}]
    assert screen.person_words("my concern", facts) == [
        {"source": "concern", "text": "my concern"}, {"source": "Relevant history", "text": "Asthma since childhood."},
        {"source": "Reported allergies", "text": "Penicillin"},
        {"source": "What have you already tried?", "text": "Rest and water."}]
    item = ConfirmedContextWrite(kind="medications", value=OVERDOSE, units=None, origin="user", profile_revision=None)
    assert screen.profile_words([item, ConfirmedContextWrite(kind="history", value="  ", units=None, origin="user",
                                                             profile_revision=None)]) == [
        {"source": "Current medications", "text": OVERDOSE}]


# --- #583: context under any other kind reaches guidance as a confirmed fact, so it is screened too -------------------
def _received(model, phrase: str) -> list[str]:
    """The tasks of the model calls whose input contained `phrase` (a screen flags a marker only when it receives it)."""
    import json
    return [c["task"] for c in model.calls if phrase in json.dumps(c["snapshot"])]


def test_583_a_red_flag_in_a_custom_context_kind_is_screened_when_the_case_is_created(local):
    from conftest import NO_RED_FLAGS
    api, model, application = local
    model.screen = _screen_matching(OVERDOSE, "RF20")
    case = api.new_case(concern="I feel sick and a bit sleepy.",
                        context=[_profile("additional_history", OVERDOSE), NO_RED_FLAGS])
    assert (case["state"], case["urgent_level"], case["issued_slots"]) == ("urgent", "emergency", 0)
    assert _received(model, OVERDOSE) == ["red_flag_screen"]
    assert _recorded(application, case["id"])[:3] == ("urgent", "emergency", ["RF20"])


def test_583_an_edit_that_adds_a_red_flag_under_a_custom_kind_is_screened(local):
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    model.screen = _screen_matching(OVERDOSE, "RF20")
    case = api.new_case(concern="I feel sick and a bit sleepy.",
                        context=[_profile("additional_history", "Hay fever every spring."), NO_RED_FLAGS])
    assert case["state"] == "intake"
    edited = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                    json={"expected_revision": case["revision"],
                          "confirmed_context": [_profile("additional_history", OVERDOSE)]})
    assert (edited["state"], edited["urgent_level"]) == ("urgent", "emergency")
    assert _received(model, OVERDOSE) == ["red_flag_screen"]


@pytest.mark.parametrize("item", [
    _profile("additional_history", OVERDOSE),
    _profile("other_notes", ["Hay fever every spring.", OVERDOSE]),
    _profile(OVERDOSE, True),  # the kind itself is shown to the guidance model as the fact's label
], ids=["text", "list", "in-the-kind"])
def test_583_the_screen_before_guidance_reads_every_custom_context_text_the_guidance_would_read(local, item):
    from conftest import NO_RED_FLAGS
    from app.runtime.zrt_provider import RuntimeTransportError
    api, model, _ = local
    model.screen = RuntimeTransportError("MODEL_UNAVAILABLE")  # the creation-time screen defers
    case = api.new_case(concern="I feel sick and a bit sleepy.", context=[item, NO_RED_FLAGS])
    assert case["state"] == "intake"
    model.screen = _screen_matching(OVERDOSE, "RF20")
    job = api.to_guided(case["id"])
    assert (job["status"], job["error_code"]) == ("failed", "RED_FLAG_DESCRIBED_EMERGENCY")
    assert "guidance" not in _received(model, OVERDOSE)  # the marker never reached the guidance model
    assert api.case(case["id"])["case"]["state"] == "urgent"


def test_583_everything_the_guidance_model_reads_from_custom_context_was_screened_first(local):
    """The control: with no red flag described, guidance is published, and every custom context fact it read (label
    and value) was in the words of the screen before it."""
    import json
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    items = [_profile("additional_history", "Hay fever every spring."), _profile("weight_kg", 72),
             _profile("other_notes", ["Works night shifts.", "Drinks little water."]), _profile("smoker", False),
             _profile("family_history", None)]
    case = api.new_case(concern="Recurring headaches after long workdays.", context=[*items, NO_RED_FLAGS])
    job = api.to_guided(case["id"])
    assert job["status"] == "succeeded"
    [guidance] = [c for c in model.calls if c["task"] == "guidance"]
    screened = json.dumps(_screen_calls(model)[-1]["snapshot"]["person_words"])
    read = [f for f in guidance["snapshot"]["case"]["confirmed_facts"]
            if f["question"] in {i["kind"] for i in items}]
    assert len(read) == len(items)
    for fact in read:
        assert fact["question"] in screened, fact
        for part in fact["answer"] if isinstance(fact["answer"], list) else [fact["answer"]]:
            if part is not None:
                assert json.dumps(part).strip('"') in screened, fact


def test_583_profile_words_keep_the_structured_and_server_kinds_out():
    from app.modules.safety import screen
    facts = [{"kind": "red_flags", "value": ["RF04"], "provenance": "user"},
             {"kind": "age_years", "value": 41, "provenance": "user"},
             {"kind": "allergy_status", "value": "none_reported", "provenance": "user"},
             {"kind": "answer:Q05", "value": "Rest.", "provenance": "user", "original_text": "Tried?"},
             {"kind": "record:medications", "value": "Synthetic record line", "provenance": "document"},
             {"kind": "fixture:urgent_signal", "value": True, "provenance": "fixture"},
             {"kind": "additional_history", "value": "Hay fever.", "provenance": "user"}]
    assert screen.profile_words(facts) == [{"source": "Other detail", "text": "additional_history: Hay fever."}]


# --- #389/#390: red-flag-screen-2 (carers' emergencies) and its ADR-002 re-qualification ------------------------------
SCREEN_QUALIFICATION = "evidence/model-qualification/2026-10-22-red-flag-screen-2"
CARER_EMERGENCIES = [  # #389 (C-02): created in intake on the Nano with red-flag-screen-1
    "My father has crushing chest pain right now and is sweating, what should I do?",
    "My father has crushing chest pain right now and is sweating.", "My dad has chest pain spreading to his left arm.",
    "My wife has chest pain and is sweating a lot.", "My brother's lips and tongue are swelling after he ate peanuts."]


def _qualification_run(device: str, name: str = "run.json") -> dict:
    from conftest import ROOT
    return json.loads((ROOT / SCREEN_QUALIFICATION / device / name).read_text())


def test_the_shipped_screen_prompt_is_the_one_qualified_on_both_devices():
    """#389: the app sends red-flag-screen-2, whose hash the qualification record, both devices' gate files and both
    model manifests name; each device's re-qualification PASSED with no urgent item missed in any repeat."""
    from conftest import ROOT
    from app.modules.safety import screen
    assert (screen.TASK, screen.PROMPT_VERSION, screen.SCHEMA_ID) == ("red_flag_screen", "red-flag-screen-2",
                                                                       "RedFlagScreen")
    assert screen.PROMPT_SHA256 == "598398e144597152e5fe1b382a884e98cdf0c0b458105c4b5f2e540156c8d9a3"
    record = (ROOT / SCREEN_QUALIFICATION / "README.md").read_text()
    assert screen.PROMPT_SHA256 in record and "**PASSED**" in record
    prompts = json.loads((ROOT / SCREEN_QUALIFICATION / "prompts.json").read_text())
    assert prompts["red-flag-screen-2"] == screen.INSTRUCTIONS
    for device, manifest, model_id in (("nano", "infra/model-manifest.json", "qwen3.6-35b-a3b-fp8"),
                                       ("fury", "infra/fury/model-manifest.json", "qwen3.8-flash-next-fp8")):
        gates = json.loads((ROOT / SCREEN_QUALIFICATION / device / "gates.json").read_text())
        assert gates["result"] == "PASSED" and all(g["pass"] for g in gates["gates"].values()), device
        assert gates["gates"]["0 identity"]["prompt"] == ["red-flag-screen-2", screen.PROMPT_SHA256], device
        assert gates["gates"]["0 identity"]["served"] == model_id, device
        recall = gates["gates"]["A recall"]
        assert recall["missed_set"] == [] == recall["missed_heldout"] and recall["urgent_set"] >= 500, device
        assert gates["gates"]["D determinism"]["repeats"] >= 3, device
        entry = json.loads((ROOT / manifest).read_text())["generation"]["red_flag_screen"]
        assert (entry["prompt_version"], entry["prompt_sha256"]) == (screen.PROMPT_VERSION, screen.PROMPT_SHA256)
        assert entry["qualification"]["result"] == "PASSED" and (ROOT / entry["qualification"]["gates_file"]).is_file()


def test_carer_emergencies_route_urgent_on_both_devices_and_did_not_before():
    """#389 (C-02): a carer's description of an acute emergency happening now routes to urgent help at the emergency
    level in every repeat on both devices; with red-flag-screen-1 the same words stayed in intake."""
    for device in ("nano", "fury"):
        run = _qualification_run(device)["rows"]
        base = {r["id"]: r for r in json.loads(
            _qual_path(f"baseline/{device}-red-flag-screen-1.json").read_text())["rows"]}
        by_text = {_case(r["id"])["words"][0]["text"]: r for r in run if len(_case(r["id"])["words"]) == 1}
        for text in CARER_EMERGENCIES:
            assert [x["level"] for x in by_text[text]["runs"]] == ["emergency"] * 3, (device, text)
            assert not any(x.get("present") for x in base[by_text[text]["id"]]["runs"]), (device, text)  # intake before
        carers = [r for r in run if _case(r["id"])["set"] in ("carer", "carer-answers", "stress-carer")]
        assert len(carers) >= 80 and all(not r["missed_runs"] for r in carers), device
        assert sum(bool(base[r["id"]]["missed_runs"]) for r in carers) > 0, device  # missed before the change
        rf_covered = {i for r in carers for i in _case(r["id"])["expect"]}
        assert rf_covered >= {f"RF{n:02d}" for n in range(1, 21)}, device


def test_another_persons_past_or_background_signs_stay_out_on_both_devices():
    """#389: the carer rule does not count another person's past illness, family history or hypothetical signs."""
    for device in ("nano", "fury"):
        for r in _qualification_run(device)["rows"]:
            if _case(r["id"])["set"] in ("carer-neg", "profile", "profile-387") and r["label"] == "negative":
                assert r["false_alarm_runs"] == 0, (device, r["id"])


def test_red_flag_screen_2_keeps_the_rules_of_red_flag_screen_1():
    """#389/#390: denials, long-past and hypothetical signs stay out, everyday words count, and doubt still counts."""
    from app.modules.safety import screen
    text = screen.INSTRUCTIONS
    for rule in ("someone they care for or are with", "happening to them now or has just happened",
                 "Do not count a sign the person denies", "long past and resolved", "hypothetical",
                 "only background to the writer's own concern", "family history",
                 "When you are unsure whether a described symptom matches a sign, count it.",
                 "using only the listed ids"):
        assert rule in text, rule


def test_the_screen_measurement_set_carries_every_labelled_urgent_set():
    """#389/#390: the set holds the amendment-2 positives, the #84 stress positives, the 33 written emergencies of the
    deployed checks, the RF20 poisonings, the QA's emergencies (12 languages, carers) and the C-03 concerns."""
    from conftest import ROOT
    data = json.loads(_qual_path("cases.json").read_text())
    assert data["synthetic"] is True
    sets = {}
    for it in data["items"]:
        sets.setdefault(it["set"], []).append(it)
    labelled = json.loads((ROOT / "evidence/clinical-review/2026-10-16-amendment-2/labelled-set.json").read_text())
    stress = json.loads((ROOT / "evidence/clinical-review/2026-10-16-screen-stress/stress-set.json").read_text())
    urgent_ids = {it["id"] for it in data["items"] if it["label"] == "urgent"}
    assert {i["id"] for i in labelled["items"] if i["label"] == "positive"} <= urgent_ids
    assert {i["id"] for i in stress["items"] if i["label"] == "positive"} <= urgent_ids
    assert {"qa-suicidal-ideation", "qa-stroke", "qa-anaphylaxis", "qa-overdose", "qa-pregnancy-bleeding",
            "qa-chest-pain-typo", "rf20-u2", "rf20-u3", "rf20-u4"} <= urgent_ids  # rf20-u1 is qa-overdose
    assert len([i for i in sets["qa7-set1"] if i["label"] == "urgent"]) == 25
    texts = {it["words"][0]["text"] for it in data["items"] if len(it["words"]) == 1}
    assert {"headache", "Headache", "stomach ache", "Bauchschmerzen", "头疼", "Me duele el estómago", "rash",
            "positive pregnancy test", "life feels meaningless", "ED", "🤒"} <= texts
    assert set(CARER_EMERGENCIES) <= texts


def _qual_path(name: str):
    from conftest import ROOT
    return ROOT / SCREEN_QUALIFICATION / name


_CASES: dict = {}


def _case(item_id: str) -> dict:
    if not _CASES:
        for f in ("cases.json", "heldout.json"):
            _CASES.update({it["id"]: it for it in json.loads(_qual_path(f).read_text())["items"]})
    return _CASES[item_id]
