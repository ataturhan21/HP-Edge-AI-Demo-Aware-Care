"""R36 retention: expired guest content is purged by the cleanup job; logs keep no symptom text or filenames."""
import pytest
from records_helpers import record_files, upload_ok

REQUIREMENT = "R36"


def test_expired_guest_session_content_is_purged(app, api):
    from app.modules.privacy.service import sweep
    ctx = app[0].state.ctx
    api.start()
    concern = "Distinctive synthetic concern zebra-lantern."
    cid = api.new_case(concern)["id"]
    upload_ok(api, cid, name="zebra-lantern-record.pdf")
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    api.wait_job(api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                        json={"expected_revision": rev, "user_reviewed": True})["id"])
    assert record_files(app) and list((ctx.settings.data_dir / "exports").iterdir())
    with ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET last_seen_at='2000-01-01T00:00:00Z'")
    sweep(ctx)
    with ctx.db.read() as conn:
        for table in ("cases", "facts", "documents", "guidance", "exports", "provider_searches"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        assert conn.execute("SELECT COUNT(*) FROM actors WHERE kind='guest'").fetchone()[0] == 0
        events = [tuple(r) for r in conn.execute("SELECT * FROM events").fetchall()]
    assert record_files(app) == [] and list((ctx.settings.data_dir / "exports").iterdir()) == []
    assert not any("zebra" in str(e) or ".pdf" in str(e) for e in events)
    assert api.req("GET", f"/cases/{cid}").status_code == 401


def test_presenter_actions_write_content_free_events(app, presenter):
    import json
    from conftest import ROOT
    fixtures = json.loads((ROOT / "fixtures/scenarios.json").read_text())["scenarios"]
    concerns = [s["concern"] for s in (fixtures.values() if isinstance(fixtures, dict) else fixtures)
                if isinstance(s, dict) and s.get("concern")]
    loaded = presenter.ok("POST", "/presenter/scenarios/routine/load", 201, "ScenarioLoaded", key=True,
                          json={"reset": True})
    presenter.wait_job(presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)["deletion_job_id"])
    with app[0].state.ctx.db.read() as conn:
        rows = [" ".join(str(v) for v in tuple(r)) for r in conn.execute("SELECT * FROM events")]
    assert rows, "presenter actions should leave operational events"
    text = "\n".join(rows)
    assert loaded["case_id"] not in text and loaded["session"]["id"] not in text
    for concern in concerns:
        assert concern[:40] not in text


def _ago(**delta) -> str:
    from datetime import timedelta
    from app.core.db import iso, utcnow
    return iso(utcnow() - timedelta(**delta))


def test_guest_expiry_is_the_earlier_of_30_minutes_idle_or_8_hours(app, api):
    """T-R36-S01 (guest boundaries): 29 idle minutes still work, 31 do not; the 8 h limit applies even when active."""
    from app.core.db import parse
    ctx = app[0].state.ctx
    api.start()
    with ctx.db.read() as conn:
        s = conn.execute("SELECT created_at, absolute_expires_at FROM sessions").fetchone()
    assert (parse(s["absolute_expires_at"]) - parse(s["created_at"])).total_seconds() == 8 * 3600
    with ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET last_seen_at=?", (_ago(minutes=29),))
    assert api.req("GET", "/cases").status_code == 200  # activity slides the idle window
    with ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET last_seen_at=?", (_ago(minutes=31),))
    assert api.req("GET", "/cases").status_code == 401
    api.start()
    with ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET absolute_expires_at=? WHERE revoked=0", (_ago(seconds=1),))
    assert api.req("GET", "/cases").status_code == 401


