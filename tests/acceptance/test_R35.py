"""R35 deletion: immediate access block, purge of owned stores, one-use token. M11."""
import time

import pytest

REQUIREMENT = "R35"


def test_delete_case_blocks_reads_and_purges_files(app, api):
    api.start()
    case = api.new_case()
    api.to_guided(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    job = api.ok("POST", f"/cases/{case['id']}/exports", 202, "Job", key=True,
                 json={"expected_revision": rev, "user_reviewed": True})
    export_id = api.wait_job(job["id"])["result_id"]
    exports_dir = app[0].state.ctx.settings.data_dir / "exports"
    assert any(exports_dir.iterdir())
    deletion = api.ok("DELETE", f"/cases/{case['id']}?expected_revision={rev}", 202, "DeletionAccepted")
    assert api.req("GET", f"/cases/{case['id']}").status_code == 404
    assert api.req("GET", f"/exports/{export_id}/download").status_code == 404
    assert api.wait_job(deletion["deletion_job_id"])["status"] == "succeeded"
    assert not any(exports_dir.iterdir())
    with app[0].state.ctx.db.read() as conn:
        for table in ("cases", "facts", "questions", "answers", "guidance", "exports"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_delete_all_requires_fresh_one_use_token(api):
    api.start()
    api.new_case()
    settings = api.ok("GET", "/settings", 200, "SettingsResponse")
    token = settings["delete_confirmation_token"]
    api.ok("POST", "/privacy/delete-all", 202, "DeletionAccepted", key=True, json={"confirmation_token": token})
    reused = api.req("POST", "/privacy/delete-all", key=True, json={"confirmation_token": token})
    assert reused.status_code == 403
    assert api.ok("GET", "/cases", 200, "CaseList")["items"] == []


def test_guest_logout_revokes_session_and_purges(app, api):
    api.start()
    case = api.new_case()
    api.ok("DELETE", "/sessions/current", 202, "DeletionAccepted")
    assert api.req("GET", f"/cases/{case['id']}").status_code == 401
    import time
    for _ in range(50):
        with app[0].state.ctx.db.read() as conn:
            # Cases and the guest actor are purged in successive transactions of one job.
            if (conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0 and
                    conn.execute("SELECT COUNT(*) FROM actors WHERE kind='guest'").fetchone()[0] == 0):
                break
        time.sleep(0.05)
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM actors WHERE kind='guest'").fetchone()[0] == 0


def test_idle_expired_session_is_rejected_immediately(app, api):
    api.start()
    with app[0].state.ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET last_seen_at='2000-01-01T00:00:00Z'")
    assert api.req("GET", "/cases").status_code == 401


def test_case_deletion_purges_record_bytes_and_cancels_late_extraction(app, api):
    from records_helpers import SAMPLE, record_files, upload
    ctx = app[0].state.ctx
    api.start()
    case = api.new_case()
    held = []
    ctx.jobs.submit, original = (lambda work: held.append(work)), ctx.jobs.submit
    try:
        r = upload(api, case["id"], SAMPLE)
    finally:
        ctx.jobs.submit = original
    assert r.status_code == 202 and len(record_files(app)) == 1
    api.ok("DELETE", f"/cases/{case['id']}?expected_revision=1", 202, "DeletionAccepted")
    import time
    for _ in range(50):
        with ctx.db.read() as conn:
            if conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0:
                break
        time.sleep(0.05)
    held[0]()  # the late extraction worker runs after the purge
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert conn.execute("SELECT status FROM jobs WHERE id=?", (r.json()["job_id"],)).fetchone()[0] == "cancelled"
    assert record_files(app) == []


def test_presenter_reset_during_generation_cancels_the_late_write(app, presenter):
    """M3 exit check: deletion (here a presenter reset) cancels late writes; nothing is resurrected."""
    from conftest import Api
    ctx = app[0].state.ctx
    loaded = presenter.ok("POST", "/presenter/scenarios/routine/load", 201, "ScenarioLoaded", key=True,
                          json={"reset": True})
    patient, cid = Api(presenter.c), loaded["case_id"]
    patient.answer_all(cid)
    rev = patient.case(cid)["case"]["revision"]
    patient.ok("POST", f"/cases/{cid}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    held, original = [], ctx.jobs.submit_generation
    ctx.jobs.submit_generation = lambda work: held.append(work)
    try:
        job = patient.ok("POST", f"/cases/{cid}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    finally:
        ctx.jobs.submit_generation = original
    reset = presenter.wait_job(presenter.ok("POST", "/presenter/reset", 202, "DeletionAccepted", key=True)[
        "deletion_job_id"])
    assert reset["status"] == "succeeded"
    held[0](0.0)  # the generation worker finishes after the reset
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM guidance").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=?", (cid,)).fetchone()[0] == 0
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()
        assert row is None or row["status"] in {"stale", "cancelled", "failed"}


SENTINEL = "orchid-sentinel"


def _rows_mentioning(conn, needle: str) -> dict[str, int]:
    """Every table whose rows mention the needle in any column (a full-database scan)."""
    found = {}
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        hits = sum(1 for r in rows if any(needle in str(v) for v in tuple(r)))
        if hits:
            found[table] = hits
    return found


def test_case_deletion_leaves_only_content_free_completion_evidence(app, api):
    """T-R35-S01: every owned store is purged before completion; what remains names no content."""
    from records_helpers import record_files, upload_ok
    from test_R03 import SEARCH
    ctx = app[0].state.ctx
    api.start()
    cid = api.new_case(f"Synthetic concern {SENTINEL}.")["id"]
    upload_ok(api, cid, name=f"{SENTINEL}.pdf")
    fact = api.ok("GET", f"/cases/{cid}/records", 200, "RecordList")["facts"][0]
    api.ok("PATCH", f"/cases/{cid}/facts/{fact['id']}", 200, "FactReviewResponse",
           json={"expected_revision": api.case(cid)["case"]["revision"], "action": "correct",
                 "corrected_value": {"value": f"Corrected {SENTINEL}", "units": None}})
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    api.ok("POST", f"/cases/{cid}/provider-search", 200, "ProviderSearchResult",
           json={"expected_revision": rev, "criteria": SEARCH})
    api.wait_job(api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                        json={"expected_revision": rev, "user_reviewed": True})["id"])
    with ctx.db.read() as conn:
        before = _rows_mentioning(conn, cid)
    assert {"facts", "documents", "guidance", "provider_searches", "exports", "questions", "answers"} <= set(before)
    deletion = api.ok("DELETE", f"/cases/{cid}?expected_revision={rev}", 202, "DeletionAccepted")
    receipt = api.wait_job(deletion["deletion_job_id"])
    assert receipt["status"] == "succeeded" and receipt["result_type"] == "deletion_receipt"
    assert record_files(app) == [] and list((ctx.settings.data_dir / "exports").iterdir()) == []
    with ctx.db.read() as conn:
        assert _rows_mentioning(conn, SENTINEL) == {}
        # Only content-free evidence keeps the case ID: job status rows and the deletion tombstone.
        assert set(_rows_mentioning(conn, cid)) <= {"jobs", "tombstones"}
        job_columns = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert not job_columns & {"body_json", "result_json", "concern", "value_json", "original_text", "display_name"}


def test_purge_failure_keeps_access_blocked_and_never_reports_success(app, api, monkeypatch):
    """T-R35-S02: a store that fails its purge leaves the case blocked; the job says failed; a retry completes."""
    import pathlib
    from records_helpers import record_files, upload_ok
    from app.modules.privacy.service import sweep
    ctx = app[0].state.ctx
    api.start()
    cid = api.new_case()["id"]
    upload_ok(api, cid)
    [stored] = record_files(app)
    # A worker is still running when the deletion starts; it must cancel when it finishes.
    held = []
    monkeypatch.setattr(ctx.jobs, "submit_generation", lambda work: held.append(work))
    api.answer_all(cid)
    rev = api.case(cid)["case"]["revision"]
    api.ok("POST", f"/cases/{cid}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    generation = api.ok("POST", f"/cases/{cid}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    original_unlink = pathlib.Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self == stored:
            raise PermissionError("simulated purge failure")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", failing_unlink)
    deletion = api.ok("DELETE", f"/cases/{cid}?expected_revision={rev}", 202, "DeletionAccepted")
    job = api.wait_job(deletion["deletion_job_id"])
    assert job["status"] == "failed" and job["error_code"] == "PURGE_FAILED"
    for path in (f"/cases/{cid}", f"/cases/{cid}/records", f"/cases/{cid}/guidance"):
        assert api.req("GET", path).status_code == 404
    assert api.ok("GET", "/cases", 200, "CaseList")["items"] == []
    assert stored.exists()
    held[0](0.0)  # the running worker finishes during the deletion
    assert api.ok("GET", f"/jobs/{generation['id']}", 200, "Job")["status"] == "cancelled"
    # The store recovers; the scheduled retry completes the purge. The failed job is not rewritten as a success.
    monkeypatch.setattr(pathlib.Path, "unlink", original_unlink)
    sweep(ctx)
    assert not stored.exists()
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=?", (cid,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM guidance").fetchone()[0] == 0
    assert api.ok("GET", f"/jobs/{deletion['deletion_job_id']}", 200, "Job")["status"] == "failed"


def test_expired_delete_confirmation_token_is_rejected(app, api):
    """T-R35-S02: an expired confirmation token cannot delete anything."""
    api.start()
    cid = api.new_case()["id"]
    token = api.ok("GET", "/settings", 200, "SettingsResponse")["delete_confirmation_token"]
    with app[0].state.ctx.db.tx() as conn:
        conn.execute("UPDATE delete_tokens SET expires_at='2000-01-01T00:00:00Z'")
    r = api.req("POST", "/privacy/delete-all", key=True, json={"confirmation_token": token})
    assert r.status_code == 403
    assert api.case(cid)["case"]["state"] == "intake"


def test_a_delete_all_retry_with_the_same_key_returns_the_original_job(app, api):
    """#156: the response of a delete-all can be lost; a retry with the same Idempotency-Key returns the original
    deletion job (202), never "confirmation expired" for a deletion that already ran. The same key with another
    token is a conflict."""
    api.start()
    api.new_case()
    token = api.ok("GET", "/settings", 200, "SettingsResponse")["delete_confirmation_token"]
    key = {"Idempotency-Key": "qa-delete-all-retry-0001"}
    first = api.ok("POST", "/privacy/delete-all", 202, "DeletionAccepted", headers=key, json={"confirmation_token": token})
    again = api.ok("POST", "/privacy/delete-all", 202, "DeletionAccepted", headers=key, json={"confirmation_token": token})
    assert again["deletion_job_id"] == first["deletion_job_id"]
    other = api.ok("GET", "/settings", 200, "SettingsResponse")["delete_confirmation_token"]
    conflict = api.req("POST", "/privacy/delete-all", headers=key, json={"confirmation_token": other})
    assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert api.req("POST", "/privacy/delete-all", json={"confirmation_token": other}).status_code == 400  # key required


# #274 (QA 2026-10-19): deleted health text must not survive in the SQLite WAL or in freed database pages.

MARKER = "ZQXJ-remanence-marker-chest-tightness-at-night"


def _marker_hits(app) -> dict[str, int]:
    data_dir = app[0].state.ctx.settings.data_dir
    return {f.name: f.read_bytes().count(MARKER.encode()) for f in data_dir.iterdir() if f.is_file()}


def _marked_case(api) -> tuple[str, int]:
    cid = api.new_case(MARKER + " and recurring headaches.")["id"]
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    api.wait_job(api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                        json={"expected_revision": rev, "user_reviewed": True})["id"])
    return cid, rev


def test_secure_delete_is_on():
    import tempfile
    from pathlib import Path
    from app.core.db import Database
    with tempfile.TemporaryDirectory() as d:
        db = Database(Path(d) / "x.sqlite3")
        with db.read() as conn:
            assert conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
        db.close()


def test_no_trace_of_a_deleted_case_in_the_database_or_wal(app, api):
    api.start()
    cid, rev = _marked_case(api)
    assert sum(_marker_hits(app).values()) > 0  # the text really was stored
    job = api.ok("DELETE", f"/cases/{cid}?expected_revision={rev}", 202, "DeletionAccepted")
    assert api.wait_job(job["deletion_job_id"])["status"] == "succeeded"
    hits = _marker_hits(app)
    assert sum(hits.values()) == 0, hits
    assert "awarecare.sqlite3-wal" in hits  # the WAL file was searched too


def test_no_trace_after_delete_all(app, api):
    api.start()
    _marked_case(api)
    token = api.ok("GET", "/settings", 200, "SettingsResponse")["delete_confirmation_token"]
    job = api.ok("POST", "/privacy/delete-all", 202, "DeletionAccepted", key=True,
                 json={"confirmation_token": token})
    assert api.wait_job(job["deletion_job_id"])["status"] == "succeeded"
    assert sum(_marker_hits(app).values()) == 0, _marker_hits(app)


def test_no_trace_after_ending_the_guest_session(app, api):
    api.start()
    _marked_case(api)
    job = api.ok("DELETE", "/sessions/current", 202, "DeletionAccepted")["deletion_job_id"]
    ctx = app[0].state.ctx
    import time
    deadline = time.time() + 5
    while time.time() < deadline:  # the session has ended, so the job is read from the store
        with ctx.db.read() as conn:
            if conn.execute("SELECT status FROM jobs WHERE id=?", (job,)).fetchone()["status"] == "succeeded":
                break
        time.sleep(0.05)
    assert sum(_marker_hits(app).values()) == 0, _marker_hits(app)


def test_no_trace_after_the_expiry_sweep(app, api):
    from app.modules.privacy.service import sweep
    api.start()
    _marked_case(api)
    ctx = app[0].state.ctx
    with ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET last_seen_at='2000-01-01T00:00:00Z'")
    sweep(ctx)
    assert sum(_marker_hits(app).values()) == 0, _marker_hits(app)


# #272 (QA 2026-10-19): no record file without a row, and uploads do not block the event loop.

def test_a_deletion_racing_an_upload_leaves_no_orphan_file(app, api):
    """The deletion commits and purges between the upload's commit and its extraction (the gap where the bytes used
    to be written after the commit)."""
    from app.modules.privacy import service as privacy
    from records_helpers import record_files, upload
    ctx = app[0].state.ctx
    api.start()
    cid = api.new_case()["id"]
    real_submit = ctx.jobs.submit

    def racing(work):
        with ctx.db.tx() as conn:
            privacy._mark_deleting(conn, [cid])
        privacy._purge(ctx, [cid])
        return real_submit(work)
    ctx.jobs.submit = racing
    try:
        r = upload(api, cid, __import__("records_helpers").SAMPLE)
    finally:
        ctx.jobs.submit = real_submit
    assert r.status_code == 202
    assert api.wait_job(r.json()["job_id"])["status"] == "cancelled"
    assert record_files(app) == []
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_extraction_removes_the_bytes_by_key_when_the_row_is_gone(app, api):
    from app.modules.records import service as records
    from records_helpers import record_files, upload
    ctx = app[0].state.ctx
    api.start()
    cid = api.new_case()["id"]
    held = []
    real_submit = ctx.jobs.submit
    ctx.jobs.submit = lambda work: held.append(work)
    try:
        r = upload(api, cid, __import__("records_helpers").SAMPLE)
    finally:
        ctx.jobs.submit = real_submit
    assert len(record_files(app)) == 1
    with ctx.db.tx() as conn:  # the row disappears without the file being removed
        conn.execute("DELETE FROM documents")
    held[0]()
    assert record_files(app) == []
    assert records.MAX_FILES == 3


def test_a_failed_upload_commit_leaves_no_bytes(app, api, monkeypatch):
    from fastapi.testclient import TestClient
    from conftest import Api
    from app.modules.records import service as records
    from records_helpers import record_files, upload
    api.start()
    cid = api.new_case()["id"]

    def broken(*a, **kw):
        raise RuntimeError("insert failed")
    monkeypatch.setattr(records, "create_job", broken)
    quiet = Api(TestClient(app[0], raise_server_exceptions=False))
    quiet.c.cookies.update(api.c.cookies)
    quiet.csrf = api.csrf
    assert upload(quiet, cid, __import__("records_helpers").SAMPLE).status_code == 500
    assert record_files(app) == []


def test_files_no_row_references_are_removed_by_the_sweep_and_at_startup(tmp_path):
    import os
    import time
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.config import load_settings
    from app.main import create_app
    from app.modules.privacy.service import sweep
    from conftest import Api
    from records_helpers import upload_ok
    settings = replace(load_settings(), data_dir=tmp_path / "data")
    with TestClient(create_app(settings)) as client:
        ctx = client.app.state.ctx
        api = Api(client)
        api.start()
        cid = api.new_case()["id"]
        upload_ok(api, cid)  # a referenced record file stays
        api.to_guided(cid)
        rev = api.case(cid)["case"]["revision"]
        api.wait_job(api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                            json={"expected_revision": rev, "user_reviewed": True})["id"])
        kept = sorted(p.name for d in ("records", "exports") for p in (settings.data_dir / d).iterdir())
        old, young = time.time() - 3600, time.time()
        for d in ("records", "exports"):
            for name, ts in (("orphan-old", old), ("orphan-young", young)):
                path = settings.data_dir / d / name
                path.write_bytes(b"orphan")
                os.utime(path, (ts, ts))
        sweep(ctx)
        left = sorted(p.name for d in ("records", "exports") for p in (settings.data_dir / d).iterdir())
        # The periodic sweep removes old orphans and leaves young files (a write may be in progress).
        assert left == sorted(kept + ["orphan-young", "orphan-young"])
    with TestClient(create_app(settings)):  # at startup nothing is being written: every orphan goes
        left = sorted(p.name for d in ("records", "exports") for p in (settings.data_dir / d).iterdir())
        assert "orphan-young" not in left


