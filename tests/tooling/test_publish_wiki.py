"""scripts/publish_wiki.py (ADR-019): the Wiki lint, and publication to a local bare repository (no network)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import publish_wiki  # noqa: E402

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class Lint(unittest.TestCase):
    def test_the_repository_wiki_source_passes(self):
        self.assertEqual(publish_wiki.lint(publish_wiki.load()), [])

    def test_unknown_pages_links_and_unlisted_files_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs/wiki").mkdir(parents=True)
            cfg = {**publish_wiki.load(), "managed_pages": ["Home.md"]}
            (root / "docs/wiki/Home.md").write_text("[a](Missing) [b](Home.md) [c](Home#x)\n")
            (root / "docs/wiki/Extra.md").write_text("x\n")
            problems = publish_wiki.lint(cfg, root)
        self.assertIn("Home.md: link to unknown Wiki page Missing", problems)
        self.assertIn("Home.md: Wiki links omit .md (Home.md)", problems)
        self.assertIn("docs/wiki/Extra.md is not listed in managed_pages", problems)
        self.assertEqual(len(problems), 3)


class Publish(unittest.TestCase):
    def test_publishes_verifies_and_is_idempotent(self):
        old = {k: os.environ.get(k) for k in ENV}
        os.environ.update(ENV)
        self.addCleanup(lambda: [os.environ.pop(k) if v is None else os.environ.__setitem__(k, v) for k, v in old.items()])
        tmp = Path(tempfile.mkdtemp(prefix="wiki-test-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        wiki = tmp / "wiki.git"
        seed = tmp / "seed"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(wiki)], check=True)
        subprocess.run(["git", "clone", "-q", str(wiki), str(seed)], check=True, capture_output=True)
        (seed / "Home.md").write_text("old\n")
        subprocess.run(["git", "-C", str(seed), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(seed), "commit", "-q", "-m", "seed"], check=True)
        subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "HEAD"], check=True, capture_output=True)
        root = tmp / "repo"
        (root / "docs/wiki").mkdir(parents=True)
        (root / "docs/wiki/Home.md").write_text("new [x](Other)\n")
        (root / "docs/wiki/Other.md").write_text("other\n")
        cfg = {**publish_wiki.load(), "managed_pages": ["Home.md", "Other.md"]}
        (root / "docs/wiki-publication.json").write_text(json.dumps(cfg))
        first = publish_wiki.publish(cfg, root, str(wiki))
        self.assertEqual(first["status"], "published")
        shown = subprocess.run(["git", "--git-dir", str(wiki), "show", "master:Home.md"], capture_output=True,
                               text=True, check=True).stdout
        self.assertEqual(shown, "new [x](Other)\n")
        self.assertEqual(publish_wiki.publish(cfg, root, str(wiki))["status"], "unchanged")


if __name__ == "__main__":
    unittest.main()