def test_export_lifetime_and_cleanup_cadence_match_the_published_settings(app, api):
    """T-R36-S01 (lifetimes): exports live 15 minutes, cleanup runs every 5 minutes, settings state both."""
    from app.core.db import parse
    from app.modules.privacy.service import SWEEP_INTERVAL_S
    api.start()
    cid = api.new_case()["id"]
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    api.wait_job(api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                        json={"expected_revision": rev, "user_reviewed": True})["id"])
    with app[0].state.ctx.db.read() as conn:
        e = conn.execute("SELECT created_at, expires_at FROM exports").fetchone()
    assert (parse(e["expires_at"]) - parse(e["created_at"])).total_seconds() == 15 * 60
    assert SWEEP_INTERVAL_S == 5 * 60
    s = api.ok("GET", "/settings", 200, "SettingsResponse")["settings"]
    assert (s["guest_idle_minutes"], s["guest_absolute_hours"], s["export_retention_minutes"],
            s["operational_event_retention_days"], s["patient_backups_enabled"]) == (30, 8, 15, 30, False)


def test_events_and_logs_hold_no_symptom_filename_prompt_output_or_parser_error_content(app, api, caplog):
    """T-R36-S02: a flow with distinctive inputs, parser failures and generation leaves content-free events/logs."""
    import logging
    from records_helpers import PNG_1PX, UNREADABLE, upload
    caplog.set_level(logging.DEBUG)
    api.start()
    cid = api.new_case("Distinctive symptom quokka-marmalade (synthetic).")["id"]
    upload_ok(api, cid, name="quokka-marmalade-report.pdf")
    upload_ok(api, cid, PNG_1PX, media_type="image/png", name="quokka-scan.png")  # extraction fails (parser path)
    assert upload(api, cid, UNREADABLE, name="quokka-broken.pdf").status_code == 422  # validation failure
    api.to_guided(cid)
    guidance = api.ok("GET", f"/cases/{cid}/guidance", 200, "Guidance")
    outputs = [guidance["case_summary"], *(a["text"] for a in guidance["actions"]),
               *(c["text"] for c in guidance["possible_explanations"]), *guidance["clinician_questions"]]
    with app[0].state.ctx.db.read() as conn:
        events = [" ".join(str(v) for v in tuple(r)) for r in conn.execute("SELECT * FROM events")]
    kinds = {e.split()[2] for e in events}
    assert {"record_extraction", "guidance_published"} <= kinds
    stored = "\n".join(events) + "\n" + caplog.text
    for needle in ("quokka", "marmalade", ".pdf", ".png", *outputs):
        assert needle not in stored, needle


def test_content_free_events_expire_after_30_days(app):
    """T-R36-S02 (retention): events older than 30 days are swept; younger ones stay."""
    from app.modules.privacy.service import sweep
    ctx = app[0].state.ctx
    with ctx.db.tx() as conn:
        for event_id, ts in (("old", _ago(days=30, minutes=1)), ("young", _ago(days=29, hours=23))):
            conn.execute("INSERT INTO events (id, ts, kind, status) VALUES (?,?,'test_event','succeeded')",
                         (event_id, ts))
    sweep(ctx)
    with ctx.db.read() as conn:
        assert [r["id"] for r in conn.execute("SELECT id FROM events WHERE kind='test_event'")] == ["young"]


def test_no_patient_content_backups_are_created(app, api):
    """T-R36-S02 (backups): a full flow and cleanup leave no backup copy of patient content in the data root."""
    from app.modules.privacy.service import sweep
    ctx = app[0].state.ctx
    api.start()
    cid = api.new_case()["id"]
    upload_ok(api, cid)
    api.to_guided(cid)
    sweep(ctx)
    names = sorted(str(p.relative_to(ctx.settings.data_dir)) for p in ctx.settings.data_dir.rglob("*"))
    assert not any("backup" in n.lower() or n.endswith((".bak", ".tar", ".tar.gz", ".zip")) for n in names), names
    # The data root holds only the live database (with its WAL files) and the record/export stores.
    top = {n.split("/")[0] for n in names}
    assert top <= {"records", "exports", "awarecare.sqlite3", "awarecare.sqlite3-wal", "awarecare.sqlite3-shm"}, top


# #42 (ADR-013): the current expiry reaches the browser on every authenticated response, so it can warn 2 minutes
# before the earlier of the 30-minute idle and the 8-hour absolute limit.

