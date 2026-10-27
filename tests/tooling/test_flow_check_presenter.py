"""infra/deploy/flow_check.py presenter check against a stub gateway, in both modes.

#487 (ADR-005 amendment): one gateway and one origin. The stub serves the patient API under /api/v1 (a presenter
assertion is never honoured there) and the presenter API under /presenter-api/v1 (identified by X-AwareCare-Gateway).
The O03 scenario handoff runs in both modes (ADR-016, #113): load `routine`, continue on the patient API, reset.
In local mode (releases declaring `local-scenarios`) the check also asserts that the scripted `failure` scenario is
refused (404); earlier releases must refuse every load there. History: the first local
deployment of v0.5.0-demo.1 rolled back when the check expected a load the server refused (#59); until #113 local
mode refused every scenario.
"""
from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra/deploy"))
import flow_check  # noqa: E402


def gateway(mode: str, load_status: dict[str, int], state: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def route(self) -> tuple[bool | None, str]:
            """(presenter, API path) for an API request, (None, path) otherwise."""
            for prefix, presenter in (("/presenter-api/v1", True), ("/api/v1", False)):
                if self.path.startswith(prefix + "/"):
                    # A broken gateway that honours a presenter header on the patient path (never in a release).
                    leaked = not presenter and state.get("leaky_patient_path") and "X-AwareCare-Presenter" in self.headers
                    return presenter or bool(leaked), self.path[len(prefix):]
            return None, self.path

        def reply(self, status: int, body: dict | None = None, presenter: bool = False):
            raw = json.dumps(body or {}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if presenter and not state.get("no_presenter_hint"):
                self.send_header("X-AwareCare-Gateway", "presenter")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            presenter, path = self.route()
            if presenter is None:
                if path == "/" and state.get("start_redirect"):
                    self.send_response(302)
                    self.send_header("Location", "/presenter/scenarios")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                if path == "/aware-care-device.js":
                    raw = ('window.AWARE_CARE_DEVICE = { name: "HP ZGX Nano", shortName: "ZGX Nano", origin: "'
                           + state.get("device_origin", "") + '" };').encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/javascript")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return None
                return self.reply(404)
            if path == "/health/ready":
                return self.reply(200, {"readiness": "ready"}, presenter)
            if path == "/presenter/runtime":
                if presenter:
                    return self.reply(200, {"mode": mode, "readiness": "ready", "app_commit": "x",
                                            "device_inventory_id": "x", "model_manifest_id": "m"}, presenter)
                return self.reply(403, {"code": "PRESENTER_REQUIRED"})
            if path in ("/cases/case-1", "/cases/case-2"):
                gone = state.get("reset") or (path.endswith("case-1") and state.get("dropped"))
                return self.reply(401 if gone else 200, {}, presenter)
            if path == "/jobs/job-1":
                return self.reply(200, {"status": "succeeded"}, presenter)
            return self.reply(404, None, presenter)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            presenter, path = self.route()
            if path == "/sessions":
                return self.reply(201, {}, presenter)
            if presenter and path.startswith("/presenter/scenarios/") and path.endswith("/load"):
                sid = path.split("/")[-2]
                status = load_status.get(sid, 404)
                state.pop("reset", None)
                # #315/#316 releases name the screen; the urgent quick demo is the second case.
                case = "case-2" if sid == "urgent" else "case-1"
                if sid == "urgent" and state.get("drop_first"):
                    state["dropped"] = True  # a server that still reset the earlier demo
                screen = {"urgent": ("urgent", "urgent")}.get(sid, ("intake", "questions"))
                body = {"case_id": case, "state": screen[0], "next_path": f"/app/cases/{case}/{screen[1]}",
                        "prepare_job_id": None}
                return self.reply(status, body if status == 201 else {"code": "NOT_FOUND"}, presenter)
            if presenter and path == "/presenter/reset":
                state["reset"] = True
                return self.reply(202, {"deletion_job_id": "job-1"}, presenter)
            return self.reply(404, None, bool(presenter))

        def do_DELETE(self):
            presenter, _ = self.route()
            return self.reply(202, {}, bool(presenter))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class PresenterCheckTest(unittest.TestCase):
    def run_check(self, mode: str, local_scenarios: bool = True, quick_demos: bool = False, state: dict | None = None,
                  quick_flows: bool = False, **load_status: int) -> dict:
        state = {} if state is None else state
        server = gateway(mode, load_status, state)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        return flow_check.presenter_check(url, "http://127.0.0.1:2", mode, request_timeout=5, scenario_handoff=True,
                                          local_scenarios=local_scenarios, quick_demos=quick_demos,
                                          quick_flows=quick_flows)

    def test_local_mode_runs_the_handoff_and_refuses_the_scripted_failure(self):
        report = self.run_check("local", routine=201, failure=404)
        self.assertEqual(report["result"], "PASSED", report["failure"])
        self.assertEqual(report["scenario_handoff"], "PASSED")
        names = [s["step"] for s in report["steps"]]
        self.assertIn("scenario_case_after_reset", names)
        self.assertIn("scripted_failure_refused_in_local_mode", names)

    def test_local_mode_fails_when_the_scripted_failure_could_be_loaded(self):
        report = self.run_check("local", routine=201, failure=201)
        self.assertEqual(report["result"], "FAILED")
        self.assertIn("scripted_failure_refused_in_local_mode", report["failure"])

    def test_local_mode_fails_when_scenarios_are_refused(self):
        report = self.run_check("local", routine=404, failure=404)
        self.assertEqual(report["result"], "FAILED")
        self.assertIn("scenario_load: HTTP 404", report["failure"])

    def test_a_release_before_113_in_local_mode_must_refuse_scenarios(self):
        """Rollback targets (for example v0.5.6-demo.2) declare no `local-scenarios` and refuse every load."""
        report = self.run_check("local", local_scenarios=False, routine=404)
        self.assertEqual(report["result"], "PASSED", report["failure"])
        self.assertEqual(report["scenario_handoff"], "REFUSED_IN_LOCAL_MODE")
        report = self.run_check("local", local_scenarios=False, routine=201)
        self.assertEqual(report["result"], "FAILED")

    def test_mock_mode_requires_the_handoff(self):
        self.assertEqual(self.run_check("mock", routine=201)["result"], "PASSED")
        report = self.run_check("mock", routine=404)
        self.assertEqual(report["result"], "FAILED")
        self.assertIn("scenario_load: HTTP 404", report["failure"])


    # #315/#316: releases declaring `quick-demos` are also checked for the handoff they add (no model call).
    def test_a_quick_demos_release_passes_the_handoff_in_both_modes(self):
        for mode in ("local", "mock"):
            with self.subTest(mode=mode):
                report = self.run_check(mode, quick_demos=True, state={"device_origin": "http://127.0.0.1:2"},
                                        routine=201, urgent=201, failure=404)
                self.assertEqual(report["result"], "PASSED", report["failure"])
                names = [s["step"] for s in report["steps"]]
                for step in ("quick_demo_load", "earlier_demo_case_kept", "device_script",
                             "quick_demo_case_after_reset"):
                    self.assertIn(step, names)

    def test_a_quick_demos_release_fails_without_the_patient_origin(self):
        report = self.run_check("mock", quick_demos=True, state={}, routine=201, urgent=201)
        self.assertEqual(report["result"], "FAILED")
        self.assertIn("device script does not name the configured address", report["failure"])

    def test_a_quick_demos_release_fails_when_a_load_drops_the_earlier_demo(self):
        report = self.run_check("mock", quick_demos=True, state={"device_origin": "http://127.0.0.1:2",
                                                                "drop_first": True}, routine=201, urgent=201)
        self.assertEqual(report["result"], "FAILED")
        self.assertIn("earlier_demo_case_kept: HTTP 401", report["failure"])

    def test_an_older_release_is_checked_as_before(self):
        """A rollback target without `quick-demos` gets no quick-demo steps, even if it would answer them."""
        report = self.run_check("mock", quick_demos=False, routine=201)
        self.assertEqual(report["result"], "PASSED", report["failure"])
        self.assertNotIn("quick_demo_load", [s["step"] for s in report["steps"]])


    # #358: releases declaring `quick-flows` show, without a model call or a new case, that the flows' request is known.
    def test_a_quick_flows_release_checks_the_flow_request_without_running_it(self):
        for mode in ("local", "mock"):
            with self.subTest(mode=mode):
                report = self.run_check(mode, quick_demos=True, quick_flows=True, failure=404, routine=201, urgent=201,
                                        state={"device_origin": "http://127.0.0.1:2"})
                self.assertEqual(report["result"], "PASSED", report["failure"])
                self.assertIn("quick_flow_request_understood", [s["step"] for s in report["steps"]])

    def test_a_quick_flows_release_fails_when_the_server_refuses_the_flow_request(self):
        report = self.run_check("mock", quick_demos=True, quick_flows=True, routine=201, urgent=201,
                                state={"device_origin": "http://127.0.0.1:2"}, **{"not-a-scenario": 422})
        self.assertEqual(report["result"], "FAILED")
        self.assertIn("quick_flow_request_understood: HTTP 422", report["failure"])

    def test_a_release_without_quick_flows_gets_no_flow_step(self):
        report = self.run_check("mock", quick_demos=True, routine=201, urgent=201,
                                state={"device_origin": "http://127.0.0.1:2"})
        self.assertEqual(report["result"], "PASSED", report["failure"])
        self.assertNotIn("quick_flow_request_understood", [s["step"] for s in report["steps"]])

    def test_the_presenter_start_page_is_recorded_and_never_fails_an_older_release(self):
        """#326: where '/' leads is recorded and never fails the check; #487: on the one address it is the home page."""
        report = self.run_check("mock", state={"start_redirect": True}, routine=201)
        self.assertEqual(report["result"], "PASSED", report["failure"])
        self.assertEqual(report["presenter_start_page"], "SCENARIOS")
        report = self.run_check("mock", routine=201)
        self.assertEqual(report["result"], "PASSED", report["failure"])
        self.assertNotEqual(report["presenter_start_page"], "SCENARIOS")

    # #487: one gateway and one origin. Every request of the check goes to the one address; the roles differ by path.
    def test_487_both_roles_are_checked_through_one_address_by_path(self):
        report = self.run_check("mock", routine=201)
        self.assertEqual(report["result"], "PASSED", report["failure"])
        names = [s["step"] for s in report["steps"]]
        for step in ("presenter_readiness", "presenter_session", "patient_readiness", "forged_session_via_patient_path",
                     "forged_runtime_via_patient_path"):
            self.assertIn(step, names)

    def test_487_a_patient_path_that_honours_a_forged_presenter_header_fails(self):
        report = self.run_check("mock", routine=201, state={"leaky_patient_path": True})
        self.assertEqual(report["result"], "FAILED")
        self.assertIn("forged", report["failure"])

    def test_487_a_presenter_path_that_does_not_identify_itself_fails(self):
        report = self.run_check("mock", routine=201, state={"no_presenter_hint": True})
        self.assertEqual(report["result"], "FAILED")
        self.assertIn("the presenter path did not identify itself", report["failure"])

    def test_487_the_presenter_flag_runs_the_presenter_check_from_the_command_line(self):
        import subprocess
        server = gateway("local", {"routine": 201, "urgent": 201, "failure": 404}, {"device_origin": "http://127.0.0.1:2"})
        self.addCleanup(server.shutdown)
        out = subprocess.run([sys.executable, str(ROOT / "infra/deploy/flow_check.py"), "--presenter", "--base-url",
                              f"http://127.0.0.1:{server.server_address[1]}", "--origin", "http://127.0.0.1:2",
                              "--mode", "local", "--request-timeout", "5"], capture_output=True, text=True, timeout=60)
        report = json.loads(out.stdout)
        self.assertEqual((out.returncode, report["check"], report["result"]), (0, "aware-care-presenter-check", "PASSED"),
                         report.get("failure"))


if __name__ == "__main__":
    unittest.main()
