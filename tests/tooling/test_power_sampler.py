"""infra/telemetry/power_sampler.py (W06, ADR-017): parsing, hourly files, retention, and the end-to-end path into the
API's per-call energy measurement, with a stand-in nvidia-smi (no GPU needed). #678: the deploy tool keeps it running
with one user crontab line per data root (a stand-in crontab keeps it in a file; the real crontab is never touched)."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra/telemetry"))
sys.path.insert(0, str(ROOT / "apps/api"))
import power_sampler  # noqa: E402
from app.runtime import metering  # noqa: E402  (standard library only)

sys.path.insert(0, str(ROOT / "infra/deploy"))
import nano_deploy  # noqa: E402

NANO = json.loads((ROOT / "infra/deploy/demo-zgx-nano.json").read_text())
# `crontab -l` prints $FAKE_CRONTAB_FILE ("no crontab" without it), `crontab -` writes it; FAKE_CRONTAB_DENY refuses.
FAKE_CRONTAB = """#!/bin/sh
[ -n "${FAKE_CRONTAB_DENY:-}" ] && { echo "You (alice) are not allowed to use this program (crontab)" >&2; exit 1; }
case "$1" in
  -l) [ -f "$FAKE_CRONTAB_FILE" ] || { echo "no crontab for alice" >&2; exit 1; }; cat "$FAKE_CRONTAB_FILE" ;;
  -) cat > "$FAKE_CRONTAB_FILE" ;;
  *) exit 2 ;;
