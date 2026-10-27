"""#319: every test the acceptance evaluation cites must exist under tests/.

The release evaluation (#55 clause map, evaluate.py) and the acceptance registry name tests by file and title. A renamed
test then reads as "missing" and silently drops its scenario (T-R37-S01 on v0.10.0-demo.1). This check makes a rename
fail CI instead."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [ROOT / "evidence/acceptance/55-clinician-scenarios/clause-map.json", ROOT / "spec/acceptance.json"]
CITE = re.compile(r'"(tests/(?:ui|acceptance)/[^"]+?)(?:::| > )([^"]+)"')


def cited() -> set[tuple[str, str]]:
    out = set()
    for source in SOURCES:
        for path, name in CITE.findall(source.read_text()):
            out.add((path, json.loads(f'"{name}"')))
    return out


def ui_title_matches(text: str, name: str) -> bool:
    """True when a test(...) title in the file is `name`. A template title such as `... (${level}) ...` matches any
    expansion of its placeholders (the evaluation cites one expansion, e.g. "(emergency)")."""
    for quote, body in re.findall(r'\btest\(\s*(["\'`])((?:\\.|(?!\1).)*)\1', text):
        if quote == "`" and "${" in body:
            pattern = "".join(".+?" if part.startswith("${") else re.escape(part)
                              for part in re.split(r"(\$\{[^}]*\})", body))
            if re.fullmatch(pattern, name):
                return True
        elif body == name:
            return True
    return False


class CitedTestsExist(unittest.TestCase):
    def test_the_sources_cite_tests(self):
        self.assertGreater(len(cited()), 100)

    def test_every_cited_test_exists(self):
        missing = []
        cache: dict[str, str] = {}
        for path, name in sorted(cited()):
            file = ROOT / path
            if not file.exists():
                missing.append(f"{path} (file missing)")
                continue
            text = cache.setdefault(path, file.read_text())
            if path.startswith("tests/ui/"):
                if not ui_title_matches(text, name):
                    missing.append(f"{path}::{name}")
            elif not re.search(rf"^def {re.escape(name.split('[')[0])}\(", text, re.M):
                missing.append(f"{path}::{name}")
        self.assertEqual(missing, [], "cited by the clause map or spec/acceptance.json but not found")


if __name__ == "__main__":
    unittest.main()
