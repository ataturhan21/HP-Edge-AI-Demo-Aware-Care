"""R01 guest session isolation (T-R01-S01/S02). M01 createSession."""
from conftest import ORIGIN
from app.core.security import CURRENT_CONSENT_VERSION

REQUIREMENT = "R01"
BODY = {"mode": "guest", "consent_version": CURRENT_CONSENT_VERSION, "adult_eligible": True}


def actor_count(app) -> int:
    with app[0].state.ctx.db.read() as conn:
        return conn.execute("SELECT COUNT(*) FROM actors WHERE kind='guest'").fetchone()[0]


def live_sessions(app) -> int:
    with app[0].state.ctx.db.read() as conn:
        return conn.execute("SELECT COUNT(*) FROM sessions WHERE revoked=0").fetchone()[0]


def test_refresh_reuses_session_and_actor(app, api):
    """Accepting consent again with a valid cookie continues the same actor (no second actor). #434: it does so under a
    rotated session (new ID and token, the old one revoked), never by reusing the token the browser presented."""
    first = api.start()
    again = api.start()  # refresh / revisit A01 with a valid cookie
    assert again["actor_id"] == first["actor_id"] and again["session_id"] != first["session_id"]
    assert actor_count(app) == 1 and live_sessions(app) == 1


def test_same_idempotency_key_replays_without_second_actor(app, api):
    headers = api.headers(key=True)
    r1 = api.c.post("/api/v1/sessions", json=BODY, headers=headers)
    api.c.cookies.delete("awarecare_session")  # response lost before the cookie was kept
    r2 = api.c.post("/api/v1/sessions", json=BODY, headers=headers)
    assert r1.status_code == r2.status_code == 201
    assert r1.json() == r2.json() and actor_count(app) == 1


def test_fresh_browser_cannot_read_other_case(api, other):
    api.start()
    case = api.new_case()
    other.start()
    r = other.req("GET", f"/cases/{case['id']}")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_origin_is_checked_before_session_exists(api):
    r = api.c.post("/api/v1/sessions", json=BODY,
                   headers={"Origin": "http://evil.example", "Idempotency-Key": "k" * 16})
    assert r.status_code == 403 and r.json()["code"] == "ORIGIN_REJECTED"
    assert "awarecare_session" not in api.c.cookies


def test_client_cannot_assign_role_or_actor(api):
    r = api.c.post("/api/v1/sessions", json={**BODY, "role": "presenter"},
                   headers={"Origin": ORIGIN, "Idempotency-Key": "k" * 16})
    assert r.status_code == 422


def test_revisiting_start_keeps_owner_and_creates_no_duplicate_context(app, api):
    """T-R01-S02: reopening A01 with a valid session continues its actor (rotated session, #434); the case stays owned
    and is not duplicated."""
    first = api.start()
    case = api.new_case()
    again = api.start()  # A01 opened again with the same valid session cookie
    assert again["actor_id"] == first["actor_id"] and again["session_id"] != first["session_id"]
    read = api.case(case["id"])
    assert read["case"]["actor_id"] == first["actor_id"]
    listed = api.ok("GET", "/cases", 200, "CaseList")
    assert [c["id"] for c in listed["items"]] == [case["id"]]
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM sessions WHERE revoked=0").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1


# --- #434 (S-05, QA 2026-10-22): session fixation ------------------------------------------------------------------

def test_434_consent_issues_a_new_session_so_a_planted_token_reads_nothing_entered_after(app):
    """An attacker starts a session and plants its cookie in the victim's browser (cookies are shared by every port of
    127.0.0.1). The victim's consent must issue a fresh token (Set-Cookie) and end the planted one, so the attacker
    cannot read the concern entered afterwards."""
    from fastapi.testclient import TestClient
    from conftest import Api
    attacker = Api(TestClient(app[0]))
    created = attacker.headers(key=True)
    planted = attacker.c.post("/api/v1/sessions", json=BODY, headers=created).json()
    token = attacker.c.cookies.get("awarecare_session")
    victim = Api(TestClient(app[0]))
    victim.c.cookies.set("awarecare_session", token, domain="testserver.local", path="/")
    r = victim.req("POST", "/sessions", key=True, json=BODY)
    assert r.status_code == 201, r.text
    assert "awarecare_session=" in r.headers.get("set-cookie", ""), "consent must issue a new session cookie"
    assert r.json()["session_id"] != planted["session_id"]
    assert victim.c.cookies.get("awarecare_session") != token
    case = victim.new_case("Synthetic QA victim concern: chest tightness when climbing stairs.")
    # The planted token was ended by the consent: it reads nothing, not even its own list.
    assert attacker.req("GET", f"/cases/{case['id']}").status_code == 401
    assert attacker.req("GET", "/cases").status_code == 401
    # Nor can the attacker get it back by replaying its own creation request: that session has ended.
    replay = attacker.c.post("/api/v1/sessions", json=BODY, headers=created)
    assert replay.status_code == 409 and replay.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert attacker.req("GET", f"/cases/{case['id']}").status_code == 401
    assert victim.case(case["id"])["case"]["concern"].startswith("Synthetic QA victim concern")


def test_434_a_presenter_session_is_rotated_the_same_way(app, presenter):
    first_token = presenter.c.cookies.get("awarecare_presenter")
    again = presenter.req("POST", "/sessions", key=True, json=BODY)
    assert again.status_code == 201 and "awarecare_presenter=" in again.headers.get("set-cookie", "")
    assert presenter.c.cookies.get("awarecare_presenter") != first_token
    assert presenter.req("GET", "/presenter/runtime").status_code == 200
