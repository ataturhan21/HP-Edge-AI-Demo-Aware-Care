"""R03 owner and role boundaries: every foreign case/job/file/export access is a non-disclosing 404. M01/M02."""
import time
from dataclasses import replace

from fastapi.testclient import TestClient

from app.core.security import CURRENT_CONSENT_VERSION
from conftest import Api, presenter_assertion, presenter_auth
from records_helpers import records, upload_ok

REQUIREMENT = "R03"
SEARCH = {"location": {"location_id": None, "city": "Dallas", "region": "TX", "postal_code": None},
          "radius_miles": 25, "specialty_ids": ["primary_care"], "exact_plan_id": None,
          "required_verified_plan": False, "visit_type": "in_person", "language": None, "required_language": False,
          "ranked_preferences": []}


def owned_world(api) -> dict:
    """A guided case with a record fact, a provider search, a finished export and jobs."""
    api.start()
    case = api.new_case()
    cid = case["id"]
    upload_job = upload_ok(api, cid)
    fact = records(api, cid)["facts"][0]
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    search = api.ok("POST", f"/cases/{cid}/provider-search", 200, "ProviderSearchResult",
                    json={"expected_revision": rev, "criteria": SEARCH})
    job = api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                 json={"expected_revision": rev, "user_reviewed": True})
    export = api.wait_job(job["id"])
    qid = next(f["source_id"] for f in api.case(cid)["case"]["confirmed_context"] if f["kind"] == "answer:Q01")
    return {"case": cid, "rev": rev, "fact": fact["id"],
            "provider": f'{search["matches"][0]["provider_id"]}?search_id={search["id"]}',  # #267
            "export": export["result_id"], "job": job["id"], "upload_job": upload_job["id"], "question": qid}


def test_foreign_actor_gets_404_everywhere_without_side_effects(app, api, other):
    w = owned_world(api)
    c, rev = w["case"], w["rev"]
    other.start()
    attempts = [
        ("GET", f"/cases/{c}", {}),
        ("PATCH", f"/cases/{c}", {"json": {"expected_revision": rev, "concern": "hijack"}}),
        ("DELETE", f"/cases/{c}?expected_revision={rev}", {}),
        ("GET", f"/cases/{c}/records", {}),
        ("POST", f"/cases/{c}/records", {"key": True, "files": {"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
                                        "data": {"expected_revision": str(rev)}}),
        ("PATCH", f"/cases/{c}/facts/{w['fact']}", {"json": {"expected_revision": rev, "action": "confirm"}}),
        ("POST", f"/cases/{c}/questions/next", {"key": True, "json": {"expected_revision": rev}}),
        ("PUT", f"/cases/{c}/answers/{w['question']}", {"json": {"expected_revision": rev, "status": "unknown",
                                                                 "value": None}}),
        ("POST", f"/cases/{c}/review", {"json": {"expected_revision": rev, "facts_confirmed": True}}),
        ("POST", f"/cases/{c}/guidance", {"key": True, "json": {"expected_revision": rev}}),
        ("GET", f"/cases/{c}/guidance", {}),
        ("GET", f"/cases/{c}/sources", {}),
        ("POST", f"/cases/{c}/provider-search", {"json": {"expected_revision": rev, "criteria": SEARCH}}),
        ("GET", f"/cases/{c}/providers/{w['provider']}", {}),
        ("POST", f"/cases/{c}/exports", {"key": True, "json": {"expected_revision": rev, "user_reviewed": True}}),
        ("GET", f"/exports/{w['export']}/download", {}),
        ("GET", f"/jobs/{w['job']}", {}),
        ("GET", f"/jobs/{w['upload_job']}", {}),
    ]
    for method, path, kw in attempts:
        r = other.req(method, path, **kw)
        assert r.status_code == 404, (method, path, r.status_code, r.text[:120])
        assert c not in r.text and "hijack" not in r.text
    assert other.ok("GET", "/cases", 200, "CaseList")["items"] == []
    # The owner's case is untouched.
    read = api.case(c)
    assert read["case"]["revision"] == rev and read["case"]["state"] == "guided"


def test_presenter_routes_reject_guest_role(api):
    api.start()
    for method, path in (("GET", "/presenter/runtime"), ("GET", "/presenter/controls")):
        r = api.req(method, path)
        assert r.status_code == 403 and r.json()["code"] == "PRESENTER_REQUIRED"
    assert api.req("POST", "/presenter/scenarios/urgent/load", key=True, json={"reset": True}).status_code == 403


# --- ADR-005 option A: presenter role only through the presenter gateway (T-R03-S02) -------------------------

def _presenter_session(app, assertion: str | None):
    """A fresh browser that asks createSession with an explicit presenter header value (or none)."""
    client = TestClient(app[0])
    api = Api(client)
    headers = {presenter_auth.HEADER: assertion} if assertion is not None else {}
    return api, api.req("POST", "/sessions", key=True, headers=headers,
                        json={"mode": "guest", "consent_version": CURRENT_CONSENT_VERSION, "adult_eligible": True})


def _runtime_status(api, assertion: str | None) -> tuple[int, str]:
    headers = {presenter_auth.HEADER: assertion} if assertion is not None else {}
    r = api.req("GET", "/presenter/runtime", headers=headers)
    return r.status_code, r.json().get("code", "")


def test_valid_assertion_creates_presenter_session_with_runtime_access(app, presenter):
    snapshot = presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")
    assert snapshot["mode"] == "mock"
    with app[0].state.ctx.db.read() as conn:
        kinds = [r[0] for r in conn.execute("SELECT kind FROM actors")]
    assert kinds == ["presenter"]
    assert presenter.req("POST", "/cases", key=True, json={"concern": "x", "confirmed_context": []}).status_code == 403


def test_forged_assertion_is_refused_and_no_session_is_created(app):
    forged = presenter_assertion(key=b"not-the-gateway-key-0123456789abcdef")
    api, r = _presenter_session(app, forged)
    assert r.status_code == 403 and r.json()["code"] == "PRESENTER_REQUIRED"
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0] == 0
    assert _presenter_session(app, "v1.not-an-assertion")[1].status_code == 403


