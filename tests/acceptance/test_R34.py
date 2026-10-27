"""R34 local boundary, server side (#156): request bodies are bounded even without Content-Length, unhandled errors are
logged content-free, the API image keeps no access log of request paths, and the audit column upgrade is in place."""

from conftest import ORIGIN, validate

REQUIREMENT = "R34"


def test_a_chunked_body_over_the_limit_is_refused_and_one_within_it_passes(api):
    """A body without Content-Length (chunked) skipped the size check; it is now read only up to the route's limit
    and refused with 413 in the API's error format."""
    api.start()
    case = api.new_case()
    big = api.req("PATCH", f"/cases/{case['id']}", headers={"Content-Type": "application/json"},
                  content=iter([b'{"expected_revision": 1, "concern": "', b"A" * 300_000, b'"}']))
    assert big.status_code == 413 and big.json()["code"] == "REQUEST_TOO_LARGE" and big.headers.get("X-Request-ID")
    small = api.req("PATCH", f"/cases/{case['id']}", headers={"Content-Type": "application/json"},
                    content=iter([b'{"expected_revision": ', str(case["revision"]).encode(),
                                  b', "concern": "Synthetic concern, edited through a chunked body."}']))
    assert small.status_code == 200, small.text
    assert api.case(case["id"])["case"]["concern"] == "Synthetic concern, edited through a chunked body."


def test_unhandled_errors_are_logged_content_free(app, api, caplog, monkeypatch):
    """An unhandled error logs its type, the route template and the request ID: never the raw path (with IDs), the
    exception message or a traceback. uvicorn's own traceback record is reduced the same way."""
    import logging
    from fastapi.testclient import TestClient
    from app.core.errors import ContentFreeErrors
    from app.modules.cases import service
    api.start()
    case = api.new_case()

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic secret concern text")
    monkeypatch.setattr(service, "read_case", boom)
    client = TestClient(app[0], raise_server_exceptions=False)
    client.cookies = api.c.cookies
    with caplog.at_level(logging.ERROR, logger="aware_care"):
        r = client.get(f"/api/v1/cases/{case['id']}")
    assert r.status_code == 500 and r.json()["code"] == "INTERNAL_ERROR"
    lines = [rec.getMessage() for rec in caplog.records if rec.name == "aware_care"]
    assert any("unhandled_error type=RuntimeError route=/cases/{case_id} method=GET request_id=" in line for line in lines), lines
    assert all(case["id"] not in line and "secret" not in line for line in lines)
    record = logging.LogRecord("uvicorn.error", logging.ERROR, __file__, 1, "Exception in ASGI application", (),
                               (RuntimeError, RuntimeError("synthetic secret concern text"), None))
    ContentFreeErrors().filter(record)
    assert record.exc_info is None and "secret" not in record.getMessage() and "RuntimeError" in record.getMessage()


