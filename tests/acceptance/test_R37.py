"""R37/R38 truthful runtime: mock mode is labeled; unmeasured timings stay null. M12."""
import pytest

REQUIREMENT = "R37"


def test_readiness_body_is_minimal(api):
    r = api.req("GET", "/health/ready")
    assert r.status_code == 200 and r.json() == {"readiness": "ready"}


def test_runtime_snapshot_labels_mock_and_has_no_fabricated_timing(presenter):
    snap = presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")
    assert snap["mode"] == "mock" and snap["model_manifest_id"] is None
    assert snap["timing_summary"]["sample_count"] == 0 and snap["timing_summary"]["total_ms"] is None


def test_measured_timing_after_mock_generation(api, presenter):
    api.start()
    case = api.new_case()
    api.to_guided(case["id"])
    snap = presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")
    assert snap["timing_summary"]["sample_count"] == 1 and snap["timing_summary"]["total_ms"] > 0
    controls = presenter.ok("GET", "/presenter/controls", 200, "ControlsResponse")
    assert all(item["status"] == "unverified" for item in controls["items"])


def test_events_are_content_free(app, api):
    api.start()
    api.new_case("UNIQUE-SENTINEL-SYMPTOM-TEXT")
    with app[0].state.ctx.db.read() as conn:
        rows = [tuple(r) for r in conn.execute("SELECT * FROM events").fetchall()]
    assert rows and "UNIQUE-SENTINEL" not in repr(rows)


# --- O03 scenario load and reset through the presenter gateway (M3.2, #24) -----------------------------------

def _patient_side(presenter):
    """The same browser on the patient gateway: same cookie jar, no presenter assertion."""
    from conftest import Api
    return Api(presenter.c)


def test_every_scenario_loads_and_continues_on_the_patient_site(app, presenter):
    import json
    from conftest import ROOT
    ids = list(json.loads((ROOT / "fixtures/scenarios.json").read_text())["scenarios"])
    ids = [s["id"] if isinstance(s, dict) else s for s in ids]
    assert ids == ["routine", "selfcare", "urgent", "unsupported", "nomatch", "failure"]
    for sid in ids:
        loaded = presenter.ok("POST", f"/presenter/scenarios/{sid}/load", 201, "ScenarioLoaded", key=True,
                              json={"reset": True})
        assert loaded["synthetic"] is True and loaded["scenario_id"] == sid
        patient = _patient_side(presenter)
        read = patient.ok("GET", f"/cases/{loaded['case_id']}", 200, "CaseReadResponse")
        assert read["case"]["id"] == loaded["case_id"]
        assert presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")["mode"] == "mock"  # presenter kept


def test_reset_is_observable_by_the_presenter_and_revokes_the_demo(app, presenter):
    loaded = presenter.ok("POST", "/presenter/scenarios/routine/load", 201, "ScenarioLoaded", key=True,
                          json={"reset": True})
    patient = _patient_side(presenter)
    assert patient.req("GET", f"/cases/{loaded['case_id']}").status_code == 200
    accepted = presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)
    job = presenter.wait_job(accepted["deletion_job_id"])
    assert job["status"] == "succeeded"
    assert patient.req("GET", f"/cases/{loaded['case_id']}").status_code == 401  # demo session revoked
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0


def test_failed_reset_blocks_loading_until_a_reset_succeeds(app, presenter, monkeypatch):
    from app.modules.operations import scenarios
    presenter.ok("POST", "/presenter/scenarios/routine/load", 201, "ScenarioLoaded", key=True, json={"reset": True})
    original = scenarios._purge

    def broken(ctx, case_ids):
        raise OSError("simulated storage failure")
    monkeypatch.setattr(scenarios, "_purge", broken)
    failed = presenter.wait_job(presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)[
        "deletion_job_id"])
    assert failed["status"] == "failed"
    blocked = presenter.req("POST", "/presenter/scenarios/selfcare/load", key=True, json={"reset": True})
    assert blocked.status_code == 503 and blocked.json()["code"] == "RESET_FAILED"
    monkeypatch.setattr(scenarios, "_purge", original)
    repaired = presenter.wait_job(presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)[
        "deletion_job_id"])
    assert repaired["status"] == "succeeded"
    presenter.ok("POST", "/presenter/scenarios/selfcare/load", 201, "ScenarioLoaded", key=True, json={"reset": True})


def test_runtime_fields_come_from_manifests_or_say_unverified(app, presenter, monkeypatch, tmp_path):
    """T-R37-S01: device, build and directory fields are read from their sources; absent ones are not invented."""
    import json
    from dataclasses import replace
    ctx = app[0].state.ctx
    inventory = json.loads(ctx.settings.device_inventory.read_text())["inventory_id"]
    directory = json.loads((ctx.settings.fixtures_dir / "providers.json").read_text())["snapshot_version"]
    monkeypatch.delenv("AWARECARE_APP_COMMIT", raising=False)
    snap = presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")
    assert (snap["device_inventory_id"], snap["directory_version"], snap["app_commit"]) == (inventory, directory, None)
    assert snap["mode"] == "mock" and snap["model_manifest_id"] is None and snap["corpus_version"] is None
    monkeypatch.setenv("AWARECARE_APP_COMMIT", "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setattr(ctx, "settings", replace(ctx.settings, device_inventory=tmp_path / "missing.json"))
    snap = presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")
    assert snap["app_commit"] == "0123456789abcdef0123456789abcdef01234567"
    assert snap["device_inventory_id"] == "unverified"


def test_readiness_reports_an_observed_storage_failure_and_stays_labelled_mock(app, api, presenter):
    """T-R37-S02: readiness follows the real condition of the data store; the runtime still says mock."""
    import os
    import pytest
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions, so the storage failure cannot be observed")
    data_dir = app[0].state.ctx.settings.data_dir
    assert api.req("GET", "/health/ready").json() == {"readiness": "ready"}
    data_dir.chmod(0o500)
    try:
        r = api.req("GET", "/health/ready")
        assert r.status_code == 503 and r.json() == {"readiness": "unavailable"}
        snap = presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")
        assert snap["readiness"] == "unavailable" and snap["mode"] == "mock"
    finally:
        data_dir.chmod(0o700)
    assert api.req("GET", "/health/ready").json() == {"readiness": "ready"}


# --- O03 scenarios in local mode (ADR-016, #113) ------------------------------------------------------------------

LOCAL_STATES = {"routine": ("intake", None), "selfcare": ("intake", None), "nomatch": ("intake", None),
                "urgent": ("urgent", 0), "unsupported": ("limited", 0)}


def test_local_mode_loads_each_live_scenario_with_its_synthetic_case_and_refuses_failure(local_presenter):
    """ADR-016: in local mode a scenario supplies only a synthetic concern and checklist answer; the case takes the
    patient gate (a ticked red flag is urgent; the scope branch is limited). `failure` would fake the AI: 404."""
    import json
    from conftest import ROOT, Api
    presenter, model, application = local_presenter
    fixtures = {s["id"]: s for s in json.loads((ROOT / "fixtures/scenarios.json").read_text())["scenarios"]}
    for sid, (state, slots) in LOCAL_STATES.items():
        loaded = presenter.ok("POST", f"/presenter/scenarios/{sid}/load", 201, "ScenarioLoaded", key=True,
                              json={"reset": True})
        assert loaded["synthetic"] is True and loaded["scenario_id"] == sid
        case = Api(presenter.c).ok("GET", f"/cases/{loaded['case_id']}", 200, "CaseReadResponse")["case"]
        assert case["state"] == state, sid
        assert case["concern"] == fixtures[sid]["local_mode"]["concern"]
        checklist = [f for f in case["confirmed_context"] if f["kind"] == "red_flags"]
        assert [f["value"] for f in checklist] == [fixtures[sid]["local_mode"]["red_flags"]]
        if slots is not None:
            assert case["issued_slots"] == slots
        assert presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")["mode"] == "local"
    refused = presenter.req("POST", "/presenter/scenarios/failure/load", key=True, json={"reset": True})
    assert refused.status_code == 404
    assert [c for c in model.calls if c["task"] == "guidance"] == []  # loading never asks the model


def test_a_loaded_local_scenario_continues_live_on_the_patient_site(local_presenter):
    """ADR-016: after loading, the reviewed questions and the local model run as for any patient case; the result
    is the model's guidance with labeled explanations, not a scripted fixture outcome."""
    from conftest import Api
    presenter, model, _ = local_presenter
    loaded = presenter.ok("POST", "/presenter/scenarios/routine/load", 201, "ScenarioLoaded", key=True,
                          json={"reset": True})
    patient = Api(presenter.c)
    job = patient.to_guided(loaded["case_id"])
    assert job["status"] == "succeeded", job
    g = patient.ok("GET", f"/cases/{loaded['case_id']}/guidance", 200, "Guidance")
    assert g["urgency"]["rule_version"] == "general-adult-4" and g["model_manifest_id"] == "test-model@local-test"
    assert not any("MOCK_SCENARIO" in code for code in g["urgency"]["reason_codes"])
    assert [c["validation_status"] for c in g["possible_explanations"]] == ["general_knowledge"]
    [call] = [c for c in model.calls if c["task"] == "guidance"]
    assert call["snapshot"]["case"]["concern"].startswith("Recurring headaches after long workdays")
    assert call["snapshot"]["case"]["confirmed_facts"][0]["question"] == "Urgent warning signs checklist"


def test_local_reset_removes_the_loaded_demo(local_presenter):
    from conftest import Api
    presenter, _, _ = local_presenter
    loaded = presenter.ok("POST", "/presenter/scenarios/selfcare/load", 201, "ScenarioLoaded", key=True,
                          json={"reset": True})
    accepted = presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)
    assert presenter.wait_job(accepted["deletion_job_id"])["status"] == "succeeded"
    assert Api(presenter.c).req("GET", f"/cases/{loaded['case_id']}").status_code == 401


