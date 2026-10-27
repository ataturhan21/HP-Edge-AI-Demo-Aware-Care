"""infra/deploy/nano_deploy.py and flow_check.py: every failure after parking restores the old release.

QA 2026-10-19 reproduced these with a fake docker (#294, #297, #300): a cancel (SIGINT/SIGTERM), a crash in a check
or a failure between parking the API and the web container skipped the rollback and left the old release stopped;
images were never compared with the release commit; a rollback made the bad release the next rollback target; and a
malformed ZRT /models reply crashed preflight. A fake docker keeps container state in memory; nothing real runs.
"""
from __future__ import annotations

import argparse
import contextlib
import errno
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra/deploy"))
import flow_check  # noqa: E402
import nano_deploy  # noqa: E402

NANO = json.loads((ROOT / "infra/deploy/demo-zgx-nano.json").read_text())
OLD = {"release_tag": "v1", "app_commit": "c1", "mode": "local", "model_id": "m", "api_image": "a@sha256:1",
       "web_image": "w@sha256:1"}
NEW = {"release_tag": "v2", "app_commit": "c2", "mode": "local", "model_id": "m", "api_image": "a@sha256:2",
       "web_image": "w@sha256:2"}
PASSED = (True, {"result": "PASSED"}, {"result": "PASSED"})


class FakeDocker:
    """In-memory containers: name -> {"running", "image"}. `fail_on` makes matching commands fail."""

    def __init__(self, revision: str = "c2", fail_on: tuple[str, ...] = ()):
        self.c = {"aware-care-demo-api": {"running": True, "image": "old"},
                  "aware-care-demo-web": {"running": True, "image": "old"}}
        self.revision = revision
        self.fail_on = fail_on
        self.calls: list[str] = []

    def __call__(self, *args, check=True, capture=True, timeout=None):
        a = list(args)
        self.calls.append(" ".join(a))
        rc, out = 0, ""
        if any(f in " ".join(a) for f in self.fail_on):
            rc = 1
        elif a[:2] == ["container", "inspect"]:
            if a[2] in self.c:
                state = self.c[a[2]]
                out = json.dumps([{"State": {"Status": "running" if state["running"] else "exited",
                                             "Running": state["running"], "ExitCode": 0},
                                   "Image": state["image"], "Config": {"Labels": {}}}])
            else:
                rc = 1
        elif a[0] == "rm":
            self.c.pop(a[-1], None)
        elif a[0] == "stop":
            self.c[a[-1]]["running"] = False
        elif a[0] == "rename":
            self.c[a[2]] = self.c.pop(a[1])
        elif a[0] == "start":
            self.c[a[1]]["running"] = True
        elif a[0] == "run":
            self.c[a[a.index("--name") + 1]] = {"running": True, "image": "new"}
        elif a[:2] == ["image", "inspect"]:
            out = json.dumps([{"Id": "x", "Architecture": "arm64", "Os": "linux",
                               "Config": {"Labels": {"org.opencontainers.image.revision": self.revision}}}])
        result = subprocess.CompletedProcess(["docker", *a], rc, out, "boom" if rc else "")
        if check and rc:
            raise nano_deploy.DeployError(f"docker {a[0]} failed: boom")
        return result

    def summary(self) -> dict:
        return {name: (state["image"], state["running"]) for name, state in self.c.items()}


RESTORED = {"aware-care-demo-api": ("old", True), "aware-care-demo-web": ("old", True)}


class DeployFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "aware-care-demo"
        args = argparse.Namespace(instance=None, data_root=str(self.root), api_port=None, web_port=None,
                                  origin=None, expected_arch="arm64")
        self.settings = nano_deploy.Settings(NANO, args)
        nano_deploy.write_state(self.settings, "current", OLD)
        self.evidence: dict = {}
        # #578: a local deploy takes the model lock; tests use their own lock file, never the device's.
        self.lock = self.root.parent / "model.lock"
        env = mock.patch.dict(os.environ, {"AWARE_CARE_MODEL_LOCK": str(self.lock), "AWARE_CARE_MODEL_LOCK_STEP": "1"})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("AWARE_CARE_MODEL_LOCK_HELD", None)
        os.environ.pop("AWARE_CARE_MODEL_LOCK_WAIT", None)

    def deploy(self, fake: FakeDocker, *patches, target: dict = NEW, action: str = "deploy"):
        with contextlib.ExitStack() as stack:
            for p in (mock.patch.object(nano_deploy, "docker", fake),
                      mock.patch.object(nano_deploy, "port_in_use", return_value=False),
                      mock.patch.object(nano_deploy, "zrt_preflight"),
                      mock.patch.object(nano_deploy.platform, "machine", return_value="aarch64"),
                      mock.patch.object(nano_deploy.shutil, "which", return_value="/usr/bin/docker"),
                      mock.patch.object(nano_deploy, "install_power_sampler", return_value={}),
                      mock.patch.object(nano_deploy, "install_boot_check", return_value={}),
                      mock.patch.object(nano_deploy, "write_evidence",
                                        lambda _s, evidence, _o: self.evidence.update(evidence)),
                      *patches):
                stack.enter_context(p)
            return nano_deploy.deploy(self.settings, target, pull=False, require_digest=True, guidance_timeout=1,
                                      evidence_out=None, action=action)