def test_the_upload_route_does_not_run_on_the_event_loop():
    import inspect
    from app.modules.records import routes
    assert not inspect.iscoroutinefunction(routes.upload_record)  # FastAPI runs it in its thread pool


# --- #607: deleted cases' queued guidance never reaches the model ----------------------------------------------------
class _HeldScreen:
    """A scripted red-flag screen that holds the first screen after `arm()` until `release()` (the worker barrier)."""

    def __init__(self):
        self.armed, self.entered, self.gate = False, __import__("threading").Event(), __import__("threading").Event()

    def arm(self):
        self.armed = True

    def __call__(self, words):
        if self.armed and not self.entered.is_set():
            self.entered.set()
            assert self.gate.wait(10), "the barrier was never released"
        return {"present": []}


def _queued_local(tmp_path):
    """A local-mode app with one active and two queued generations (no ZRT): set its scripted model once started."""
    from dataclasses import replace
    from app.config import load_settings
    from app.main import create_app
    settings = replace(load_settings(), mode="local", model_id="test-model", data_dir=tmp_path / "local",
                       active_generation_limit=1, queued_generation_limit=2)
    return create_app(settings)


def _reviewed(api, marker: str) -> tuple[str, int]:
    from conftest import NO_RED_FLAGS
    case = api.new_case(concern=f"Recurring headaches after long workdays ({marker}).", context=[NO_RED_FLAGS])
    api.answer_all(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    rev = api.ok("POST", f"/cases/{case['id']}/review", 200, "Case",
                 json={"expected_revision": rev, "facts_confirmed": True})["revision"]
    return case["id"], rev


def _drain(ctx, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while ctx.jobs.snapshot() != (0, 0):
        assert time.time() < deadline, "the generation workers did not drain"
        time.sleep(0.02)


def _delete_three(api, ctx, cases, how):
    from app.modules.privacy.service import sweep
    if how == "case":
        for cid, rev in cases:
            receipt = api.ok("DELETE", f"/cases/{cid}?expected_revision={rev}", 202, "DeletionAccepted")
            assert api.wait_job(receipt["deletion_job_id"])["status"] == "succeeded"
    elif how == "delete-all":
        token = api.ok("GET", "/settings", 200, "SettingsResponse")["delete_confirmation_token"]
        receipt = api.ok("POST", "/privacy/delete-all", 202, "DeletionAccepted", key=True,
                         json={"confirmation_token": token})
        assert api.wait_job(receipt["deletion_job_id"])["status"] == "succeeded"
    else:  # the guest's idle expiry, purged by the sweep
        with ctx.db.tx() as conn:
            conn.execute("UPDATE sessions SET last_seen_at='2000-01-01T00:00:00Z'")
        sweep(ctx)


@pytest.mark.parametrize("how", ["case", "delete-all", "expiry-sweep"])
def test_607_deleted_cases_queued_guidance_never_reaches_the_model(tmp_path, how):
    from fastapi.testclient import TestClient
    from conftest import Api, LocalModel
    application = _queued_local(tmp_path)
    with TestClient(application) as client:
        ctx = application.state.ctx
        ctx.runtime = model = LocalModel()
        api = Api(client)
        api.start()
        held = _HeldScreen()
        model.screen = held
        cases = [_reviewed(api, marker) for marker in ("MARKER-A-607", "MARKER-B-607", "MARKER-C-607")]
        held.arm()
        jobs = [api.ok("POST", f"/cases/{cases[0][0]}/guidance", 202, "Job", key=True,
                       json={"expected_revision": cases[0][1]})]
        assert held.entered.wait(5)  # the first job is running, inside its red-flag screen
        jobs += [api.ok("POST", f"/cases/{cid}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
                 for cid, rev in cases[1:]]
        assert ctx.jobs.snapshot() == (2, 1)  # two queued, one active
        cases = [(cid, api.case(cid)["case"]["revision"]) for cid, _ in cases] if how == "case" else cases
        _delete_three(api, ctx, cases, how)
        with ctx.db.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0
            assert {tuple(r) for r in conn.execute("SELECT status, error_code FROM jobs WHERE kind='guidance'")} == {
                ("cancelled", "CASE_DELETED")}
        mark = len(model.calls)
        held.gate.set()
        _drain(ctx)
        late = [c["task"] for c in model.calls[mark:]
                if "MARKER-B-607" in str(c["snapshot"]) or "MARKER-C-607" in str(c["snapshot"])]
        assert late == []  # no screen and no guidance for a purged case
        with ctx.db.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM guidance").fetchone()[0] == 0
            assert {tuple(r) for r in conn.execute("SELECT status, error_code FROM jobs WHERE kind='guidance'")} == {
                ("cancelled", "CASE_DELETED")}


def test_607_queued_guidance_of_a_live_case_still_runs_after_the_active_one(tmp_path):
    """The control: with nothing deleted, the queued jobs start after the active one and publish."""
    from fastapi.testclient import TestClient
    from conftest import Api, LocalModel
    application = _queued_local(tmp_path)
    with TestClient(application) as client:
        ctx = application.state.ctx
        ctx.runtime = model = LocalModel()
        api = Api(client)
        api.start()
        held = _HeldScreen()
        model.screen = held
        cases = [_reviewed(api, marker) for marker in ("MARKER-A-607", "MARKER-B-607", "MARKER-C-607")]
        held.arm()
        jobs = [api.ok("POST", f"/cases/{cases[0][0]}/guidance", 202, "Job", key=True,
                       json={"expected_revision": cases[0][1]})]
        assert held.entered.wait(5)
        jobs += [api.ok("POST", f"/cases/{cid}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
                 for cid, rev in cases[1:]]
        held.gate.set()
        assert [api.wait_job(j["id"])["status"] for j in jobs] == ["succeeded"] * 3
        assert [c["task"] for c in model.calls].count("guidance") == 3
