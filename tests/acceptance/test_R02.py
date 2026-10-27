"""R02 versioned consent and write protection (CONSENT_REQUIRED, CSRF). M01."""
import pytest

from app.core.security import CURRENT_CONSENT_VERSION

REQUIREMENT = "R02"


def test_health_write_without_session_is_rejected(api):
    r = api.req("POST", "/cases", key=True, json={"concern": "x", "confirmed_context": []})
    assert r.status_code == 401


def test_outdated_consent_version_is_rejected(api):
    r = api.req("POST", "/sessions", key=True,
                json={"mode": "guest", "consent_version": "old-version", "adult_eligible": True})
    assert r.status_code == 403 and r.json()["code"] == "CONSENT_REQUIRED"


def test_adult_ineligible_never_gets_health_session(api):
    r = api.req("POST", "/sessions", key=True,
                json={"mode": "guest", "consent_version": CURRENT_CONSENT_VERSION, "adult_eligible": False})
    assert r.status_code == 403 and "awarecare_session" not in api.c.cookies


def test_saved_mode_is_refused_without_identity_layer(api):
    r = api.req("POST", "/sessions", key=True,
                json={"mode": "saved", "consent_version": CURRENT_CONSENT_VERSION, "adult_eligible": True})
    assert r.status_code == 403 and r.json()["code"] == "SAVED_MODE_UNAVAILABLE"


def test_write_requires_matching_csrf(api):
    api.start()
    r = api.req("POST", "/cases", key=True, headers={"X-CSRF-Token": "wrong"},
                json={"concern": "x", "confirmed_context": []})
    assert r.status_code == 403 and r.json()["code"] == "CSRF_REJECTED"
    assert api.ok("GET", "/cases", 200, "CaseList")["items"] == []


def test_consent_is_recorded_with_version_and_time(app, api):
    created = api.start()
    with app[0].state.ctx.db.read() as conn:
        row = conn.execute("SELECT consent_version, consent_at FROM sessions WHERE id=?",
                           (created["session_id"],)).fetchone()
    assert row["consent_version"] == CURRENT_CONSENT_VERSION and row["consent_at"]


def _world_counts(app) -> dict:
    tables = ("cases", "facts", "answers", "documents", "fact_reviews", "jobs", "provider_searches", "exports",
              "guidance", "questions")
    with app[0].state.ctx.db.read() as conn:
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        counts["revisions"] = [r[0] for r in conn.execute("SELECT revision FROM cases ORDER BY id")]
    return counts


def test_every_health_write_requires_current_recorded_consent(app, api):
    """T-R02-S01: with missing or obsolete consent on the session, each health write is refused, nothing changes."""
    from records_helpers import SAMPLE
    from test_R03 import SEARCH
    api.start()
    cid = api.new_case()["id"]
    question = api.ok("POST", f"/cases/{cid}/questions/next", 200, "NextQuestionResponse", key=True,
                      json={"expected_revision": 1})["question"]
    writes = [
        ("POST", "/cases", {"key": True, "json": {"concern": "Another synthetic concern.", "confirmed_context": []}}),
        ("PATCH", f"/cases/{cid}", {"json": {"expected_revision": 1, "concern": "Changed"}}),
        ("POST", f"/cases/{cid}/questions/next", {"key": True, "json": {"expected_revision": 1}}),
        ("PUT", f"/cases/{cid}/answers/{question['id']}", {"json": {"expected_revision": 1, "status": "unknown",
                                                                     "value": None}}),
        ("POST", f"/cases/{cid}/records", {"key": True, "files": {"file": ("r.pdf", SAMPLE, "application/pdf")},
                                           "data": {"expected_revision": "1"}}),
        ("PATCH", f"/cases/{cid}/facts/00000000-0000-4000-8000-000000000000",
         {"json": {"expected_revision": 1, "action": "confirm"}}),
        ("POST", f"/cases/{cid}/review", {"json": {"expected_revision": 1, "facts_confirmed": True}}),
        ("POST", f"/cases/{cid}/guidance", {"key": True, "json": {"expected_revision": 1}}),
        ("POST", f"/cases/{cid}/provider-search", {"json": {"expected_revision": 1, "criteria": SEARCH}}),
        ("POST", f"/cases/{cid}/exports", {"key": True, "json": {"expected_revision": 1, "user_reviewed": True}}),
        ("PUT", "/profile", {"json": {}}),
    ]
    for consent in ("aware-care-demo-consent-0.9", ""):  # obsolete, then missing
        with app[0].state.ctx.db.tx() as conn:
            conn.execute("UPDATE sessions SET consent_version=?", (consent,))
        before = _world_counts(app)
        for method, path, kw in writes:
            r = api.req(method, path, **kw)
            assert r.status_code == 403 and r.json()["code"] == "CONSENT_REQUIRED", (consent, method, path, r.text[:120])
        assert _world_counts(app) == before, consent
    # Readiness stays reachable without consent (help is a public page: tests/ui/W05.spec.ts).
    assert api.req("GET", "/health/ready").status_code == 200