def test_an_events_table_from_before_the_audit_column_is_upgraded_in_place(tmp_path):
    """Databases created before ADR-005's audit column get `actor_ref` added; their rows stay readable."""
    import sqlite3
    from app.core.db import Database
    path = tmp_path / "old.sqlite3"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE events (id TEXT PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, operation_id TEXT, "
                "status TEXT NOT NULL, error_code TEXT, duration_ms REAL)")
    old.execute("INSERT INTO events VALUES ('e1', '2026-10-01T00:00:00Z', 'case_created', 'createCase', 'intake', NULL, NULL)")
    old.commit()
    old.close()
    db = Database(path)
    with db.read() as conn:
        assert "actor_ref" in {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
        assert conn.execute("SELECT kind FROM events").fetchone()["kind"] == "case_created"


def test_the_api_image_runs_without_an_access_log():
    """Request lines carry case, question and export IDs, so uvicorn's access log is off in the image."""
    from conftest import ROOT
    assert '"--no-access-log"' in (ROOT / "infra/deploy/api.Dockerfile").read_text()


def test_a_non_numeric_content_length_is_a_malformed_request(api):
    """#269: it was answered 413 (too large) instead of 400."""
    api.start()
    for value in ("abc", "12a", "-5", "1e3"):
        r = api.req("POST", "/cases", key=True, content=b'{"concern":"x","confirmed_context":[]}',
                    headers={"Content-Type": "application/json", "Content-Length": value})
        assert r.status_code == 400 and r.json()["code"] == "MALFORMED_REQUEST", (value, r.status_code)
    r = api.req("POST", "/cases", key=True, content=b"{}",
                headers={"Content-Type": "application/json", "Content-Length": str(10 * 1024 * 1024)})
    assert r.status_code == 413


# --- #431 (S-02, QA 2026-10-22): the body limit follows the exact route, before any parsing or session lookup --------

def asgi_call(application, method: str, path: str, body: bytes, headers: dict[str, str] | None = None
              ) -> tuple[int, dict, int]:
    """Call the ASGI app directly and count how often it asks for the request body. Returns (status, error body,
    receive calls); a refusal before reading the body makes no receive call."""
    import asyncio
    import json as _json
    calls, out = [0], {"status": 0, "body": b""}
    given = {"origin": ORIGIN, "content-type": "application/json", "content-length": str(len(body)),
             **{k.lower(): v for k, v in (headers or {}).items()}}
    raw = [(k.encode(), v.encode()) for k, v in given.items()]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "", "headers": raw,
             "client": ("testclient", 50000), "server": ("testserver", 80), "app": application,
             "state": {}}

    async def receive():
        calls[0] += 1
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
        elif message["type"] == "http.response.body":
            out["body"] += message.get("body", b"")

    asyncio.run(application(scope, receive, send))
    return out["status"], _json.loads(out["body"] or b"null"), calls[0]


ROUTES_ENDING_IN_RECORDS = [("PATCH", "/api/v1/cases/records"), ("PUT", "/api/v1/cases/x/answers/records"),
                            ("PATCH", "/api/v1/cases/x/facts/records"), ("POST", "/api/v1/cases/x/records/records")]


def test_431_a_json_body_over_256_kib_is_refused_on_every_route_whose_path_ends_in_records(app):
    """Only uploadRecord (POST /cases/{case_id}/records) has the 30 MiB allowance. Any other request whose last path
    segment is "records" was parsed with that allowance and answered 401 after the JSON was decoded."""
    body = b'{"expected_revision":1,"concern":"x","confirmed_context":[' + b"0," * (150 * 1024) + b"0]}"
    assert len(body) > 256 * 1024
    for method, path in ROUTES_ENDING_IN_RECORDS:
        status, error, reads = asgi_call(app[0], method, path, body)
        assert (status, error["code"], reads) == (413, "REQUEST_TOO_LARGE", 0), (method, path, status, reads)
        validate("Error", error)
    assert asgi_call(app[0], "GET", "/api/v1/cases/records", body)[0] == 413  # any method, as before


def test_431_a_chunked_body_gets_the_json_limit_on_those_routes_too(api):
    chunks = [b'{"expected_revision":1,"concern":"', b"A" * 300_000, b'"}']
    for method, path in ROUTES_ENDING_IN_RECORDS:
        r = api.c.request(method, path, headers={"Origin": ORIGIN, "Content-Type": "application/json"},
                          content=iter(chunks))
        assert r.status_code == 413 and r.json()["code"] == "REQUEST_TOO_LARGE", (method, path, r.status_code)


def test_431_an_upload_without_a_session_is_refused_before_its_body_is_read(app):
    """The upload route keeps its 30 MiB allowance only for a valid session: without one it is answered 401 before a
    byte of the body is read or parsed (it used to be parsed first)."""
    status, error, reads = asgi_call(app[0], "POST", "/api/v1/cases/0b0b0b0b-0000-0000-0000-000000000000/records",
                                     b"x" * (1024 * 1024), {"content-type": "multipart/form-data; boundary=b"})
    assert (status, error["code"], reads) == (401, "SESSION_REQUIRED", 0)
    status, error, reads = asgi_call(app[0], "POST", "/api/v1/cases/x/records", b"x" * (31 * 1024 * 1024))
    assert (status, error["code"], reads) == (413, "REQUEST_TOO_LARGE", 0)


