#!/usr/bin/env python3
"""WCAG 2.2 AA contrast check for the web design tokens (#98).

Reads the :root tokens from apps/web/src/styles.css and checks every foreground/background pairing the design uses:
4.5:1 for text (1.4.3), and 3:1 for UI boundaries, focus indicators and large text (1.4.11). Exits non-zero on any
failure. Usage: python3 scripts/check_contrast.py [--json]
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "apps/web/src/styles.css"
TEXT, UI = 4.5, 3.0
LARGE = 3.0  # WCAG 1.4.3 large text: 18.66 px bold or 24 px regular (#245 selected scale numerals)

# (foreground, background, minimum, where it is used). Names are tokens; "#rrggbb" literals are used as written.
PAIRS: list[tuple[str, str, float, str]] = [
    ("ink", "canvas", TEXT, "body text on the page"),
    ("ink", "surface", TEXT, "text in cards"),
    ("ink", "sunken", TEXT, "text on sunken areas"),
    ("muted", "canvas", TEXT, "secondary text on the page"),
    ("muted", "surface", TEXT, "secondary text in cards, signature detail"),
    ("muted", "sunken", TEXT, "secondary text on sunken areas"),
    ("brand-ink", "surface", TEXT, "links, eyebrows, active nav"),
    ("brand-ink", "canvas", TEXT, "links and eyebrows on the page"),
    ("brand-ink", "brand-tint", TEXT, "active nav item, level badge, badges"),
    ("#ffffff", "brand", TEXT, "primary button"),
    ("#ffffff", "brand-hover", TEXT, "primary button hover"),
    ("brand", "surface", UI, "focus ring, selected choice border, progress"),
    ("brand", "canvas", UI, "focus ring on the page"),
    ("brand", "brand-tint", UI, "selected choice border on its tint"),
    ("info", "info-tint", TEXT, "information banner title"),
    ("ink", "info-tint", TEXT, "information banner text"),
    ("warn", "warn-tint", TEXT, "attention banner title, amber badge"),
    ("ink", "warn-tint", TEXT, "attention banner text"),
    ("urgent", "urgent-tint", TEXT, "urgent and error banner title, red badge"),
    ("ink", "urgent-tint", TEXT, "urgent banner text"),
    ("urgent", "surface", TEXT, "field errors, urgent link, danger button"),
    ("urgent", "canvas", TEXT, "urgent text on the page"),
    ("#ffffff", "urgent", TEXT, "911 button"),
    ("#ffffff", "urgent-hover", TEXT, "911 button hover"),
    ("urgent", "urgent-tint", TEXT, "#342 error summary heading and links"),
    ("#ffffff", "urgent", TEXT, "#342 error summary and field error mark"),
    ("focus", "surface", UI, "#342 focus ring around the focused error summary, in a card"),
    ("success", "success-tint", TEXT, "success banner, green badge"),
    ("success", "surface", TEXT, "local-AI signature icon (ok)"),
    ("warn", "surface", TEXT, "local-AI signature icon (mock, degraded)"),
    ("teal", "surface", TEXT, "teal accent text"),
    ("#3d5566", "sunken", TEXT, "gray badge, undetermined level"),
    ("night-ink", "night", TEXT, "demo banner"),
    ("#ffffff", "night", TEXT, "demo banner emphasis"),
    ("#ffffff", "#101d3c", TEXT, "presenter toolbar"),
    ("#6f8b9c", "surface", UI, "text field border"),
    ("#c27a12", "surface", UI, "status dot (mock, degraded) beside its text"),
    ("#1e8e5a", "surface", UI, "status dot (ok) beside its text"),
    ("#ffffff", "#0a3cb4", TEXT, "hero panel heading (gradient middle)"),
    ("#d6e2ff", "#0a3cb4", TEXT, "hero panel text (gradient middle)"),
    ("#eef3ff", "#1d5cf0", TEXT, "hero panel facts (lightest gradient stop)"),
    ("#ffffff", "#1d5cf0", TEXT, "hero panel heading (lightest gradient stop)"),
    ("#c9d8ff", "#0a3cb4", TEXT, "hero panel kicker and closing line"),
    # W06 telemetry (ADR-017): chart marks are graphical objects (1.4.11), always labeled with text values too.
    ("chart-cloud", "surface", UI, "W06 cost bar and line: same model, cloud API"),
    ("chart-frontier", "surface", UI, "W06 cost bar: frontier cloud API"),
    ("chart-local", "surface", UI, "W06 cost bar and line: this device"),
    ("chart-cloud", "sunken", UI, "W06 cloud bar on its track"),
    ("chart-frontier", "sunken", UI, "W06 frontier bar on its track"),
    ("chart-local", "sunken", UI, "W06 device bar on its track"),
    ("chart-frontier-2", "surface", UI, "W06 cost bar: second frontier cloud API (#127)"),
    ("chart-frontier-2", "sunken", UI, "W06 second frontier bar on its track"),
    ("violet-ink", "violet-tint", TEXT, "#239 violet chip and badge text on its tint"),
    ("violet-ink", "surface", TEXT, "#239 violet label text in cards"),
    ("violet", "surface", UI, "#239 violet accent band, icon and border in cards"),
    ("violet", "violet-tint", UI, "#239 violet border on its tint"),
    ("sky-ink", "sky-tint", TEXT, "#239 sky chip and badge text on its tint"),
    ("sky-ink", "surface", TEXT, "#239 sky label text in cards"),
    ("sky", "surface", UI, "#239 sky accent band, icon and border in cards"),
    ("sky", "sky-tint", UI, "#239 sky border on its tint"),
    ("amber-ink", "amber-tint", TEXT, "#239 amber chip and badge text on its tint"),
    ("amber-ink", "surface", TEXT, "#239 amber label text in cards"),
    ("amber", "surface", UI, "#239 amber accent band, icon and border in cards"),
    ("amber", "amber-tint", UI, "#239 amber border on its tint"),
    ("rose-ink", "rose-tint", TEXT, "#239 rose chip and badge text on its tint"),
    ("rose-ink", "surface", TEXT, "#239 rose label text in cards"),
    ("rose", "surface", UI, "#239 rose accent band, icon and border in cards"),
    ("rose", "rose-tint", UI, "#239 rose border on its tint"),
    ("green-ink", "green-tint", TEXT, "#239 green chip and badge text on its tint"),
    ("green-ink", "surface", TEXT, "#239 green label text in cards"),
    ("green", "surface", UI, "#239 green accent band, icon and border in cards"),
    ("green", "green-tint", UI, "#239 green border on its tint"),
    ("coral-ink", "coral-tint", TEXT, "#239 coral chip and badge text on its tint"),
    ("coral-ink", "surface", TEXT, "#239 coral label text in cards"),
    ("coral", "surface", UI, "#239 coral accent band, icon and border in cards"),
    ("coral", "coral-tint", UI, "#239 coral border on its tint"),
    ("slate-ink", "slate-tint", TEXT, "#239 slate chip and badge text on its tint"),
    ("slate-ink", "surface", TEXT, "#239 slate label text in cards"),
    ("slate", "surface", UI, "#239 slate accent band, icon and border in cards"),
    ("slate", "slate-tint", UI, "#239 slate border on its tint"),
    ("teal-ink", "teal-tint", TEXT, "#239 teal chip text on its tint"),
    ("teal-ink", "canvas", TEXT, "#242 done journey step label on the page"),
    ("teal-solid", "canvas", UI, "#242 done step ring and connector on the page"),
    ("teal-solid", "surface", UI, "#239 teal accent band and icon"),
    ("ink", "violet-tint", TEXT, "#240 text over the hero wash (violet)"),
    ("ink", "sky-tint", TEXT, "#240 text over the hero wash (sky)"),
    ("muted", "violet-tint", TEXT, "#240 secondary text over the hero wash"),
    ("muted", "teal-tint", TEXT, "#240 secondary text over the hero wash"),
    ("#1e8e5a", "surface", UI, "#245 scale value 0 border"),
    ("#ffffff", "#1e8e5a", LARGE, "#245 selected scale value 0 (19 px bold numeral)"),
    ("#14896a", "surface", UI, "#245 scale value 1 border"),
    ("#ffffff", "#14896a", LARGE, "#245 selected scale value 1 (19 px bold numeral)"),
    ("#00897b", "surface", UI, "#245 scale value 2 border"),
    ("#ffffff", "#00897b", LARGE, "#245 selected scale value 2 (19 px bold numeral)"),
    ("#0b7fc2", "surface", UI, "#245 scale value 3 border"),
    ("#ffffff", "#0b7fc2", LARGE, "#245 selected scale value 3 (19 px bold numeral)"),
    ("#3a6bd1", "surface", UI, "#245 scale value 4 border"),
    ("#ffffff", "#3a6bd1", LARGE, "#245 selected scale value 4 (19 px bold numeral)"),
    ("#5b4cc4", "surface", UI, "#245 scale value 5 border"),
    ("#ffffff", "#5b4cc4", LARGE, "#245 selected scale value 5 (19 px bold numeral)"),
    ("#7340b8", "surface", UI, "#245 scale value 6 border"),
    ("#ffffff", "#7340b8", LARGE, "#245 selected scale value 6 (19 px bold numeral)"),
    ("#9b3aa6", "surface", UI, "#245 scale value 7 border"),
    ("#ffffff", "#9b3aa6", LARGE, "#245 selected scale value 7 (19 px bold numeral)"),
    ("#c8336f", "surface", UI, "#245 scale value 8 border"),
    ("#ffffff", "#c8336f", LARGE, "#245 selected scale value 8 (19 px bold numeral)"),
    ("#c4473f", "surface", UI, "#245 scale value 9 border"),
    ("#ffffff", "#c4473f", LARGE, "#245 selected scale value 9 (19 px bold numeral)"),
    ("#b3452b", "surface", UI, "#245 scale value 10 border"),
    ("#ffffff", "#b3452b", LARGE, "#245 selected scale value 10 (19 px bold numeral)"),
    ("#ffffff", "brand-deep", TEXT, "#251 primary button text at the gradient's far end"),
    ("ink", "green-tint", TEXT, "#255 accepted consent panel text; #256 None of these apply ticked"),
    ("muted", "green-tint", TEXT, "#255 consent version on the accepted panel"),
    ("green-ink", "green-tint", TEXT, "#255 accepted consent checkbox label"),
    ("ink", "rose-tint", TEXT, "#256 a ticked warning sign's text"),
    ("violet-ink", "violet-tint", TEXT, "#254 an open FAQ item's question on hover"),
    ("ink", "violet-tint", TEXT, "#254 an open FAQ item's answer"),
    ("violet", "surface", UI, "#254 FAQ chevron"),
    ("slate-ink", "surface", TEXT, "#257 an unanswered summary value"),
    # #548: the presenter's Logs view (level word on its tint, the level stripe and chip borders, a failed row's tint)
    ("success", "success-tint", TEXT, "#548 OK level word and chip"),
    ("warn", "warn-tint", TEXT, "#548 WARN level word and chip"),
    ("urgent", "urgent-tint", TEXT, "#548 FAIL level word and chip"),
    ("slate-ink", "slate-tint", TEXT, "#548 INFO level word and chip"),
    ("green", "surface", UI, "#548 OK row stripe"),
    ("amber", "surface", UI, "#548 WARN row stripe"),
    ("urgent", "surface", UI, "#548 FAIL row stripe"),
    ("slate", "surface", UI, "#548 INFO row stripe"),
    ("amber", "warn-tint", UI, "#548 WARN chip border"),
    ("ink", "#fffafa", TEXT, "#548 text of a failed log row"),
    ("muted", "#fffafa", TEXT, "#548 secondary text of a failed log row"),
    ("muted", "surface", TEXT, "#548 a level chip switched off"),
    ("sky-ink", "sky-tint", TEXT, "#252 example choice chips"),
    ("sky", "sunken", UI, "#259 queue timing bar"),
    ("violet", "sunken", UI, "#259 inference timing bar"),
    ("teal-solid", "sunken", UI, "#259 validation timing bar"),
    ("brand", "sunken", UI, "#259 total timing bar"),
    ("green", "surface", UI, "#259 ready status tile edge and icon"),
    ("amber", "surface", UI, "#259 degraded status tile edge and icon"),
    ("urgent", "surface", UI, "#259 unavailable status tile edge and icon"),
    # #487: the home page's role cards (W01): text on each card's tint (the top of its wash), the kicker and the band.
    ("ink", "brand-tint", TEXT, "#487 patient card heading and points on its tint"),
    ("muted", "brand-tint", TEXT, "#487 patient card lead on its tint"),
    ("ink", "violet-tint", TEXT, "#487 presenter card heading and points on its tint"),
    ("muted", "violet-tint", TEXT, "#487 presenter card lead on its tint"),
    ("brand-ink", "surface", TEXT, "#487 patient card kicker and point icons"),
    ("violet-ink", "surface", TEXT, "#487 presenter card kicker and point icons"),
    ("brand", "brand-tint", UI, "#487 patient card band and icon border on its tint"),
    ("violet", "violet-tint", UI, "#487 presenter card band and icon border on its tint"),
    ("#ffffff", "#101d3c", TEXT, "#487 presenter toolbar link to the home page"),
]


def tokens(css: str) -> dict[str, str]:
    root = css[css.index(":root {"):css.index("}", css.index(":root {"))]
    return {m.group(1): m.group(2).lower() for m in re.finditer(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b", root)}


def luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def check(css_text: str) -> list[dict]:
    t = tokens(css_text)
    rows = []
    for fg, bg, minimum, where in PAIRS:
        a, b = (x if x.startswith("#") else t[x] for x in (fg, bg))
        raw = ratio(a, b)
        # #301: the raw ratio is compared (4.496 is below 4.5, although it rounds to 4.5); the shown value is
        # truncated, never rounded up, so a failing pair never displays as meeting its minimum.
        rows.append({"fg": fg, "bg": bg, "fg_hex": a, "bg_hex": b, "ratio": math.floor(raw * 100) / 100,
                     "raw_ratio": raw, "minimum": minimum, "passed": raw >= minimum, "used_for": where})
    return rows


def main() -> int:
    rows = check(CSS.read_text())
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=1))
    else:
        for r in rows:
            print(f"{'PASS' if r['passed'] else 'FAIL'} {r['ratio']:>5}:1 (min {r['minimum']}) {r['fg']} on {r['bg']} — {r['used_for']}")
    failed = [r for r in rows if not r["passed"]]
    print(f"{len(rows) - len(failed)}/{len(rows)} pairs pass WCAG 2.2 AA", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