def test_writes_depend_on_the_recorded_consent_in_utc(app, api):
    """T-R02-S02: version and UTC time are recorded; later writes are authorized by that record, not the request."""
    from datetime import datetime, timedelta
    created = api.start()
    with app[0].state.ctx.db.read() as conn:
        row = conn.execute("SELECT consent_version, consent_at FROM sessions WHERE id=?",
                           (created["session_id"],)).fetchone()
    assert row["consent_version"] == CURRENT_CONSENT_VERSION
    stamp = datetime.fromisoformat(row["consent_at"].replace("Z", "+00:00"))
    assert stamp.utcoffset() == timedelta(0)
    api.new_case()  # authorized by the recorded consent
    with app[0].state.ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET consent_version='withdrawn' WHERE id=?", (created["session_id"],))
    r = api.req("POST", "/cases", key=True, json={"concern": "Synthetic.", "confirmed_context": []})
    assert r.status_code == 403 and r.json()["code"] == "CONSENT_REQUIRED"
    # Client-supplied role or actor fields never confer authority (also test_R03 payload test).
    for extra in ({"actor_id": created["actor_id"]}, {"role": "presenter"}, {"consent_version": CURRENT_CONSENT_VERSION}):
        r = api.req("POST", "/cases", key=True, json={"concern": "Synthetic.", "confirmed_context": [], **extra})
        assert r.status_code in {403, 422}, extra


def test_a_non_ascii_csrf_token_is_refused_not_a_server_error(api):
    """#156: compare_digest raised TypeError on a non-ASCII str, so a malformed token gave a 500, not a 403."""
    api.start()
    r = api.req("POST", "/cases", key=True, headers={"X-CSRF-Token": "caf\xe9-token".encode("latin-1")},
                json={"concern": "x", "confirmed_context": []})
    assert r.status_code == 403 and r.json()["code"] == "CSRF_REJECTED"


# --- #463 (S-07, QA 2026-10-22): consent, confirmations and revisions are strict JSON types, never coerced ----------


@pytest.mark.parametrize("value", ["yes", "on", "true", "1", 1, 1.0])
def test_463_adult_eligibility_must_be_the_json_boolean_true(app, api, value):
    r = api.req("POST", "/sessions", key=True,
                json={"mode": "guest", "consent_version": CURRENT_CONSENT_VERSION, "adult_eligible": value})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_FAILED", (value, r.status_code)
    assert r.json()["field_errors"][0]["field"] == "adult_eligible"
    assert "awarecare_session" not in api.c.cookies
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0] == 0


@pytest.mark.parametrize("revision", ["1", True, 1.0])
def test_463_an_expected_revision_must_be_a_json_integer(api, revision):
    api.start()
    case = api.new_case("Synthetic QA: headache.")
    edit = api.req("PATCH", f"/cases/{case['id']}", json={"expected_revision": revision, "concern": "Synthetic QA: 1"})
    assert edit.status_code == 422 and edit.json()["field_errors"][0]["field"] == "expected_revision", edit.text
    nxt = api.req("POST", f"/cases/{case['id']}/questions/next", key=True, json={"expected_revision": revision})
    assert nxt.status_code == 422, nxt.text
    after = api.case(case["id"])["case"]
    assert after["revision"] == 1 and after["concern"] == "Synthetic QA: headache." and after["issued_slots"] == 0


@pytest.mark.parametrize("value", [1, 1.0, "true"])
def test_463_review_and_export_confirmations_must_be_the_json_boolean_true(api, value):
    api.start()
    case = api.new_case()
    api.answer_all(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    review = api.req("POST", f"/cases/{case['id']}/review", json={"expected_revision": rev, "facts_confirmed": value})
    assert review.status_code == 422 and review.json()["field_errors"][0]["field"] == "facts_confirmed"
    assert api.case(case["id"])["case"]["state"] == "review"
    api.ok("POST", f"/cases/{case['id']}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    job = api.ok("POST", f"/cases/{case['id']}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    api.wait_job(job["id"])
    export = api.req("POST", f"/cases/{case['id']}/exports", key=True,
                     json={"expected_revision": rev, "user_reviewed": value})
    assert export.status_code == 422 and export.json()["field_errors"][0]["field"] == "user_reviewed"
    api.ok("POST", f"/cases/{case['id']}/exports", 202, "Job", key=True,
           json={"expected_revision": rev, "user_reviewed": True})