def test_431_a_valid_upload_still_gets_its_allowance(app, api):
    from records_helpers import upload
    api.start()
    case = api.new_case()
    r = upload(api, case["id"], b"%PDF-1.4\n" + b"0" * (300 * 1024), "application/pdf")
    assert r.status_code == 422 and r.json()["code"] == "RECORD_MALFORMED"  # read and validated, not 413


# --- #464 (S-08): the framework's own refusals answer in the Error schema; HEAD answers like GET without a body -----

def test_464_undecodable_bodies_unknown_paths_and_wrong_methods_answer_in_the_error_schema(api):
    deep = b'{"mode": ' + b"[" * 30000 + b"]" * 30000 + b"}"
    big_int = b'{"concern": "x", "confirmed_context": [{"kind": "age_years", "value": ' + b"9" * 5000 + \
        b', "units": null, "origin": "user", "profile_revision": null}]}'
    for path, body in (("/sessions", b'{"mode":"guest","consent_version":"\xff","adult_eligible":true}'),
                       ("/sessions", deep), ("/cases", big_int)):
        r = api.req("POST", path, key=True, content=body, headers={"Content-Type": "application/json"})
        assert r.status_code == 400, (path, r.status_code, r.text[:200])
        assert r.json()["code"] == "MALFORMED_REQUEST" and "detail" not in r.json()
        validate("Error", r.json())
    for method, path, status, code in (("GET", "/nope", 404, "NOT_FOUND"),
                                       ("PUT", "/health/ready", 405, "METHOD_NOT_ALLOWED"),
                                       ("OPTIONS", "/cases", 405, "METHOD_NOT_ALLOWED")):
        r = api.req(method, path)
        assert (r.status_code, r.json()["code"]) == (status, code), (method, path, r.text)
        validate("Error", r.json())
        assert r.headers.get("X-Request-ID") == r.json()["request_id"]
        if status == 405:
            assert r.headers["Allow"]


def test_464_head_is_answered_like_get_without_a_body(api):
    get = api.c.get("/api/v1/health/ready")
    head = api.c.head("/api/v1/health/ready")
    assert head.status_code == get.status_code == 200
    assert head.content == b"" and head.headers["Content-Type"] == "application/json"
    assert head.headers["Content-Length"] == get.headers["Content-Length"]
    assert head.headers["Cache-Control"] == "no-store"
    assert api.c.head("/api/v1/sessions").status_code == 405  # POST only: still refused, without a body


# --- #465 (S-09): every API response carries nosniff, Referrer-Policy and framing protection ------------------------

HARDENING = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
             "Cache-Control": "no-store"}


def test_465_personal_data_json_and_every_error_carry_the_browser_hardening(app, api):
    from fastapi.testclient import TestClient
    api.start()
    case = api.new_case("Synthetic concern for the header check.")
    responses = [api.req("GET", path) for path in ("/cases", f"/cases/{case['id']}", "/settings", "/profile",
                                                   f"/cases/{case['id']}/guidance", "/nope", "/health/ready")]
    responses.append(api.req("PATCH", f"/cases/{case['id']}", json={"expected_revision": "x"}))  # 422
    responses.append(TestClient(app[0]).get("/api/v1/cases"))  # 401 without a session
    responses.append(api.req("PATCH", "/cases/records", content=b"x" * (300 * 1024),
                             headers={"Content-Type": "application/json"}))  # 413 before the app
    assert {r.status_code for r in responses} >= {200, 401, 404, 413, 422}
    for r in responses:
        for name, value in HARDENING.items():
            assert r.headers.get(name) == value, (r.request.url.path, r.status_code, name)