def test_every_authenticated_response_reports_the_sliding_expiry(app, api):
    from datetime import timedelta
    from app.core.db import parse, utcnow
    created = api.start()
    first = api.req("GET", "/settings")
    assert first.status_code == 200
    reported = parse(first.headers["X-Session-Expires-At"])
    assert abs((reported - (utcnow() + timedelta(minutes=30))).total_seconds()) < 5
    case = api.new_case()
    r = api.req("GET", f"/cases/{case['id']}")
    assert r.headers["X-Session-Expires-At"] == r.json()["case"]["expires_at"]  # the same authoritative value
    # The session-creation response reports the same value as its body.
    other = api.c.post("/api/v1/sessions", headers={**api.headers(key=True)},
                       json={"mode": "guest", "consent_version": "aware-care-demo-consent-1.0", "adult_eligible": True})
    assert other.headers["X-Session-Expires-At"] == other.json()["expires_at"]
    assert parse(created["expires_at"]) <= reported


def test_the_reported_expiry_never_passes_the_absolute_limit(app, api):
    from datetime import timedelta
    from app.core.db import iso, parse, utcnow
    api.start()
    absolute = utcnow() + timedelta(minutes=10)
    with app[0].state.ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET absolute_expires_at=? WHERE revoked=0", (iso(absolute),))
    for _ in range(3):  # "staying signed in" cannot extend past 8 hours
        r = api.req("GET", "/settings")
        assert r.status_code == 200 and parse(r.headers["X-Session-Expires-At"]) == parse(iso(absolute))


def test_no_expiry_is_reported_without_a_live_session(app, api):
    r = api.req("GET", "/health/ready")
    assert "X-Session-Expires-At" not in r.headers
    assert "X-Session-Expires-At" not in api.req("GET", "/settings").headers  # 401: no session yet
    api.start()
    assert "X-Session-Expires-At" in api.req("GET", "/settings").headers
    ended = api.req("DELETE", "/sessions/current")
    assert ended.status_code == 202 and "X-Session-Expires-At" not in ended.headers
    after = api.req("GET", "/settings")
    assert after.status_code == 401 and "X-Session-Expires-At" not in after.headers


# #275 (QA 2026-10-19): events keep no urgency level and only the hour.

def test_urgent_events_carry_no_level_and_events_keep_the_hour_only(local):
    from conftest import NO_RED_FLAGS, red_flags
    api, model, application = local
    model.screen = {"present": ["RF19"]}  # an emergency described in the concern
    described = api.new_case("Back pain and now I cannot start to pee.", context=[NO_RED_FLAGS])
    assert described["state"] == "urgent"
    model.screen = {"present": []}
    api.new_case(context=[red_flags("RF04")])  # a ticked red flag
    routine = api.new_case(context=[NO_RED_FLAGS])
    model.screen = {"present": ["RF19"]}
    api.to_guided(routine["id"])  # found before guidance
    with application.state.ctx.db.read() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM events")]
    urgent = [r for r in rows if r["kind"] == "urgent_interrupt"]
    assert len(urgent) == 3
    assert {r["error_code"] for r in urgent} <= {None, "RED_FLAG_DESCRIBED"}
    text = repr(rows).upper()
    assert "EMERGENCY" not in text and "URGENT_CLINICIAN" not in text
    assert all(len(r["ts"]) == 20 and r["ts"].endswith(":00:00Z") for r in rows), {r["ts"] for r in rows}


def test_hour_precision_events_still_expire_after_30_days(app):
    from datetime import UTC, datetime, timedelta
    from app.core.db import hour
    from app.modules.privacy.service import sweep
    ctx = app[0].state.ctx
    now = datetime.now(UTC)
    with ctx.db.tx() as conn:
        for event_id, ts in (("old", hour(now - timedelta(days=30, hours=1))),
                             ("young", hour(now - timedelta(days=29, hours=22)))):
            conn.execute("INSERT INTO events (id, ts, kind, status) VALUES (?,?,'test_event','succeeded')",
                         (event_id, ts))
    sweep(ctx)
    with ctx.db.read() as conn:
        assert [r["id"] for r in conn.execute("SELECT id FROM events WHERE kind='test_event'")] == ["young"]


