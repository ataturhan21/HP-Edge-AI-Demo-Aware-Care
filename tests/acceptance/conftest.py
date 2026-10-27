"""Shared acceptance fixtures: isolated app instance per test and contract validation.

Run from apps/api: `uv run pytest`. Every response checked with `api.ok(...)` is
validated against the canonical schema embedded in spec/api/openapi.json.
Mock mode by default; the `local` fixture runs local mode with a scripted model, so
these tests never contact ZRT.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.config import load_settings
from app.core.security import CURRENT_CONSENT_VERSION
from app.main import create_app
from app.modules.access import presenter as presenter_auth

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from spec_utils import format_checker  # noqa: E402  (#301: date-time and uri are really checked)
OPENAPI = json.loads((ROOT / "spec/api/openapi.json").read_text())
ORIGIN = "http://127.0.0.1:15173"
# Test-only presenter gateway key; TestClient requests arrive from the peer "testclient".
TEST_PRESENTER_KEY = b"test-presenter-key-0123456789abcdef0123456789"


def presenter_assertion(key: bytes = TEST_PRESENTER_KEY, ts: float | None = None) -> str:
    return presenter_auth.sign(key, int(time.time() if ts is None else ts), uuid.uuid4().hex)


def validate(name: str, body) -> None:
    schema = {**OPENAPI, "$ref": f"#/components/schemas/{name}"}
    errors = list(Draft202012Validator(schema, format_checker=format_checker()).iter_errors(body))
    assert not errors, f"{name} contract violation: {[e.message for e in errors[:3]]}"


class Api:
    def __init__(self, client: TestClient, presenter: bool = False):
        self.c = client
        self.presenter = presenter  # behaves like a browser behind the presenter gateway
        self.csrf: str | None = None
        self.c.get("/api/v1/health/ready")  # obtains the pre-session nonce cookie

    def headers(self, key: bool = False, csrf: bool = True) -> dict[str, str]:
        h = {"Origin": ORIGIN}
        if csrf and self.csrf:
            h["X-CSRF-Token"] = self.csrf
        if key:
            h["Idempotency-Key"] = str(uuid.uuid4())
        if self.presenter:
            h[presenter_auth.HEADER] = presenter_assertion()
        return h

    def req(self, method: str, path: str, *, key: bool = False, headers: dict | None = None, **kw):
        h = {**self.headers(key=key), **(headers or {})}
        r = self.c.request(method, f"/api/v1{path}", headers=h, **kw)
        if r.headers.get("X-CSRF-Token"):
            self.csrf = r.headers["X-CSRF-Token"]
        assert r.headers.get("Cache-Control") == "no-store"
        return r

    def ok(self, method: str, path: str, status: int, schema: str | None, **kw):
        r = self.req(method, path, **kw)
        assert r.status_code == status, (r.status_code, r.text)
        if schema:
            validate(schema, r.json())
        return r.json()

    def start(self) -> dict:
        return self.ok("POST", "/sessions", 201, "CreateSessionResponse", key=True,
                       json={"mode": "guest", "consent_version": CURRENT_CONSENT_VERSION, "adult_eligible": True})

    def new_case(self, concern: str = "Recurring headaches after long workdays.", context: list | None = None) -> dict:
        return self.ok("POST", "/cases", 201, "Case", key=True,
                       json={"concern": concern, "confirmed_context": context or []})

    def case(self, case_id: str) -> dict:
        return self.ok("GET", f"/cases/{case_id}", 200, "CaseReadResponse")

    def answer_all(self, case_id: str) -> dict:
        """Answer every issued question with its first valid option until review is required."""
        rev = self.case(case_id)["case"]["revision"]
        while True:
            nq = self.ok("POST", f"/cases/{case_id}/questions/next", 200, "NextQuestionResponse", key=True,
                         json={"expected_revision": rev})
            if nq["kind"] == "review_required":
                return nq
            q = nq["question"]
            value = {"single_choice": lambda: q["choices"][0]["id"],
                     "multiple_choice": lambda: [q["choices"][0]["id"]],
                     "text": lambda: "No changes yet.", "scale": lambda: 4}[q["response_type"]]()
            saved = self.ok("PUT", f"/cases/{case_id}/answers/{q['id']}", 200, "SaveAnswerResponse",
                            json={"expected_revision": rev, "status": "answered", "value": value})
            rev = saved["case_revision"]

    def wait_job(self, job_id: str, timeout: float = 5.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.ok("GET", f"/jobs/{job_id}", 200, "Job")
            if job["status"] in {"succeeded", "failed", "stale", "cancelled"}:
                return job
            time.sleep(0.05)
        raise AssertionError("job did not finish")

    def to_guided(self, case_id: str) -> dict:
        self.answer_all(case_id)
        rev = self.case(case_id)["case"]["revision"]
        self.ok("POST", f"/cases/{case_id}/review", 200, "Case", json={"expected_revision": rev,
                                                                         "facts_confirmed": True})
        job = self.ok("POST", f"/cases/{case_id}/guidance", 202, "Job", key=True, json={"expected_revision": rev})
        return self.wait_job(job["id"])


@pytest.fixture
def app(tmp_path):
    settings = replace(load_settings(), data_dir=tmp_path / "data", presenter_key=TEST_PRESENTER_KEY,
                       presenter_trusted_peers=("testclient",))
    application = create_app(settings)
    with TestClient(application) as client:
        yield application, client


@pytest.fixture
def api(app) -> Api:
    return Api(app[1])


@pytest.fixture
def other(app) -> Api:
    """A second, independent browser against the same server."""
    return Api(TestClient(app[0]))


@pytest.fixture
def presenter(app) -> Api:
    """A presenter session created through createSession behind the (simulated) presenter gateway (ADR-005 A)."""
    api = Api(TestClient(app[0]), presenter=True)
    api.start()
    return api


NO_RED_FLAGS = {"kind": "red_flags", "value": [], "units": None, "origin": "user", "profile_revision": None}


def red_flags(*ids: str) -> dict:
    """The A03 checklist answer (ADR-003): ticked RF IDs, or none of them."""
    return {**NO_RED_FLAGS, "value": list(ids)}


class LocalModel:
    """Stands in for the ZRT adapter in local-mode tests. Never contacts ZRT.

    `guidance` calls get a draft built from the snapshot (so fact IDs are real) by `draft(snapshot)`, or the next
    scripted output (a dict, or an exception to raise); `certainty_review` calls clear every statement except those
    containing one of `unsafe_phrases` (judged unsafe with `unsafe_category`);
    `red_flag_screen` calls (general-adult-3) return `screen` (a dict, an exception to raise, or a function of the
    screened words that returns either), by default no red flag. Every call is recorded.
    """

    def __init__(self, *outputs, level: str | None = None):
        self.outputs, self.calls, self.level = list(outputs), [], level
        self.override: dict = {}  # fields merged into every built draft
        self.screen: Any = {"present": []}  # the red-flag screen's output, or an exception to raise
        self.concern: Any = {"health_concern": True}  # #154 concern check's output, or an exception to raise
        self.unsafe_phrases: tuple[str, ...] = ()  # statements the certainty reviewer judges unsafe
        self.unsafe_category = "definitive_diagnosis"

    def draft(self, snapshot: dict) -> dict:
        case = snapshot["case"]
        level = self.level or case["reviewed_urgency_decision"]
        fact = case["confirmed_facts"][0]["id"]
        category = "self_care" if level == "self_care_candidate" else (
            "seek_care" if level in {"urgent_clinician", "emergency"} else "discuss_with_clinician")
        return {
            "urgency_level": level, "reason_codes": ["TEST_DRAFT"], "outcome_title": "Next steps for this concern",
            "actions": [{"text": "Keep a short symptom diary.", "category": category,
                         "rationale": "It helps a clinician see the pattern.", "evidence_ids": []}],
            "claims": [{"text": "You described when this began.", "kind": "case_fact", "fact_ids": [fact],
                        "evidence_ids": []},
                       # ADR-015: every draft carries a possible explanation from general medical knowledge.
                       {"text": "Concerns like this are often linked to everyday factors such as sleep or workload.",
                        "kind": "clinical", "fact_ids": [], "evidence_ids": []}],
            "clinician_questions": ["What should I track?", "When should I come back?"],
            "escalation_advice": ["If it gets much worse, seek care promptly."],
            "uncertainties": ["Some details were not answered."] if any(
                f["answer"] is None for f in case["confirmed_facts"]) else [],
            **self.override,
        }

    async def generate_json(self, task, prompt_version, snapshot, schema_id, timeout_s):
        self.calls.append({"task": task, "prompt_version": prompt_version, "schema_id": schema_id,
                           "snapshot": snapshot})
        if task == "certainty_review":
            def unsafe(text):
                return any(p in text for p in self.unsafe_phrases)
            return {"verdicts": [{"index": s["index"], "unsafe": unsafe(s["text"]),
                                  "category": self.unsafe_category if unsafe(s["text"]) else "none"}
                                 for s in snapshot["statements"]]}
        if task == "red_flag_screen":
            out = self.screen(snapshot["person_words"]) if callable(self.screen) else self.screen
            if isinstance(out, BaseException):
                raise out
            return out
        if task == "concern_check":
            if isinstance(self.concern, BaseException):
                raise self.concern
            return self.concern
        out = self.outputs.pop(0) if self.outputs else self.draft(snapshot)
        if isinstance(out, BaseException):
            raise out
        return out

    async def health(self):
        return {"status": "ready", "provider": "zrt", "model_id": "test-model", "reason_code": None}

    async def manifest(self):
        return {"manifest_id": "test-model@local-test", "adapter_version": "test", "model": None}


PROFILE_SOURCES = {"Relevant history", "Current medications", "Reported allergies"}


def concern_screens_only(model) -> bool:
    """#153/#154: the only model calls so far read the concern (#387: with the profile free text) at case creation or
    an edit: the red-flag screen of the concern and profile, and the concern check. No answer was screened."""
    def concern_only(c):
        if c["task"] == "concern_check":
            return set(c["snapshot"]) == {"instructions", "text"}
        words = c["snapshot"]["person_words"] if c["task"] == "red_flag_screen" else []
        return (bool(words) and words[0]["source"] == "concern"
                and all(w["source"] in PROFILE_SOURCES for w in words[1:]))
    return bool(model.calls) and all(concern_only(c) for c in model.calls)


@pytest.fixture
def local(tmp_path):
    """A local-mode app with the reviewed pathway and a scripted model: yields (Api, LocalModel, app)."""
    settings = replace(load_settings(), mode="local", model_id="test-model", data_dir=tmp_path / "local")
    application = create_app(settings)
    with TestClient(application) as client:
        model = LocalModel()
        application.state.ctx.runtime = model
        api = Api(client)
        api.start()
        yield api, model, application


@pytest.fixture
def local_presenter(tmp_path):
    """A local-mode app with a presenter gateway (ADR-005 A) and a scripted model: yields (presenter Api, LocalModel,
    app). The patient side of the same browser is `Api(presenter.c)` (same cookie jar, no presenter assertion)."""
    settings = replace(load_settings(), mode="local", model_id="test-model", data_dir=tmp_path / "local",
                       presenter_key=TEST_PRESENTER_KEY, presenter_trusted_peers=("testclient",))
    application = create_app(settings)
    with TestClient(application):
        model = LocalModel()
        application.state.ctx.runtime = model
        presenter = Api(TestClient(application), presenter=True)
        presenter.start()
        yield presenter, model, application