class RollbackOnAnyFailure(DeployFixture):
    """#294."""

    def test_a_failure_between_parking_the_api_and_the_web_container_restores_the_api(self):
        fake = FakeDocker(fail_on=("stop -t 20 aware-care-demo-web",))
        with mock.patch.object(nano_deploy, "verify", return_value=PASSED) as verify:
            code = self.deploy(fake)
        self.assertEqual(code, 1)
        self.assertEqual(fake.summary(), RESTORED)       # the parked API is back, the unparked web kept running
        self.assertEqual(self.evidence["rollback"]["outcome"], "ROLLED_BACK")
        verify.assert_called_once()                      # only the restored release was checked
        self.assertFalse(any(call.startswith("run ") for call in fake.calls))

    def test_a_crash_in_the_checks_rolls_back_then_re_raises(self):
        fake = FakeDocker()
        crash = AttributeError("'NoneType' object has no attribute 'get'")
        with mock.patch.object(nano_deploy, "verify", side_effect=[crash, PASSED]):
            with self.assertRaises(AttributeError):
                self.deploy(fake)
        self.assertEqual(fake.summary(), RESTORED)
        self.assertEqual(self.evidence["rollback"]["outcome"], "ROLLED_BACK")
        self.assertEqual(self.evidence["failure"], "unexpected error: AttributeError")
        self.assertEqual(nano_deploy.read_state(self.settings, "current")["release_tag"], "v1")

    def test_a_cancel_restores_the_parked_containers_without_rechecking_them(self):
        fake = FakeDocker()
        with mock.patch.object(nano_deploy, "wait_ready", side_effect=KeyboardInterrupt()), \
                mock.patch.object(flow_check, "run") as flow:
            with self.assertRaises(KeyboardInterrupt):
                self.deploy(fake)
        self.assertEqual(fake.summary(), RESTORED)
        self.assertEqual(self.evidence["rollback"]["outcome"], "RESTORED_UNCHECKED")
        self.assertEqual(self.evidence["failure"], "interrupted by signal SIGINT")
        flow.assert_not_called()

    def test_sigterm_from_a_workflow_cancel_or_timeout_restores_too(self):
        fake = FakeDocker()
        previous = signal.signal(signal.SIGTERM, nano_deploy._raise_interrupted)
        self.addCleanup(signal.signal, signal.SIGTERM, previous)

        def terminated(*_args):
            os.kill(os.getpid(), signal.SIGTERM)
            raise AssertionError("SIGTERM was not delivered")
        with mock.patch.object(nano_deploy, "verify", side_effect=terminated):
            with self.assertRaises(nano_deploy.DeployInterrupted):
                self.deploy(fake)
        self.assertEqual(fake.summary(), RESTORED)
        self.assertEqual(self.evidence["rollback"]["outcome"], "RESTORED_UNCHECKED")
        self.assertEqual(self.evidence["failure"], "interrupted by signal SIGTERM")

    def test_a_cancel_before_anything_was_parked_changes_nothing(self):
        fake = FakeDocker()
        with mock.patch.object(nano_deploy, "park_current", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.deploy(fake)
        self.assertEqual(fake.summary(), RESTORED)
        self.assertIsNone(self.evidence["rollback"])

    def test_an_error_after_the_new_release_passed_does_not_remove_it(self):
        fake = FakeDocker()
        late = mock.patch.object(nano_deploy, "install_boot_check", side_effect=RuntimeError("late"))
        with mock.patch.object(nano_deploy, "verify", return_value=PASSED):
            with self.assertRaises(RuntimeError):
                self.deploy(fake, late)
        self.assertEqual(fake.summary(), {"aware-care-demo-api": ("new", True), "aware-care-demo-web": ("new", True)})
        self.assertIsNone(self.evidence["rollback"])

    def test_the_failed_restore_is_reported_not_raised(self):
        fake = FakeDocker()
        with mock.patch.object(nano_deploy, "verify", return_value=(False, {"result": "FAILED", "failure": "x"},
                                                                    None)), \
                mock.patch.object(nano_deploy, "restore_parked", side_effect=KeyError("State")):
            code = self.deploy(fake)
        self.assertEqual(code, 1)
        self.assertEqual(self.evidence["rollback"], {"outcome": "ROLLBACK_FAILED",
                                                     "detail": "unexpected error: KeyError"})


class StateCommit(DeployFixture):
    """#591: recording the deployment (state/current.json, state/previous.json) is part of its commit. QA injected
    ENOSPC while the state was written after the checks passed: the new release kept running, the parked old one was
    already removed and current.json still named the old release, because the rollback guard was cleared first."""

    maxDiff = None
    V0 = {**OLD, "release_tag": "v0", "app_commit": "c0", "api_image": "a@sha256:0", "web_image": "w@sha256:0"}

    def fault(self, which: str, how: str) -> list:
        """ENOSPC while state/<which>.json's new content is written (a file of that name is created in the state
        folder), or EACCES when it is put in place (a rename onto state/<which>.json). Every such attempt fails."""
        state = self.settings.state_dir
        real_open, real_replace = os.open, os.replace

        def fake_open(path, flags, *args, **kwargs):
            p = Path(path)
            if how == "write" and p.parent == state and p.name.startswith(which) and flags & os.O_CREAT:
                raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), str(p))
            return real_open(path, flags, *args, **kwargs)

        def fake_replace(src, dst, *args, **kwargs):
            if how == "rename" and Path(dst) == state / f"{which}.json":
                raise OSError(errno.EACCES, os.strerror(errno.EACCES), str(dst))
            return real_replace(src, dst, *args, **kwargs)
        return [mock.patch.object(nano_deploy.os, "open", fake_open),
                mock.patch.object(nano_deploy.os, "replace", fake_replace)]

    def outcome(self, fake: FakeDocker, *patches, **kwargs) -> dict:
        self.evidence.clear()
        try:
            with mock.patch.object(nano_deploy, "verify", return_value=PASSED), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = self.deploy(fake, *patches, **kwargs)
        except Exception as exc:  # noqa: BLE001  (the unfixed tool let the OSError escape)
            code = f"raised {type(exc).__name__}"
        state = lambda which: (nano_deploy.read_state(self.settings, which) or {}).get("release_tag")  # noqa: E731
        return {"code": code, "containers": fake.summary(), "current": state("current"),
                "previous": state("previous"), "outcome": self.evidence.get("outcome"),
                "state files": sorted(p.name for p in self.settings.state_dir.iterdir())}

    def test_591_a_failed_state_write_restores_the_old_release_which_stays_recorded(self):
        for which in ("previous", "current"):
            for how, name in (("write", "ENOSPC"), ("rename", "EACCES")):
                with self.subTest(which=which, how=how):
                    nano_deploy.write_state(self.settings, "current", OLD)
                    nano_deploy.write_state(self.settings, "previous", self.V0)
                    fake = FakeDocker()
                    self.assertEqual(self.outcome(fake, *self.fault(which, how)), {
                        "code": 1, "containers": RESTORED, "current": "v1", "previous": "v0", "outcome": "ROLLED_BACK",
                        "state files": ["current.json", "previous.json"]})
                    self.assertIn("could not record the deployment", self.evidence["failure"])
                    self.assertIn(name, self.evidence["failure"])
                    self.assertNotIn("rolled_back_from", self.evidence)

    def test_591_a_failed_state_write_during_a_rollback_keeps_the_rollback_target(self):
        """#300 clears previous.json after a rollback; a failed write of current.json must not have cleared it."""
        for how in ("write", "rename"):
            with self.subTest(how=how):
                nano_deploy.write_state(self.settings, "current", NEW)  # v2 runs, v1 is the rollback target
                nano_deploy.write_state(self.settings, "previous", OLD)
                result = self.outcome(FakeDocker(revision="c1"), *self.fault("current", how), target=OLD,
                                      action="rollback")
                self.assertEqual(result, {"code": 1, "containers": RESTORED, "current": "v2", "previous": "v1",
                                          "outcome": "ROLLED_BACK", "state files": ["current.json", "previous.json"]})

    def test_591_a_file_that_cannot_be_put_back_is_named_and_its_former_content_kept(self):
        nano_deploy.write_state(self.settings, "current", OLD)
        nano_deploy.write_state(self.settings, "previous", self.V0)
        real_replace = os.replace

        def replace(src, dst, *args, **kwargs):  # current.json cannot be swapped in, previous.json not put back
            if Path(dst).name == "current.json" or Path(src).name == "previous.json.undo":
                raise OSError(errno.EIO, os.strerror(errno.EIO), str(dst))
            return real_replace(src, dst, *args, **kwargs)
        with mock.patch.object(nano_deploy.os, "replace", replace), \
                self.assertRaisesRegex(nano_deploy.DeployError, r"nor put back previous\.json \(its former content "
                                                                r"is previous\.json\.undo\)"):
            nano_deploy.commit_state(self.settings, {"previous": OLD, "current": NEW})
        self.assertEqual(json.loads((self.settings.state_dir / "previous.json.undo").read_text())["release_tag"], "v0")
        self.assertEqual(nano_deploy.read_state(self.settings, "current")["release_tag"], "v1")

    def test_591_control_without_a_fault_the_new_release_is_recorded_and_the_parked_one_removed(self):
        nano_deploy.write_state(self.settings, "previous", self.V0)
        self.assertEqual(self.outcome(FakeDocker()), {
            "code": 0, "containers": {"aware-care-demo-api": ("new", True), "aware-care-demo-web": ("new", True)},
            "current": "v2", "previous": "v1", "outcome": "SUCCEEDED", "state files": ["current.json", "previous.json"]})