def test_a_deleted_cases_jobs_keep_no_link_level_or_fine_time(local):
    """#275: after deleteCase the guidance job row is only a timing sample: no case, urgency level or exact time."""
    from conftest import NO_RED_FLAGS
    api, model, application = local
    case = api.new_case(context=[NO_RED_FLAGS])
    model.screen = {"present": ["RF19"]}  # found before guidance: the job routes the owner to urgent help
    assert api.to_guided(case["id"])["error_code"] == "RED_FLAG_DESCRIBED_EMERGENCY"
    rev = api.case(case["id"])["case"]["revision"]
    deletion = api.ok("DELETE", f"/cases/{case['id']}?expected_revision={rev}", 202, "DeletionAccepted")
    assert api.wait_job(deletion["deletion_job_id"])["status"] == "succeeded"  # the purge runs in the background
    with application.state.ctx.db.read() as conn:
        jobs = [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE kind != 'deletion'")]
    assert jobs, "the timing sample is kept"
    assert all(j["case_id"] is None and j["result_id"] is None for j in jobs)
    assert "EMERGENCY" not in repr(jobs).upper()
    for j in jobs:
        for key in ("created_at", "started_at", "finished_at"):
            assert j[key] is None or j[key].endswith(":00:00Z"), (key, j[key])


# --- #440 (T-11/P-14) and #471 (T-12), QA 2026-10-22: retention of job records and AI usage counts ------------------

def _jobs(ctx) -> list[dict]:
    with ctx.db.read() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM jobs")]


def _unlinked(jobs: list[dict], actor_id: str) -> None:
    assert jobs, "the timing samples are kept"
    for j in jobs:
        assert j["actor_id"] == "ended" and j["actor_id"] != actor_id
        assert j["case_id"] is None and j["result_id"] is None, j
        for key in ("created_at", "started_at", "finished_at"):
            assert j[key] is None or j[key].endswith(":00:00Z"), (j["kind"], key, j[key])


def test_440_ending_the_session_unlinks_its_job_rows_including_the_deletion_job(app, api):
    """QA: after DELETE /sessions/current the actor and cases were gone, but the guidance and deletion job rows kept the
    actor ID (the deletion job with microsecond times), and nothing ever removed them."""
    import time
    ctx = app[0].state.ctx
    session = api.start()
    cid = api.new_case()["id"]
    assert api.to_guided(cid)["status"] == "succeeded"
    ended = api.ok("DELETE", "/sessions/current", 202, "DeletionAccepted")
    deadline = time.time() + 5
    while time.time() < deadline and any(j["status"] != "succeeded" for j in _jobs(ctx)
                                         if j["id"] == ended["deletion_job_id"] or j["kind"] == "deletion"):
        time.sleep(0.05)  # the purge runs in the background; the session is gone, so the job cannot be polled
    jobs = _jobs(ctx)
    assert {j["kind"] for j in jobs} >= {"guidance", "deletion"}
    _unlinked(jobs, session["actor_id"])
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0] == 0


def test_440_guest_expiry_and_older_rows_are_unlinked_by_the_sweep(app, api):
    from app.modules.privacy.service import sweep
    ctx = app[0].state.ctx
    session = api.start()
    cid = api.new_case()["id"]
    api.to_guided(cid)
    with ctx.db.tx() as conn:  # a row left by an earlier release for an actor that no longer exists
        conn.execute("INSERT INTO jobs (id, actor_id, case_id, kind, status, created_at, finished_at) VALUES "
                     "('legacy', 'gone-actor', NULL, 'deletion', 'succeeded', '2026-10-22T03:19:42.638874Z', "
                     "'2026-10-22T03:19:43.100000Z')")
        conn.execute("UPDATE sessions SET last_seen_at='2000-01-01T00:00:00Z'")
    sweep(ctx)
    _unlinked(_jobs(ctx), session["actor_id"])