def test_presenter_actions_are_audited_with_the_presenter_actor(app, presenter):
    """#156 (ADR-005 rule 5): loading a scenario and resetting write content-free events with the presenter's actor
    ID; patient events carry none."""
    presenter.ok("POST", "/presenter/scenarios/routine/load", 201, "ScenarioLoaded", key=True, json={"reset": True})
    accepted = presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)
    assert presenter.wait_job(accepted["deletion_job_id"])["status"] == "succeeded"
    with app[0].state.ctx.db.read() as conn:
        actor = conn.execute("SELECT actor_id FROM sessions WHERE role='presenter'").fetchone()["actor_id"]
        rows = conn.execute("SELECT kind, operation_id, status, actor_ref FROM events WHERE actor_ref IS NOT NULL").fetchall()
        audited = {(r["kind"], r["operation_id"], r["status"]) for r in rows}
        assert {r["actor_ref"] for r in rows} == {actor}
        assert {("scenario_loaded", "loadScenario", "succeeded"), ("reset_completed", "loadScenario", "succeeded"),
                ("reset_requested", "resetDemo", "running"), ("reset_completed", "resetDemo", "succeeded")} <= audited
        assert conn.execute("SELECT COUNT(*) FROM events WHERE kind='case_created' AND actor_ref IS NOT NULL").fetchone()[0] == 0


def test_a_loaded_scenario_reports_the_effective_session_expiry(presenter):
    """#269: ScenarioLoaded reported the 8-hour absolute expiry; the session really ends after 30 idle minutes."""
    from datetime import datetime, timedelta
    loaded = presenter.ok("POST", "/presenter/scenarios/routine/load", 201, "ScenarioLoaded", key=True,
                          json={"reset": True})
    s = loaded["session"]

    def at(ts):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert at(s["expires_at"]) - at(s["last_seen_at"]) == timedelta(minutes=30)


# --- #315/#316: handoff path, coexisting demos and quick demos prepared ahead of time (CHG-DEV-API-002) ----------

def _load(presenter, sid: str, *, reset: bool, prepare: str | None = None, status: int = 201):
    body = {"reset": reset} if prepare is None else {"reset": reset, "prepare": prepare}
    return presenter.ok("POST", f"/presenter/scenarios/{sid}/load", status, "ScenarioLoaded" if status == 201 else None,
                        key=True, json=body)


def _fixtures():
    import json
    from conftest import ROOT
    return {s["id"]: s for s in json.loads((ROOT / "fixtures/scenarios.json").read_text())["scenarios"]}


def _current_search(app, case_id: str) -> dict | None:
    import json
    with app.state.ctx.db.read() as conn:
        row = conn.execute("SELECT result_json FROM provider_searches WHERE case_id=? AND current=1",
                           (case_id,)).fetchone()
    return json.loads(row["result_json"]) if row else None


def test_a_load_names_the_case_state_and_the_patient_screen_to_open(presenter):
    """#315: ScenarioLoaded says where the patient tab opens, so O03 needs no trip through History."""
    expected = {"routine": ("intake", "/questions"), "urgent": ("urgent", "/urgent"),
                "unsupported": ("limited", None)}
    for sid, (state, suffix) in expected.items():
        loaded = _load(presenter, sid, reset=True)
        assert loaded["state"] == state and loaded["prepare_job_id"] is None
        path = f"/app/cases/{loaded['case_id']}{suffix}" if suffix else "/app/limits"
        assert loaded["next_path"] == path, sid


def test_reset_false_keeps_the_earlier_demo_cases_under_one_patient_session(app, presenter):
    """#316: loading with reset=false adds the case to the presenter's live demo patient; History lists both."""
    first = _load(presenter, "routine", reset=True)
    second = _load(presenter, "urgent", reset=False)
    assert first["session"]["actor_id"] == second["session"]["actor_id"]
    patient = _patient_side(presenter)
    listed = patient.ok("GET", "/cases", 200, "CaseList")
    assert {c["id"] for c in listed["items"]} == {first["case_id"], second["case_id"]}
    for loaded in (first, second):
        assert patient.ok("GET", f"/cases/{loaded['case_id']}", 200, "CaseReadResponse")["case"]["id"] == \
            loaded["case_id"]
    # reset=true still starts afresh: both earlier cases are removed.
    third = _load(presenter, "selfcare", reset=True)
    assert third["session"]["actor_id"] != first["session"]["actor_id"]
    with app[0].state.ctx.db.read() as conn:
        assert {r["id"] for r in conn.execute("SELECT id FROM cases").fetchall()} == {third["case_id"]}


def test_reset_false_without_a_live_demo_creates_one_and_a_failed_reset_still_blocks(app, presenter, monkeypatch):
    from app.modules.operations import scenarios
    loaded = _load(presenter, "routine", reset=False)
    assert _patient_side(presenter).req("GET", f"/cases/{loaded['case_id']}").status_code == 200
    monkeypatch.setattr(scenarios, "_purge", lambda ctx, ids: (_ for _ in ()).throw(OSError("simulated")))
    failed = presenter.wait_job(presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)[
        "deletion_job_id"])
    assert failed["status"] == "failed"
    blocked = presenter.req("POST", "/presenter/scenarios/urgent/load", key=True, json={"reset": False})
    assert blocked.status_code == 503 and blocked.json()["code"] == "RESET_FAILED"


