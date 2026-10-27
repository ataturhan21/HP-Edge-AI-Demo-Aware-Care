"""infra/telemetry/power_sampler.py (W06, ADR-017): parsing, hourly files, retention, and the end-to-end path into the
API's per-call energy measurement, with a stand-in nvidia-smi (no GPU needed)."""
from __future__ import annotations

import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra/telemetry"))
sys.path.insert(0, str(ROOT / "apps/api"))
import power_sampler  # noqa: E402
from app.runtime import metering  # noqa: E402  (standard library only)


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


if __name__ == "__main__":
    unittest.main()
