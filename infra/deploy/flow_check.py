#!/usr/bin/env python3
"""Post-deployment readiness and flow check for Aware Care (M12; R01, R02, R03, R26, R37).

Drives one synthetic guest journey through the deployed web gateway, the way a
browser behind the SSH tunnel would: readiness -> session -> case -> questions
-> review -> guidance job -> guidance -> session deletion. Standard library only,
so it runs on the deployment host without installing anything.

Every check has an overall time budget, and any error (a truncated response, an unexpected body, a bug) is
reported as FAILED rather than raised (#294), so the deploy tool always gets a result it can roll back on.

Mode is explicit. In mock mode the guidance must come from the labeled mock
fixture adapter. In local mode a mock-labeled result, a 503 or any failed step
is a failure: a failed local inference is never reported as success.

The report holds step names, HTTP statuses and timings only. No request or
response bodies are written, so no health content reaches logs or evidence.
"""
from __future__ import annotations

import argparse
import http.client
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

MOCK_MANIFEST_ID = "mock-fixture-adapter-1"
CONSENT_VERSION = "aware-care-demo-consent-1.0"
SYNTHETIC_CONCERN = "Synthetic deployment check: recurring headaches after long workdays."
# The A03 red-flag checklist answer "none of these apply" (ADR-003). Local mode limits a case without it; releases
# before the checklist store it as ordinary context.
NO_RED_FLAGS = {"kind": "red_flags", "value": [], "units": None, "origin": "user", "profile_revision": None}
MAX_QUESTIONS = 12  # the product cap is 10 issued slots; stop well before looping forever
FLOW_OVERHEAD_SECONDS = 60      # run(): default total budget = guidance timeout + this
PRESENTER_CHECK_SECONDS = 120   # presenter_check(): default total budget
CLEANUP_TIMEOUT_SECONDS = 10    # each session deletion after the budget, so cleanup still happens


class FlowError(RuntimeError):
    pass


# #487 (ADR-005 amendment): one gateway and one origin; the patient API is /api/v1 (any presenter assertion stripped)
# and the presenter API is /presenter-api/v1 (signed by the gateway), both the same API operations.
PATIENT_API = "/api/v1"
PRESENTER_API = "/presenter-api/v1"


class Client:
    def __init__(self, base_url: str, origin: str, timeout: float, jar: http.cookiejar.CookieJar | None = None,
                 deadline: float | None = None, api_prefix: str = PATIENT_API):
        self.base = base_url.rstrip("/")
        self.api_prefix = api_prefix
        self.origin = origin
        self.timeout = timeout
        self.deadline = deadline  # time.monotonic() value after which no further request starts
        self.csrf: str | None = None
        self.jar = jar if jar is not None else http.cookiejar.CookieJar()
        # #587: straight to the gateway on this host, never through an HTTP proxy from the environment
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                  urllib.request.HTTPCookieProcessor(self.jar))
        self.steps: list[dict] = []
        self.last_headers: dict[str, str] = {}

    def call(self, step: str, method: str, path: str, expect: set[int], body: dict | None = None,
             idempotent: bool = False, api: bool = True, extra: dict | None = None) -> tuple[int, dict | str | None]:
        headers = {"Accept": "application/json" if api else "text/html", **(extra or {})}
        if api:
            headers["Origin"] = self.origin
            if self.csrf:
                headers["X-CSRF-Token"] = self.csrf
            if idempotent:
                headers["Idempotency-Key"] = str(uuid.uuid4())
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        url = f"{self.base}{self.api_prefix}{path}" if api else f"{self.base}{path}"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        timeout = self.timeout
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise FlowError(f"{step}: the check's time budget is exhausted")
            timeout = min(timeout, remaining)
        started = time.perf_counter()
        try:
            try:
                with self.opener.open(request, timeout=timeout) as response:
                    status, raw, response_headers = response.status, response.read(), response.headers
            except urllib.error.HTTPError as exc:
                status, raw, response_headers = exc.code, exc.read(), exc.headers
        # URLError, timeouts and resets are OSErrors; a truncated body is http.client.IncompleteRead (#294).
        except (OSError, http.client.HTTPException) as exc:
            self.steps.append({"step": step, "status": None, "ok": False, "error": type(exc).__name__,
                               "ms": round((time.perf_counter() - started) * 1000, 1)})
            raise FlowError(f"{step}: {type(exc).__name__}") from exc
        ok = status in expect
        self.last_headers = {k.lower(): v for k, v in response_headers.items()}
        self.steps.append({"step": step, "status": status, "ok": ok,
                           "ms": round((time.perf_counter() - started) * 1000, 1)})
        if response_headers.get("X-CSRF-Token"):
            self.csrf = response_headers["X-CSRF-Token"]
        if not ok:
            raise FlowError(f"{step}: HTTP {status}, expected {sorted(expect)}")
        if not api:
            return status, raw.decode(errors="replace")
        try:
            return status, (json.loads(raw) if raw else None)
        except ValueError as exc:
            raise FlowError(f"{step}: response is not JSON") from exc

    def cleanup_mode(self) -> None:
        """After the budget: short per-request timeouts, no deadline, so the synthetic session is still deleted."""
        self.deadline = None
        self.timeout = min(self.timeout, CLEANUP_TIMEOUT_SECONDS)