def test_the_request_rejects_a_non_boolean_reset_and_an_unknown_prepare(presenter):
    for body in ({"reset": "true"}, {"reset": True, "prepare": "skip"}, {}, {"reset": True, "extra": 1}):
        assert presenter.req("POST", "/presenter/scenarios/routine/load", key=True, json=body).status_code == 422


def test_prepare_result_in_mock_mode_reaches_guidance_with_the_scenario_answers(app, presenter):
    """#316: the server answers the questions with the fixture's synthetic answers, confirms the review and runs the
    (scripted, mock-mode) guidance as the demo patient; the routine result also has a doctor search."""
    quick = _fixtures()["routine"]["local_mode"]["quick"]
    loaded = _load(presenter, "routine", reset=True, prepare="result")
    assert loaded["state"] == "intake" and loaded["next_path"] == f"/app/cases/{loaded['case_id']}/guidance"
    job = presenter.wait_job(loaded["prepare_job_id"])
    assert (job["status"], job["kind"], job["case_id"], job["result_type"]) == (
        "succeeded", "scenario_prepare", None, "prepare_receipt")
    patient = _patient_side(presenter)
    read = patient.ok("GET", f"/cases/{loaded['case_id']}", 200, "CaseReadResponse")
    assert read["case"]["state"] == "guided" and read["case"]["issued_slots"] == 10
    answers = {f["kind"]: f["value"] for f in read["case"]["confirmed_context"] if f["kind"].startswith("answer:")}
    assert answers["answer:Q01"] == "More than a month ago" and answers["answer:Q03"] == quick["answers"]["Q03"]
    assert answers["answer:Q04"] == ["After long screen sessions"] and answers["answer:Q05"] == quick["answers"]["Q05"]
    g = patient.ok("GET", f"/cases/{loaded['case_id']}/guidance", 200, "Guidance")
    assert g["model_manifest_id"] == "mock-fixture-adapter-1"  # mock mode keeps its scripted, labelled outcome
    search = _current_search(app[0], loaded["case_id"])
    assert search and [m for m in search["matches"] if m["eligible"]] and search["no_match_reason"] is None


def test_prepared_nomatch_has_a_strict_plan_search_with_no_match(app, presenter):
    loaded = _load(presenter, "nomatch", reset=True, prepare="result")
    assert loaded["next_path"] == f"/app/cases/{loaded['case_id']}/doctors?preset=strict-plan"
    assert presenter.wait_job(loaded["prepare_job_id"])["status"] == "succeeded"
    search = _current_search(app[0], loaded["case_id"])
    assert search["no_match_reason"] and not [m for m in search["matches"] if m["eligible"]]
    assert [s["field"] for s in search["suggested_filter_changes"]] == ["required_verified_plan"]


def test_prepared_demos_coexist_and_reset_removes_them_all(app, presenter):
    ids = []
    for index, sid in enumerate(["urgent", "unsupported", "routine", "selfcare", "nomatch"]):
        loaded = _load(presenter, sid, reset=index == 0, prepare="result")
        if loaded["prepare_job_id"]:
            assert presenter.wait_job(loaded["prepare_job_id"])["status"] == "succeeded", sid
        ids.append(loaded["case_id"])
    patient = _patient_side(presenter)
    states = {c["id"]: c["state"] for c in patient.ok("GET", "/cases", 200, "CaseList")["items"]}
    assert [states[i] for i in ids] == ["urgent", "limited", "guided", "guided", "guided"]
    accepted = presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)
    assert presenter.wait_job(accepted["deletion_job_id"])["status"] == "succeeded"
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0


def test_a_replayed_prepare_load_returns_the_same_job_and_one_case(app, presenter):
    key = "6f0c8e8e-0000-4000-8000-000000000316"
    first = presenter.ok("POST", "/presenter/scenarios/selfcare/load", 201, "ScenarioLoaded",
                         headers={"Idempotency-Key": key}, json={"reset": True, "prepare": "result"})
    again = presenter.ok("POST", "/presenter/scenarios/selfcare/load", 201, "ScenarioLoaded",
                         headers={"Idempotency-Key": key}, json={"reset": True, "prepare": "result"})
    assert again["prepare_job_id"] == first["prepare_job_id"] and again["case_id"] == first["case_id"]
    presenter.wait_job(first["prepare_job_id"])
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind='scenario_prepare'").fetchone()[0] == 1


def test_the_presenter_reads_only_the_prepare_status_never_patient_content(app, presenter):
    """#316 least privilege: the presenter follows a content-free job; the case, the guidance and the patient's
    guidance job stay the demo patient's."""
    loaded = _load(presenter, "routine", reset=True, prepare="result")
    job = presenter.wait_job(loaded["prepare_job_id"])
    assert set(job) == {"id", "actor_id", "case_id", "input_revision", "kind", "status", "result_id", "error_code",
                        "error_detail", "error_reason", "created_at", "finished_at", "result_type", "stage"}
    assert job["case_id"] is None and job["input_revision"] is None and job["actor_id"] != loaded["session"]["actor_id"]
    cid = loaded["case_id"]
    assert presenter.req("GET", f"/cases/{cid}").status_code == 403
    assert presenter.req("GET", f"/cases/{cid}/guidance").status_code == 403
    with app[0].state.ctx.db.read() as conn:
        guidance_job = conn.execute("SELECT id FROM jobs WHERE kind='guidance' AND case_id=?", (cid,)).fetchone()["id"]
    assert presenter.req("GET", f"/jobs/{guidance_job}").status_code == 404
    # The patient side cannot read the presenter's job either.
    assert _patient_side(presenter).req("GET", f"/jobs/{loaded['prepare_job_id']}").status_code == 404


def test_a_busy_device_refuses_the_generation_and_the_case_stays_ready_to_generate(app, presenter, monkeypatch):
    from app.core.errors import ApiError
    ctx = app[0].state.ctx

    def busy():
        raise ApiError(429, "QUEUE_FULL", "The local runtime is busy. Try again shortly.", retryable=True)
    monkeypatch.setattr(ctx.jobs, "admit_generation", busy)
    loaded = _load(presenter, "routine", reset=True, prepare="result")
    job = presenter.wait_job(loaded["prepare_job_id"])
    assert (job["status"], job["error_code"]) == ("failed", "QUEUE_FULL")
    read = _patient_side(presenter).ok("GET", f"/cases/{loaded['case_id']}", 200, "CaseReadResponse")
    assert read["case"]["state"] == "reviewed" and "generate_guidance" in read["allowed_actions"]


def test_quick_answers_are_valid_answers_to_the_reviewed_questions():
    """The fixture's synthetic answers use the reviewed general-adult-4 template and choice IDs (and so the mock
    templates', which share them); the fixture pack stays a disabled synthetic pack."""
    import json
    from conftest import ROOT
    from app.modules.intake.schemas import AnswerWrite
    from app.modules.intake.service import _validate
    pack = json.loads((ROOT / "fixtures/scenarios.json").read_text())
    assert pack["data_mode"] == "synthetic" and pack["clinical_execution_enabled"] is False
    for folder in ("content/pathways/general-adult-4/questions.json", "fixtures/questions.json"):
        templates = {q["template_id"]: q for q in json.loads((ROOT / folder).read_text())["questions"]}
        for sid, scenario in _fixtures().items():
            for tid, value in scenario["local_mode"].get("quick", {}).get("answers", {}).items():
                _validate(templates[tid], AnswerWrite(expected_revision=1, status="answered", value=value))


