#!/usr/bin/env python3
"""Publish the reviewed Wiki source (docs/wiki/) to the repository Wiki (ADR-019; replaces the ADR-011 completion flow).

  lint      Check docs/wiki/: every managed page exists, nothing unlisted is there, and Wiki and repository links resolve.
  publish   Copy the managed pages from the working tree to the Wiki, commit and push, then fetch the Wiki back and
            confirm it holds exactly these pages. Nothing to change is a success.

Configuration: docs/wiki-publication.json (source_dir, wiki_remote, wiki_web, managed_pages).
Credentials: WIKI_PUSH_TOKEN, when set, reaches git through a transient credential helper read from the environment at
use time; it never appears in arguments, files, remote URLs or output. Without it, git's own credential helper is used.
Standard library only. Exit status: 0 done, 1 lint problems or a failed publication.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "docs" / "wiki-publication.json"
LINK = re.compile(r"\]\(([^)\s]+)\)")
PUBLISHER = ("Aware Care Wiki Publisher", "41898282+github-actions[bot]@users.noreply.github.com")


def load(path: Path = CONFIG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def lint(cfg: dict, root: Path = ROOT) -> list[str]:
    problems = []
    src = root / cfg["source_dir"]
    pages = cfg["managed_pages"]
    names = {p[:-3] for p in pages}
    files = {p.name for p in src.iterdir() if p.is_file()}
    problems += [f"managed page {p} is missing from {cfg['source_dir']}/" for p in pages if p not in files]
    problems += [f"{cfg['source_dir']}/{p} is not listed in managed_pages" for p in sorted(files - set(pages))]
    repo_web = cfg["wiki_web"].rsplit("/wiki", 1)[0]
    prefixes = (f"{repo_web}/blob/main/", f"{repo_web}/tree/main/")
    for page in pages:
        if not (src / page).exists():
            continue
        for target in LINK.findall((src / page).read_text(encoding="utf-8")):
            if target.startswith(("#", "mailto:")):
                continue
            if target.startswith(prefixes):
                rel = target.split("/main/", 1)[1].split("#")[0]
                if not (root / rel).exists():
                    problems.append(f"{page}: repository link to missing path {rel}")
            elif target.startswith(cfg["wiki_web"] + "/"):
                name = target[len(cfg["wiki_web"]) + 1:].split("#")[0]
                if name and name not in names:
                    problems.append(f"{page}: Wiki link to unknown page {name}")
            elif not target.startswith(("http://", "https://")):
                name = target.split("#")[0]
                if name.endswith(".md"):
                    problems.append(f"{page}: Wiki links omit .md ({target})")
                elif name not in names:
                    problems.append(f"{page}: link to unknown Wiki page {target}")
    return problems


def git(*args: str, cwd: Path | None = None, auth: bool = False) -> subprocess.CompletedProcess:
    helper = []
    if auth and os.environ.get("WIKI_PUSH_TOKEN"):
        script = '!f() { test "$1" = get || exit 0; echo username=x-access-token; echo "password=${WIKI_PUSH_TOKEN}"; }; f'
        helper = ["-c", "credential.helper=", "-c", f"credential.helper={script}"]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    return subprocess.run(["git", *helper, *args], cwd=cwd, env=env, capture_output=True, text=True)


def clone(url: str, dest: Path) -> None:
    result = git("clone", "--quiet", "--depth", "1", url, str(dest), auth=True)
    if result.returncode:
        raise RuntimeError(f"cloning the Wiki failed: {result.stderr.strip()[-300:]}")


def publish(cfg: dict, root: Path = ROOT, url: str | None = None) -> dict:
    url = url or cfg["wiki_remote"]
    src = root / cfg["source_dir"]
    source = git("rev-parse", "HEAD", cwd=root).stdout.strip() or "unknown"
    with tempfile.TemporaryDirectory(prefix="wiki-") as tmp:
        wiki = Path(tmp) / "wiki"
        clone(url, wiki)
        for page in cfg["managed_pages"]:
            (wiki / page).write_bytes((src / page).read_bytes())
        git("add", "--", *cfg["managed_pages"], cwd=wiki)
        status = "unchanged"
        if git("diff", "--cached", "--quiet", cwd=wiki).returncode:
            message = f"Publish docs/wiki from {source[:12]}\n\nSource-Commit: {source}\n"
            git("-c", f"user.name={PUBLISHER[0]}", "-c", f"user.email={PUBLISHER[1]}", "commit", "--quiet", "-m",
                message, cwd=wiki)
            pushed = git("push", "--quiet", "origin", "HEAD", cwd=wiki, auth=True)
            if pushed.returncode:
                raise RuntimeError(f"Wiki push refused: {pushed.stderr.strip()[-300:]}")
            status = "published"
        check = Path(tmp) / "check"
        clone(url, check)
        mismatched = [p for p in cfg["managed_pages"]
                      if not (check / p).exists() or (check / p).read_bytes() != (src / p).read_bytes()]
        if mismatched:
            raise RuntimeError("the published Wiki differs from docs/wiki/: " + ", ".join(mismatched))
    return {"status": status, "source_commit": source, "pages": len(cfg["managed_pages"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["lint", "publish"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--wiki-url", help="Override the Wiki remote (tests)")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    cfg = load(root / "docs" / "wiki-publication.json")
    problems = lint(cfg, root)
    if args.command == "lint" or problems:
        print(json.dumps({"lint": "FAILED" if problems else "PASSED", "problems": problems}, indent=2))
        return 1 if problems else 0
    try:
        print(json.dumps(publish(cfg, root, args.wiki_url), indent=2))
    except RuntimeError as exc:
        print(json.dumps({"publish": "FAILED", "error": str(exc)}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
