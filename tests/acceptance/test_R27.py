"""R27 results computed for revision n are discarded after an edit to n+1. M08/M10."""
import time

import pytest
from test_R03 import SEARCH

REQUIREMENT = "R27"


def held(ctx, attr):
    queue = []
    original = getattr(ctx.jobs, attr)
    setattr(ctx.jobs, attr, lambda work: queue.append(work))
    return queue, lambda: setattr(ctx.jobs, attr, original)


def test_late_guidance_is_not_installed(app, api):
    ctx = app[0].state.ctx
    api.start()
    cid = api.new_case()["id"]
    api.answer_all(cid)
    rev = api.case(cid)["case"]["revision"]
    api.ok("POST", f"/cases/{cid}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    queue, restore = held(ctx, "submit_generation")
    try:
        job = api.ok("POST", f"/cases/{cid}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    finally:
        restore()
    # generating is not editable; deletion of the case is the conflicting change available mid-generation.
    with ctx.db.tx() as conn:
        conn.execute("UPDATE cases SET revision=revision+1 WHERE id=?", (cid,))
    queue[0](0.0)
    assert api.ok("GET", f"/jobs/{job['id']}", 200, "Job")["status"] == "stale"
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM guidance WHERE case_id=?", (cid,)).fetchone()[0] == 0


def test_late_export_is_discarded_and_bytes_removed(app, api):
    ctx = app[0].state.ctx
    api.start()
    cid = api.new_case()["id"]
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    queue, restore = held(ctx, "submit")
    try:
        job = api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                     json={"expected_revision": rev, "user_reviewed": True})
    finally:
        restore()
    api.ok("PATCH", f"/cases/{cid}", 200, "Case", json={"expected_revision": rev, "concern": "Edited."})
    queue[0]()
    done = api.ok("GET", f"/jobs/{job['id']}", 200, "Job")
    assert done["status"] == "stale" and done["result_id"] is None
    export_dir = ctx.settings.data_dir / "exports"
    assert not export_dir.exists() or list(export_dir.iterdir()) == []




def reviewed(api) -> tuple[str, int]:
    api.start()
    cid = api.new_case()["id"]
    api.answer_all(cid)
    rev = api.case(cid)["case"]["revision"]
    api.ok("POST", f"/cases/{cid}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    return cid, rev


def test_answer_edit_during_generation_discards_the_late_result_everywhere(app, api):
    """T-R27-S01: a user edit commits n+1 mid-generation; the n result never becomes current or powers anything."""
    cid, rev = reviewed(api)
    queue, restore = held(app[0].state.ctx, "submit_generation")
    try:
        job = api.ok("POST", f"/cases/{cid}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    finally:
        restore()
    q1 = next(f["source_id"] for f in api.case(cid)["case"]["confirmed_context"] if f["kind"] == "answer:Q01")
    edited = api.ok("PUT", f"/cases/{cid}/answers/{q1}", 200, "SaveAnswerResponse",
                    json={"expected_revision": rev, "status": "unknown", "value": None})
    assert edited["case_revision"] == rev + 1
    queue[0](0.0)
    assert api.ok("GET", f"/jobs/{job['id']}", 200, "Job")["status"] == "stale"
    read = api.case(cid)["case"]
    assert read["latest_guidance_id"] is None and read["revision"] == rev + 1
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM guidance WHERE case_id=?", (cid,)).fetchone()[0] == 0
    assert api.req("GET", f"/cases/{cid}/guidance").status_code == 404  # #269: never generated
    for revision in (rev, rev + 1):
        assert api.req("POST", f"/cases/{cid}/provider-search",
                       json={"expected_revision": revision, "criteria": SEARCH}).status_code == 409
        assert api.req("POST", f"/cases/{cid}/exports", key=True,
                       json={"expected_revision": revision, "user_reviewed": True}).status_code == 409


# Changes made while a job runs that the API cannot produce mid-job are applied directly (T-R27-S02).
CHANGES = {
    "ownership": "UPDATE cases SET actor_id=:other WHERE id=:cid",
    "reviewed-revision": "UPDATE cases SET reviewed_revision=NULL WHERE id=:cid",
    "state": "UPDATE cases SET state='limited' WHERE id=:cid",
    "tombstone": "UPDATE cases SET state='deleting' WHERE id=:cid",
    "superseded-guidance": "UPDATE cases SET latest_guidance_id=NULL WHERE id=:cid",
}


def change(app, other, name: str, cid: str) -> None:
    other_actor = other.start()["actor_id"]
    with app[0].state.ctx.db.tx() as conn:
        conn.execute(CHANGES[name], {"cid": cid, "other": other_actor})


@pytest.mark.parametrize("name", ["ownership", "reviewed-revision", "state", "tombstone"])
def test_guidance_worker_rechecks_every_publication_guard(app, api, other, name):
    """T-R27-S02: a guidance result is refused at commit when any guard changed while it ran."""
    cid, rev = reviewed(api)
    queue, restore = held(app[0].state.ctx, "submit_generation")
    try:
        job = api.ok("POST", f"/cases/{cid}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    finally:
        restore()
    change(app, other, name, cid)
    queue[0](0.0)
    with app[0].state.ctx.db.read() as conn:
        done = conn.execute("SELECT status, result_id FROM jobs WHERE id=?", (job["id"],)).fetchone()
        assert conn.execute("SELECT COUNT(*) FROM guidance WHERE case_id=?", (cid,)).fetchone()[0] == 0
        row = conn.execute("SELECT state, latest_guidance_id FROM cases WHERE id=?", (cid,)).fetchone()
    assert done["status"] in {"stale", "cancelled"} and done["result_id"] is None
    assert row["latest_guidance_id"] is None and row["state"] != "guided"


@pytest.mark.parametrize("name", ["ownership", "reviewed-revision", "state", "tombstone", "superseded-guidance"])
def test_export_worker_rechecks_every_publication_guard(app, api, other, name):
    """T-R27-S02: an export is refused at commit, and its bytes removed, when any guard changed while it ran."""
    ctx = app[0].state.ctx
    api.start()
    cid = api.new_case()["id"]
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    queue, restore = held(ctx, "submit")
    try:
        job = api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                     json={"expected_revision": rev, "user_reviewed": True})
    finally:
        restore()
    change(app, other, name, cid)
    queue[0]()
    with ctx.db.read() as conn:
        done = conn.execute("SELECT status, result_id FROM jobs WHERE id=?", (job["id"],)).fetchone()
        assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0
    assert done["status"] in {"stale", "cancelled"} and done["result_id"] is None
    export_dir = ctx.settings.data_dir / "exports"
    assert not export_dir.exists() or list(export_dir.iterdir()) == []


def test_late_guidance_and_export_do_not_resurrect_a_deleted_case(app, api):
    """T-R27-S02: jobs that finish after a real case deletion publish nothing and leave no bytes."""
    ctx = app[0].state.ctx
    api.start()
    cid = api.new_case()["id"]
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    queue, restore = held(ctx, "submit")
    try:
        export_job = api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                            json={"expected_revision": rev, "user_reviewed": True})
    finally:
        restore()
    api.ok("DELETE", f"/cases/{cid}?expected_revision={rev}", 202, "DeletionAccepted")
    deadline = time.time() + 5
    while api.req("GET", f"/cases/{cid}").status_code != 404 and time.time() < deadline:
        time.sleep(0.05)
    queue[0]()
    with ctx.db.read() as conn:
        done = conn.execute("SELECT status FROM jobs WHERE id=?", (export_job["id"],)).fetchone()
        assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM guidance WHERE case_id=?", (cid,)).fetchone()[0] == 0
    assert done is None or done["status"] == "cancelled"
    export_dir = ctx.settings.data_dir / "exports"
    assert not export_dir.exists() or list(export_dir.iterdir()) == []