def test_urgent_and_unsupported_are_at_their_result_at_once_without_a_model(local_presenter):
    presenter, model, application = local_presenter
    for sid, state, path in (("urgent", "urgent", "/urgent"), ("unsupported", "limited", None)):
        loaded = _load(presenter, sid, reset=True, prepare="result")
        assert loaded["state"] == state and loaded["prepare_job_id"] is None
        assert loaded["next_path"] == (f"/app/cases/{loaded['case_id']}{path}" if path else "/app/limits")
    assert model.calls == []
    with application.state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind IN ('guidance','scenario_prepare')").fetchone()[0] == 0


def test_local_prepare_runs_the_reviewed_questions_and_the_live_local_model(local_presenter):
    """#316 in local mode: the guidance is the local model's, validated as for any case; never a scripted outcome."""
    from conftest import Api
    presenter, model, application = local_presenter
    quick = _fixtures()["routine"]["local_mode"]["quick"]
    loaded = _load(presenter, "routine", reset=True, prepare="result")
    job = presenter.wait_job(loaded["prepare_job_id"], timeout=15)
    assert job["status"] == "succeeded", job
    patient = Api(presenter.c)
    g = patient.ok("GET", f"/cases/{loaded['case_id']}/guidance", 200, "Guidance")
    assert g["urgency"]["rule_version"] == "general-adult-4" and g["model_manifest_id"] == "test-model@local-test"
    assert not any("MOCK_SCENARIO" in code for code in g["urgency"]["reason_codes"])
    [call] = [c for c in model.calls if c["task"] == "guidance"]
    facts = {f["question"]: f["answer"] for f in call["snapshot"]["case"]["confirmed_facts"]}
    assert facts["What have you already tried?"] == quick["answers"]["Q05"]
    assert facts["How much does it affect your day?"] == 4
    assert _current_search(application, loaded["case_id"]) is not None  # the doctor result is ready too


def test_a_failing_local_model_leaves_the_case_recoverable_and_reports_the_failure(local_presenter):
    """Fail closed: invalid output twice (the single repair included) publishes nothing; the case is limited with a
    retry exactly as for a patient, and the presenter sees OUTPUT_VALIDATION_FAILED, not a substitute."""
    from conftest import Api
    presenter, model, application = local_presenter
    model.outputs = [{"not": "a draft"}, {"still": "not a draft"}]
    loaded = _load(presenter, "selfcare", reset=True, prepare="result")
    job = presenter.wait_job(loaded["prepare_job_id"], timeout=15)
    assert (job["status"], job["error_code"]) == ("failed", "OUTPUT_VALIDATION_FAILED")
    assert job["error_detail"] == ["1:schema@output", "2:schema@output"]  # #538: content-free, from the guidance job
    read = Api(presenter.c).ok("GET", f"/cases/{loaded['case_id']}", 200, "CaseReadResponse")
    assert read["case"]["state"] == "limited" and "retry" in read["allowed_actions"]
    assert Api(presenter.c).req("GET", f"/cases/{loaded['case_id']}/guidance").status_code == 404
    with application.state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM guidance").fetchone()[0] == 0


def test_prepare_actions_are_audited_with_the_presenter_actor_only(app, presenter):
    loaded = _load(presenter, "routine", reset=True, prepare="result")
    presenter.wait_job(loaded["prepare_job_id"])
    with app[0].state.ctx.db.read() as conn:
        actor = conn.execute("SELECT actor_id FROM sessions WHERE role='presenter'").fetchone()["actor_id"]
        prepared = conn.execute("SELECT actor_ref FROM events WHERE kind='scenario_prepared'").fetchall()
        assert [r["actor_ref"] for r in prepared] == [actor]
        # The patient-side steps are the ordinary patient events, with no presenter reference.
        assert conn.execute("SELECT COUNT(*) FROM events WHERE kind IN ('answer_saved','guidance_published') "
                            "AND actor_ref IS NOT NULL").fetchone()[0] == 0


def test_a_reset_during_preparation_cancels_it_and_removes_the_case(local_presenter):
    """A reset while the device is still generating: the prepare job ends cancelled (RESET), the late guidance is never
    published for a removed case, and no case is left."""
    import asyncio
    presenter, model, application = local_presenter
    original = model.generate_json

    async def slow(task, *args):
        if task == "guidance":
            await asyncio.sleep(1.0)
        return await original(task, *args)
    model.generate_json = slow
    loaded = _load(presenter, "routine", reset=True, prepare="result")
    import time
    deadline = time.time() + 5
    while time.time() < deadline:  # wait until the guidance job exists (the device is generating)
        with application.state.ctx.db.read() as conn:
            if conn.execute("SELECT 1 FROM jobs WHERE kind='guidance'").fetchone():
                break
        time.sleep(0.02)
    accepted = presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)
    assert presenter.wait_job(accepted["deletion_job_id"])["status"] == "succeeded"
    job = presenter.wait_job(loaded["prepare_job_id"], timeout=10)
    assert (job["status"], job["error_code"]) == ("cancelled", "RESET")
    time.sleep(1.2)  # the late generation finishes and finds no case
    with application.state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM guidance").fetchone()[0] == 0


# --- #358: one-click flows run live at the click (ADR-016 amendment 2, CHG-DEV-API-006) ---------------------------

def _written(presenter, sid: str = "urgent", *, key: str | None = None, prepare: str = "start", status: int = 201):
    headers = {"Idempotency-Key": key} if key else None
    r = presenter.req("POST", f"/presenter/scenarios/{sid}/load", key=key is None, headers=headers,
                      json={"reset": False, "prepare": prepare, "urgency_input": "written"})
    assert r.status_code == status, (r.status_code, r.text)
    return r.json()


def test_358_the_written_emergency_is_routed_to_urgent_help_by_the_device_ai_at_creation(local_presenter):
    """#358 Urgent warning sign: no ticked box; the device's red-flag screen reads the written concern and routes the
    case to urgent help when the case is created, exactly as for a patient who writes it (#153)."""
    import json
    from conftest import Api
    presenter, model, application = local_presenter
    model.screen = {"present": ["RF01"]}
    from conftest import validate
    loaded = _written(presenter)
    validate("ScenarioLoaded", loaded)
    assert loaded["state"] == "urgent" and loaded["prepare_job_id"] is None
    assert loaded["next_path"] == f"/app/cases/{loaded['case_id']}/urgent"
    [call] = model.calls
    assert call["task"] == "red_flag_screen"
    assert call["snapshot"]["person_words"] == [{"source": "concern",
                                                 "text": _fixtures()["urgent"]["local_mode"]["concern"]}]
    with application.state.ctx.db.read() as conn:
        case = conn.execute("SELECT * FROM cases WHERE id=?", (loaded["case_id"],)).fetchone()
        assert (case["state"], case["urgent_level"], json.loads(case["urgent_rule_ids"]), case["urgent_revision"]) == (
            "urgent", "emergency", ["RF01"], 1)
        fact = conn.execute("SELECT value_json FROM facts WHERE case_id=? AND kind='red_flags'",
                            (loaded["case_id"],)).fetchone()
        assert json.loads(fact["value_json"]) == []  # the checklist was answered "none of these apply"
        assert conn.execute("SELECT error_code FROM events WHERE kind='urgent_interrupt' AND "
                            "operation_id='loadScenario'").fetchone()["error_code"] == "RED_FLAG_DESCRIBED"
    assert Api(presenter.c).ok("GET", f"/cases/{loaded['case_id']}", 200, "CaseReadResponse")["case"]["state"] == \
        "urgent"


