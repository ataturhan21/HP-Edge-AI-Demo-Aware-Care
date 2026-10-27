"""R26 visible failure and no silent fallback; scripted failure keeps answers and retries. M08/M12."""
from dataclasses import replace

import pytest

from app.config import load_settings
from app.main import create_app

REQUIREMENT = "R26"


def test_failure_scenario_preserves_answers_and_recovers_by_explicit_retry(app, presenter):
    from conftest import Api
    from fastapi.testclient import TestClient
    loaded = presenter.ok("POST", "/presenter/scenarios/failure/load", 201, "ScenarioLoaded", key=True,
                          json={"reset": True})
    ctx = app[0].state.ctx
    # Act as the loaded synthetic guest: issue a cookie for that session in a separate client.
    from app.core.security import hash_token
    guest = Api(TestClient(app[0]))
    with ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET token_hash=?, csrf_token='guest-csrf' WHERE id=?",
                     (hash_token("guest-token"), loaded["session"]["id"]))
    guest.c.cookies.set("awarecare_session", "guest-token", path="/")
    guest.csrf = "guest-csrf"
    case_id = loaded["case_id"]
    failed = guest.to_guided(case_id)
    assert failed["status"] == "failed" and failed["error_code"] == "GENERATION_FAILED"
    read = guest.case(case_id)
    assert read["case"]["state"] == "limited" and "retry" in read["allowed_actions"]
    answered = [f for f in read["case"]["confirmed_context"] if f["kind"].startswith("answer:")]
    assert len(answered) == 10
    nq = guest.ok("POST", f"/cases/{case_id}/questions/next", 200, "NextQuestionResponse", key=True,
                  json={"expected_revision": read["case"]["revision"]})
    assert nq["kind"] == "review_required"
    rev = guest.case(case_id)["case"]["revision"]
    guest.ok("POST", f"/cases/{case_id}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    job = guest.ok("POST", f"/cases/{case_id}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    assert guest.wait_job(job["id"])["status"] == "succeeded"


def test_local_mode_without_reviewed_content_is_unavailable_not_mock(tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    empty = tmp_path / "pathways"
    empty.mkdir()
    (empty / "registry.json").write_text(json.dumps({"enabled_pathways": [], "packages": []}))
    settings = replace(load_settings(), mode="local", data_dir=tmp_path / "d", pathways_dir=empty)
    with TestClient(create_app(settings)) as client:
        r = client.get("/api/v1/health/ready")
        assert r.status_code == 503 and r.json() == {"readiness": "unavailable"}
        runtime = client.app.state.ctx.runtime  # metered for W06 (ADR-017), wrapping the ZRT adapter only
        assert type(runtime).__name__ == "MeteredRuntime" and type(runtime.inner).__name__ == "ZrtRuntimeAdapter"


def test_local_mode_without_a_configured_model_is_unavailable(tmp_path):
    """The reviewed pathway alone is not enough: with no model ID, local guidance can never be produced."""
    from fastapi.testclient import TestClient
    settings = replace(load_settings(), mode="local", data_dir=tmp_path / "d", model_id=None)
    with TestClient(create_app(settings)) as client:
        r = client.get("/api/v1/health/ready")
        assert r.status_code == 503 and r.json() == {"readiness": "unavailable"}


def test_cloud_fallback_cannot_be_enabled(monkeypatch):
    import pytest
    from app.config import ConfigError
    monkeypatch.setenv("AWARECARE_ALLOW_CLOUD_FALLBACK", "true")
    with pytest.raises(ConfigError):
        load_settings()
    monkeypatch.setenv("AWARECARE_ALLOW_CLOUD_FALLBACK", "false")
    monkeypatch.setenv("AWARECARE_MODEL_BASE_URL", "https://api.example.com/v1")
    with pytest.raises(ConfigError):
        load_settings()



def test_the_model_endpoint_must_parse_as_this_devices_loopback(monkeypatch):
    """#150 (ADR-014): the check parses the URL. A loopback-looking prefix with user info, a look-alike host or a
    parser trick would send every concern, answer and fact off the device."""
    import pytest
    from app.config import ConfigError
    for good in ("http://127.0.0.1:8080/v1", "http://localhost:8080/v1", "http://[::1]:8080/v1", "http://127.0.0.1:8080/v1/"):
        monkeypatch.setenv("AWARECARE_MODEL_BASE_URL", good)
        assert load_settings().model_base_url == good.rstrip("/")
    for bad in ("http://127.0.0.1:8080@remote.example/v1", "http://user:pw@127.0.0.1:8080/v1",
                "http://127.0.0.1.evil.example:8080/v1", "https://127.0.0.1:8080/v1", "http://127.0.0.1/v1",
                "http://127.0.0.1:8080\\@remote.example/v1", "http://127.0.0.1:8080/v1?next=http://x", "http://127.0.0.1:99999/v1",
                "http://10.0.0.5:8080/v1", "http://[::2]:8080/v1", "http://localhost.:8080/v1", "ftp://127.0.0.1:8080/v1"):
        monkeypatch.setenv("AWARECARE_MODEL_BASE_URL", bad)
        with pytest.raises(ConfigError):
            load_settings()

def test_queue_saturation_returns_429_with_retry_after(app):
    import pytest
    from app.core.errors import ApiError
    jobs = app[0].state.ctx.jobs
    for _ in range(4):
        jobs.admit_generation()
    with pytest.raises(ApiError) as err:
        jobs.admit_generation()
    assert err.value.status == 429 and err.value.headers["Retry-After"] == "5"


def test_failed_generation_shows_no_partial_result_and_keeps_answer_values(app, presenter):
    """T-R26-S02: after the failure nothing generated is readable anywhere; every answer value survives."""
    from conftest import Api
    from fastapi.testclient import TestClient
    from app.core.security import hash_token
    loaded = presenter.ok("POST", "/presenter/scenarios/failure/load", 201, "ScenarioLoaded", key=True,
                          json={"reset": True})
    ctx = app[0].state.ctx
    guest = Api(TestClient(app[0]))
    with ctx.db.tx() as conn:
        conn.execute("UPDATE sessions SET token_hash=?, csrf_token='guest-csrf' WHERE id=?",
                     (hash_token("guest-token"), loaded["session"]["id"]))
    guest.c.cookies.set("awarecare_session", "guest-token", path="/")
    guest.csrf = "guest-csrf"
    cid = loaded["case_id"]
    guest.answer_all(cid)
    before = {f["source_id"]: (f["kind"], f["value"]) for f in guest.case(cid)["case"]["confirmed_context"]}
    failed = guest.to_guided(cid)
    assert failed["status"] == "failed" and failed["error_code"] == "GENERATION_FAILED"
    assert failed["result_id"] is None and failed["result_type"] is None
    r = guest.req("GET", f"/cases/{cid}/guidance")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND" and "claims" not in r.text  # #269
    with ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM guidance WHERE case_id=?", (cid,)).fetchone()[0] == 0
    read = guest.case(cid)
    assert read["case"]["latest_guidance_id"] is None and "view_guidance" not in read["allowed_actions"]
    assert {f["source_id"]: (f["kind"], f["value"]) for f in read["case"]["confirmed_context"]} == before


# --- Local generation path (#51): one repair with the same snapshot, then a typed failure -------------------------

@pytest.mark.parametrize("bad,code", [
    ({"urgency_level": "self_care_candidate"}, "urgency_lowered"),
    ({"claims": [{"text": "x", "kind": "case_fact", "fact_ids": ["99999999-9999-4999-8999-999999999999"],
                  "evidence_ids": []}]}, "invalid_ids"),
    ({"actions": [{"text": "Rest and keep a diary.", "category": "self_care", "rationale": "r",
                   "evidence_ids": []}]}, "self_care_action_without_decision"),
    ({"outcome_title": "See Dr. Smith at https://example.org"}, "invented_url_or_provider"),
    ({"extra_field": 1}, "schema"),
], ids=["urgency", "ids", "self-care", "url", "schema"])
def test_local_path_repairs_once_with_the_same_snapshot(bad, code):
    """R26: a draft failing validation is retried once with the same case plus the error, then accepted."""
    from test_R24 import ScriptedModel, local_draft, run_local
    model = ScriptedModel(local_draft(**bad), local_draft())
    result = run_local(model)
    assert [a["result"] for a in result.attempts] == ["rejected", "valid"] and code in result.attempts[0]["codes"]
    first, second = (c["snapshot"] for c in model.calls)
    assert {k: v for k, v in second.items() if k != "repair"} == first  # same snapshot
    assert second["repair"]["previous_output_errors"] and "repair" not in first


def test_local_path_second_failure_raises_a_typed_error_and_publishes_nothing():
    """R26: two failed attempts give OUTPUT_VALIDATION_FAILED; no third call, no partial result."""
    import pytest as _pytest
    from app.modules.guidance.local import LocalGenerationFailed
    from test_R24 import ScriptedModel, local_draft, run_local
    lowered = local_draft(urgency_level="self_care_candidate")
    model = ScriptedModel(lowered, lowered)
    with _pytest.raises(LocalGenerationFailed) as exc:
        run_local(model)
    assert exc.value.code == "OUTPUT_VALIDATION_FAILED" and len(model.calls) == 2
    assert [a["result"] for a in exc.value.attempts] == ["rejected", "rejected"]


def test_local_path_non_json_output_uses_the_repair_but_transport_errors_do_not():
    """R26: unparsable output is repairable; an unreachable or timed-out model fails at once, typed, no fallback."""
    import pytest as _pytest
    from app.modules.guidance.local import LocalGenerationFailed
    from app.runtime.zrt_provider import RuntimeOutputError, RuntimeTransportError
    from test_R24 import ScriptedModel, local_draft, run_local
    result = run_local(ScriptedModel(RuntimeOutputError("not json"), local_draft()))
    assert [a["result"] for a in result.attempts] == ["MODEL_OUTPUT_INVALID", "valid"]
    model = ScriptedModel(RuntimeTransportError("down"), local_draft())
    with _pytest.raises(LocalGenerationFailed) as exc:
        run_local(model)
    assert exc.value.code == "MODEL_UNAVAILABLE" and len(model.calls) == 1


def test_local_path_deadline_covers_the_repair():
    """R26: the second attempt only gets the time that is left, and no time left means a typed failure."""
    import asyncio
    import pytest as _pytest
    from app.modules.guidance import local
    from test_R24 import local_draft, local_inputs

    class Slow:
        def __init__(self):
            self.timeouts = []

        async def generate_json(self, task, prompt_version, snapshot, schema_id, timeout_s):
            self.timeouts.append(timeout_s)
            await asyncio.sleep(0.3)
            return local_draft(urgency_level="self_care_candidate")

    slow = Slow()
    with _pytest.raises(local.LocalGenerationFailed) as exc:
        asyncio.run(local.generate(slow, local_inputs(), deadline_s=0.5))
    assert exc.value.code in {"DEADLINE_EXCEEDED", "OUTPUT_VALIDATION_FAILED"}
    assert slow.timeouts[0] == _pytest.approx(0.5, abs=0.05)
    assert len(slow.timeouts) == 1 or slow.timeouts[1] < 0.25


def test_local_generation_failure_is_visible_and_retryable_never_mock(local):
    """Two drafts that give self-care advice while unsure: the job fails with a typed code, the case is limited with
    a retry, and nothing is published."""
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    unsure_with_self_care = {"urgency_level": "undetermined", "actions": [
        {"text": "Rest at home.", "category": "self_care", "rationale": "r", "evidence_ids": []}]}
    model.override = unsure_with_self_care
    case = api.new_case(context=[NO_RED_FLAGS])
    job = api.to_guided(case["id"])
    assert job["status"] == "failed" and job["error_code"] == "OUTPUT_VALIDATION_FAILED"
    read = api.case(case["id"])
    assert read["case"]["state"] == "limited" and "retry" in read["allowed_actions"]
    assert api.req("GET", f"/cases/{case['id']}/guidance").status_code == 404  # #269: never generated
    assert len([c for c in model.calls if c["task"] == "guidance"]) == 2


def test_local_transport_failure_fails_the_job_without_a_repair(local):
    from app.runtime.zrt_provider import RuntimeTransportError
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    model.outputs = [RuntimeTransportError("down")]
    case = api.new_case(context=[NO_RED_FLAGS])
    job = api.to_guided(case["id"])
    assert job["status"] == "failed" and job["error_code"] == "MODEL_UNAVAILABLE"
    assert len([c for c in model.calls if c["task"] == "guidance"]) == 1


# #75: a schema repair names the actual problem, so a model that invents non-UUID ids can correct itself.

def test_a_schema_repair_names_the_invalid_ids():
    from app.modules.guidance import local
    from test_R24 import ScriptedModel, local_draft, local_inputs, run_local
    invented = local_draft(claims=[{"text": "The case is undetermined.", "kind": "case_fact",
                                    "fact_ids": ["case_concern_id"], "evidence_ids": []}])
    model = ScriptedModel(invented, local_draft())
    result = run_local(model, local_inputs())
    assert [a["result"] for a in result.attempts] == ["rejected", "valid"]
    errors = model.calls[1]["snapshot"]["repair"]["previous_output_errors"]
    assert any(e.startswith("schema: claims[0].fact_ids[0] is not an id from the input") for e in errors), errors
    assert "case_concern_id" not in " ".join(errors)  # paths only, nothing echoed from the draft


def test_the_gate_check_applies_the_adr_002_gates_unrelaxed(tmp_path):
    import json
    import sys
    from types import SimpleNamespace
    from conftest import ROOT
    sys.path.insert(0, str(ROOT / "scripts"))
    import qualify_model
    q = ROOT / "evidence/model-qualification"
    args = lambda run: SimpleNamespace(identity=None, failures=str(q / "2026-10-15-rerun/failures.json"),  # noqa: E731
                                       run=str(run), context=str(q / "2026-10-15-rerun/context.json"),
                                       judge=str(q / "2026-10-15-rerun/judge.json"),
                                       egress=None)  # its egress log predates the listener fields (#151, #295)
    passed = qualify_model.gates(args(q / "2026-10-15-rerun/run.json"))
    assert passed["stages"]["2 structured output"]["result"] == "PASSED"
    assert passed["result"] == "INCOMPLETE"  # stage 0 identity was not part of the rerun
    # #296: without the certainty reviewer stage 2 cannot pass, and the qualification is incomplete.
    no_judge = qualify_model.gates(SimpleNamespace(**{**vars(args(q / "2026-10-15-rerun/run.json")), "judge": None}))
    assert no_judge["stages"]["2 structured output"]["result"] == "INCOMPLETE"
    assert no_judge["stages"]["2 structured output"]["certainty_reviewer"] == "NOT_RUN"
    assert no_judge["result"] == "INCOMPLETE"
    # 64/69 valid (the ZRT 0.43.0 run before #75) fails stage 2: >= 95% first and >= 99% after repair.
    failed = qualify_model.gates(args(q / "2026-10-15-zrt-0.43.0/run.json"))
    assert failed["stages"]["2 structured output"]["result"] == "FAILED"
    assert failed["stages"]["2 structured output"]["fallback_cases"] == ["unsupported-noev"]
    assert failed["result"] == "FAILED"



def test_the_gate_check_expects_the_revision_of_the_given_manifest():
    """#137: stage 0 checks the selected model's revision by default, or a candidate's with --manifest."""
    import sys
    from types import SimpleNamespace
    from conftest import ROOT
    sys.path.insert(0, str(ROOT / "scripts"))
    import qualify_model
    fury = ROOT / "evidence/model-qualification/2026-10-17-fury-qwen3.8-flash-next"
    files = {n: str(fury / f"candidate-configA-auto-kernels/{n}.json") for n in ("identity", "failures", "run", "context", "judge")}
    egress = str(fury / "candidate-configA-auto-kernels/egress.log")
    default = qualify_model.gates(SimpleNamespace(**files, egress=egress))  # no manifest attribute: older callers
    assert default["stages"]["0 identity"]["result"] == "FAILED"  # the candidate is not the Nano's selected model
    assert default["stages"]["0 identity"]["expected_revision"] == "95a723d08a9490559dae23d0cff1d9466213d989"
    candidate = qualify_model.gates(SimpleNamespace(**files, egress=egress,
                                                    manifest=str(fury / "operator/candidate-manifest.json")))
    assert candidate["stages"]["0 identity"]["result"] == "PASSED"
    assert candidate["stages"]["0 identity"]["revision"] == "236dfdf285828023ca3bcd3f37366c58a3469b13"
    assert all(candidate["stages"][s]["result"] == "PASSED" for s in list(candidate["stages"])[:6])
    # #295: this 2026-10-17 log predates the listener fields (#151), so re-evaluated today stage 6 fails; the stored
    # gates.json next to it keeps the result it had when it was recorded.
    assert candidate["stages"]["6 boundary"]["result"] == "FAILED"
    assert candidate["stages"]["6 boundary"]["listeners_checked"] is False
    assert candidate["result"] == "FAILED"


def test_the_boundary_gate_parses_connections_and_listeners(tmp_path):
    """#151: stage 6 fails on a non-loopback connection or listener of the model processes. Fields are parsed:
    `listen_non_loopback=0` also ends in `non_loopback=0`, so a line-ending match would miss a bad connection."""
    import sys
    from types import SimpleNamespace
    from conftest import ROOT
    sys.path.insert(0, str(ROOT / "scripts"))
    import qualify_model

    def boundary(text):
        log = tmp_path / "egress.log"
        log.write_text(text)
        args = SimpleNamespace(identity=None, failures=None, run=None, context=None, judge=None, egress=str(log))
        return qualify_model.gates(args)["stages"]["6 boundary"]

    clean = boundary("1 sockets=0 non_loopback=0 listen=7 listen_non_loopback=0\n2 sockets=1 non_loopback=0 listen=7 listen_non_loopback=0\n")
    assert clean["result"] == "PASSED" and clean["listeners_checked"] is True and clean["samples"] == 2
    trap = boundary("1 sockets=2 non_loopback=1 listen=7 listen_non_loopback=0\n")
    assert trap["result"] == "FAILED" and trap["non_loopback_samples"] == 1
    exposed = boundary("1 sockets=0 non_loopback=0 listen=7 listen_non_loopback=7\n")  # the Fury before #151
    assert exposed["result"] == "FAILED" and exposed["non_loopback_listener_samples"] == 1
    gaps = boundary("1 sockets=0 non_loopback=0 listen=0 listen_non_loopback=0 no_process\n")
    assert gaps["result"] == "FAILED" and gaps["samples"] == 0 and gaps["no_process_samples"] == 1
    # #295: logs before #151 carry no listener fields; they no longer pass.
    old = boundary("1 sockets=0 non_loopback=0\n")
    assert old["result"] == "FAILED" and old["listeners_checked"] is False and old["incomplete_samples"] == 1
    truncated = boundary("1 sockets=0 non_loopback=0 listen=7 listen_non_loopback=0\n2 sockets=0 non_loopback=0 listen=7 listen_non_loopback=\n")
    assert truncated["result"] == "FAILED" and truncated["incomplete_samples"] == 1
    never_listening = boundary("1 sockets=0 non_loopback=0 listen=0 listen_non_loopback=0\n")  # server never seen up
    assert never_listening["result"] == "FAILED" and never_listening["samples_with_server_listening"] == 0
    some_gaps = boundary("1 sockets=0 non_loopback=0 listen=0 listen_non_loopback=0 no_process\n"
                         "2 sockets=1 non_loopback=0 listen=7 listen_non_loopback=0\n")
    assert some_gaps["result"] == "PASSED" and some_gaps["samples"] == 1

def test_only_a_case_without_facts_gets_the_no_facts_line():
    """#75: the guard changes nothing for a case with facts (every app case has the checklist answer)."""
    from dataclasses import replace
    from app.modules.guidance import local
    from test_R24 import local_inputs
    with_facts = local.snapshot(local_inputs())
    assert "no_facts" not in with_facts["case"]
    assert set(with_facts["case"]) == {"concern", "confirmed_facts", "reviewed_urgency_decision", "note"}
    empty = local.snapshot(replace(local_inputs(), facts=[]))
    assert empty["case"]["no_facts"].startswith("There are no confirmed facts")
    assert empty["instructions"] == local.INSTRUCTIONS  # the qualified prompt is unchanged


def test_every_local_app_case_reaches_the_model_with_at_least_one_fact(local):
    """The checklist answer is always a fact, so the no-facts guard never applies to an app case."""
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    case = api.new_case(context=[NO_RED_FLAGS])
    rev = case["revision"]
    while True:  # every question answered "Not sure": the fewest facts an app case can have
        nq = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                    json={"expected_revision": rev})
        if nq["kind"] == "review_required":
            break
        rev = api.ok("PUT", f"/cases/{case['id']}/answers/{nq['question']['id']}", 200, "SaveAnswerResponse",
                     json={"expected_revision": rev, "status": "unknown", "value": None})["case_revision"]
    rev = api.case(case["id"])["case"]["revision"]
    api.ok("POST", f"/cases/{case['id']}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    api.wait_job(api.ok("POST", f"/cases/{case['id']}/guidance", 202, "Job", key=True, json={"expected_revision": rev})["id"])
    snap = next(c for c in model.calls if c["task"] == "guidance")["snapshot"]
    assert snap["case"]["confirmed_facts"] and "no_facts" not in snap["case"]


# #263 (QA 2026-10-19): the job runner lives in memory only. Work a restart interrupted is settled at startup, and a
# job that cannot be submitted never leaves its case stuck or its admission slot taken.

class Restartable:
    """One data directory served by an app that is stopped and started again, like an API restart."""

    def __init__(self, tmp_path):
        from conftest import TEST_PRESENTER_KEY
        self.settings = replace(load_settings(), data_dir=tmp_path / "data", presenter_key=TEST_PRESENTER_KEY,
                                presenter_trusted_peers=("testclient",))

    def __enter__(self):
        from conftest import Api
        from fastapi.testclient import TestClient
        self.app = create_app(self.settings)
        self.client = TestClient(self.app).__enter__()
        self.api = Api(self.client)
        return self

    def __exit__(self, *exc):
        self.client.__exit__(*exc)

    def restart(self):
        """Stops this app (its in-memory job runner and queued work are gone) and starts a new one on the same data,
        continuing the same browser session."""
        from conftest import Api
        from fastapi.testclient import TestClient
        cookies, csrf = dict(self.client.cookies), self.api.csrf
        self.client.__exit__(None, None, None)
        self.app = create_app(self.settings)
        self.client = TestClient(self.app).__enter__()
        for name, value in cookies.items():
            self.client.cookies.set(name, value, path="/")
        self.api = Api(self.client)
        self.api.csrf = csrf
        return self.api

    def drop(self, attr):
        """The next submitted work of this kind is lost, as when the process dies right after the 202."""
        setattr(self.app.state.ctx.jobs, attr, lambda work: None)


def _reviewed(api):
    case = api.new_case()
    api.answer_all(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    api.ok("POST", f"/cases/{case['id']}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    return case["id"], rev


def test_a_generation_interrupted_by_a_restart_fails_visibly_and_offers_a_retry(tmp_path):
    with Restartable(tmp_path) as server:
        api = server.api
        api.start()
        cid, rev = _reviewed(api)
        server.drop("submit_generation")
        job = api.ok("POST", f"/cases/{cid}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
        assert api.case(cid)["case"]["state"] == "generating"
        api = server.restart()
        after = api.ok("GET", f"/jobs/{job['id']}", 200, "Job")
        assert (after["status"], after["error_code"]) == ("failed", "INTERRUPTED")
        read = api.case(cid)
        assert read["case"]["state"] == "limited" and "retry" in read["allowed_actions"]
        # The explicit retry path works and the answers were kept.
        assert len([f for f in read["case"]["confirmed_context"] if f["kind"].startswith("answer:")]) == 10
        assert api.to_guided(cid)["status"] == "succeeded"


def test_an_export_interrupted_by_a_restart_fails_and_a_new_one_works(tmp_path):
    with Restartable(tmp_path) as server:
        api = server.api
        api.start()
        cid = api.new_case()["id"]
        api.to_guided(cid)
        rev = api.case(cid)["case"]["revision"]
        server.drop("submit")
        job = api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                     json={"expected_revision": rev, "user_reviewed": True})
        api = server.restart()
        assert api.ok("GET", f"/jobs/{job['id']}", 200, "Job")["error_code"] == "INTERRUPTED"
        again = api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                       json={"expected_revision": rev, "user_reviewed": True})
        assert api.wait_job(again["id"])["status"] == "succeeded"


def test_an_extraction_interrupted_by_a_restart_fails_and_its_bytes_are_removed(tmp_path):
    from records_helpers import records, upload
    with Restartable(tmp_path) as server:
        api = server.api
        api.start()
        cid = api.new_case()["id"]
        server.drop("submit")
        r = upload(api, cid, (__import__("records_helpers").SAMPLE))
        assert r.status_code == 202
        record_dir = server.settings.data_dir / "records"
        assert len(list(record_dir.iterdir())) == 1
        api = server.restart()
        assert api.ok("GET", f"/jobs/{r.json()['job_id']}", 200, "Job")["error_code"] == "INTERRUPTED"
        doc = records(api, cid)["documents"][0]
        assert doc["status"] == "failed"
        assert list(record_dir.iterdir()) == []


def test_a_deletion_interrupted_by_a_restart_is_run_again_to_completion(tmp_path):
    with Restartable(tmp_path) as server:
        api = server.api
        api.start()
        cid = api.new_case()["id"]
        api.to_guided(cid)
        rev = api.case(cid)["case"]["revision"]
        job = api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True,
                     json={"expected_revision": rev, "user_reviewed": True})
        api.wait_job(job["id"])
        server.drop("submit")
        deletion = api.ok("DELETE", f"/cases/{cid}?expected_revision={rev}", 202, "DeletionAccepted")
        assert api.req("GET", f"/cases/{cid}").status_code == 404  # access is blocked at once
        api = server.restart()
        assert api.ok("GET", f"/jobs/{deletion['deletion_job_id']}", 200, "Job")["status"] == "succeeded"
        assert list((server.settings.data_dir / "exports").iterdir()) == []
        with server.app.state.ctx.db.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] == 0


def test_a_failed_generation_submit_rolls_back_and_releases_the_admission_slot(app, api):
    ctx = app[0].state.ctx
    api.start()
    cid, rev = _reviewed(api)

    def broken(fn):
        raise RuntimeError("executor unavailable")
    original = ctx.jobs._generation.submit
    ctx.jobs._generation.submit = broken
    try:
        r = api.req("POST", f"/cases/{cid}/guidance", key=True, json={"expected_revision": rev})
    finally:
        ctx.jobs._generation.submit = original
    assert r.status_code == 503 and r.json()["retryable"] is True
    assert ctx.jobs.snapshot() == (0, 0) and ctx.jobs._inflight == 0
    read = api.case(cid)
    assert read["case"]["state"] == "reviewed" and "generate_guidance" in read["allowed_actions"]
    retry = api.ok("POST", f"/cases/{cid}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
    assert api.wait_job(retry["id"])["status"] == "succeeded"


def test_a_request_failing_after_admission_releases_the_slot(app, api, monkeypatch):
    from app.modules.guidance import service as guidance
    ctx = app[0].state.ctx
    api.start()
    cid, rev = _reviewed(api)

    def broken(*a, **kw):
        raise RuntimeError("store failed")
    monkeypatch.setattr(guidance, "create_job", broken)
    from fastapi.testclient import TestClient
    from conftest import Api
    quiet = Api(TestClient(app[0], raise_server_exceptions=False))
    quiet.c.cookies.update(api.c.cookies)
    quiet.csrf = api.csrf
    assert quiet.req("POST", f"/cases/{cid}/guidance", key=True, json={"expected_revision": rev}).status_code == 500
    assert ctx.jobs._inflight == 0
    assert api.case(cid)["case"]["state"] == "reviewed"


# #528: ZRT serves a model under its label (our serve scripts) or, started without one, under the repository id, with
# any revision (a test machine: `Qwen/Qwen3.6-35B-A3B-FP8`, pulled `@main`). The same model is ready under every name, and
# the app talks to ZRT with the ID ZRT lists; only another model is "not served".
NANO_LABEL = "qwen3.6-35b-a3b-fp8"


def _fake_zrt(monkeypatch, served_ids):
    import httpx
    from app.runtime import zrt_provider
    requests = []

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [{"id": i, "object": "model"} for i in served_ids]})
        body = __import__("json").loads(request.content)
        requests.append(body["model"])
        if body["model"] not in served_ids:
            return httpx.Response(404, json={"error": "model not found"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"ok\": true}"}}],
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 2}})

    real = httpx.AsyncClient
    monkeypatch.setattr(zrt_provider.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return requests


@pytest.mark.parametrize("served", [NANO_LABEL, "Qwen/Qwen3.6-35B-A3B-FP8", "Qwen/Qwen3.6-35B-A3B-FP8@main",
                                    "qwen/qwen3.6-35b-a3b-fp8@main",
                                    "hf:Qwen/Qwen3.6-35B-A3B-FP8@95a723d08a9490559dae23d0cff1d9466213d989",
                                    "/opt/hp/zrt/models/hf/Qwen/Qwen3.6-35B-A3B-FP8/main"])
def test_the_same_model_under_any_zrt_name_is_ready_and_requests_use_the_served_id(tmp_path, monkeypatch, served):
    import asyncio
    from fastapi.testclient import TestClient
    requests = _fake_zrt(monkeypatch, ["Qwen/Qwen2.5-0.5B-Instruct", served])
    settings = replace(load_settings(), mode="local", model_id=NANO_LABEL, data_dir=tmp_path / "d")
    with TestClient(create_app(settings)) as client:
        r = client.get("/api/v1/health/ready")
        assert r.status_code == 200 and r.json() == {"readiness": "ready"}
        runtime = client.app.state.ctx.runtime
        assert asyncio.run(runtime.health())["model_id"] == served
        out = asyncio.run(runtime.generate_json("concern_check", "p1", {"text": "x"}, "S", 5))
    assert out == {"ok": True} and requests == [served]


def test_a_fresh_adapter_resolves_the_served_id_before_its_first_request(monkeypatch):
    import asyncio
    from app.runtime.zrt_provider import ZrtRuntimeAdapter
    requests = _fake_zrt(monkeypatch, ["Qwen/Qwen3.6-35B-A3B-FP8@main"])
    adapter = ZrtRuntimeAdapter("http://127.0.0.1:8080/v1", NANO_LABEL, load_settings().model_manifest)
    assert asyncio.run(adapter.generate_json("concern_check", "p1", {"text": "x"}, "S", 5)) == {"ok": True}
    assert requests == ["Qwen/Qwen3.6-35B-A3B-FP8@main"]


def test_an_entirely_different_model_is_not_served_and_generation_fails_visibly(tmp_path, monkeypatch):
    import asyncio
    from fastapi.testclient import TestClient
    from app.runtime.zrt_provider import RuntimeTransportError
    _fake_zrt(monkeypatch, ["Qwen/Qwen3.8-27B-FP8@main", "Qwen/Qwen3.6-35B-A3B"])
    settings = replace(load_settings(), mode="local", model_id=NANO_LABEL, data_dir=tmp_path / "d")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health/ready").json() == {"readiness": "degraded"}
        runtime = client.app.state.ctx.runtime
        assert asyncio.run(runtime.health())["reason_code"] == "MODEL_NOT_SERVED"
        with pytest.raises(RuntimeTransportError):
            asyncio.run(runtime.generate_json("concern_check", "p1", {"text": "x"}, "S", 5))


# ------------------------------------------------------------------ #550: thinking off per request, typed failures


def _capture_zrt(monkeypatch, reply):
    """A fake ZRT that records each chat request body and answers with `reply(body)` (an httpx.Response or raises)."""
    import httpx
    from app.runtime import zrt_provider
    bodies = []

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [{"id": NANO_LABEL, "object": "model"}]})
        body = __import__("json").loads(request.content)
        bodies.append(body)
        return reply(body)

    real = httpx.AsyncClient
    monkeypatch.setattr(zrt_provider.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return bodies


def _content(text):
    import httpx
    return lambda body: httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {}})