def test_replayed_assertion_is_refused_for_session_creation(app):
    assertion = presenter_assertion()
    _, first = _presenter_session(app, assertion)
    assert first.status_code == 201
    _, replay = _presenter_session(app, assertion)
    assert replay.status_code == 403 and replay.json()["code"] == "PRESENTER_REQUIRED"


def test_stale_assertion_is_refused(app):
    _, r = _presenter_session(app, presenter_assertion(ts=time.time() - 120))
    assert r.status_code == 403


def test_presenter_cookie_without_gateway_assertion_is_not_authority(presenter):
    # The patient gateway strips the header, so this is what a presenter cookie looks like there. Without a valid
    # assertion the presenter cookie is not even read (ADR-005 A, separate cookie), so there is no session at all.
    presenter.presenter = False
    assert _runtime_status(presenter, None) == (401, "SESSION_REQUIRED")
    assert _runtime_status(presenter, presenter_assertion(key=b"wrong-key-0123456789abcdef0123456789")) == \
        (401, "SESSION_REQUIRED")
    assert presenter.req("POST", "/presenter/reset", key=True).status_code == 401


def test_assertion_from_untrusted_peer_is_refused(app):
    app[0].state.ctx.settings = replace(app[0].state.ctx.settings, presenter_trusted_peers=("127.0.0.1",))
    _, r = _presenter_session(app, presenter_assertion())
    assert r.status_code == 403


def test_presenter_access_is_disabled_without_a_key(app):
    app[0].state.ctx.settings = replace(app[0].state.ctx.settings, presenter_key=None)
    _, r = _presenter_session(app, presenter_assertion())
    assert r.status_code == 403
    api, created = _presenter_session(app, None)
    assert created.status_code == 201
    assert _runtime_status(api, presenter_assertion()) == (403, "PRESENTER_REQUIRED")


def test_session_payload_cannot_carry_identity_or_role(app):
    """T-R03-S02: identity and role come only from the server; extra or altered body fields are refused."""
    api = Api(TestClient(app[0]))
    base = {"mode": "guest", "consent_version": CURRENT_CONSENT_VERSION, "adult_eligible": True}
    attempts = [{"actor_id": "00000000-0000-4000-8000-000000000001"},
                {"session_id": "00000000-0000-4000-8000-000000000002"},
                {"role": "presenter"},
                {"actor_id": "00000000-0000-4000-8000-000000000003", "role": "presenter", "kind": "presenter"},
                {"mode": "presenter"}]
    for extra in attempts:
        r = api.req("POST", "/sessions", key=True, json={**base, **extra})
        assert r.status_code == 422, (extra, r.status_code)
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_presenter_and_patient_sessions_coexist_without_crossing(app):
    """One browser (one cookie jar) holds both sessions; the gateway decides which applies (ADR-005 A)."""
    client = TestClient(app[0])
    patient, pres = Api(client), Api(client, presenter=True)
    patient.start()
    pres.start()
    assert {"awarecare_session", "awarecare_presenter"} <= set(client.cookies.keys())
    case = patient.new_case()  # still the patient session after the presenter session was created
    assert pres.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")["mode"] == "mock"
    assert patient.req("GET", f"/cases/{case['id']}").status_code == 200
    # Through the presenter gateway the patient session is invisible, and the reverse.
    assert pres.req("GET", f"/cases/{case['id']}").status_code in {403, 404}
    assert patient.req("GET", "/presenter/runtime").status_code == 403