def test_358_when_the_device_ai_finds_no_warning_sign_the_case_stays_at_its_questions(local_presenter):
    """Nothing is substituted: without a match the written case is an ordinary case at its first question."""
    presenter, model, application = local_presenter
    loaded = _written(presenter)  # the scripted model's default screen: no red flag
    assert loaded["state"] == "intake" and loaded["next_path"].endswith("/questions")
    assert [c["task"] for c in model.calls] == ["red_flag_screen"]


def test_358_a_written_screen_that_cannot_run_fails_closed_and_creates_nothing(local_presenter):
    presenter, model, application = local_presenter
    model.screen = TimeoutError("the device did not answer")
    failed = _written(presenter, status=503)
    assert failed["code"] == "RED_FLAG_SCREEN_UNAVAILABLE" and failed["retryable"] is True
    with application.state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0


def test_358_a_written_flow_in_mock_mode_is_the_scripted_outcome_without_a_model(app, presenter):
    loaded = _written(presenter)
    assert loaded["state"] == "urgent" and loaded["next_path"].endswith("/urgent")
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT scenario_id FROM cases").fetchone()["scenario_id"] == "urgent"


def test_358_a_replayed_written_flow_returns_the_same_case_and_screens_once(local_presenter):
    import uuid
    presenter, model, application = local_presenter
    model.screen = {"present": ["RF01"]}
    key = str(uuid.uuid4())
    first, again = _written(presenter, key=key), _written(presenter, key=key)
    assert again["case_id"] == first["case_id"]
    assert [c["task"] for c in model.calls] == ["red_flag_screen"]
    # The same key with the checklist input is a different request.
    r = presenter.req("POST", "/presenter/scenarios/urgent/load", headers={"Idempotency-Key": key},
                      json={"reset": False, "prepare": "start"})
    assert r.status_code == 409 and r.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_358_the_one_click_flow_is_presenter_only_and_validated(app, api, presenter):
    body = {"reset": False, "prepare": "start", "urgency_input": "written"}
    api.start()  # a guest on the patient gateway
    r = api.req("POST", "/presenter/scenarios/urgent/load", key=True, json=body)
    assert r.status_code == 403 and r.json()["code"] == "PRESENTER_REQUIRED"
    # The presenter's own browser on the patient gateway (no gateway assertion) is not a presenter there either.
    assert _patient_side(presenter).req("POST", "/presenter/scenarios/urgent/load", key=True,
                                        json=body).status_code in (401, 403)
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0
    for body in ({"reset": False, "urgency_input": "typed"}, {"reset": False, "urgency_input": None}):
        assert presenter.req("POST", "/presenter/scenarios/urgent/load", key=True, json=body).status_code == 422
    # The deploy check's model-free probe (infra/deploy/flow_check.py, `quick-flows`): understood, then 404, no case.
    probe = presenter.req("POST", "/presenter/scenarios/not-a-scenario/load", key=True,
                          json={"reset": False, "prepare": "result", "urgency_input": "written"})
    assert probe.status_code == 404


def test_358_the_guidance_flows_run_live_on_the_local_model_and_join_the_live_demo(local_presenter):
    """Guidance from the local AI and Self-care guidance: reset=false, prepare=result at the click; the guidance is the
    device model's, never a scripted outcome, and the second run keeps the first case."""
    from conftest import Api
    presenter, model, application = local_presenter
    runs = [_load(presenter, sid, reset=False, prepare="result") for sid in ("routine", "selfcare")]
    for loaded in runs:
        assert presenter.wait_job(loaded["prepare_job_id"], timeout=15)["status"] == "succeeded"
        assert loaded["next_path"] == f"/app/cases/{loaded['case_id']}/guidance"
        g = Api(presenter.c).ok("GET", f"/cases/{loaded['case_id']}/guidance", 200, "Guidance")
        assert g["model_manifest_id"] == "test-model@local-test"
        assert not any("MOCK_SCENARIO" in code for code in g["urgency"]["reason_codes"])
    assert runs[0]["session"]["actor_id"] == runs[1]["session"]["actor_id"]
    assert len([c for c in model.calls if c["task"] == "guidance"]) == 2


# --- QA 2026-10-22 presenter findings (CHG-DEV-API-007): #396, #425, #426, #428, #429 --------------------------------

def _idle_out(app, role: str, minutes: int = 31) -> None:
    """Let every session of `role` go idle past the 30-minute limit (as the QA did in the mock DB)."""
    from datetime import timedelta
    from app.core.db import iso, utcnow
    with app[0].state.ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET last_seen_at=? WHERE role=?", (iso(utcnow() - timedelta(minutes=minutes)), role))


def _demo_actor_count(app) -> int:
    with app[0].state.ctx.db.read() as conn:
        return conn.execute("SELECT COUNT(*) FROM actors WHERE kind LIKE 'demo:%'").fetchone()[0]


def _rival(app):
    """A presenter in another browser on the same device (its own cookies and lineage)."""
    from fastapi.testclient import TestClient
    from conftest import Api
    rival = Api(TestClient(app[0]), presenter=True)
    rival.start()
    return rival


def test_396_reset_removes_the_demo_cases_of_an_earlier_presenter_session(app, presenter, other):
    """#396 (R-01): the presenter session ends while the demo patient session is still in use (30 idle minutes, the
    8-hour limit, or ended); a new presenter session in the same browser resets. Every earlier demo case of this
    browser's presenter is removed and the patient tab's session ends, as the Reset text says; a patient guest's own
    case and another presenter browser's demo are never touched."""
    other.start()
    guest_case = other.new_case()["id"]
    rival = _rival(app)
    rival_case = _load(rival, "unsupported", reset=False)["case_id"]
    quick = _load(presenter, "routine", reset=False, prepare="result")
    assert presenter.wait_job(quick["prepare_job_id"])["status"] == "succeeded"
    journey = _load(presenter, "urgent", reset=False)
    patient = _patient_side(presenter)
    listed = {c["id"] for c in patient.ok("GET", "/cases", 200, "CaseList")["items"]}
    assert listed == {quick["case_id"], journey["case_id"]}
    _idle_out(app, "presenter")  # the presenter sessions end; the demo patient sessions stay live
    assert presenter.req("GET", "/presenter/runtime").status_code == 401
    presenter.start()  # a new presenter session in the same browser: a new presenter actor, the same lineage
    job = presenter.wait_job(presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)[
        "deletion_job_id"])
    assert job["status"] == "succeeded"
    for case_id in (quick["case_id"], journey["case_id"]):
        assert patient.req("GET", f"/cases/{case_id}").status_code == 401  # the demo session ended with it
    assert patient.req("GET", "/cases").status_code == 401
    with app[0].state.ctx.db.read() as conn:
        assert {r["id"] for r in conn.execute("SELECT id FROM cases").fetchall()} == {guest_case, rival_case}
    assert other.ok("GET", f"/cases/{guest_case}", 200, "CaseReadResponse")["case"]["id"] == guest_case
    assert _patient_side(rival).ok("GET", f"/cases/{rival_case}", 200, "CaseReadResponse")["case"]["id"] == rival_case


def test_396_reset_after_this_browser_ended_its_presenter_session(app, presenter):
    """#396, as reproduced on the Nano: the browser's own presenter session is ended (DELETE /sessions/current through
    the presenter gateway, which removes its presenter actor); the next presenter session's reset still removes the
    earlier demo."""
    loaded = _load(presenter, "selfcare", reset=False)
    presenter.ok("DELETE", "/sessions/current", 202, "DeletionAccepted")
    presenter.start()
    assert presenter.wait_job(presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)[
        "deletion_job_id"])["status"] == "succeeded"
    assert _patient_side(presenter).req("GET", f"/cases/{loaded['case_id']}").status_code == 401
    assert _demo_actor_count(app) == 0


