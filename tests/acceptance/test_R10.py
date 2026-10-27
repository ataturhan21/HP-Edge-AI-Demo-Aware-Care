"""R10 history lists owned cases with server state; deleted cases cannot be restored. M03/M11.

Saved-account resume needs ADR-005 identity; this covers the guest-session history semantics.
"""
REQUIREMENT = "R10"


def test_history_reflects_server_state_and_order(api):
    api.start()
    first = api.new_case()["id"]
    second = api.new_case("Second synthetic concern.")["id"]
    api.to_guided(first)
    items = api.ok("GET", "/cases", 200, "CaseList")["items"]
    assert [i["id"] for i in items] == [second, first]
    assert {i["id"]: i["state"] for i in items} == {first: "guided", second: "intake"}
    assert api.case(first)["case"]["state"] == "guided"


def test_deleted_case_leaves_history_and_cannot_be_read(api):
    api.start()
    cid = api.new_case()["id"]
    api.ok("DELETE", f"/cases/{cid}?expected_revision=1", 202, "DeletionAccepted")
    assert api.ok("GET", "/cases", 200, "CaseList")["items"] == []
    for path in (f"/cases/{cid}", f"/cases/{cid}/guidance", f"/cases/{cid}/records"):
        assert api.req("GET", path).status_code == 404


def test_stale_delete_revision_is_refused(api):
    api.start()
    cid = api.new_case()["id"]
    assert api.req("DELETE", f"/cases/{cid}?expected_revision=9").status_code == 409
    assert api.case(cid)["case"]["state"] == "intake"


def test_resume_reads_owned_answers_from_the_server_with_only_the_session_cookie(app, api):
    """T-R10-S01: a reloaded browser keeps nothing but its session cookie; the case and answers come from the server."""
    from fastapi.testclient import TestClient
    from conftest import Api
    api.start()
    cid = api.new_case()["id"]
    api.answer_all(cid)
    saved = {f["kind"]: (f["source_id"], f["value"]) for f in api.case(cid)["case"]["confirmed_context"]
             if f["kind"].startswith("answer:")}
    assert len(saved) == 10
    # A fresh client stands in for the reloaded page: no in-memory state, only the session cookie.
    reloaded = Api(TestClient(app[0]))
    reloaded.c.cookies.set("awarecare_session", api.c.cookies.get("awarecare_session"))
    assert [i["id"] for i in reloaded.ok("GET", "/cases", 200, "CaseList")["items"]] == [cid]
    read = reloaded.case(cid)
    assert read["case"]["state"] == "review"
    assert {f["kind"]: (f["source_id"], f["value"]) for f in read["case"]["confirmed_context"]
            if f["kind"].startswith("answer:")} == saved
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM answers WHERE case_id=?", (cid,)).fetchone()[0] == 10


def test_expired_case_cannot_be_read_by_its_old_url(app, api):
    """T-R10-S02 (expiry): the old URL is refused as soon as the guest session expires, then the content is purged."""
    from app.modules.privacy.service import sweep
    api.start()
    cid = api.new_case("Expiring synthetic concern.")["id"]
    with app[0].state.ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET last_seen_at='2000-01-01T00:00:00Z'")
    for path in (f"/cases/{cid}", f"/cases/{cid}/records", "/cases"):
        r = api.req("GET", path)
        assert r.status_code == 401 and r.json()["code"] == "SESSION_REQUIRED"
        assert "Expiring synthetic concern" not in r.text and cid not in r.text
    sweep(app[0].state.ctx)
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cases WHERE id=? AND state NOT IN ('deleting','deleted')",
                            (cid,)).fetchone()[0] == 0
    # A new session in the same browser cannot reach the expired case either.
    api.start()
    assert api.req("GET", f"/cases/{cid}").status_code == 404


# #266 (QA 2026-10-19): listCases honours limit (default 20) and a working keyset cursor reaches every case.

def test_history_pages_reach_every_owned_case_newest_first(app, api, other):
    api.start()
    ids = [api.new_case(f"Synthetic concern {i}.")["id"] for i in range(55)]
    with app[0].state.ctx.db.tx() as conn:  # two cases with the same creation time are still ordered and paged
        conn.execute("UPDATE cases SET created_at=(SELECT created_at FROM cases WHERE id=?) WHERE id=?",
                     (ids[1], ids[2]))
    first = api.ok("GET", "/cases", 200, "CaseList")
    assert len(first["items"]) == 20 and first["next_cursor"]
    seen, cursor, pages = [], None, 0
    while True:
        page = api.ok("GET", "/cases?limit=7" + (f"&cursor={cursor}" if cursor else ""), 200, "CaseList")
        pages += 1
        seen += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == 8 and len(seen) == 55 and {c["id"] for c in seen} == set(ids)
    keys = [(c["created_at"], c["id"]) for c in seen]
    assert keys == sorted(keys, reverse=True)
    assert [c["id"] for c in first["items"]] == [c["id"] for c in seen[:20]]
    exact = api.ok("GET", "/cases?limit=50", 200, "CaseList")
    rest = api.ok("GET", f"/cases?limit=50&cursor={exact['next_cursor']}", 200, "CaseList")
    assert len(rest["items"]) == 5 and rest["next_cursor"] is None
    # Another browser's cursor walk never shows these cases.
    other.start()
    assert api.ok("GET", "/cases?limit=1", 200, "CaseList")["next_cursor"]
    assert other.ok("GET", f"/cases?cursor={first['next_cursor']}", 200, "CaseList")["items"] == []


def test_invalid_limits_and_cursors_are_field_errors(api):
    api.start()
    api.new_case()
    for query in ("limit=0", "limit=51", "limit=abc", "cursor=not-a-cursor", "cursor=W10", "cursor="):
        r = api.req("GET", f"/cases?{query}")
        assert r.status_code == 422 and r.json()["code"] == "VALIDATION_FAILED", (query, r.text)
