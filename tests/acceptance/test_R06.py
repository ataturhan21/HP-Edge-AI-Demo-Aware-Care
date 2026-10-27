"""R06 profile saving optional: guest context never creates a persistent profile. M02."""
REQUIREMENT = "R06"


def test_guest_context_creates_no_profile(app, api):
    api.start()
    api.ok("POST", "/cases", 201, "Case", key=True, json={"concern": "Synthetic.", "confirmed_context": [
        {"kind": "age_years", "value": 38, "units": None, "origin": "user", "profile_revision": None}]})
    assert api.ok("GET", "/profile", 200, "ProfileResponse") == {"profile": None}
    r = api.req("PUT", "/profile", json={"expected_revision": None, "profile": {}})
    assert r.status_code in {403, 422}
    if r.status_code == 403:
        assert r.json()["code"] == "SAVED_MODE_REQUIRED"


def test_profile_origin_context_is_refused_for_guests(api):
    api.start()
    r = api.req("POST", "/cases", key=True, json={"concern": "Synthetic.", "confirmed_context": [
        {"kind": "age_years", "value": 38, "units": None, "origin": "profile", "profile_revision": 1}]})
    assert r.status_code == 422


def test_guest_history_medications_and_allergies_stay_in_the_case_only(app, api):
    """T-R06-S01: guest context is usable in the case under guest retention; no persistent profile record exists."""
    from datetime import datetime, timedelta
    created = api.start()
    items = [{"kind": "history", "value": "Fictional history", "units": None, "origin": "user", "profile_revision": None},
             {"kind": "medications", "value": "Fictional medication", "units": None, "origin": "user",
              "profile_revision": None},
             {"kind": "allergy_status", "value": "reported", "units": None, "origin": "user", "profile_revision": None},
             {"kind": "allergies", "value": "Fictional allergy", "units": None, "origin": "user", "profile_revision": None}]
    case = api.ok("POST", "/cases", 201, "Case", key=True, json={"concern": "Synthetic.", "confirmed_context": items})
    stored = {f["kind"]: f["value"] for f in api.case(case["id"])["case"]["confirmed_context"]}
    assert stored["history"] == "Fictional history" and stored["medications"] == "Fictional medication"
    assert stored["allergies"] == "Fictional allergy"
    # Guest retention: the case expires with the guest session (no later than the 8 h absolute limit).
    expires = datetime.fromisoformat(api.case(case["id"])["case"]["expires_at"].replace("Z", "+00:00"))
    started = datetime.fromisoformat(created["expires_at"].replace("Z", "+00:00")) - timedelta(minutes=30)
    assert expires <= started + timedelta(hours=8, minutes=1)
    assert api.ok("GET", "/profile", 200, "ProfileResponse")["profile"] is None
    with app[0].state.ctx.db.read() as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert not [t for t in tables if "profile" in t]  # no persistent profile store exists for guests