def test_396_the_lineage_cookie_is_presenter_only_http_only_and_strict(app, api, presenter):
    """The browser lineage that ties presenter sessions together is an HttpOnly, SameSite=Strict cookie set only
    through the presenter gateway; a patient session never gets one, and only its hash is stored."""
    from fastapi.testclient import TestClient
    from conftest import Api
    fresh = Api(TestClient(app[0]), presenter=True)
    r = fresh.req("POST", "/sessions", key=True, json={"mode": "guest", "consent_version": "aware-care-demo-consent-1.0",
                                                       "adult_eligible": True})
    assert r.status_code == 201
    cookie = next(c for c in r.headers.get_list("set-cookie") if c.startswith("awarecare_presenter_lineage="))
    flags = {part.strip().lower() for part in cookie.split(";")[1:]}
    assert {"httponly", "samesite=strict", "path=/"} <= flags and any(f.startswith("max-age=") for f in flags)
    token = cookie.split(";")[0].split("=", 1)[1]
    with app[0].state.ctx.db.read() as conn:
        stored = [r["lineage_hash"] for r in conn.execute("SELECT lineage_hash FROM presenter_lineages").fetchall()]
    assert token not in stored and len(stored) == 2  # this browser's and the `presenter` fixture's, as hashes
    patient = api.req("POST", "/sessions", key=True, json={"mode": "guest", "consent_version": "aware-care-demo-consent-1.0",
                                                           "adult_eligible": True})
    assert patient.status_code == 201
    assert not any(c.startswith("awarecare_presenter_lineage=") for c in patient.headers.get_list("set-cookie"))


def test_396_a_reset_also_cancels_a_quick_flow_of_an_earlier_presenter_session(app, presenter, monkeypatch):
    """Delayed work cannot restore cleared data: a quick flow still running for an ended presenter session ends with
    the reset of the next one (its late steps find no case)."""
    import threading
    from app.modules.operations import scenarios
    gate = threading.Event()
    original = scenarios._prepare_result

    def held(*args, **kwargs):
        gate.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(scenarios, "_prepare_result", held)
    loaded = _load(presenter, "selfcare", reset=False, prepare="result")
    _idle_out(app, "presenter")
    presenter.start()
    assert presenter.wait_job(presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)[
        "deletion_job_id"])["status"] == "succeeded"
    gate.set()
    with app[0].state.ctx.db.read() as conn:
        prepare = conn.execute("SELECT status, error_code FROM jobs WHERE id=?", (loaded["prepare_job_id"],)).fetchone()
        assert (prepare["status"], prepare["error_code"]) == ("cancelled", "RESET")
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0


def test_425_a_failed_reset_blocks_and_is_reported_to_every_later_presenter_session(app, presenter, monkeypatch):
    """#425 (R-05): the server is the source of truth for the blocked state. getRuntime reports the device's last
    reset to every presenter view (after a reload, in a second tab, after a new presenter session), and a failed reset
    of an earlier presenter session still blocks a new demo until a reset succeeds."""
    from app.modules.operations import scenarios
    assert presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")["demo"] == {
        "reset_status": "none", "reset_finished_at": None, "live_case_ids": []}
    _load(presenter, "routine", reset=False)
    monkeypatch.setattr(scenarios, "_purge", lambda ctx, ids: (_ for _ in ()).throw(OSError("simulated")))
    failed = presenter.wait_job(presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)[
        "deletion_job_id"])
    assert failed["status"] == "failed"
    assert presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")["demo"]["reset_status"] == "failed"
    _idle_out(app, "presenter")
    presenter.start()  # a new presenter session in the same browser
    demo = presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")["demo"]
    assert demo["reset_status"] == "failed" and demo["reset_finished_at"]
    for body in ({"reset": False}, {"reset": False, "prepare": "result"}):
        blocked = presenter.req("POST", "/presenter/scenarios/selfcare/load", key=True, json=body)
        assert blocked.status_code == 503 and blocked.json()["code"] == "RESET_FAILED"
    # Another presenter browser has its own demos and its own last reset: not blocked by this one.
    rival = _rival(app)
    assert rival.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")["demo"]["reset_status"] == "none"
    _load(rival, "urgent", reset=False)
    monkeypatch.undo()
    assert presenter.wait_job(presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)[
        "deletion_job_id"])["status"] == "succeeded"
    assert presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")["demo"]["reset_status"] == "succeeded"
    _load(presenter, "selfcare", reset=False)


def test_426_the_presenter_learns_which_demo_cases_the_patient_tab_can_still_open(app, presenter, other):
    """#426 (R-06): a Show must not land on the consent page after the demo session ended. getRuntime lists the demo
    cases whose demo patient still has a live session (IDs only); never a patient guest's case."""
    other.start()
    guest_case = other.new_case()["id"]
    rival_case = _load(_rival(app), "selfcare", reset=False)["case_id"]
    first = _load(presenter, "urgent", reset=False)
    second = _load(presenter, "unsupported", reset=False)
    live = presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")["demo"]["live_case_ids"]
    assert set(live) == {first["case_id"], second["case_id"]}  # never a guest's case or another presenter's
    assert guest_case not in live and rival_case not in live
    _idle_out(app, "patient")  # 30 minutes without patient-tab activity: the demo sessions end
    assert _patient_side(presenter).req("GET", f"/cases/{first['case_id']}").status_code == 401
    assert presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")["demo"]["live_case_ids"] == []
    third = _load(presenter, "urgent", reset=False)  # a new demo patient starts
    assert presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")["demo"]["live_case_ids"] == [
        third["case_id"]]
    presenter.wait_job(presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)["deletion_job_id"])
    assert presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")["demo"]["live_case_ids"] == []


def test_428_mock_timings_report_no_inference_time(api, presenter):
    """#428 (R-08, R38): mock mode runs no model, so the runtime reports no inference time; the scripted pipeline's
    own durations stay (and O01 labels them scripted)."""
    api.start()
    api.to_guided(api.new_case()["id"])
    snap = presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")
    timing = snap["timing_summary"]
    assert snap["mode"] == "mock" and timing["sample_count"] == 1
    assert timing["inference_ms"] is None and timing["total_ms"] is not None
    assert snap["timings_latest_at"] is not None


def test_429_runtime_values_carry_their_source_and_observation_time(app, presenter, local_presenter):
    """#429 (R-09, R37): observed values say when they were observed, the device inventory when it was recorded, and
    in local mode the serving runtime's versions come from the model manifest with its last passed qualification."""
    import json
    from datetime import UTC, datetime
    ctx = app[0].state.ctx
    inventory = json.loads(ctx.settings.device_inventory.read_text())
    manifest = json.loads(ctx.settings.model_manifest.read_text())
    mock = presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")
    observed = datetime.fromisoformat(mock["observed_at"].replace("Z", "+00:00"))
    assert abs((datetime.now(UTC) - observed).total_seconds()) < 60
    assert (mock["device_inventory_id"], mock["device_inventory_observed_on"]) == (
        inventory["inventory_id"], inventory["observed_on"])
    assert mock["runtime_version"] is None and mock["runtime_qualified_on"] is None  # mock mode: no runtime claimed
    local, _, _ = local_presenter
    snap = local.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")
    runtime = manifest["runtime"]
    assert snap["runtime_version"] == (f"ZRT {runtime['zrt_version_observed']} ({runtime['internal_engine']} "
                                       f"{runtime['internal_engine_version']})")
    passed = [r for r in manifest["qualification"]["runtime_requalifications"] if r["result"].startswith("PASSED")]
    assert snap["runtime_qualified_on"] == passed[-1]["date"]


