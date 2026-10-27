#!/usr/bin/env python3
"""Which browser specs (tests/ui) to run for the files changed against a base (#509, `check_all.sh --changed`).

  python3 scripts/changed_ui_specs.py [--base origin/main] [--explain] [-- FILE...]

Changed files are the branch's commits since its merge base with --base, plus uncommitted and untracked files (or the
files given after `--`). Output, one per line: `ALL` (run the whole suite), or Playwright file filters
(`tests/ui/A07.spec.ts`; #526: Playwright matches them against the spec paths and finds nothing for a `../../` path), or
nothing (no browser spec is related). --explain writes the reasons to stderr.

Playwright's own `--only-changed` follows imports from spec files, and the specs drive the built app through a browser
without importing its source, so it would only catch changed spec and helper files. This mapping adds the app side:
- shared infrastructure (the API client, Layout, routing, global state and styles, shared UI primitives, the Playwright
  config, tests/ui/support/, web dependencies and build config) -> ALL;
- a changed spec -> that spec;
- a screen `apps/web/src/screens/<ID>.tsx` -> `<ID>.spec.ts` and every spec that names the screen ID or its static
  route;
- a component -> the specs of every screen that imports it (and specs that name the component);
- anything else (backend, docs, scripts) -> no browser spec; the backend suite covers apps/api and CI runs everything.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = "apps/web/"
SPECS = ROOT / "tests/ui"
FULL = (
    "apps/web/src/api/", "apps/web/src/components/Layout.tsx", "apps/web/playwright.config.ts", "tests/ui/support/",
    "apps/web/src/main.tsx", "apps/web/src/routes.tsx", "apps/web/src/state/", "apps/web/src/styles.css",
    "apps/web/src/components/ui.tsx", "apps/web/src/components/useCase.ts", "apps/web/package.json",
    "apps/web/package-lock.json", "apps/web/vite.config.ts", "apps/web/index.html", "apps/web/tsconfig.json",
)


def git(*args: str) -> list[str]:
    r = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"changed_ui_specs: git {' '.join(args)} failed: {r.stderr.strip()}")
    return [line for line in r.stdout.splitlines() if line]


def changed_files(base: str) -> list[str]:
    merge_base = git("merge-base", base, "HEAD")[0]
    files = set(git("diff", "--name-only", merge_base))  # commits since the merge base and the working tree
    files |= set(git("ls-files", "--others", "--exclude-standard"))
    return sorted(files)


def spec_names() -> list[str]:
    return sorted(p.name for p in SPECS.glob("*.spec.ts"))


def screens() -> dict[str, str]:
    data = json.loads((ROOT / "spec/screens.json").read_text())
    return {s["id"]: s["route"] for s in data.get("screens", data)}


def mentioning(patterns: list[str]) -> set[str]:
    found = set()
    for name in spec_names():
        text = (SPECS / name).read_text()
        if any(re.search(p, text) for p in patterns):
            found.add(name)
    return found


def screen_specs(screen_id: str, routes: dict[str, str]) -> set[str]:
    route = routes.get(screen_id, "")
    pats = [rf"\b{screen_id}\b"]
    if route and ":" not in route and route != "/":  # a static route, quoted literally ("/app/new")
        pats.append(re.escape(route) + r"['\"`?#/]")
    own = {f"{screen_id}.spec.ts"} & set(spec_names())
    return own | mentioning(pats)


def component_specs(path: str, routes: dict[str, str]) -> set[str]:
    stem = Path(path).stem
    users = set()
    for screen in (ROOT / "apps/web/src/screens").glob("*.ts*"):
        if re.search(rf"from ['\"]\.\./components/{re.escape(stem)}['\"]", screen.read_text()):
            users.add(screen.stem)
    found = mentioning([rf"\b{re.escape(stem)}\b"])
    for sid in users:
        if sid in routes:
            found |= screen_specs(sid, routes)
    return found


def select(files: list[str], explain) -> list[str] | str:
    routes = screens()
    chosen: set[str] = set()
    for f in files:
        if any(f == p or (p.endswith("/") and f.startswith(p)) for p in FULL):
            explain(f"{f}: shared infrastructure -> ALL")
            return "ALL"
        if f.startswith("tests/ui/") and f.endswith(".spec.ts"):
            if (ROOT / f).exists():
                chosen.add(Path(f).name)
                explain(f"{f}: changed spec")
            continue
        if f.startswith("apps/web/src/screens/"):
            sid = re.match(r"[A-Z]\d\d", Path(f).stem)
            got = screen_specs(sid.group(0), routes) if sid else set()
            explain(f"{f}: screen -> {sorted(got) or 'no spec'}")
            chosen |= got
            continue
        if f.startswith("apps/web/src/components/"):
            got = component_specs(f, routes)
            explain(f"{f}: component -> {sorted(got) or 'no spec'}")
            chosen |= got
            continue
        if f.startswith("apps/web/src/"):  # an unmapped web source file: be safe
            explain(f"{f}: web source without a mapping -> ALL")
            return "ALL"
    return sorted(chosen)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--explain", action="store_true")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args(argv)
    files = args.files or changed_files(args.base)
    explain = (lambda msg: print(msg, file=sys.stderr)) if args.explain else (lambda msg: None)
    result = select(files, explain)
    if result == "ALL":
        print("ALL")
    else:
        for name in result:
            print(f"tests/ui/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
