"""#170 recovery exercise: what the drills found and what now guards it.

- Redeploying the release that already runs kept no rollback target: `state/previous.json` became the same deployment.
- State files followed the umask (664 on the Fury).
- The Nano's model had no boot unit: ZRT has no autostart, so a reboot left local mode failing. Its unit must serve
  exactly the manifest's qualified command.
- After a reboot nothing recorded whether the demo came back: `boot_check.py` does, content-free and private.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra/deploy"))
import boot_check  # noqa: E402
import nano_deploy  # noqa: E402

NANO = json.loads((ROOT / "infra/deploy/demo-zgx-nano.json").read_text())


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def record(tag: str, api: str = "api@sha256:a", web: str = "web@sha256:b") -> dict:
    return {"release_tag": tag, "app_commit": "c", "mode": "local", "model_id": "m", "api_image": api,
            "web_image": web, "deployed_at": "2026-10-18T00:00:00+00:00", "instance": "aware-care-demo"}


class StateTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "aware-care-demo"
        args = argparse.Namespace(instance=None, data_root=str(self.root), api_port=None, web_port=None, origin=None)
        self.settings = nano_deploy.Settings(NANO, args)
        self.old_umask = os.umask(0o002)  # the Fury's umask

    def tearDown(self):
        os.umask(self.old_umask)

    def test_state_files_are_private_whatever_the_umask(self):
        nano_deploy.write_state(self.settings, "current", record("v1"))
        self.assertEqual(mode(self.settings.state_dir), 0o700)
        self.assertEqual(mode(self.settings.state_dir / "current.json"), 0o600)
        self.assertEqual(nano_deploy.read_state(self.settings, "current")["release_tag"], "v1")

    def test_only_a_different_deployment_replaces_the_rollback_target(self):
        self.assertTrue(nano_deploy.same_deployment(record("v0.8.0"), {**record("v0.8.0"), "deployed_at": "later"}))
        self.assertFalse(nano_deploy.same_deployment(record("v0.7.1"), record("v0.8.0")))
        self.assertFalse(nano_deploy.same_deployment(record("v0.8.0"), record("v0.8.0", api="api@sha256:z")))
        self.assertFalse(nano_deploy.same_deployment({**record("v0.8.0"), "mode": "mock"}, record("v0.8.0")))
        self.assertFalse(nano_deploy.same_deployment(None, record("v0.8.0")))

    def test_a_same_release_redeploy_keeps_the_previous_release_as_the_rollback_target(self):
        nano_deploy.write_state(self.settings, "current", record("v0.8.0"))
        nano_deploy.write_state(self.settings, "previous", record("v0.7.1"))
        target = record("v0.8.0")
        with mock.patch.multiple(nano_deploy, docker=mock.DEFAULT, park_current=mock.DEFAULT,
                                 start_containers=mock.DEFAULT, remove_container=mock.DEFAULT,
                                 zrt_preflight=mock.DEFAULT, port_in_use=mock.DEFAULT, container_state=mock.DEFAULT,
                                 install_power_sampler=mock.DEFAULT, install_boot_check=mock.DEFAULT,
                                 inspect_image=mock.DEFAULT, verify=mock.DEFAULT) as m:
            m["port_in_use"].return_value = False
            m["container_state"].return_value = None
            m["inspect_image"].return_value = {"architecture": self.settings.expected_arch, "revision_label": "c"}
            m["verify"].return_value = (True, {"result": "PASSED"}, {"result": "PASSED"})
            m["install_power_sampler"].return_value = {"installed": "x"}
            m["install_boot_check"].return_value = {"installed": "y"}
            m["park_current"].return_value = True
            with mock.patch.object(nano_deploy.platform, "machine", return_value=self.settings.expected_arch), \
                    mock.patch.object(nano_deploy.shutil, "which", return_value="/usr/bin/docker"):
                code = nano_deploy.deploy(self.settings, target, pull=False, require_digest=True,
                                          guidance_timeout=1, evidence_out=None)
        self.assertEqual(code, 0)
        self.assertEqual(nano_deploy.read_state(self.settings, "previous")["release_tag"], "v0.7.1")
        self.assertEqual(nano_deploy.read_state(self.settings, "current")["release_tag"], "v0.8.0")

    def test_the_deploy_copies_the_boot_check_and_reports_its_reboot_line(self):
        crontab = mock.Mock(stdout="* * * * * power_sampler.py\n@reboot /usr/bin/python3 ~/x/ops/boot_check.py\n")
        with mock.patch.object(nano_deploy.subprocess, "run", return_value=crontab):
            result = nano_deploy.install_boot_check(self.settings)
        self.assertTrue(result["cron_at_reboot"])
        copied = self.root / "ops" / "boot_check.py"
        self.assertEqual(copied.read_text(), (ROOT / "infra/deploy/boot_check.py").read_text())
        self.assertEqual(mode(copied.parent), 0o700)
        with mock.patch.object(nano_deploy.subprocess, "run", return_value=mock.Mock(stdout="")):
            self.assertFalse(nano_deploy.install_boot_check(self.settings)["cron_at_reboot"])


class BootCheckTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "aware-care-demo"
        (self.root / "state").mkdir(parents=True)
        (self.root / "state" / "current.json").write_text(json.dumps(record("v0.8.0-demo.1")))

    def test_it_records_when_each_piece_came_back_privately(self):
        calls = {"n": 0}

        def model_after_two_polls() -> bool:
            calls["n"] += 1
            return calls["n"] >= 3

        probes = {"model_listed": model_after_two_polls, "app_ready": lambda: True}
        out = boot_check.run(self.root, probes, booted=time.time() - 30, timeout=600, interval=0,
                             extra=lambda: {"non_loopback_listeners": [], "clock_synchronised": "no"})
        self.assertEqual(out["result"], "PASSED")
        self.assertEqual(out["missing"], [])
        self.assertGreaterEqual(out["seconds_after_boot"]["model_listed"], 30)
        self.assertEqual(out["deployment"]["release_tag"], "v0.8.0-demo.1")
        path = Path(out["path"])
        self.assertEqual(mode(path), 0o600)
        self.assertEqual(mode(path.parent), 0o700)
        saved = json.loads(path.read_text())
        self.assertEqual(saved["schema"], "aware-care-boot-check/1")
        self.assertNotIn("concern", json.dumps(saved))

    def test_a_piece_that_never_comes_back_fails_the_record(self):
        out = boot_check.run(self.root, {"model_listed": lambda: False, "app_ready": lambda: True},
                             booted=time.time() - 10, timeout=10, interval=0)
        self.assertEqual(out["result"], "FAILED")
        self.assertEqual(out["missing"], ["model_listed"])

    def test_the_boot_check_finds_the_model_under_zrts_names(self):
        """#528: ZRT lists the model by our label or, without one, by its repository id with any revision."""
        for name in ("qwen3.6-35b-a3b-fp8", "Qwen/Qwen3.6-35B-A3B-FP8", "Qwen/Qwen3.6-35B-A3B-FP8@main",
                     "hf:qwen/qwen3.6-35b-a3b-fp8@95a723d"):
            self.assertTrue(boot_check.same_model(name, "qwen3.6-35b-a3b-fp8"), name)
        for name in ("Qwen/Qwen3.6-35B-A3B", "Qwen/Qwen3.8-27B-FP8@main", "qwen3.8-flash-next-fp8", ""):
            self.assertFalse(boot_check.same_model(name, "qwen3.6-35b-a3b-fp8"), name)
        self.assertFalse(boot_check.same_model("m", None))

    def test_mock_deployments_do_not_wait_for_a_model(self):
        probes = boot_check.default_probes({**record("v1"), "mode": "mock"}, "http://127.0.0.1:1/v1",
                                           "http://127.0.0.1:1/r")
        self.assertNotIn("model_listed", probes)
        self.assertIn("model_listed", boot_check.default_probes(record("v1"), "http://127.0.0.1:1/v1",
                                                                "http://127.0.0.1:1/r"))


