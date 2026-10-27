"""Every file an image COPYs from the build context must be allowlisted in .dockerignore.

.dockerignore excludes everything (`*`) and re-includes named paths with `!`. A COPY of a path that is not
re-included fails only at image build time, in CI's package smoke test or the release build (as content/pathways did
before #27 landed), so this check runs with the fast tooling tests.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILES = sorted((ROOT / "infra/deploy").glob("*.Dockerfile"))


def allowlist() -> list[str]:
    lines = (ROOT / ".dockerignore").read_text().splitlines()
    return [line[1:].strip().rstrip("/") for line in lines if line.startswith("!")]


def context_sources(dockerfile: Path) -> list[str]:
    """Context paths copied by COPY instructions without --from (multi-stage copies read other stages)."""
    sources = []
    for line in dockerfile.read_text().splitlines():
        if not line.startswith("COPY ") or "--from=" in line:
            continue
        parts = [p for p in line.split()[1:] if not p.startswith("--")]
        sources += parts[:-1]  # the last argument is the destination
    return sources


def allowed(source: str, entries: list[str]) -> bool:
    source = source.rstrip("/")
    return any(source == e or source.startswith(e + "/") for e in entries)


class BuildContextTest(unittest.TestCase):
    def test_dockerfiles_exist(self):
        self.assertEqual([p.name for p in DOCKERFILES], ["api.Dockerfile", "web.Dockerfile"])

    def test_every_copied_source_is_allowlisted_and_exists(self):
        entries = allowlist()
        for dockerfile in DOCKERFILES:
            for source in context_sources(dockerfile):
                with self.subTest(dockerfile=dockerfile.name, source=source):
                    self.assertTrue(allowed(source, entries), f"{source} is not re-included in .dockerignore")
                    self.assertTrue((ROOT / source).exists(), f"{source} does not exist")

    def test_the_api_image_ships_the_reviewed_pathways(self):
        api = ROOT / "infra/deploy/api.Dockerfile"
        self.assertIn("content/pathways", context_sources(api))
        self.assertTrue(re.search(r"^!content/pathways/?$", (ROOT / ".dockerignore").read_text(), re.M))


if __name__ == "__main__":
    unittest.main()