esac
"""


class PowerSamplerTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_parses_watts_and_rejects_unavailable_readings(self):
        self.assertEqual(power_sampler.parse_watts("12.15\n"), 12.15)
        self.assertIsNone(power_sampler.parse_watts("[N/A]"))
        self.assertIsNone(power_sampler.parse_watts(""))
        self.assertIsNone(power_sampler.parse_watts("-3"))

    def test_hourly_files_and_48_hour_retention(self):
        now = time.time()
        power_sampler.append(self.dir, now, 20.0)
        power_sampler.append(self.dir, now - 50 * 3600, 20.0)
        self.assertEqual(len(list(self.dir.glob("*.csv"))), 2)
        power_sampler.prune(self.dir, now)
        self.assertEqual([p.name for p in self.dir.glob("*.csv")], [power_sampler.hour_file(self.dir, now).name])

    def test_a_stand_in_nvidia_smi_feeds_the_api_energy_measurement(self):
        fake = self.dir / "nvidia-smi"
        fake.write_text("#!/bin/sh\nfor w in 30 30 30 \"[N/A]\" 30 30; do echo \"$w\"; sleep 0.2; done\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        out = self.dir / "power"
        start = time.time()
        self.assertEqual(power_sampler.main(["--out", str(out), "--nvidia-smi", str(fake)]), 0)
        end = time.time()
        samples = metering.read_power(out, start, end)
        self.assertEqual(len(samples), 5)  # the [N/A] reading is skipped
        energy = metering.energy_wh(samples, start, end)
        self.assertIsNotNone(energy)
        self.assertAlmostEqual(energy, 30 * (end - start) / 3600, places=4)

    def test_no_samples_means_not_measured(self):
        self.assertIsNone(metering.energy_wh([], 0, 10))
        gap = [(0.0, 10.0), (5.0, 10.0), (10.0, 10.0)]  # 5 s apart: not a measurement
        self.assertIsNone(metering.energy_wh(gap, 0, 10))


class PowerSamplerKeeperTest(unittest.TestCase):
    """#678 (owner decision, 28 Oct 2026): setup, local and every local-mode deployment keep the sampler running."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "home/.local/share/aware-care-demo"
        args = argparse.Namespace(instance=None, data_root=str(self.root), api_port=None, web_port=None, origin=None)
        self.settings = nano_deploy.Settings(NANO, args)
        self.root = self.settings.root
        fake = self.tmp / "crontab"
        fake.write_text(FAKE_CRONTAB)
        fake.chmod(0o755)
        self.crontab = self.tmp / "crontab.txt"
        env = mock.patch.dict(os.environ, {"FAKE_CRONTAB_FILE": str(self.crontab)})
        env.start()
        self.addCleanup(env.stop)
        program = mock.patch.object(nano_deploy, "CRONTAB", str(fake))
        program.start()
        self.addCleanup(program.stop)
        # never a real sampler process in a test
        started = mock.patch.object(nano_deploy, "start_power_sampler", return_value=True)
        self.start = started.start()
        self.addCleanup(started.stop)
        self.line = (f"* * * * * /usr/bin/flock -n {self.root}/telemetry/sampler.lock /usr/bin/python3 "
                     f"{self.root}/telemetry/power_sampler.py --out {self.root}/data/local/power >> "
                     f"{self.root}/telemetry/sampler.log 2>&1")
        self.comment = (f"# Aware Care (#678): the GPU power sampler for the telemetry page of {self.root}; "
                        "./demo.sh uninstall removes it")

    def lines(self) -> list[str]:
        return self.crontab.read_text().splitlines() if self.crontab.exists() else []

    def test_the_line_is_the_runbooks_line(self):
        self.assertEqual(nano_deploy.sampler_cron_line(self.root), self.line)
        runbook = (ROOT / "spec/engineering/08-delivery-and-nano-runbook.md").read_text()
        self.assertIn(self.line.replace(str(self.root), "$DR"), runbook)

    def test_it_adds_the_line_once_keeps_every_other_line_and_a_rerun_changes_nothing(self):
        self.crontab.write_text("17 3 * * 1 /usr/bin/python3 /x/monitoring.py collect\n")
        result = nano_deploy.install_power_sampler(self.settings, keep=True, start=True)
        self.assertEqual((result["cron_keeper"], result["added"], result["line"]), (True, True, self.line))
        self.assertEqual(self.lines(), ["17 3 * * 1 /usr/bin/python3 /x/monitoring.py collect", self.comment, self.line])
        self.assertTrue((self.root / "telemetry/power_sampler.py").is_file())
        self.start.assert_called_once_with(self.root)  # no reading yet: one starts now
        before = self.crontab.read_text()
        again = nano_deploy.install_power_sampler(self.settings, keep=True, start=True)
        self.assertEqual((again["cron_keeper"], again["added"]), (True, False))
        self.assertEqual(self.crontab.read_text(), before)
        # with a reading in the last seconds nothing is started
        self.start.reset_mock()
        power = self.root / "data/local/power"
        power.mkdir(parents=True)
        (power / "20261028T18.csv").write_text("1,500.0\n")
        nano_deploy.install_power_sampler(self.settings, keep=True, start=True)
        self.start.assert_not_called()

    def test_the_maintainers_existing_line_is_recognised_and_another_roots_line_is_not(self):
        fury = ("# GPU power sampler for the telemetry page (W06, ADR-017): one nvidia-smi power reading per second.\n"
                f"{self.line}\n")
        self.crontab.write_text(fury)
        self.assertFalse(nano_deploy.keep_power_sampler(self.root)["added"])
        self.assertEqual(self.crontab.read_text(), fury)
        other = nano_deploy.sampler_cron_line(Path(f"{self.root}-2"))
        commented = f"# {self.line}"
        self.crontab.write_text(f"{other}\n{commented}\n")
        self.assertTrue(nano_deploy.keep_power_sampler(self.root)["added"])
        self.assertEqual(self.lines(), [other, commented, self.comment, self.line])

    def test_remove_drops_only_this_roots_line_and_its_comment_and_stops_the_sampler(self):
        keep = ["17 3 * * 1 /usr/bin/python3 /x/monitoring.py collect", nano_deploy.sampler_cron_line(Path("/other"))]
        self.crontab.write_text("\n".join([keep[0], self.comment, self.line, keep[1]]) + "\n")
        with mock.patch.object(nano_deploy, "stop_power_sampler", return_value=1) as stop:
            result = nano_deploy.drop_power_sampler(self.root)
        self.assertEqual(result, {"removed_lines": 1, "stopped": 1})
        stop.assert_called_once_with(self.root)
        self.assertEqual(self.lines(), keep)

    def test_a_crontab_that_cannot_be_used_is_reported_never_raised(self):
        with mock.patch.dict(os.environ, {"FAKE_CRONTAB_DENY": "1"}):
            result = nano_deploy.install_power_sampler(self.settings, keep=True, start=True)
            state = nano_deploy.sampler_state(self.root)
        self.assertFalse(result["cron_keeper"])
        self.assertIn("not allowed", result["error"])
        self.start.assert_not_called()
        self.assertIsNone(state["cron_keeper"])
        with mock.patch.object(nano_deploy, "CRONTAB", str(self.tmp / "missing-crontab")):
            self.assertFalse(nano_deploy.install_power_sampler(self.settings, keep=True)["cron_keeper"])

    def test_without_keep_it_only_reads(self):
        self.crontab.write_text("")
        result = nano_deploy.install_power_sampler(self.settings)
        self.assertFalse(result["cron_keeper"])
        self.assertEqual(self.crontab.read_text(), "")

    def test_a_local_deployment_keeps_it_a_mock_one_does_not(self):
        recorded = {}
        target = {"release_tag": "v1", "app_commit": "c", "mode": "local", "model_id": "m",
                  "api_image": "api@sha256:a", "web_image": "web@sha256:b"}
        for mode in ("local", "mock"):
            with self.subTest(mode=mode), contextlib.ExitStack() as stack:
                for name in ("docker", "park_current", "start_containers", "remove_container", "zrt_preflight",
                             "install_boot_check"):
                    stack.enter_context(mock.patch.object(nano_deploy, name))
                stack.enter_context(mock.patch.object(nano_deploy, "port_in_use", return_value=False))
                stack.enter_context(mock.patch.object(nano_deploy, "container_state", return_value=None))
                stack.enter_context(mock.patch.object(nano_deploy, "inspect_image", return_value={
                    "architecture": self.settings.expected_arch, "revision_label": "c"}))
                stack.enter_context(mock.patch.object(nano_deploy, "verify", return_value=(
                    True, {"result": "PASSED"}, {"result": "PASSED"})))
                stack.enter_context(mock.patch.object(nano_deploy, "write_evidence",
                                                      lambda _s, evidence, _o: recorded.update(evidence)))
                stack.enter_context(mock.patch.object(nano_deploy, "model_lock"))
                stack.enter_context(mock.patch.object(nano_deploy.platform, "machine",
                                                      return_value=self.settings.expected_arch))
                stack.enter_context(mock.patch.object(nano_deploy.shutil, "which", return_value="/usr/bin/docker"))
                self.crontab.unlink(missing_ok=True)
                code = nano_deploy.deploy(self.settings, {**target, "mode": mode}, pull=False, require_digest=True,
                                          guidance_timeout=1, evidence_out=None)
                self.assertEqual(code, 0)
                self.assertEqual(recorded["power_sampler"]["cron_keeper"], mode == "local")
                self.assertEqual(self.lines(), [self.comment, self.line] if mode == "local" else [])
                self.start.assert_not_called()  # the workflow's job ends; cron starts it within a minute

    def test_the_command_line_power_sampler_check_dry_run_and_status(self):
        def cli(*args: str) -> tuple[int, dict]:
            out = io.StringIO()
            argv = ["nano_deploy.py", "--data-root", str(self.root), *args]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
                code = nano_deploy.main()
            return code, json.loads(out.getvalue())

        code, dry = cli("power-sampler", "--dry-run")
        self.assertEqual((code, dry["would"], dry["line"], dry["cron_keeper"]), (0, "add", self.line, False))
        self.assertFalse(self.crontab.exists(), "a dry run writes nothing")
        code, done = cli("power-sampler")
        self.assertEqual((code, done["added"]), (0, True))
        self.assertEqual(cli("power-sampler", "--dry-run")[1]["would"], "nothing")
        self.assertEqual(cli("power-sampler", "--remove", "--dry-run")[1]["would"], "remove")
        self.assertTrue(cli("power-sampler", "--check")[1]["cron_keeper"])
        with mock.patch.object(nano_deploy, "stop_power_sampler", return_value=0):
            code, removed = cli("power-sampler", "--remove")
        self.assertEqual((code, removed["removed_lines"]), (0, 1))
        self.assertEqual(self.lines(), [])
        with mock.patch.object(nano_deploy, "container_state", return_value=None), \
                mock.patch.object(nano_deploy, "presenter_status", return_value=None), \
                mock.patch.object(nano_deploy, "model_base_url", return_value=None), \
                mock.patch.object(nano_deploy, "http_status", return_value=(None, None)):
            code, status = cli("status")
        self.assertEqual(status["power_sampler"]["cron_keeper"], False)
        self.assertIsNone(status["power_sampler"]["last_reading_age_s"])

    def test_stop_ends_only_this_roots_sampler(self):
        script = self.root / "telemetry/power_sampler.py"
        script.parent.mkdir(parents=True)
        script.write_text("import time\ntime.sleep(60)\n")
        other = self.tmp / "other/telemetry/power_sampler.py"
        other.parent.mkdir(parents=True)
        other.write_text("import time\ntime.sleep(60)\n")
        mine = subprocess.Popen([sys.executable, str(script), "--out", "x"])
        theirs = subprocess.Popen([sys.executable, str(other), "--out", "x"])
        for proc in (theirs, mine):
            self.addCleanup(proc.wait, 10)
            self.addCleanup(proc.kill)
        time.sleep(0.3)
        self.assertEqual(nano_deploy.stop_power_sampler(self.root), 1)
        self.assertEqual(mine.wait(timeout=10), -15)
        self.assertIsNone(theirs.poll())


if __name__ == "__main__":
    unittest.main()