class NanoBootUnitTest(unittest.TestCase):
    def test_the_nano_unit_serves_exactly_the_manifests_qualified_command(self):
        manifest = json.loads((ROOT / "infra/model-manifest.json").read_text())
        script = (ROOT / "infra/nano/zrt/serve-model.sh").read_text()
        model = manifest["model"]
        uri = f"hf:{model['repository_id']}@{model['revision']}"
        self.assertIn(f"MODEL={uri}", script)
        self.assertIn(f"LABEL={model['served_model_id']}", script)
        # #549: `"${ZRT[@]}"` is `zrt`, plus `-m <mode>` only when model.env names a mode other than ZRT's default
        exec_line = next(line for line in script.splitlines() if line.startswith('exec "${ZRT[@]}" service start'))
        exec_line = exec_line.replace('"${ZRT[@]}"', "zrt")
        served = shlex.split(exec_line.replace('"$MODEL"', uri).replace('"$LABEL"', model["served_model_id"]))[1:]
        self.assertEqual(served, shlex.split(manifest["serving"]["command"]))
        unit = (ROOT / "infra/nano/zrt/aware-care-zrt-model.service").read_text()
        self.assertIn("ExecStart=%h/.local/share/aware-care-demo/zrt/serve-model.sh", unit)
        # #528: the unit reads the served revision from model.env, and stops whichever revision the script serves.
        self.assertIn("EnvironmentFile=-%h/.config/aware-care-demo/model.env", unit)
        self.assertIn("ExecStop=%h/.local/share/aware-care-demo/zrt/serve-model.sh stop", unit)
        self.assertIn('if [ "${1:-}" = stop ]; then exec "${ZRT[@]}" service stop "$MODEL"; fi', script)
        self.assertIn('ZRT=(zrt)\n[ -z "${AWARECARE_ZRT_MODE:-}" ] || ZRT+=(-m "$AWARECARE_ZRT_MODE")', script)
        self.assertIn("WantedBy=default.target", unit)
        self.assertIn("already served", script)  # enabling it never restarts a running model
        # #175: vLLM's usage statistics stay off, as on the Fury.
        self.assertIn("export VLLM_NO_USAGE_STATS=1 VLLM_DO_NOT_TRACK=1 DO_NOT_TRACK=1 HF_HUB_OFFLINE=1", script)
        self.assertTrue(manifest["serving"]["environment"]["VLLM_NO_USAGE_STATS"].startswith("1"))


if __name__ == "__main__":
    unittest.main()