class GatewayAddress(DeployFixture):
    """#587: the gateway binds network.bind_host (or --bind-host), which accepts the IPv6 loopback ::1, but readiness,
    the flow and presenter checks and status all asked http://127.0.0.1:<port>, so a healthy IPv6-only gateway failed
    its readiness check and was rolled back."""

    def bound(self, host: str, presenter: bool = False) -> nano_deploy.Settings:
        args = argparse.Namespace(instance=None, data_root=str(self.root), api_port=None, web_port=None, origin=None,
                                  expected_arch="arm64", bind_host=host)
        settings = nano_deploy.Settings(NANO, args)
        if presenter:
            settings.presenter_key.parent.mkdir(parents=True, exist_ok=True)
            settings.presenter_key.write_text("k")
            os.chmod(settings.presenter_key, 0o600)
        else:
            settings.presenter_key.unlink(missing_ok=True)
        return settings

    def test_587_readiness_the_flow_and_presenter_checks_and_status_ask_the_bound_address(self):
        port, ready = NANO["network"]["web_port"], NANO["readiness"]["path"]
        for host, base, presenter in (("::1", f"http://[::1]:{port}", True),
                                      ("127.0.0.1", f"http://127.0.0.1:{port}", True),
                                      ("localhost", f"http://localhost:{port}", True),
                                      ("::", f"http://[::1]:{port}", False),  # a wildcard: its family's loopback
                                      ("0.0.0.0", f"http://127.0.0.1:{port}", False)):
            with self.subTest(bind_host=host):
                settings, asked = self.bound(host, presenter), []

                def http_status(url, timeout=5.0):
                    asked.append(url)
                    return 200, {"readiness": "ready"}

                def check(base_url, *_args, **_kwargs):
                    asked.append(base_url)
                    return {"result": "PASSED"}
                with mock.patch.object(nano_deploy, "http_status", http_status), \
                        mock.patch.object(flow_check, "run", check), \
                        mock.patch.object(flow_check, "presenter_check", check), \
                        mock.patch.object(nano_deploy, "presenter_support", return_value="enabled"), \
                        mock.patch.object(nano_deploy, "api_capabilities", return_value=set()):
                    ok, _readiness, flow = nano_deploy.verify(settings, "mock", 1)
                    self.assertTrue(ok, flow)
                    with mock.patch.object(nano_deploy, "container_state", return_value=None), \
                            mock.patch.object(nano_deploy, "model_base_url", return_value=None), \
                            contextlib.redirect_stdout(io.StringIO()):
                        nano_deploy.status(settings)
                self.assertEqual(asked, [base + ready, base] + ([base] if presenter else []) + [base + ready])

    @unittest.skipUnless(socket.has_ipv6, "no IPv6")
    def test_587_a_gateway_listening_on_ipv6_loopback_only_passes_its_checks(self):
        """A real listener on [::1] only, and an HTTP proxy in the environment whose no_proxy names 127.0.0.1 but not
        ::1 (as on the maintainer's machines): readiness and the flow and presenter checks' requests reach it."""
        import http.server

        class Ready(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = b'{"readiness": "ready"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        class V6Server(http.server.HTTPServer):
            address_family = socket.AF_INET6
        try:
            server = V6Server(("::1", 0), Ready)
        except OSError:
            self.skipTest("no IPv6 loopback")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        settings = self.bound("::1")
        settings.web_port, settings.readiness_timeout = server.server_address[1], 3
        proxy = {"http_proxy": "http://192.0.2.1:9", "HTTP_PROXY": "http://192.0.2.1:9",
                 "no_proxy": "localhost,127.0.0.1", "NO_PROXY": "localhost,127.0.0.1"}
        base = f"http://[::1]:{settings.web_port}"
        with mock.patch.dict(os.environ, proxy), \
                mock.patch.object(nano_deploy, "container_state", return_value={"running": True}):
            readiness = nano_deploy.wait_ready(settings)
            try:
                page = flow_check.Client(base, settings.origin, 3).call("web_index", "GET", "/", {200}, api=False)[0]
            except flow_check.FlowError as exc:
                page = str(exc)
            start = flow_check.presenter_start_page(base, 3)
        self.assertEqual((readiness["result"], readiness["url"], page, start),
                         ("PASSED", f"http://[::1]:{settings.web_port}{NANO['readiness']['path']}", 200, "INDEX"))

    def test_587_a_genuinely_failing_check_on_an_ipv6_gateway_still_rolls_back(self):
        """The new release's gateway on [::1] is not ready; the restored one is, at the same address."""
        self.settings = self.bound("::1")
        self.settings.readiness_timeout = 1
        fake = FakeDocker()
        url = f"http://[::1]:{NANO['network']['web_port']}{NANO['readiness']['path']}"

        def http_status(asked, timeout=5.0):
            running = fake.c.get("aware-care-demo-web", {}).get("image")
            return (200, {"readiness": "ready"}) if asked == url and running == "old" else (503, None)
        with mock.patch.object(nano_deploy, "http_status", http_status), \
                mock.patch.object(flow_check, "run", return_value={"result": "PASSED"}):
            code = self.deploy(fake)
        self.assertEqual((code, self.evidence["outcome"], fake.summary()), (1, "ROLLED_BACK", RESTORED))
        self.assertEqual(self.evidence["readiness"]["url"], url)
        self.assertEqual(self.evidence["rollback"]["readiness"]["result"], "PASSED")


class ModelLockDuringChecks(DeployFixture):
    """#578: the deploy's test consultation (the flow check calls the device model in local mode) takes the device's
    model lock (scripts/dev/with_model_lock.sh, #544), so it never runs beside another AI job. ./demo.sh local and setup
    and both deploy workflows run this same deploy tool."""

    def lock_free(self) -> bool:
        if not self.lock.exists():
            return True
        return subprocess.run(["flock", "-n", str(self.lock), "true"], timeout=10).returncode == 0

    def checked(self):
        seen = []

        def verify(*_args, **_kwargs):
            seen.append(self.lock_free())
            return PASSED
        return seen, mock.patch.object(nano_deploy, "verify", side_effect=verify)

    def test_local_mode_holds_the_model_lock_through_the_checks(self):
        seen, verify = self.checked()
        with verify:
            code = self.deploy(FakeDocker())
        self.assertEqual(code, 0, self.evidence.get("failure"))
        self.assertEqual(seen, [False], "the lock is held while the flow check runs")
        self.assertTrue(self.lock_free(), "and released after the deploy")
        self.assertTrue(any(self.lock.parent.glob("model.lock.holder.*")))

    def test_mock_mode_never_takes_it(self):
        nano_deploy.write_state(self.settings, "current", {**OLD, "mode": "mock"})
        seen, verify = self.checked()
        with verify:
            code = self.deploy(FakeDocker(), target={**NEW, "mode": "mock"})
        self.assertEqual(code, 0, self.evidence.get("failure"))
        self.assertEqual(seen, [True])
        self.assertFalse(self.lock.exists())

    def test_a_busy_model_fails_the_deploy_before_anything_changes(self):
        self.lock.touch()
        holder = subprocess.Popen(["flock", str(self.lock), "sleep", "30"])
        self.addCleanup(lambda: (holder.kill(), holder.wait()))
        for _ in range(100):
            if not self.lock_free():
                break
            threading.Event().wait(0.05)
        fake = FakeDocker()
        with mock.patch.dict(os.environ, {"AWARE_CARE_MODEL_LOCK_WAIT": "1"}), \
                mock.patch.object(nano_deploy, "verify", return_value=PASSED) as verify:
            code = self.deploy(fake)
        self.assertEqual(code, 1)
        verify.assert_not_called()
        self.assertEqual(fake.summary(), RESTORED)
        self.assertFalse(any(c.startswith(("stop", "rename", "run ")) for c in fake.calls), fake.calls)
        self.assertIn("another AI job kept the device model busy", self.evidence["failure"])
        self.assertIsNone(self.evidence["rollback"])


class ImageRevision(DeployFixture):
    """#297."""

    def test_an_image_built_from_another_commit_is_refused_before_anything_changes(self):
        fake = FakeDocker(revision="0" * 40)
        code = self.deploy(fake)
        self.assertEqual(code, 1)
        self.assertIn("revision label", self.evidence["failure"])
        self.assertEqual(self.evidence["images"]["api"]["revision_label"], "0" * 40)
        self.assertEqual(fake.summary(), RESTORED)
        self.assertFalse(any(call.startswith(("stop", "rename", "run")) for call in fake.calls))

    def test_an_image_without_the_label_is_refused(self):
        fake = FakeDocker(revision=None)
        self.assertEqual(self.deploy(fake), 1)
        self.assertIn("revision label None", self.evidence["failure"])

    def test_the_matching_label_deploys(self):
        with mock.patch.object(nano_deploy, "verify", return_value=PASSED):
            self.assertEqual(self.deploy(FakeDocker(revision="c2")), 0)


class RollbackTarget(DeployFixture):
    """#300: a rollback never makes the release it rolled back from the next rollback target."""

    def test_a_rollback_clears_the_target_instead_of_naming_the_bad_release(self):
        nano_deploy.write_state(self.settings, "current", NEW)     # v2 runs, v1 is the rollback target
        nano_deploy.write_state(self.settings, "previous", OLD)
        with mock.patch.object(nano_deploy, "verify", return_value=PASSED):
            code = self.deploy(FakeDocker(revision="c1"), target=OLD, action="rollback")
        self.assertEqual(code, 0)
        self.assertEqual(nano_deploy.read_state(self.settings, "current")["release_tag"], "v1")
        self.assertIsNone(nano_deploy.read_state(self.settings, "previous"))
        self.assertEqual(self.evidence["rolled_back_from"]["release_tag"], "v2")

    def test_redeploying_the_rollback_target_through_the_workflow_is_a_rollback_too(self):
        nano_deploy.write_state(self.settings, "current", NEW)
        nano_deploy.write_state(self.settings, "previous", OLD)
        with mock.patch.object(nano_deploy, "verify", return_value=PASSED):
            self.assertEqual(self.deploy(FakeDocker(revision="c1"), target=OLD), 0)
        self.assertIsNone(nano_deploy.read_state(self.settings, "previous"))

    def test_an_ordinary_deploy_still_records_what_ran_before(self):
        with mock.patch.object(nano_deploy, "verify", return_value=PASSED):
            self.assertEqual(self.deploy(FakeDocker()), 0)
        self.assertEqual(nano_deploy.read_state(self.settings, "previous")["release_tag"], "v1")

    def test_a_second_rollback_has_nothing_to_redeploy(self):
        config = self.root.parent / "nano.json"
        config.write_text(json.dumps(NANO))
        argv = ["nano_deploy.py", "--config", str(config), "--data-root", str(self.root), "rollback"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(nano_deploy, "deploy") as deploy, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(nano_deploy.main(), 1)
        deploy.assert_not_called()


class ZrtPreflight(unittest.TestCase):
    """#300: a malformed /models reply is a reported failure, not a traceback."""

    def setUp(self):
        args = argparse.Namespace(instance=None, data_root=tempfile.mkdtemp(), api_port=None, web_port=None,
                                  origin=None)
        self.settings = nano_deploy.Settings(NANO, args)

    def test_non_object_replies_fail_with_a_message(self):
        for body in (["m"], "m", None, {"data": "m"}, {"data": None}, {}):
            evidence: dict = {}
            with self.subTest(body=body), mock.patch.object(nano_deploy, "http_status", return_value=(200, body)):
                with self.assertRaisesRegex(nano_deploy.DeployError, "without a model list"):
                    nano_deploy.zrt_preflight(self.settings, "m", evidence)
                self.assertEqual(evidence["zrt"]["served_model_ids"], [])
                self.assertTrue(evidence["zrt"]["malformed_reply"])

    def test_a_listed_model_passes(self):
        evidence: dict = {}
        with mock.patch.object(nano_deploy, "http_status", return_value=(200, {"data": [{"id": "m"}, "junk"]})):
            nano_deploy.zrt_preflight(self.settings, "m", evidence)
        self.assertTrue(evidence["zrt"]["model_listed"])

    def test_the_same_model_under_zrts_default_name_and_another_revision_passes_with_a_note(self):
        """#528: a test machine serves the Nano's model as ZRT names it by default, pulled @main."""
        for served, revision in (("Qwen/Qwen3.6-35B-A3B-FP8@main", "main"), ("Qwen/Qwen3.6-35B-A3B-FP8", None),
                                 ("hf:qwen/qwen3.6-35b-a3b-fp8@main", "main")):
            evidence: dict = {}
            with self.subTest(served=served), contextlib.redirect_stdout(io.StringIO()) as out, \
                    mock.patch.object(nano_deploy, "http_status", return_value=(200, {"data": [{"id": served}]})):
                nano_deploy.zrt_preflight(self.settings, "qwen3.6-35b-a3b-fp8", evidence)
                self.assertTrue(evidence["zrt"]["model_listed"])
                self.assertEqual(evidence["zrt"]["served_as"], served)
                self.assertEqual(evidence["zrt"]["served_revision"], revision)
                if revision:
                    note = "serving revision main; this app was qualified on 95a723d…"
                    self.assertEqual(evidence["zrt"]["revision_note"], note)
                    self.assertIn(note, out.getvalue())

    def test_an_entirely_different_model_fails_and_names_what_is_served(self):
        evidence: dict = {}
        body = {"data": [{"id": "Qwen/Qwen3.8-27B-FP8@main"}]}
        with mock.patch.object(nano_deploy, "http_status", return_value=(200, body)):
            with self.assertRaisesRegex(nano_deploy.DeployError, "it serves: Qwen/Qwen3.8-27B-FP8@main"):
                nano_deploy.zrt_preflight(self.settings, "qwen3.6-35b-a3b-fp8", evidence)
        self.assertFalse(evidence["zrt"]["model_listed"])


def truncating_server() -> str:
    """One HTTP response that announces 1000 bytes and sends 14 (http.client.IncompleteRead)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\nContent-Type: text/html\r\n\r\n<div id=\"root\"")
        conn.close()
        srv.close()
    threading.Thread(target=serve, daemon=True).start()
    return f"http://127.0.0.1:{srv.getsockname()[1]}"


class ChecksNeverRaise(unittest.TestCase):
    """#294: flow_check.run and presenter_check report any error as FAILED."""

    def test_a_truncated_response_fails_the_flow_check(self):
        report = flow_check.run(truncating_server(), "http://x", "mock", 1, 2)
        self.assertEqual(report["result"], "FAILED")
        self.assertEqual(report["failure"], "web_index: IncompleteRead")

    def test_an_unexpected_error_fails_both_checks(self):
        with mock.patch.object(flow_check.Client, "call", side_effect=RuntimeError("bug")):
            flow = flow_check.run("http://127.0.0.1:9", "http://x", "mock", 1, 1)
            presenter = flow_check.presenter_check("http://127.0.0.1:9", "http://x", "http://127.0.0.1:9",
                                                   "http://y", "mock")
        self.assertEqual((flow["result"], flow["failure"]), ("FAILED", "unexpected error: RuntimeError"))
        self.assertEqual((presenter["result"], presenter["failure"]), ("FAILED", "unexpected error: RuntimeError"))

    def test_a_check_stops_at_its_time_budget(self):
        client = flow_check.Client("http://127.0.0.1:9", "http://x", 15, deadline=0.0)
        with self.assertRaisesRegex(flow_check.FlowError, "time budget"):
            client.call("web_index", "GET", "/", {200}, api=False)


class ZrtBaseUrlOverride(DeployFixture):
    """#535: on an HP Z8 ZRT served the model on its own service endpoint (127.0.0.1:9093), not on the proxy's 8080
    that the configuration names. demo.sh passes the address it uses as --zrt-base-url; the loopback rule stays."""

    def override(self, url: str | None) -> nano_deploy.Settings:
        args = argparse.Namespace(instance=None, data_root=str(self.root), api_port=None, web_port=None, origin=None,
                                  expected_arch="arm64", zrt_base_url=url)
        return nano_deploy.Settings(NANO, args)

    def test_the_override_replaces_the_config_and_reaches_the_api_and_the_evidence(self):
        self.settings = self.override("http://127.0.0.1:9093/v1/")
        self.assertEqual(self.settings.zrt_base_url, "http://127.0.0.1:9093/v1")
        fake = FakeDocker()
        self.assertEqual(self.deploy(fake, mock.patch.object(nano_deploy, "verify", return_value=PASSED)), 0)
        self.assertEqual(self.evidence["zrt_base_url"], "http://127.0.0.1:9093/v1")
        self.assertEqual(self.evidence["zrt_base_url_source"], "--zrt-base-url")
        api_run = next(c for c in fake.calls if c.startswith("run ") and "aware-care-demo-api " in c + " ")
        self.assertIn("AWARECARE_MODEL_BASE_URL=http://127.0.0.1:9093/v1", api_run)
        # The preflight asks the same address.
        evidence: dict = {}
        with mock.patch.object(nano_deploy, "http_status", return_value=(200, {"data": [{"id": "m"}]})) as status:
            nano_deploy.zrt_preflight(self.settings, "m", evidence)
        status.assert_called_once_with("http://127.0.0.1:9093/v1/models", timeout=10)
        self.assertEqual(evidence["zrt"]["base_url"], "http://127.0.0.1:9093/v1")

    def test_without_the_override_the_config_value_is_used_and_named(self):
        settings = self.override(None)
        self.assertEqual(settings.zrt_base_url, "http://127.0.0.1:8080/v1")
        self.assertEqual(settings.zrt_base_url_source, "config zrt.base_url")

    def test_the_override_keeps_the_loopback_rule(self):
        for bad in ("http://192.0.2.1:9093/v1", "https://127.0.0.1:9093/v1", "http://127.0.0.1/v1",
                    "http://127.0.0.1:9093@remote.example/v1", "http://127.0.0.1.evil.example:9093/v1",
                    "http://user:pw@127.0.0.1:9093/v1", "http://127.0.0.1:9093/v1?x=1"):
            with self.subTest(url=bad), self.assertRaisesRegex(nano_deploy.DeployError, "--zrt-base-url must be a loopback"):
                self.override(bad)

    def test_the_command_line_refuses_a_remote_override_before_anything_runs(self):
        run = subprocess.run([sys.executable, str(ROOT / "infra/deploy/nano_deploy.py"), "--data-root", str(self.root),
                              "--zrt-base-url", "http://192.0.2.1:9093/v1", "status"],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn("configuration error: --zrt-base-url must be a loopback ZRT endpoint", run.stderr)

    def test_status_names_the_address_the_running_api_uses(self):
        def fake(*args, check=True, capture=True, timeout=None):
            out = json.dumps(["PATH=/usr/bin", "AWARECARE_MODEL_BASE_URL=http://127.0.0.1:9093/v1"]) \
                if "{{json .Config.Env}}" in args else ""
            return subprocess.CompletedProcess(["docker", *args], 0 if out else 1, out, "")
        with mock.patch.object(nano_deploy, "docker", fake):
            self.assertEqual(nano_deploy.model_base_url("aware-care-demo-api"), "http://127.0.0.1:9093/v1")


if __name__ == "__main__":
    unittest.main()