def test_440_a_presenter_reset_unlinks_the_demo_patients_job_rows(app, presenter):
    ctx = app[0].state.ctx
    loaded = presenter.ok("POST", "/presenter/scenarios/selfcare/load", 201, "ScenarioLoaded", key=True,
                          json={"reset": True, "prepare": "result"})
    presenter.wait_job(loaded["prepare_job_id"])
    demo = loaded["session"]["actor_id"]
    reset = presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True, json={})
    presenter.wait_job(reset["deletion_job_id"])
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE actor_id=?", (demo,)).fetchone()[0] == 0
        guidance = [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE kind='guidance'")]
    _unlinked(guidance, demo)


def test_440_finished_job_rows_are_deleted_after_30_days_and_live_work_is_kept(app):
    from datetime import UTC, datetime, timedelta
    from app.core.db import iso
    from app.modules.privacy.service import sweep
    ctx = app[0].state.ctx
    now = datetime.now(UTC)
    rows = [("old", now - timedelta(days=30, hours=1), "succeeded"), ("young", now - timedelta(days=29), "failed"),
            ("old-running", now - timedelta(days=31), "running")]
    with ctx.db.tx() as conn:
        for job_id, created, status in rows:
            conn.execute("INSERT INTO jobs (id, actor_id, kind, status, created_at) VALUES (?,?,?,?,?)",
                         (job_id, "ended", "guidance", status, iso(created)))
    sweep(ctx)
    assert sorted(j["id"] for j in _jobs(ctx)) == ["old-running", "young"]


def test_471_ai_usage_counts_older_than_90_days_are_removed_by_the_sweep_without_new_ai_calls(app):
    """QA: the sweep removed a 143-day-old event but kept the 143-day-old model_calls row until a new AI call was
    recorded; an idle device kept AI usage rows past 90 days indefinitely."""
    from datetime import UTC, datetime, timedelta
    from app.core.db import hour
    from app.modules.privacy.service import sweep
    ctx = app[0].state.ctx
    now = datetime.now(UTC)
    with ctx.db.tx() as conn:
        for call_id, when in (("old", now - timedelta(days=143)), ("edge", now - timedelta(days=90, hours=2)),
                              ("young", now - timedelta(days=89))):
            conn.execute("INSERT INTO model_calls (id, hour, mode, task, outcome, duration_ms) "
                         "VALUES (?,?,'local','guidance','ok',1.0)", (call_id, hour(when)))
    sweep(ctx)
    with ctx.db.read() as conn:
        assert [r["id"] for r in conn.execute("SELECT id FROM model_calls ORDER BY id")] == ["young"]


def test_440_471_the_privacy_settings_and_page_state_the_retention_the_api_enforces():
    """W04 names every kind of record kept and its period; the periods are the ones the sweep enforces."""
    from conftest import ROOT
    from app.modules.privacy import service
    from app.runtime import metering
    page = " ".join((ROOT / "apps/web/src/screens/W04.tsx").read_text().split())
    assert service.EVENT_RETENTION.days == 30
    assert "Operational events contain no health content and are kept for 30 days" in page
    assert service.JOB_RETENTION.days == 30 and "Job records" in page and "deleted after 30 days" in page
    assert service.AI_USAGE_RETENTION.days == metering.RETENTION_DAYS == 90
    assert "AI usage counts are kept for 90 days" in page
    assert service.SWEEP_INTERVAL_S == 300 and "a cleanup every 5 minutes" in page


# --- #608: a guest session that ends while its guidance runs invalidates that guidance --------------------------------
def _reviewed_case(api) -> tuple[str, int]:
    from conftest import NO_RED_FLAGS
    case = api.new_case(concern="Recurring headaches after long workdays (MARKER-608).", context=[NO_RED_FLAGS])
    api.answer_all(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    return case["id"], api.ok("POST", f"/cases/{case['id']}/review", 200, "Case",
                              json={"expected_revision": rev, "facts_confirmed": True})["revision"]


def _held_screen():
    """A scripted red-flag screen held at its first call until `gate` is set (the worker barrier)."""
    import threading
    entered, gate = threading.Event(), threading.Event()

    def screen(words):
        if not entered.is_set():
            entered.set()
            assert gate.wait(10), "the barrier was never released"
        return {"present": []}
    return screen, entered, gate


def _drained(ctx, timeout: float = 10.0) -> None:
    import time
    deadline = time.time() + timeout
    while ctx.jobs.snapshot() != (0, 0):
        assert time.time() < deadline, "the generation worker did not finish"
        time.sleep(0.02)


def _outcome(ctx, job_id: str, case_id: str) -> tuple:
    with ctx.db.read() as conn:
        job = conn.execute("SELECT status, error_code, result_id FROM jobs WHERE id=?", (job_id,)).fetchone()
        case = conn.execute("SELECT state, latest_guidance_id FROM cases WHERE id=?", (case_id,)).fetchone()
        rows = conn.execute("SELECT COUNT(*) FROM guidance").fetchone()[0]
    return tuple(job), (tuple(case) if case else None), rows


@pytest.mark.parametrize("expiry", ["absolute-rejected", "idle-unnoticed"])
def test_608_guidance_running_when_the_guest_session_ends_is_never_published(local, expiry):
    api, model, application = local
    ctx = application.state.ctx
    cid, rev = _reviewed_case(api)
    model.screen, entered, gate = _held_screen()
    job = api.ok("POST", f"/cases/{cid}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    assert entered.wait(5)  # the job is running, inside its red-flag screen
    with ctx.db.tx() as conn:
        if expiry == "absolute-rejected":  # the 8-hour limit passes; the next request is refused and revokes it
            conn.execute("UPDATE sessions SET absolute_expires_at=?", (_ago(seconds=1),))
        else:  # 31 idle minutes; no request notices it before the job ends
            conn.execute("UPDATE sessions SET last_seen_at=?", (_ago(minutes=31),))
    if expiry == "absolute-rejected":
        assert api.req("GET", "/cases").status_code == 401
        with ctx.db.read() as conn:
            assert conn.execute("SELECT revoked FROM sessions").fetchone()[0] == 1
    gate.set()
    _drained(ctx)
    assert _outcome(ctx, job["id"], cid) == (("cancelled", "SESSION_ENDED", None), ("generating", None), 0)
    from app.modules.privacy.service import sweep
    sweep(ctx)  # the recovery control: the sweep still purges the ended guest's case
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0


def test_608_queued_guidance_whose_session_ended_never_reaches_the_model(local):
    api, model, application = local
    ctx = application.state.ctx
    cid, rev = _reviewed_case(api)
    held, original = [], ctx.jobs.submit_generation
    ctx.jobs.submit_generation = lambda work: held.append(work)
    try:
        job = api.ok("POST", f"/cases/{cid}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    finally:
        ctx.jobs.submit_generation = original
    with ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET absolute_expires_at=?", (_ago(seconds=1),))
    calls = len(model.calls)
    held[0](0.0)  # the worker takes the job after the session ended
    assert model.calls[calls:] == []
    assert _outcome(ctx, job["id"], cid) == (("cancelled", "SESSION_ENDED", None), ("generating", None), 0)


def test_608_guidance_of_a_live_session_is_still_published(local):
    """The control: the same barrier with the session left alone publishes."""
    api, model, application = local
    ctx = application.state.ctx
    cid, rev = _reviewed_case(api)
    model.screen, entered, gate = _held_screen()
    job = api.ok("POST", f"/cases/{cid}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    assert entered.wait(5)
    gate.set()
    assert api.wait_job(job["id"])["status"] == "succeeded"
    assert api.case(cid)["case"]["state"] == "guided"