@pytest.mark.parametrize(("task", "cap"), [("guidance", 2048), ("certainty_review", 512), ("red_flag_screen", 256),
                                           ("concern_check", 64)])
def test_every_request_switches_thinking_off_itself_and_caps_its_output(monkeypatch, task, cap):
    """#550: the qualified setting (thinking off) no longer depends on the server's --default-chat-template-kwargs. With
    thinking on, the Nano's red-flag screen spent 441 reasoning tokens and answered `{}`, so every Quick flow failed as
    "guidance failed" (evidence/clinical-review/2026-10-26-selfcare-speed/). #551: a cap far above any real answer."""
    import asyncio
    from app.runtime.zrt_provider import ZrtRuntimeAdapter
    bodies = _capture_zrt(monkeypatch, _content('{"ok": true}'))
    adapter = ZrtRuntimeAdapter("http://127.0.0.1:8080/v1", NANO_LABEL, load_settings().model_manifest)
    assert asyncio.run(adapter.generate_json(task, "p1", {"text": "x"}, "S", 5)) == {"ok": True}
    [body] = bodies
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == cap and body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}


def test_a_leading_think_block_is_not_the_answer(monkeypatch):
    """#550: a server whose template ignores the switch and has no reasoning parser puts its thinking in the content."""
    import asyncio
    from app.runtime.zrt_provider import ZrtRuntimeAdapter
    _capture_zrt(monkeypatch, _content('<think>\nThe person reports no warning signs.\n</think>\n\n{"present": []}'))
    adapter = ZrtRuntimeAdapter("http://127.0.0.1:8080/v1", NANO_LABEL, load_settings().model_manifest)
    assert asyncio.run(adapter.generate_json("red_flag_screen", "p1", {}, "S", 5)) == {"present": []}


