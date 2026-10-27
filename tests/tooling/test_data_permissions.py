"""#152: the data root and the API's data folders are private to the deploying user (0700), even when they already
existed with a permissive mode, and the power sampler creates only private folders and files whatever the umask.

On the ZGX Fury (umask 002) the sampler's cron line created data/local/power before the first local deployment, so
data/local stayed 775 and the SQLite files were readable by other local users (QA 2026-10-18)."""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra/deploy"))
import nano_deploy  # noqa: E402

FURY = json.loads((ROOT / "infra/deploy/demo-zgx-fury.json").read_text())


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class DataPermissionsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "aware-care-demo"
        args = argparse.Namespace(instance=None, data_root=str(self.root), api_port=None, web_port=None, origin=None)
        self.settings = nano_deploy.Settings(FURY, args)
        self.old_umask = os.umask(0o002)  # the Fury's umask

    def tearDown(self):
        os.umask(self.old_umask)

    def test_a_deployment_makes_existing_permissive_folders_private(self):
        power = self.root / "data" / "local" / "power"
        power.mkdir(parents=True)  # as the sampler's first run did on the Fury
        for p in (self.root, self.root / "data", self.root / "data" / "local"):
            os.chmod(p, 0o775)
        with mock.patch.object(nano_deploy, "docker"):
            nano_deploy.start_containers(self.settings, {"mode": "local", "release_tag": "v0.0.0-test", "app_commit": "abc",
                                                         "model_id": "m", "api_image": "api@x", "web_image": "web@y"})
        for p in (self.root, self.root / "data", self.root / "data" / "local"):
            self.assertEqual(mode(p), 0o700, p)

    def test_new_folders_are_private_and_the_presenter_key_path_too(self):
        nano_deploy.harden_data_root(self.settings, "mock")
        for p in (self.root, self.root / "data", self.root / "data" / "mock"):
            self.assertEqual(mode(p), 0o700, p)
        self.assertEqual(nano_deploy.create_presenter_key(self.settings, rotate=False), 0)
        self.assertEqual(mode(self.root / "secrets"), 0o700)
        self.assertEqual(mode(self.root / "secrets" / "presenter.key"), 0o600)

    def test_the_deploy_lock_is_a_context_manager_on_a_private_root(self):
        """The deploy path's lock (serializes deployments) still works and leaves the root private."""
        os.makedirs(self.root, exist_ok=True)
        os.chmod(self.root, 0o755)
        with nano_deploy.deploy_lock(self.root):
            self.assertTrue((self.root / "deploy.lock").exists())
        self.assertEqual(mode(self.root), 0o700)
        self.assertIsInstance(nano_deploy.private_dir(self.root / "x"), Path)

    def test_the_power_sampler_creates_only_private_folders_and_files(self):
        out = self.root / "data" / "local" / "power"
        fake = self.root.parent / "fake-nvidia-smi"
        fake.write_text("#!/bin/sh\necho 41.5\necho 42.0\n")
        fake.chmod(0o755)
        code = subprocess.run([sys.executable, str(ROOT / "infra/telemetry/power_sampler.py"), "--out", str(out),
                               "--nvidia-smi", str(fake)], capture_output=True, text=True, check=False).returncode
        self.assertEqual(code, 0)
        for p in (self.root, self.root / "data", self.root / "data" / "local", out):
            self.assertEqual(mode(p), 0o700, p)
        files = list(out.glob("*.csv"))
        self.assertTrue(files)
        for f in files:
            self.assertEqual(mode(f), 0o600, f)


if __name__ == "__main__":
    unittest.main()
