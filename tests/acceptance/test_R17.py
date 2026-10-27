"""R17 fail safely when urgency cannot be assessed (local mode, ADR-003). M05.

Local mode serves guidance only with the active reviewed pathway and a red-flag checklist answer. Without either, the
case is limited and generation is refused; urgent routing still works. These tests use a scripted model and never
contact ZRT.
"""
from dataclasses import replace
from datetime import datetime, timezone

from conftest import concern_screens_only

REQUIREMENT = "R17"


def test_a_local_case_without_the_checklist_is_limited(local):
    api, model, _ = local
    case = api.new_case(context=[])
    assert case["state"] == "limited" and case["issued_slots"] == 0
    read = api.case(case["id"])
    assert "next_question" not in read["allowed_actions"] and "retry" not in read["allowed_actions"]
    assert model.calls == []


def test_a_local_case_with_the_checklist_starts_intake(local):
    from conftest import NO_RED_FLAGS
    api, _, _ = local
    assert api.new_case(context=[NO_RED_FLAGS])["state"] == "intake"


def test_an_expired_pathway_limits_new_cases_and_refuses_generation_but_still_routes_urgent(local):
    from conftest import NO_RED_FLAGS, red_flags
    api, model, app = local
    ctx = app.state.ctx
    case = api.new_case(context=[NO_RED_FLAGS])
    api.answer_all(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    api.ok("POST", f"/cases/{case['id']}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    ctx.pathway = replace(ctx.pathway, expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    r = api.req("POST", f"/cases/{case['id']}/guidance", key=True, json={"expected_revision": rev})
    assert r.status_code == 503 and r.json()["code"] == "SERVICE_LIMITED"
    assert api.req("GET", "/health/ready").json() == {"readiness": "unavailable"}
    assert api.new_case(context=[NO_RED_FLAGS])["state"] == "limited"
    assert api.new_case(context=[red_flags("RF02")])["state"] == "urgent"
    assert [c for c in model.calls if c["task"] == "guidance"] == []


def test_an_unapproved_pathway_is_not_active(local):
    _, _, app = local
    ctx = app.state.ctx
    assert ctx.pathway.active()
    assert not replace(ctx.pathway, approved=False).active()
    assert not replace(ctx.pathway, enabled=False).active()


def test_local_readiness_reports_a_missing_model_as_degraded(local):
    api, model, _ = local
    assert api.req("GET", "/health/ready").json() == {"readiness": "ready"}

    async def unserved():
        return {"status": "unavailable", "provider": "zrt", "model_id": "test-model", "reason_code": "MODEL_NOT_SERVED"}
    model.health = unserved
    r = api.req("GET", "/health/ready")
    assert r.status_code == 200 and r.json() == {"readiness": "degraded"}


def test_a_malformed_package_fails_startup(tmp_path):
    import json
    import shutil
    import pytest
    from app.config import load_settings
    from app.main import create_app
    from app.modules.safety.pathway import PathwayError
    from conftest import ROOT
    from fastapi.testclient import TestClient
    broken = tmp_path / "pathways"
    shutil.copytree(ROOT / "content/pathways", broken)
    [enabled] = json.loads((broken / "registry.json").read_text())["enabled_pathways"]
    flags = json.loads((broken / enabled / "red-flags.json").read_text())
    flags["red_flags"] = flags["red_flags"][:-1]  # the checklist no longer matches urgent_rules
    (broken / enabled / "red-flags.json").write_text(json.dumps(flags))
    settings = replace(load_settings(), mode="local", data_dir=tmp_path / "d", pathways_dir=broken)
    with pytest.raises(PathwayError):
        with TestClient(create_app(settings)):
            pass


# #55 connected acceptance with the reviewed pathway (local mode, scripted model; ADR-003).

def test_local_unavailable_pathway_keeps_answers_and_assumes_no_negative_finding(local):
    """T-R17-S01: with the pathway package unavailable after intake, a direct generation request is refused with
    SERVICE_LIMITED; completed answers stay with the case, and the missing assessment is not turned into a result."""
    from conftest import NO_RED_FLAGS
    api, model, app = local
    ctx = app.state.ctx
    case = api.new_case(context=[NO_RED_FLAGS])
    api.answer_all(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    api.ok("POST", f"/cases/{case['id']}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    answers = [f for f in api.case(case["id"])["case"]["confirmed_context"] if f["kind"].startswith("answer:")]
    assert len(answers) == 10
    ctx.pathway = None  # the reviewed package is unavailable
    r = api.req("POST", f"/cases/{case['id']}/guidance", key=True, json={"expected_revision": rev})
    assert r.status_code == 503 and r.json()["code"] == "SERVICE_LIMITED"
    read = api.case(case["id"])
    assert read["case"]["state"] == "reviewed"  # not guided, not urgent: nothing was concluded
    assert [f for f in read["case"]["confirmed_context"] if f["kind"].startswith("answer:")] == answers
    assert api.req("GET", f"/cases/{case['id']}/guidance").status_code in (404, 409)
    assert concern_screens_only(model)  # #153: only the concern screen at creation, while the pathway was enabled
    assert api.req("GET", "/health/ready").json() == {"readiness": "unavailable"}


def test_local_routine_generation_unavailable_still_serves_urgent_routing(local):
    """T-R17-S02: while routine generation is unavailable (the loaded package is no longer active), the reviewed red
    flags still route to urgent help, and no fallback produces a self-care result."""
    from conftest import NO_RED_FLAGS, red_flags
    api, model, app = local
    ctx = app.state.ctx
    ctx.pathway = replace(ctx.pathway, expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    for flag in ("RF01", "RF15"):
        urgent = api.new_case(context=[red_flags(flag)])
        assert (urgent["state"], urgent["issued_slots"]) == ("urgent", 0)
    limited = api.new_case(context=[NO_RED_FLAGS])
    assert limited["state"] == "limited"
    assert api.case(limited["id"])["allowed_actions"] == ["view_limits", "view_history", "delete"]
    assert model.calls == []


# #264 (QA 2026-10-19): a case limited only because the checklist was not answered can be corrected.

def test_a_case_limited_for_the_missing_checklist_is_corrected_by_answering_it(local):
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    case = api.new_case(context=[])
    assert case["state"] == "limited"
    read = api.case(case["id"])
    assert "edit" in read["allowed_actions"] and "save_answer" not in read["allowed_actions"]
    edited = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                    json={"expected_revision": case["revision"], "confirmed_context": [NO_RED_FLAGS]})
    assert edited["state"] == "intake" and edited["revision"] == case["revision"] + 1
    # The concern was never screened (no checklist at creation); it is screened now, as at creation.
    assert concern_screens_only(model) and {c["task"] for c in model.calls} == {"red_flag_screen", "concern_check"}
    read = api.case(case["id"])
    assert "next_question" in read["allowed_actions"] and "edit" in read["allowed_actions"]


def test_a_correcting_edit_that_ticks_a_red_flag_routes_to_urgent(local):
    from conftest import red_flags
    api, model, _ = local
    case = api.new_case(context=[])
    edited = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                    json={"expected_revision": case["revision"], "confirmed_context": [red_flags("RF04")]})
    assert edited["state"] == "urgent" and edited["urgent_level"] is not None
    assert model.calls == []


def test_an_edit_without_the_checklist_keeps_the_case_limited(local):
    api, model, _ = local
    case = api.new_case(context=[])
    edited = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                    json={"expected_revision": case["revision"], "confirmed_context": [
                        {"kind": "age_years", "value": 40, "units": None, "origin": "user",
                         "profile_revision": None}]})
    assert edited["state"] == "limited"
    assert "edit" in api.case(case["id"])["allowed_actions"]


def test_other_limited_reasons_stay_final(local):
    """Unsupported scope and a failed generation are not corrected by an edit (409; a failed generation has its own
    retry)."""
    from conftest import NO_RED_FLAGS
    api, model, application = local
    ctx = application.state.ctx
    for reason in ("unsupported_scope", "no_reviewed_pathway", "generation_failed_recoverable"):
        case = api.new_case(context=[])
        with ctx.db.tx() as conn:
            conn.execute("UPDATE cases SET limited_reason=? WHERE id=?", (reason, case["id"]))
        r = api.req("PATCH", f"/cases/{case['id']}", json={"expected_revision": case["revision"],
                                                          "confirmed_context": [NO_RED_FLAGS]})
        assert r.status_code == 409 and r.json()["code"] == "STATE_CONFLICT", reason
        assert "edit" not in api.case(case["id"])["allowed_actions"]