def _cookie_paths(response) -> dict[str, str]:
    """Each Set-Cookie of a response: name -> its Path attribute (lower case)."""
    out = {}
    for raw in response.headers.get_list("set-cookie"):
        name = raw.split("=", 1)[0]
        attrs = dict((part.strip().split("=", 1) + [""])[:2] for part in raw.split(";")[1:])
        out[name] = {k.lower(): v for k, v in attrs.items()}.get("path", "")
    return out


def test_487_every_cookie_reaches_both_api_paths_of_the_one_address(app):
    """#487 (ADR-005 amendment): one address serves the patient API (/api/...) and the presenter API (/presenter-api/...,
    which the gateway maps to the API's /api/...). Every cookie is scoped to "/", so the browser sends each to both
    prefixes, as it sent them to both ports before: the pre-session nonce, the presenter session and its lineage, the
    demo patient session a scenario hands the patient tab, and the removal of a session cookie. The role still comes
    only from the verified assertion (the tests above); a cookie never grants it."""
    client = TestClient(app[0])
    assert _cookie_paths(client.get("/api/v1/health/ready")) == {"awarecare_presession": "/"}
    pres = Api(client, presenter=True)
    created = pres.req("POST", "/sessions", key=True, json={"mode": "guest", "consent_version": CURRENT_CONSENT_VERSION,
                                                            "adult_eligible": True})
    assert created.status_code == 201
    assert _cookie_paths(created) == {"awarecare_presenter": "/", "awarecare_presenter_lineage": "/"}
    loaded = pres.req("POST", "/presenter/scenarios/routine/load", key=True, json={"reset": True})
    assert loaded.status_code == 201, loaded.text
    assert _cookie_paths(loaded) == {"awarecare_session": "/"}
    # The demo patient session works on the patient API of the same address (the presenter's patient tab).
    patient = Api(client)
    assert patient.req("GET", f"/cases/{loaded.json()['case_id']}").status_code == 200
    ended = pres.req("DELETE", "/sessions/current")
    assert ended.status_code == 202
    assert _cookie_paths(ended) == {"awarecare_presenter": "/"}


def test_foreign_and_absent_ids_get_the_same_non_disclosing_answer(app, api, other):
    """T-R03-S01: a foreign ID is indistinguishable from an absent one, and nothing of the owner's leaks."""
    import uuid as _uuid
    w = owned_world(api)
    with app[0].state.ctx.db.read() as conn:
        doc_secrets = [v for r in conn.execute("SELECT id, display_name, storage_key FROM documents") for v in r if v]
    assert doc_secrets  # the owner really has a document with a filename and storage key
    concern = api.case(w["case"])["case"]["concern"]
    other.start()
    other.new_case()  # B has its own data; A's IDs are foreign to B

    def probes(ids):
        c, rev = ids["case"], w["rev"]
        return [
            ("GET", f"/cases/{c}", {}), ("GET", f"/cases/{c}/records", {}), ("GET", f"/cases/{c}/guidance", {}),
            ("GET", f"/cases/{c}/sources", {}), ("GET", f"/cases/{c}/providers/{ids['provider']}", {}),
            ("PATCH", f"/cases/{c}", {"json": {"expected_revision": rev, "concern": "x"}}),
            ("PATCH", f"/cases/{c}/facts/{ids['fact']}", {"json": {"expected_revision": rev, "action": "confirm"}}),
            ("PUT", f"/cases/{c}/answers/{ids['question']}", {"json": {"expected_revision": rev, "status": "unknown",
                                                                       "value": None}}),
            ("GET", f"/exports/{ids['export']}/download", {}), ("GET", f"/jobs/{ids['job']}", {}),
            ("GET", f"/jobs/{ids['upload_job']}", {}),
        ]
    absent = {k: str(_uuid.uuid4()) for k in ("case", "fact", "export", "job", "upload_job")}
    absent.update(provider=w["provider"], question=w["question"])
    for (m, path, kw), (_, apath, akw) in zip(probes(w), probes(absent)):
        foreign_r, absent_r = other.req(m, path, **kw), other.req(m, apath, **akw)
        assert foreign_r.status_code == absent_r.status_code == 404, (m, path, foreign_r.status_code, absent_r.status_code)
        fb, ab = foreign_r.json(), absent_r.json()
        assert (fb["code"], fb["message"], fb.get("field_errors")) == (ab["code"], ab["message"], ab.get("field_errors")), path
        text = foreign_r.text
        assert "%PDF" not in text and concern not in text and w["case"] not in text
        for secret in [w["fact"], w["export"], *doc_secrets]:
            assert secret not in text, (path, secret)