def answer_value(question: dict):
    kind = question.get("response_type")
    if kind == "single_choice":
        return question["choices"][0]["id"]
    if kind == "multiple_choice":
        return [question["choices"][0]["id"]]
    if kind == "text":
        return "No changes yet."
    if kind == "scale":
        return 4
    raise FlowError(f"unsupported question response_type {kind!r}")


def run(base_url: str, origin: str, mode: str, guidance_timeout: float, request_timeout: float,
        total_timeout: float | None = None) -> dict:
    budget = total_timeout if total_timeout is not None else guidance_timeout + FLOW_OVERHEAD_SECONDS
    client = Client(base_url, origin, request_timeout, deadline=time.monotonic() + budget)
    report: dict = {"check": "aware-care-flow-check", "mode": mode, "base_url": base_url, "origin": origin,
                    "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "result": "FAILED", "failure": None, "steps": client.steps}
    session_created = False
    try:
        _, html = client.call("web_index", "GET", "/", {200}, api=False)
        if '<div id="root"' not in html:
            raise FlowError("web_index: application shell not served")
        client.call("web_deep_route", "GET", "/app/start", {200}, api=False)
        _, ready = client.call("readiness", "GET", "/health/ready", {200})
        if not isinstance(ready, dict) or ready.get("readiness") != "ready":
            raise FlowError("readiness: not ready")
        client.call("create_session", "POST", "/sessions", {201}, idempotent=True,
                    body={"mode": "guest", "consent_version": CONSENT_VERSION, "adult_eligible": True})
        session_created = True
        _, case = client.call("create_case", "POST", "/cases", {201}, idempotent=True,
                              body={"concern": SYNTHETIC_CONCERN, "confirmed_context": [NO_RED_FLAGS]})
        case_id, revision = case["id"], case["revision"]
        for index in range(1, MAX_QUESTIONS + 1):
            _, nxt = client.call(f"next_question_{index}", "POST", f"/cases/{case_id}/questions/next", {200},
                                 idempotent=True, body={"expected_revision": revision})
            if nxt["kind"] == "review_required":
                break
            question = nxt["question"]
            _, saved = client.call(f"save_answer_{index}", "PUT", f"/cases/{case_id}/answers/{question['id']}", {200},
                                   body={"expected_revision": revision, "status": "answered",
                                         "value": answer_value(question)})
            revision = saved["case_revision"]
        else:
            raise FlowError("intake did not reach review within the slot cap")
        _, current = client.call("get_case", "GET", f"/cases/{case_id}", {200})
        revision = current["case"]["revision"]
        client.call("confirm_review", "POST", f"/cases/{case_id}/review", {200},
                    body={"expected_revision": revision, "facts_confirmed": True})
        _, job = client.call("generate_guidance", "POST", f"/cases/{case_id}/guidance", {202}, idempotent=True,
                             body={"expected_revision": revision})
        deadline = time.monotonic() + guidance_timeout
        polls = 0
        while True:
            polls += 1
            _, job = client.call("poll_job", "GET", f"/jobs/{job['id']}", {200})
            if job["status"] in {"succeeded", "failed", "stale", "cancelled"}:
                break
            if time.monotonic() > deadline:
                raise FlowError(f"guidance job still {job['status']} after {guidance_timeout:.0f}s")
            time.sleep(0.25)
        # Collapse the poll entries so the report stays short.
        poll_steps = [s for s in client.steps if s["step"] == "poll_job"]
        client.steps[:] = [s for s in client.steps if s["step"] != "poll_job"]
        client.steps.append({"step": "poll_job", "status": poll_steps[-1]["status"], "ok": True,
                             "polls": polls, "ms": round(sum(s["ms"] for s in poll_steps), 1)})
        if job["status"] != "succeeded":
            raise FlowError(f"guidance job ended {job['status']}")
        _, guidance = client.call("get_guidance", "GET", f"/cases/{case_id}/guidance", {200})
        manifest_id = guidance.get("model_manifest_id")
        report["guidance_model_manifest_id"] = manifest_id
        if mode == "mock" and manifest_id != MOCK_MANIFEST_ID:
            raise FlowError("mock mode: guidance did not come from the labeled mock fixture adapter")
        if mode == "local" and (not manifest_id or str(manifest_id).startswith("mock")):
            raise FlowError("local mode: guidance is mock-labeled; refusing to report it as local inference")
        report["result"] = "PASSED"
    except FlowError as exc:
        report["failure"] = str(exc)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        report["failure"] = f"unexpected response shape: {type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001  (#294: any error is a FAILED check, never a crash of the deploy)
        report["failure"] = f"unexpected error: {type(exc).__name__}"
    finally:
        if session_created:
            client.cleanup_mode()
            try:
                # deleteSession is asynchronous: the contract's only success status is 202.
                client.call("delete_session", "DELETE", "/sessions/current", {202})
            except Exception as exc:  # noqa: BLE001
                report["result"] = "FAILED"
                report["failure"] = report["failure"] or (f"cleanup failed: {exc}" if isinstance(exc, FlowError)
                                                          else f"cleanup failed: {type(exc).__name__}")
        report["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return report


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


def presenter_start_page(presenter_url: str, timeout: float) -> str:
    """#326: where the address itself ('/') leads, recorded (never a failure): INDEX for the app shell (#487: the home
    page with the patient or presenter choice), SCENARIOS for the former presenter port's redirect to O03, otherwise
    HTTP <status> or the error class."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)  # #587: no proxy
    request = urllib.request.Request(presenter_url.rstrip("/") + "/", headers={"Accept": "text/html"})
    try:
        try:
            with opener.open(request, timeout=timeout) as response:
                status, location = response.status, response.headers.get("Location", "")
        except urllib.error.HTTPError as exc:
            status, location = exc.code, exc.headers.get("Location", "")
    except (OSError, http.client.HTTPException) as exc:
        return type(exc).__name__
    if status in (301, 302, 303, 307, 308) and location.rstrip("/").endswith("/presenter/scenarios"):
        return "SCENARIOS"
    return "INDEX" if status == 200 else f"HTTP {status}"


FORGED_ASSERTION = "v1.0." + "0" * 32 + "." + "0" * 64


def _scenario_handoff(pres: Client, base_url: str, origin: str, request_timeout: float,
                      quick_demos: bool = False, quick_flows: bool = False) -> str:
    """O03 in the same browser: load a scenario through the presenter API, continue it through the patient API of the
    same address (#487; shared cookie jar, separate cookies), then reset and confirm the demo session is gone.

    Releases declaring `quick-demos` (#315/#316) are also checked for the handoff they add, without any model call: the
    load names the patient screen to open, a second load with reset=false keeps the first case, an urgent quick demo
    (prepare=result) is at its result at once, and the device script names the one configured address.

    Releases declaring `quick-flows` (#358) also show that the one-click flows' request is understood, still without
    a model call and without creating anything: `urgency_input` passes validation and an unknown scenario is then
    refused 404 (a release without it refuses the field itself, 422)."""
    _, loaded = pres.call("scenario_load", "POST", "/presenter/scenarios/routine/load", {201}, idempotent=True,
                          body={"reset": True})
    browser = Client(base_url, origin, request_timeout, jar=pres.jar, deadline=pres.deadline)
    browser.steps = pres.steps
    browser.call("scenario_case_on_patient_site", "GET", f"/cases/{loaded['case_id']}", {200})
    cases = [loaded["case_id"]]
    if quick_demos:
        if loaded.get("next_path") != f"/app/cases/{loaded['case_id']}/questions":
            raise FlowError("scenario load did not name the first-question screen")
        _, quick = pres.call("quick_demo_load", "POST", "/presenter/scenarios/urgent/load", {201}, idempotent=True,
                             body={"reset": False, "prepare": "result"})
        if (quick.get("state"), quick.get("prepare_job_id"), quick.get("next_path")) != (
                "urgent", None, f"/app/cases/{quick['case_id']}/urgent"):
            raise FlowError("the urgent quick demo was not at its result at once")
        browser.call("quick_demo_case_on_patient_site", "GET", f"/cases/{quick['case_id']}", {200})
        browser.call("earlier_demo_case_kept", "GET", f"/cases/{loaded['case_id']}", {200})
        cases.append(quick["case_id"])
        _, script = pres.call("device_script", "GET", "/aware-care-device.js", {200}, api=False)
        if f'origin: "{origin}"' not in str(script):
            raise FlowError("the device script does not name the configured address")
    if quick_flows:
        pres.call("quick_flow_request_understood", "POST", "/presenter/scenarios/not-a-scenario/load", {404},
                  idempotent=True, body={"reset": False, "prepare": "result", "urgency_input": "written"})
    pres.call("presenter_still_active", "GET", "/presenter/runtime", {200})
    _, accepted = pres.call("presenter_reset", "POST", "/presenter/reset", {202}, idempotent=True)
    deadline = time.monotonic() + 30
    while True:
        _, job = pres.call("presenter_reset_job", "GET", f"/jobs/{accepted['deletion_job_id']}", {200})
        if job["status"] in {"succeeded", "failed", "stale", "cancelled"}:
            break
        if time.monotonic() > deadline:
            raise FlowError("presenter reset did not finish within 30 s")
        time.sleep(0.25)
    if job["status"] != "succeeded":
        raise FlowError(f"presenter reset ended {job['status']}")
    for index, case_id in enumerate(cases):
        browser.call("scenario_case_after_reset" if index == 0 else "quick_demo_case_after_reset", "GET",
                     f"/cases/{case_id}", {401})
    return "PASSED"


def presenter_check(base_url: str, origin: str, expected_mode: str, request_timeout: float = 15.0,
                    scenario_handoff: bool = False, local_scenarios: bool = False,
                    total_timeout: float = PRESENTER_CHECK_SECONDS, quick_demos: bool = False,
                    quick_flows: bool = False) -> dict:
    """ADR-005 option A on the deployed gateway (#487: one port and one origin): a presenter session works through
    the presenter path /presenter-api/, and a forged assertion sent to the patient path /api/ never yields presenter
    access.

    The O03 scenario handoff runs in mock mode, and in local mode for releases that declare `local-scenarios`
    (ADR-016, #113): there a scenario only starts its synthetic case and the rest runs live, so the check also asserts
    that the scripted `failure` scenario is refused (404), because forcing it would fake the local AI. Earlier releases
    (for example a rollback target) refuse every scenario in local mode, and the check asserts that instead. Releases
    that declare `quick-demos` (#315/#316) also get the model-free quick-demo handoff check (see _scenario_handoff);
    older releases are checked exactly as before. Releases that declare `quick-flows` (#358) also get the model-free
    check that the one-click flows' request is understood."""
    report: dict = {"check": "aware-care-presenter-check", "result": "FAILED", "failure": None, "steps": []}
    body = {"mode": "guest", "consent_version": CONSENT_VERSION, "adult_eligible": True}
    sessions = []
    deadline = time.monotonic() + total_timeout
    try:
        pres = Client(base_url, origin, request_timeout, deadline=deadline, api_prefix=PRESENTER_API)
        report["steps"] = pres.steps
        pres.call("presenter_readiness", "GET", "/health/ready", {200})
        if pres.last_headers.get("x-awarecare-gateway") != "presenter":
            raise FlowError("the presenter path did not identify itself")
        pres.call("presenter_session", "POST", "/sessions", {201}, idempotent=True, body=body)
        sessions.append(pres)
        _, runtime = pres.call("presenter_runtime", "GET", "/presenter/runtime", {200})
        if runtime.get("mode") != expected_mode:
            raise FlowError(f"runtime mode {runtime.get('mode')!r} is not {expected_mode!r}")
        report["runtime"] = {k: runtime.get(k) for k in ("mode", "readiness", "app_commit", "device_inventory_id",
                                                           "model_manifest_id")}
        report["presenter_start_page"] = presenter_start_page(base_url, min(request_timeout, 5.0))
        if not scenario_handoff:
            report["scenario_handoff"] = "NOT_SUPPORTED_BY_RELEASE"
        elif expected_mode == "mock" or local_scenarios:
            report["scenario_handoff"] = _scenario_handoff(pres, base_url, origin, request_timeout,
                                                           quick_demos=quick_demos, quick_flows=quick_flows)
            if expected_mode == "local":
                pres.call("scripted_failure_refused_in_local_mode", "POST", "/presenter/scenarios/failure/load",
                          {404}, idempotent=True, body={"reset": True})
        else:
            # Releases before #113 keep scenarios mock-only: local mode must refuse to load one.
            pres.call("scenario_load_refused_in_local_mode", "POST", "/presenter/scenarios/routine/load", {404},
                      idempotent=True, body={"reset": True})
            report["scenario_handoff"] = "REFUSED_IN_LOCAL_MODE"
        patient = Client(base_url, origin, request_timeout, deadline=deadline)
        patient.steps = pres.steps
        patient.call("patient_readiness", "GET", "/health/ready", {200})
        if patient.last_headers.get("x-awarecare-gateway"):
            raise FlowError("the patient path claims to be the presenter path")
        forged = {"X-AwareCare-Presenter": FORGED_ASSERTION}
        # The patient path strips the header, so this becomes an ordinary guest session.
        patient.call("forged_session_via_patient_path", "POST", "/sessions", {201}, idempotent=True, body=body,
                     extra=forged)
        sessions.append(patient)
        _, refused = patient.call("forged_runtime_via_patient_path", "GET", "/presenter/runtime", {403},
                                  extra=forged)
        if (refused or {}).get("code") != "PRESENTER_REQUIRED":
            raise FlowError("forged presenter request was not refused with PRESENTER_REQUIRED")
        report["result"] = "PASSED"
    except FlowError as exc:
        report["failure"] = str(exc)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        report["failure"] = f"unexpected response shape: {type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001  (#294: any error is a FAILED check)
        report["failure"] = f"unexpected error: {type(exc).__name__}"
    finally:
        for index, client in enumerate(sessions):
            client.cleanup_mode()
            try:
                client.call(f"delete_session_{index + 1}", "DELETE", "/sessions/current", {202})
            except Exception as exc:  # noqa: BLE001
                report["result"] = "FAILED"
                report["failure"] = report["failure"] or (f"cleanup failed: {exc}" if isinstance(exc, FlowError)
                                                          else f"cleanup failed: {type(exc).__name__}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True, help="Web gateway URL, e.g. http://127.0.0.1:8180")
    parser.add_argument("--origin", required=True, help="Browser origin allowed by the API, e.g. http://127.0.0.1:18180")
    parser.add_argument("--mode", required=True, choices=["mock", "local"])
    parser.add_argument("--guidance-timeout", type=float, default=90.0)
    parser.add_argument("--request-timeout", type=float, default=15.0)
    parser.add_argument("--output", help="Write the JSON report here as well as to stdout")
    parser.add_argument("--presenter", action="store_true",
                        help="#487: run the model-free presenter check of this release (the /presenter-api/ path, the "
                             "forged-header refusal on /api/ and the O03 handoff) instead of the guest journey")
    args = parser.parse_args()
    if args.presenter:
        report = presenter_check(args.base_url, args.origin, args.mode, args.request_timeout, scenario_handoff=True,
                                 local_scenarios=True, quick_demos=True, quick_flows=True)
    else:
        report = run(args.base_url, args.origin, args.mode, args.guidance_timeout, args.request_timeout)
    text = json.dumps(report, indent=2)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return 0 if report["result"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