def test_429_each_device_inventory_matches_the_runtime_its_model_manifest_records():
    """#429 (R-09): the inventory O01 cites must describe the device it runs on. Each device's inventory records the
    ZRT version and snap revision its model manifest was qualified on (the Nano's inventory said ZRT 0.39.0, snap
    x3, 'No models served' while the device ran 0.43.0, x4, serving the selected model)."""
    import json
    from conftest import ROOT
    for folder in ("infra", "infra/fury"):
        inventory = json.loads((ROOT / folder / "device-inventory.json").read_text())
        manifest = json.loads((ROOT / folder / "model-manifest.json").read_text())
        zrt, runtime = inventory["software"]["zrt"], manifest["runtime"]
        assert (zrt["version"], zrt["snap_revision"]) == (
            runtime["zrt_version_observed"], runtime["zrt_snap_revision_observed"]), folder
        assert zrt.get("internal_vllm_version") == runtime["internal_engine_version"], folder
        assert inventory["observed_on"] >= runtime_observed_date(runtime), folder


def runtime_observed_date(runtime: dict) -> str:
    """The latest ISO date named in the manifest's runtime note (when the running ZRT was last observed)."""
    import re
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", runtime.get("note", ""))
    return max(dates) if dates else "0000-00-00"


# --- #435 (S-06, QA 2026-10-22): concurrent duplicate scenario loads serialize -------------------------------------


@pytest.mark.parametrize("body", [{"reset": False}, {"reset": False, "prepare": "result"}, {"reset": True}],
                         ids=["add", "one-click", "reset"])
def test_435_concurrent_duplicate_loads_with_one_key_all_return_the_original_201(app, monkeypatch, body):
    """QA: 3-4 identical loads at once with one Idempotency-Key gave 500 (IntegrityError on the second store) or 409
    RESET_PENDING. Every duplicate must return the original 201 body, and one case is created. The window between the
    load's two transactions is widened here so the race always happens."""
    import time
    import uuid
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from conftest import Api
    from app.modules.operations import scenarios
    original = scenarios.quick_block

    def slow_quick_block(scenario):
        time.sleep(0.3)
        return original(scenario)

    monkeypatch.setattr(scenarios, "quick_block", slow_quick_block)
    presenter = Api(TestClient(app[0], raise_server_exceptions=False), presenter=True)
    presenter.start()
    key = str(uuid.uuid4())

    def load(_):
        r = presenter.c.post("/api/v1/presenter/scenarios/routine/load", json=body,
                             headers={**presenter.headers(), "Idempotency-Key": key})
        return r.status_code, r.json()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(load, range(4)))
    assert [status for status, _ in results] == [201] * 4, results
    bodies = [b for _, b in results]
    assert all(b == bodies[0] for b in bodies)
    if body.get("prepare") == "result":
        presenter.wait_job(bodies[0]["prepare_job_id"])
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind='reset'").fetchone()[0] == int(body["reset"])
    # A later sequential replay still returns the same 201 body.
    status, again = load(0)
    assert status == 201 and again["case_id"] == bodies[0]["case_id"]


def test_a_failed_self_care_quick_demo_tells_the_presenter_which_rule_rejected_which_statement(local_presenter):
    """#538 (app-01): the Self-care Quick flow failed 5 of 5 times on the Nano with only OUTPUT_VALIDATION_FAILED to go
    on. The prepare job now carries the guidance job's content-free reasons: rule, reviewer category and place."""
    presenter, model, application = local_presenter
    model.override = {"claims": [
        {"text": "You have no urgent warning signs.", "kind": "case_fact", "fact_ids": [], "evidence_ids": []},
        {"text": "Neck stiffness is often linked to sleeping position.", "kind": "clinical", "fact_ids": [],
         "evidence_ids": []}]}
    model.unsafe_phrases, model.unsafe_category = ("You have no urgent",), "rules_out_risk"
    loaded = _load(presenter, "selfcare", reset=True, prepare="result")
    job = presenter.wait_job(loaded["prepare_job_id"], timeout=15)
    assert (job["status"], job["error_code"]) == ("failed", "OUTPUT_VALIDATION_FAILED")
    assert job["error_detail"] == ["1:prohibited_certainty/rules_out_risk@claims[0].text",
                                   "2:prohibited_certainty/rules_out_risk@claims[0].text"]
    [repair] = [c for c in model.calls if c["task"] == "guidance" and c["snapshot"].get("repair")]
    assert any(e.startswith('prohibited_certainty: claims[0].text says "you have no urgent warning signs", judged to '
                            "rule out a risk") for e in repair["snapshot"]["repair"]["previous_output_errors"])


def test_548_a_running_quick_demo_reports_its_real_step(app, presenter):
    """#548: the presenter's progress dialog shows the step a quick demo is on, from real state only: the prepare job
    before its guidance job exists, the guidance job's queue, then the device's model calls since that job started
    (red-flag screen, draft, repair draft, checks); null once the job has ended, and for every other job."""
    import time as _time
    import uuid as _uuid
    from app.core.db import iso, utcnow
    from app.modules.operations import scenarios
    ctx = app[0].state.ctx
    with ctx.db.read() as conn:
        actor = conn.execute("SELECT actor_id FROM sessions WHERE role='presenter'").fetchone()["actor_id"]
    prep, guid = str(_uuid.uuid4()), str(_uuid.uuid4())
    with ctx.db.tx() as conn:
        for jid, kind, owner, status in ((prep, "scenario_prepare", actor, "running"),
                                         (guid, "guidance", str(_uuid.uuid4()), "queued")):
            conn.execute("INSERT INTO jobs (id, actor_id, kind, status, created_at) VALUES (?,?,?,?,?)",
                         (jid, owner, kind, status, iso(utcnow())))
    stage = lambda: presenter.ok("GET", f"/jobs/{prep}", 200, "Job")["stage"]  # noqa: E731
    assert stage() == "preparing"
    scenarios._PREPARE_GUIDANCE[prep] = guid
    try:
        assert stage() == "queued"
        with ctx.db.tx() as conn:
            conn.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?", (iso(utcnow()), guid))
        calls = ctx.runtime._calls
        calls.clear()
        now = _time.time()
        calls.append({"task": "guidance", "started": now - 600, "ended": now - 590, "outcome": "ok"})  # an older job
        assert stage() == "preparing"
        steps = [({"task": "red_flag_screen", "started": now, "ended": None}, "screening"),
                 ({"task": "guidance", "started": now + 1, "ended": None}, "writing"),
                 (None, "checking"),  # the draft is in: the validator checks it
                 ({"task": "certainty_review", "started": now + 2, "ended": None}, "checking"),
                 ({"task": "guidance", "started": now + 3, "ended": None}, "rewriting")]
        for call, expected in steps:
            if calls and calls[-1]["ended"] is None:
                calls[-1]["ended"] = calls[-1]["started"] + 0.5
            if call:
                calls.append({**call, "outcome": None})
            assert stage() == expected, (call, expected)
        with ctx.db.tx() as conn:
            conn.execute("UPDATE jobs SET status='succeeded' WHERE id=?", (guid,))
        assert stage() == "finishing"
        with ctx.db.tx() as conn:
            conn.execute("UPDATE jobs SET status='succeeded', finished_at=? WHERE id=?", (iso(utcnow()), prep))
        assert stage() is None
    finally:
        scenarios._PREPARE_GUIDANCE.pop(prep, None)
    # A quick demo that ran end to end reports no step once it is done.
    loaded = _load(presenter, "routine", reset=True, prepare="result")
    assert presenter.wait_job(loaded["prepare_job_id"])["stage"] is None


