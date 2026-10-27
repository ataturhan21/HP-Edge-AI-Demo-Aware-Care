"""scripts/check_contrast.py: the web design tokens meet WCAG 2.2 AA (#98)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import check_contrast  # noqa: E402


class ContrastTest(unittest.TestCase):
    def test_every_design_pair_meets_its_minimum(self):
        rows = check_contrast.check(check_contrast.CSS.read_text())
        failed = [f"{r['fg']} on {r['bg']}: {r['ratio']} < {r['minimum']}" for r in rows if not r["passed"]]
        self.assertEqual(failed, [])

    def test_the_checked_literals_are_the_ones_the_stylesheet_uses(self):
        css = check_contrast.CSS.read_text().lower()
        for fg, bg, _, _ in check_contrast.PAIRS:
            for colour in (fg, bg):
                if colour.startswith("#") and colour != "#ffffff":
                    self.assertIn(colour, css, f"{colour} is checked but not used in styles.css")

    def test_the_ratio_matches_known_values(self):
        self.assertAlmostEqual(check_contrast.ratio("#000000", "#ffffff"), 21.0, places=2)
        self.assertAlmostEqual(check_contrast.ratio("#777777", "#ffffff"), 4.48, places=2)

    def test_a_low_contrast_token_fails(self):
        css = check_contrast.CSS.read_text().replace("--muted: #4a6372;", "--muted: #b0bec5;")
        self.assertTrue(any(not r["passed"] for r in check_contrast.check(css) if r["fg"] == "muted"))


if __name__ == "__main__":
    unittest.main()
