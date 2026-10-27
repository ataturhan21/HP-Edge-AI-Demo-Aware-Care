"""The device specs' wiring (#367): tests/devices runs only through apps/web/playwright.devices.config.ts (a tunnelled
device on 127.0.0.1:18180, #487: one address for both roles; DEVICE selects it) and never in the mock suite. Nothing here contacts a device."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DeviceSpecs(unittest.TestCase):
    def test_the_mock_suite_never_picks_up_the_device_specs(self):
        mock = (ROOT / "apps/web/playwright.config.ts").read_text()
        self.assertIn('testDir: "../../tests/ui"', mock)
        for spec in (ROOT / "tests/ui").rglob("*.ts"):
            self.assertNotIn("tests/devices", spec.read_text(), spec)
            self.assertNotIn("../devices/", spec.read_text(), spec)

    def test_the_device_config(self):
        cfg = (ROOT / "apps/web/playwright.devices.config.ts").read_text()
        self.assertIn('testDir: "../../tests/devices"', cfg)
        self.assertIn('baseURL: "http://127.0.0.1:18180"', cfg)
        self.assertIn("width: 1440, height: 900", cfg)
        self.assertIn("width: 360, height: 780", cfg)
        self.assertNotIn("webServer", cfg)
        # #487: one address for patients and presenters; the former presenter port is gone.
        support = (ROOT / "tests/devices/support/device.ts").read_text()
        self.assertIn('export const BASE = "http://127.0.0.1:18180";', support)
        self.assertNotIn("18181", support)
        scripts = json.loads((ROOT / "apps/web/package.json").read_text())["scripts"]
        self.assertIn("-c playwright.devices.config.ts", scripts["test:device"])
        self.assertEqual(sorted(p.name for p in (ROOT / "tests/devices").glob("*.spec.ts")),
                         ["measures.spec.ts", "quick-flows.spec.ts", "smoke.spec.ts", "usability-walk.spec.ts", "walkthrough.spec.ts"])

    def test_the_device_specs_fail_on_off_device_requests(self):
        for spec in ("walkthrough.spec.ts", "quick-flows.spec.ts", "smoke.spec.ts"):
            self.assertIn("expect(off).toEqual([])", (ROOT / "tests/devices" / spec).read_text())

    def test_the_release_smoke_runs_every_presenter_quick_flow_and_fails_on_any(self):
        """#538: the smoke ran only the first Quick flow, so the Self-care flow failed on the Nano through three
        releases. It must run each of O03's Quick flows and require each to show its result."""
        o03 = (ROOT / "apps/web/src/screens/O03.tsx").read_text()
        flows = re.search(r"const FLOWS: Flow\[\] = \[(.*?)\n\];", o03, re.S).group(1)
        titles = re.findall(r'\{ id: "[a-z]+", title: "([^"]+)"', flows)
        self.assertEqual(titles, ["Guidance from the local AI", "Self-care guidance", "Urgent warning sign"])
        smoke = (ROOT / "tests/devices/smoke.spec.ts").read_text()
        listed = re.search(r"const QUICK_FLOWS: \[string, RegExp, string\]\[\] = \[(.*?)\n\];", smoke, re.S).group(1)
        self.assertEqual(re.findall(r'\["([^"]+)", /', listed), titles)
        self.assertIn("for (const [title, path, heading] of QUICK_FLOWS)", smoke)
        self.assertIn("name: `Run on HP ZGX ${DEV}: ${title}`", smoke)
        self.assertIn('QUICK_FLOWS.map(([t]) => [t, "shown"])', smoke)  # every flow must be shown
        self.assertNotIn("Guidance from the local AI` }).click()", smoke)  # no single hard-wired flow

    def test_the_walkthrough_expects_the_a12_sections_of_417(self):
        """#493: since #417 the A12 preview shows every PDF section (9 without a doctor search); the walkthrough expected
        the 5 cards of before and failed on both devices at v0.15.0-demo.1."""
        walk = (ROOT / "tests/devices/walkthrough.spec.ts").read_text()
        self.assertNotRegex(walk, r'card-title"\)\)\.toHaveCount\(')
        self.assertIn("await expect(titles).toHaveText(SUMMARY_SECTIONS);", walk)
        self.assertIn("expect(pdfHeadings(pdf)).toEqual(", walk)
        support = (ROOT / "tests/devices/support/device.ts").read_text()
        listed = re.search(r"export const SUMMARY_SECTIONS = \[(.*?)\];", support, re.S)
        self.assertIsNotNone(listed)
        device = re.findall(r'"([^"]+)"', listed.group(1))
        # The spec's list (spec/screens.json, A12 validation rule #417), without the doctor search this walk never does;
        # outside mock mode the next steps are plural.
        a12 = next(s for s in json.loads((ROOT / "spec/screens.json").read_text())["screens"] if s["id"] == "A12")
        rule = next(r for r in a12["validation_rules"] if r.startswith("#417:"))
        items = re.search(r"with the same items: (.*?)\.", rule).group(1).replace(" and ", ", ").split(", ")
        spec = [i.replace("suggested next step(s)", "suggested next steps") for i in items if i != "doctors you found"]
        self.assertEqual([t.lower() for t in device], spec)
        self.assertEqual(len(device), 9)


if __name__ == "__main__":
    unittest.main()