def test_567_the_doctor_search_after_the_guidance_reports_finishing(app, presenter, monkeypatch):
    """#567: after the guidance job ends, the quick demo's doctor search is its last step ("finishing"); the stage fell
    back to "preparing" (the dialog's first step) because the guidance job was forgotten before the search ran."""
    from app.modules.operations import scenarios
    from app.modules.providers import service as providers
    ctx = app[0].state.ctx
    seen: list[str | None] = []
    search = providers.search

    def observed(*args, **kwargs):
        with ctx.db.read() as conn:
            job = conn.execute("SELECT * FROM jobs WHERE kind='scenario_prepare' AND status='running'").fetchone()
        seen.append(scenarios.prepare_stage(ctx, dict(job)) if job else "no running prepare job")
        return search(*args, **kwargs)

    monkeypatch.setattr(providers, "search", observed)
    loaded = _load(presenter, "routine", reset=True, prepare="result")
    assert presenter.wait_job(loaded["prepare_job_id"])["status"] == "succeeded"
    assert seen == ["finishing"]
    assert loaded["prepare_job_id"] not in scenarios._PREPARE_GUIDANCE  # forgotten once the prepare job ends

def test_the_presenter_gets_the_rejection_reason_in_plain_words(local_presenter):
    """#550: the failure message names what was rejected and where, in plain words, from the content-free reasons
    only (Job.error_reason; Track C's modal and logs view show it)."""
    presenter, model, application = local_presenter
    model.override = {"claims": [
        {"text": "You have no urgent warning signs.", "kind": "case_fact", "fact_ids": [], "evidence_ids": []},
        {"text": "Neck stiffness is often linked to sleeping position.", "kind": "clinical", "fact_ids": [],
         "evidence_ids": []}]}
    model.unsafe_phrases, model.unsafe_category = ("You have no urgent",), "rules_out_risk"
    loaded = _load(presenter, "selfcare", reset=True, prepare="result")
    job = presenter.wait_job(loaded["prepare_job_id"], timeout=15)
    assert job["error_reason"] == (
        "The first draft was rejected: a statement was judged to rule out a risk (a stated fact or explanation). "
        "The repair was rejected: a statement was judged to rule out a risk (a stated fact or explanation). "
        "Nothing was published.")
    assert "warning signs" not in job["error_reason"] and "neck" not in job["error_reason"].lower()
    from conftest import validate
    validate("Job", job)


def test_a_thinking_models_empty_screen_answer_says_why_instead_of_only_guidance_failed(local_presenter):
    """#550: with thinking left on by the server, the Nano's red-flag screen answered `{}` (recorded in
    evidence/clinical-review/2026-10-26-selfcare-speed/), and the Quick flow showed only "the guidance failed on the
    device" with no detail. The jobs now carry the screen's content-free cause and say it in plain words."""
    from test_R25 import speed_nano
    presenter, model, application = local_presenter
    model.screen = speed_nano("thinking_screen")["output"]
    assert model.screen == {}
    loaded = _load(presenter, "selfcare", reset=True, prepare="result")
    job = presenter.wait_job(loaded["prepare_job_id"], timeout=15)
    assert (job["status"], job["error_code"]) == ("failed", "GENERATION_FAILED")
    assert job["error_detail"] == ["0:RED_FLAG_SCREEN_INVALID/invalid_output"]
    assert job["error_reason"].startswith("The warning-sign check before the draft failed: the AI answered something "
                                          "other than a list of warning signs")
    assert not [c for c in model.calls if c["task"] == "guidance"]  # fail closed, nothing substituted
    from conftest import validate
    validate("Job", job)
    with application.state.ctx.db.read() as conn:
        [guidance] = conn.execute("SELECT error_code, error_detail FROM jobs WHERE kind='guidance'").fetchall()
    assert guidance["error_code"] == "RED_FLAG_SCREEN_INVALID"


# --- #588 (QA 2026-10-26, F08): O01's timing medians are the mathematical median ------------------------------------


def _timing_jobs(db, mode: str, samples: list[tuple[float, float | None, float, float]]) -> None:
    """Succeeded guidance jobs of `mode` with (queue, inference, validation, total) milliseconds."""
    import uuid
    with db.tx() as conn:
        for minute, (queue, inference, validation, total) in enumerate(samples):
            conn.execute("INSERT INTO jobs (id, actor_id, kind, status, created_at, finished_at, queue_ms, inference_ms, "
                         "validation_ms, total_ms, mode) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (str(uuid.uuid4()), "synthetic", "guidance", "succeeded", f"2026-10-26T10:{minute:02d}:00Z",
                          f"2026-10-26T10:{minute:02d}:30Z", queue, inference, validation, total, mode))


def test_588_the_timing_median_of_an_even_sample_count_is_the_mean_of_the_middle_two(app, presenter, local_presenter):
    """#588 (R38): the runtime timing card's median of [2, 10, 22, 98] ms is 16 ms and of [10, 20] ms 15 ms (before:
    the upper middle value, 22 and 20). Odd counts keep the middle value, no samples stay null, each mode counts only
    its own jobs, and mock mode still reports no inference time."""
    from app.modules.operations.service import timing_summary
    db = app[0].state.ctx.db
    empty = timing_summary(db, "local")
    assert empty == {"sample_count": 0, "queue_ms": None, "retrieval_ms": None, "inference_ms": None,
                     "validation_ms": None, "total_ms": None}
    _timing_jobs(db, "local", [(10, 10, 10, 10), (20, 20, 20, 20)])
    two = timing_summary(db, "local")
    assert (two["sample_count"], two["queue_ms"], two["inference_ms"], two["validation_ms"], two["total_ms"]) == (
        2, 15, 15, 15, 15)
    _timing_jobs(db, "local", [(2, 2, 2, 2), (98, 98, 98, 98)])
    four = timing_summary(db, "local")  # [2, 10, 20, 98]
    assert (four["sample_count"], four["queue_ms"], four["inference_ms"], four["validation_ms"], four["total_ms"]) == (
        4, 15, 15, 15, 15)
    _timing_jobs(db, "local", [(7, None, 7, 7)])  # a sample without an inference time counts for the others only
    odd = timing_summary(db, "local")  # [2, 7, 10, 20, 98]; inference [2, 10, 20, 98]
    assert (odd["sample_count"], odd["queue_ms"], odd["inference_ms"], odd["validation_ms"], odd["total_ms"]) == (
        5, 10, 15, 10, 10)
    # Mode filtering: the mock jobs of the same data directory never enter the local medians, and back.
    _timing_jobs(db, "mock", [(1, 1, 1, 1), (3, 3, 3, 3), (1000, 1000, 1000, 1000)])
    assert timing_summary(db, "local")["queue_ms"] == 10
    mock = timing_summary(db, "mock")
    assert (mock["sample_count"], mock["queue_ms"], mock["inference_ms"], mock["total_ms"]) == (3, 3, None, 3)
    snap = presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")  # what O01 shows in mock mode
    assert snap["mode"] == "mock" and snap["timing_summary"]["sample_count"] == 3
    assert snap["timing_summary"]["inference_ms"] is None and snap["timing_summary"]["total_ms"] == 3
    # The QA sample, as O01 reads it in local mode: 16 ms, not 22 ms.
    local, _, application = local_presenter
    _timing_jobs(application.state.ctx.db, "local", [(98, 98, 98, 98), (2, 2, 2, 2), (22, 22, 22, 22), (10, 10, 10, 10)])
    timing = local.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")["timing_summary"]
    assert (timing["sample_count"], timing["queue_ms"], timing["inference_ms"], timing["validation_ms"],
            timing["total_ms"]) == (4, 16, 16, 16, 16)
