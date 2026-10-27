"""R33 expired, foreign or stale exports are denied; bytes are removed on expiry or deletion. M10/M11."""
REQUIREMENT = "R33"


def export_for(api):
    api.start()
    cid = api.new_case()["id"]
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    job = api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                 json={"expected_revision": rev, "user_reviewed": True})
    return cid, rev, api.wait_job(job["id"])["result_id"]


def files(app):
    d = app[0].state.ctx.settings.data_dir / "exports"
    return list(d.iterdir()) if d.exists() else []


def test_expired_export_bytes_are_swept(app, api):
    from app.modules.privacy.service import sweep
    cid, _, export = export_for(api)
    assert len(files(app)) == 1
    with app[0].state.ctx.db.tx() as conn:
        conn.execute("UPDATE exports SET expires_at='2000-01-01T00:00:00Z'")
    r = api.req("GET", f"/exports/{export}/download")
    assert r.status_code == 409 and r.json()["code"] == "EXPORT_EXPIRED"
    sweep(app[0].state.ctx)
    assert files(app) == []
    assert api.req("GET", f"/exports/{export}/download").status_code == 404


def test_case_deletion_removes_export_bytes(app, api):
    cid, rev, export = export_for(api)
    api.ok("DELETE", f"/cases/{cid}?expected_revision={rev}", 202, "DeletionAccepted")
    assert api.req("GET", f"/exports/{export}/download").status_code == 404
    import time
    for _ in range(50):
        if not files(app):
            break
        time.sleep(0.05)
    assert files(app) == []


def test_foreign_and_stale_downloads_are_denied(api, other):
    cid, rev, export = export_for(api)
    other.start()
    assert other.req("GET", f"/exports/{export}/download").status_code == 404
    api.ok("PATCH", f"/cases/{cid}", 200, "Case", json={"expected_revision": rev, "concern": "Edited."})
    assert api.req("GET", f"/exports/{export}/download").status_code in {404, 409}


def test_the_downloaded_copy_is_stated_to_be_outside_server_deletion(api):
    """T-R33-S02: the summary itself says a downloaded copy is outside the server's deletion controls."""
    from test_R32 import pdf_lines
    _, _, export_id = export_for(api)
    pdf = api.req("GET", f"/exports/{export_id}/download").content
    assert "A downloaded copy is outside Aware Care's server deletion controls." in pdf_lines(pdf)


# #592 (QA 2026-10-26): the PDF is written before its export row commits. A publication that failed after that (here
# its INSERT, injected with a trigger on this test's own database) kept the PDF, and a case deletion, which finds
# export files through their committed rows, then reported success while the case's text stayed on disk.
EXPORT_MARKER = "SYNTHETIC-PRIVATE-EXPORT-ATOMICITY-CASE"


def test_592_a_failed_export_publication_removes_its_pdf_and_a_deletion_leaves_no_copy(app, api):
    ctx = app[0].state.ctx
    api.start()
    cid = api.new_case(f"{EXPORT_MARKER} and recurring headaches after long workdays.")["id"]
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    body = {"expected_revision": rev, "user_reviewed": True}
    with ctx.db.tx() as conn:
        conn.execute("CREATE TEMP TRIGGER fail_export_insert BEFORE INSERT ON exports "
                     "BEGIN SELECT RAISE(FAIL, 'synthetic storage failure'); END")
    failed = api.wait_job(api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True, json=body)["id"])
    assert (failed["status"], failed["error_code"]) == ("failed", "EXPORT_FAILED")
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0
    assert files(app) == []  # no PDF without a committed row, not even a young one the sweep would leave
    # The control: once storage works again a new summary is published, kept and carries the case's text.
    with ctx.db.tx() as conn:
        conn.execute("DROP TRIGGER fail_export_insert")
    done = api.wait_job(api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True, json=body)["id"])
    assert done["status"] == "succeeded"
    [pdf] = files(app)
    assert EXPORT_MARKER.encode() in pdf.read_bytes()
    deletion = api.ok("DELETE", f"/cases/{cid}?expected_revision={rev}", 202, "DeletionAccepted")
    assert api.wait_job(deletion["deletion_job_id"])["status"] == "succeeded"
    assert files(app) == []