def test_a_model_that_does_not_answer_in_time_is_a_timeout_not_unavailable(monkeypatch):
    import asyncio
    import httpx
    from app.runtime.zrt_provider import RuntimeTimeoutError, RuntimeTransportError, ZrtRuntimeAdapter

    def slow(body):
        raise httpx.ReadTimeout("timed out")
    _capture_zrt(monkeypatch, slow)
    adapter = ZrtRuntimeAdapter("http://127.0.0.1:8080/v1", NANO_LABEL, load_settings().model_manifest)
    with pytest.raises(RuntimeTimeoutError) as failed:
        asyncio.run(adapter.generate_json("guidance", "p1", {}, "S", 5))
    assert failed.value.code == "TIMEOUT" and isinstance(failed.value, RuntimeTransportError)


# --- #585: one total deadline across model discovery, the completion, its body, the repair and the review ------------
class _SlowZrt:
    """A short-lived loopback ZRT stand-in: /models answers after `models_s`; /chat/completions sends its headers after
    `chat_s` and then its body in `chunks` pieces, `chunk_s` apart. No model, no device."""

    def __init__(self, models_s=0.0, chat_s=0.0, chunks=1, chunk_s=0.0):
        import http.server
        import json
        import threading
        import time
        body = json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}}).encode()
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, payload: bytes, delay: float, pieces: int, gap: float):
                time.sleep(delay)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                size = -(-len(payload) // pieces)
                for i in range(0, len(payload), size):
                    if i:
                        time.sleep(gap)
                    self.wfile.write(payload[i:i + size])
                    self.wfile.flush()

            def do_GET(self):
                self._send(json.dumps({"object": "list", "data": [{"id": NANO_LABEL, "object": "model"}]}).encode(),
                           stub.models_s, 1, 0.0)

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self._send(body, stub.chat_s, stub.chunks, stub.chunk_s)

        self.models_s, self.chat_s, self.chunks, self.chunk_s = models_s, chat_s, chunks, chunk_s
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.mark.parametrize("delays", [
    {"models_s": 0.65, "chat_s": 0.65},  # cold discovery plus the completion, each within the per-operation timeout
    {"chat_s": 0.1, "chunks": 6, "chunk_s": 0.25},  # a body that keeps trickling in
], ids=["discovery-plus-completion", "slow-body"])
def test_585_a_generation_call_never_runs_past_its_total_deadline(delays):
    import asyncio
    import time
    from app.runtime.zrt_provider import RuntimeTimeoutError, ZrtRuntimeAdapter
    stub = _SlowZrt(**delays)
    try:
        adapter = ZrtRuntimeAdapter(stub.url, NANO_LABEL, load_settings().model_manifest)
        t0 = time.perf_counter()
        with pytest.raises(RuntimeTimeoutError) as failed:
            asyncio.run(adapter.generate_json("guidance", "p1", {}, "S", 1.0))
        elapsed = time.perf_counter() - t0
    finally:
        stub.close()
    assert failed.value.code == "TIMEOUT"
    assert elapsed < 1.25, f"the 1.0 s deadline ended after {elapsed:.2f} s"


def test_585_a_generation_call_inside_its_deadline_still_answers():
    """The control: discovery and the completion together within the deadline."""
    import asyncio
    from app.runtime.zrt_provider import ZrtRuntimeAdapter
    stub = _SlowZrt(models_s=0.1, chat_s=0.1, chunks=3, chunk_s=0.05)
    try:
        adapter = ZrtRuntimeAdapter(stub.url, NANO_LABEL, load_settings().model_manifest)
        assert asyncio.run(adapter.generate_json("guidance", "p1", {}, "S", 1.0)) == {"ok": True}
    finally:
        stub.close()


class _Late:
    """A runtime that answers each call after `delay_s`, whatever time it was given (as a call that overran)."""

    def __init__(self, delay_s, *outputs):
        self.delay_s, self.outputs, self.timeouts = delay_s, list(outputs), []

    async def generate_json(self, task, prompt_version, snapshot, schema_id, timeout_s):
        import asyncio
        self.timeouts.append(timeout_s)
        await asyncio.sleep(self.delay_s)
        out = self.outputs.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


@pytest.mark.parametrize("path", ["repair", "review"])
def test_585_a_valid_draft_finished_after_the_deadline_is_not_accepted(path):
    import asyncio
    from app.modules.guidance import local
    from app.runtime.zrt_provider import RuntimeOutputError
    from test_R24 import local_draft, local_inputs
    if path == "repair":  # the first draft is not JSON; the repair answers valid output after the deadline
        runtime = _Late(0.3, RuntimeOutputError("not json"), local_draft())
    else:  # a flagged statement's review clears it after the deadline
        runtime = _Late(0.3, local_draft(escalation_advice=["Nothing here is guaranteed; seek care if it worsens."]),
                        {"verdicts": [{"index": 0, "unsafe": False, "category": "none"}]})
    with pytest.raises(local.LocalGenerationFailed) as failed:
        asyncio.run(local.generate(runtime, local_inputs(), deadline_s=0.5))
    assert failed.value.code == "DEADLINE_EXCEEDED"
    assert len(runtime.timeouts) == 2 and runtime.timeouts[1] < 0.25  # the second call only got what was left
