"""Recognise the configured model among the IDs ZRT serves and the copies it has downloaded (#528).

ZRT names a served model by its `--label` when one is given (our serve scripts: `qwen3.6-35b-a3b-fp8`), otherwise by
the model's canonical name (`Qwen/Qwen3.6-35B-A3B-FP8`); its own listings write the model URI as
`hf:<org>/<name>@<revision>` (`main` when pulled without a revision), and its cache keeps each copy under
`<base>/models/hf/<org>/<name>/<revision>/` (a bare vLLM names a model by that path). So the same model can appear as
any of:

    qwen3.6-35b-a3b-fp8                         our short name (the label)
    Qwen/Qwen3.6-35B-A3B-FP8                    the Hugging Face repository id, any case
    Qwen/Qwen3.6-35B-A3B-FP8@main               ... with any revision
    hf:Qwen/Qwen3.6-35B-A3B-FP8@95a723d...      ... with the hf: scheme
    /opt/hp/zrt/models/hf/Qwen/Qwen3.6-35B-A3B-FP8/main   the cache path

A revision other than the qualified one still matches: it is reported as a note, never a failure (ADR-019). Only a
different model does not match. The app then talks to ZRT with the ID ZRT actually serves.

Standard library only: the API imports it, and demo.sh and infra/deploy run it as a script (see `main`).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

_CACHE_PATH = re.compile(r"/models/(?:hf/)?([^/@\s]+)/([^/@\s]+)/([^/\s]+)/*$")
# Table cells of `zrt services` / `zrt models`: an hf: URI, then (services) the name it is served as.
_URI = re.compile(r"hf:([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)(?:@([A-Za-z0-9._-]+))?", re.IGNORECASE)
_SERVICE_ROW = re.compile(r"(hf:[A-Za-z0-9._/-]+(?:@[A-Za-z0-9._-]+)?)\s*[│|]\s*([^\s│|]+)")


@dataclass(frozen=True)
class ServedMatch:
    served_id: str          # exactly as ZRT lists it; requests must use this
    revision: str | None    # the revision ZRT serves, when it is known


def split_ref(ref: str) -> tuple[str, str | None]:
    """(name, revision) of a model reference: lower-case name without `hf:` or `@revision`; revision or None."""
    text = ref.strip()
    path = _CACHE_PATH.search(text)
    if path:
        return f"{path[1]}/{path[2]}".lower(), path[3]
    if text[:3].lower() == "hf:":
        text = text[3:]
    name, _, revision = text.partition("@")
    return name.strip().strip("/").lower(), (revision.strip() or None)


def aliases(model_id: str, repository: str | None = None) -> set[str]:
    """Every name, lower case and without revision, under which ZRT may serve this model."""
    names = {split_ref(model_id)[0]}
    if repository:
        names.add(split_ref(repository)[0])
    return {n for n in names if n}


def find_served(served_ids: Iterable[Any], model_id: str, repository: str | None = None) -> ServedMatch | None:
    """The served ID that is this model (the exact configured ID first), or None for an entirely different model."""
    ids = [i for i in served_ids if isinstance(i, str) and i.strip()]
    if model_id in ids:
        return ServedMatch(model_id, split_ref(model_id)[1])
    wanted = aliases(model_id, repository)
    for served in ids:
        name, revision = split_ref(served)
        if name in wanted:
            return ServedMatch(served, revision)
    return None


def manifest_ref(manifest: Any, model_id: str | None) -> str | None:
    """`<repository>@<revision>` from a model manifest (infra/model-manifest.json, infra/fury/model-manifest.json),
    only when the manifest describes the configured model."""
    model = manifest.get("model") if isinstance(manifest, dict) else None
    if not model_id or not isinstance(model, dict) or not isinstance(model.get("repository_id"), str):
        return None
    repository, label = model["repository_id"], model.get("served_model_id")
    names = aliases(model_id)
    if not names & (aliases(repository) | (aliases(label) if isinstance(label, str) else set())):
        return None
    revision = model.get("revision")
    return f"{repository}@{revision}" if isinstance(revision, str) and revision else repository


def catalog_manifest(catalog: Any, model_id: str | None, root: Path) -> dict | None:
    """#537: the manifest of the catalogue entry (infra/models/catalog.json) whose label or repository is this model:
    the entry's inline manifest, or the file it names (relative to `root`, the repository or image root)."""
    if not model_id or not isinstance(catalog, dict) or not isinstance(catalog.get("models"), list):
        return None
    names = aliases(model_id)
    for entry in catalog["models"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("label"), str):
            continue
        if not names & aliases(entry["label"], entry.get("repository_id") if isinstance(entry.get("repository_id"),
                                                                                       str) else None):
            continue
        manifest = entry.get("manifest")
        if isinstance(manifest, str):
            manifest = _json(_read(str(root / manifest)))
        return manifest if isinstance(manifest, dict) else None
    return None


def selected_manifest(manifest_path: Path, catalog_path: Path | None, model_id: str | None, root: Path) -> dict:
    """The model manifest for the configured model (#537): the configured file when it describes the model (or no
    model is configured), else the catalogue entry selected by the served label, else the configured file."""
    manifest = _json(_read(str(manifest_path)))
    manifest = manifest if isinstance(manifest, dict) else {}
    if not model_id or manifest_ref(manifest, model_id) is not None or catalog_path is None:
        return manifest
    return catalog_manifest(_json(_read(str(catalog_path))), model_id, root) or manifest


def same_revision(a: str | None, b: str | None) -> bool:
    """Equal revisions; a commit hash abbreviated to at least 7 characters counts as the same."""
    if not a or not b:
        return False
    a, b = a.lower(), b.lower()
    return a == b or (min(len(a), len(b)) >= 7 and (a.startswith(b) or b.startswith(a)))


def revision_note(served: str | None, qualified: str | None) -> str | None:
    """None when ZRT serves the qualified revision; otherwise a note (never a failure)."""
    if not qualified or same_revision(served, qualified):
        return None
    short = qualified[:7] + "…" if len(qualified) > 12 else qualified
    if not served:
        return f"ZRT does not say which revision it serves; this app was qualified on {short}"
    return f"serving revision {served}; this app was qualified on {short}"


def served_ids_from(body: Any) -> list[str]:
    data = body.get("data") if isinstance(body, dict) else None
    return [m["id"] for m in data if isinstance(m, dict) and isinstance(m.get("id"), str)] if isinstance(data, list) \
        else []


def revision_from_zrt(served_id: str, proxy_json: Any = None, services_text: str = "") -> str | None:
    """The revision behind a served ID whose name carries none, from ZRT's proxy registry (proxy.json: services with
    `label` and `model_uri`) or the `zrt services` table (MODEL URI | SERVED AS)."""
    name = split_ref(served_id)[0]
    pairs: list[tuple[str, str]] = []
    services = proxy_json.get("services") if isinstance(proxy_json, dict) else None
    for s in services if isinstance(services, list) else []:
        if isinstance(s, dict) and isinstance(s.get("model_uri"), str):
            pairs.append((s["model_uri"], s.get("label") if isinstance(s.get("label"), str) else ""))
    pairs += _SERVICE_ROW.findall(services_text or "")
    for uri, label in pairs:
        uri_name, revision = split_ref(uri)
        if name in {split_ref(label)[0] if label else uri_name, uri_name}:
            return revision or "main"
    return None


@dataclass(frozen=True)
class ZrtService:
    """One row of the `zrt services` table (#535)."""
    pid: str
    names: tuple[str, ...]  # the MODEL URI and SERVED AS cells, with their continuation lines
    endpoint: str           # the API ENDPOINT cell; "-" when ZRT names none
    status: str
    uptime: str


_UPTIME = re.compile(r"\b\d+[smhd]\b")


def _cells(line: str) -> list[str] | None:
    text = line.strip()
    if not text.startswith("│"):
        return None
    cells = [c.strip() for c in text.split("│")[1:]]
    return cells[:-1] if cells and not cells[-1] else cells


def parse_services(text: str) -> list[ZrtService]:
    """The services in `zrt services` output. ZRT prints two layouts, and both may wrap a cell onto continuation lines
    (an empty PID cell):

      │ GPU │ PID   │ MODEL URI / SERVED AS            │ API ENDPOINT          │ STATUS │ MEM USAGE      │ UPTIME │
      │ 0,1 │ 97820 │ hf:Qwen/Qwen3.6-35B-A3B-FP8@main │ http://127.0.0.1:9093 │ Ready  │ 65.3 GB (VRAM) │ 6m ago │
      │     │       │ Qwen/Qwen3.6-35B-A3B-FP8         │                       │        │                │        │

      │ PID    │ MODEL URI                         │ SERVED AS           │ API ENDPOINT │ STATUS │ MEM USAGE │ UPTIME │
      │ 129042 │ hf:Qwen/Qwen3.6-35B-A3B-FP8@95a7… │ qwen3.6-35b-a3b-fp8 │ -            │ Ready  │ 47.0 GB   │ 4d ago │

    Rows are read by their cells: the PID before the hf: URI, the SERVED AS cells after it, then the endpoint (a URL
    or "-"), the status and the uptime. So a table without its header line reads the same."""
    services: list[dict] = []
    current: dict | None = None
    for line in (text or "").splitlines():
        cells = _cells(line)
        if not cells:
            continue
        uri = next((i for i, c in enumerate(cells) if c[:3].lower() == "hf:"), None)
        if uri is None:
            # A continuation line of the last service: its name cells hold the rest of the name, or the served name.
            if current is not None and len(cells) == current["width"] and not any(cells[:current["uri"]]):
                for i in current["name_cols"]:
                    if i < len(cells) and cells[i]:
                        current["names"].append(cells[i])
                        current["parts"].setdefault(i, []).append(cells[i])
            continue
        end = next((j for j in range(uri + 1, len(cells)) if cells[j] == "-" or cells[j].startswith("http")), None)
        pid = cells[uri - 1] if uri > 0 else ""
        if end is None or not pid.isdigit():
            current = None
            continue
        rest = cells[end + 1:]
        current = {"pid": pid, "names": [c for c in cells[uri:end] if c], "endpoint": cells[end],
                   "status": rest[0] if rest else "-",
                   "uptime": next((c for c in reversed(rest[1:]) if _UPTIME.search(c)), "-"),
                   "uri": uri, "name_cols": list(range(uri, end)), "width": len(cells),
                   "parts": {i: [cells[i]] for i in range(uri, end) if cells[i]}}
        services.append(current)
    out = []
    for s in services:
        # A name wrapped over lines is also tried whole (its parts joined).
        joined = ["".join(p) for p in s["parts"].values() if len(p) > 1]
        out.append(ZrtService(s["pid"], tuple(s["names"] + joined), s["endpoint"], s["status"], s["uptime"]))
    return out


def service_serves(service: ZrtService, model_id: str, repository: str | None = None) -> bool:
    """Whether a `zrt services` row is this model (the same rule as `find_served`)."""
    wanted = aliases(model_id, repository)
    return any(split_ref(name)[0] in wanted for name in service.names)


def loopback_api_url(endpoint: str) -> str | None:
    """`<endpoint>/v1` when a service endpoint is on this device's loopback (http, an explicit port, no user info);
    else None. The API and the deploy tool apply the same rule again (ADR-014)."""
    url = (endpoint or "").strip().rstrip("/")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if (parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost", "::1"} or port is None
            or parts.username is not None or parts.password is not None or parts.query or parts.fragment):
        return None
    return url if url.endswith("/v1") else f"{url}/v1"


def uptime_seconds(text: str) -> int:
    """`6m ago`, `1h 2m ago`, `4d ago` in seconds (0 when unknown)."""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return sum(int(t[:-1]) * units[t[-1]] for t in _UPTIME.findall(text or ""))


def local_revisions(repository: str, zrt_models_text: str = "", store: Path | None = None) -> list[str]:
    """Revisions of this repository in ZRT's local cache: `zrt models` rows (hf:<repo>@<rev>) and the cache
    directory <store>/hf/<org>/<name>/<revision>/ (only complete copies: with a config.json)."""
    name = split_ref(repository)[0]
    found: list[str] = []
    for repo, revision in _URI.findall(zrt_models_text or ""):
        if repo.lower() == name and (revision or "main") not in found:
            found.append(revision or "main")
    if store is not None:
        for org_dir in _children(store / "hf"):
            for model_dir in _children(org_dir):
                if f"{org_dir.name}/{model_dir.name}".lower() != name:
                    continue
                for rev_dir in _children(model_dir):
                    if (rev_dir / "config.json").is_file() and rev_dir.name not in found:
                        found.append(rev_dir.name)
    return found


def shared_revisions(repository: str, store: Path) -> list[str]:
    """#644: revisions of this repository in a model cache another account owns: the system ZRT's (`/opt/hp/zrt/models`,
    group `zrt`), seen from user mode. A complete copy (with a config.json) counts, and so does a revision folder this
    account cannot read but sees by name through its readable parent; "?" when only the model's folder shows (it
    cannot be listed, so its revisions are unknown). Folders are found by listing, else by their path in the
    repository's own case (a folder that can be searched but not listed)."""
    name = split_ref(repository)[0]
    exact = repository.strip()
    if exact[:3].lower() == "hf:":
        exact = exact[3:]
    exact = exact.partition("@")[0].strip("/")
    model_dirs = [m for o in _children(store / "hf") for m in _children(o) if f"{o.name}/{m.name}".lower() == name]
    if not model_dirs and (store / "hf" / exact).is_dir():
        model_dirs = [store / "hf" / exact]
    found: list[str] = []
    for model_dir in model_dirs:
        try:
            revisions = sorted(p for p in model_dir.iterdir() if p.is_dir())
        except OSError:
            found.append("?")
            continue
        for rev_dir in revisions:
            readable = os.access(rev_dir, os.R_OK | os.X_OK)
            if (not readable or (rev_dir / "config.json").is_file()) and rev_dir.name not in found:
                found.append(rev_dir.name)
    return found


def choose_local(revisions: list[str], qualified: str | None, wanted: str | None = None) -> str | None:
    """The copy to serve: the wanted revision if asked for (None if absent), else the qualified one, else `main`,
    else any other copy."""
    if wanted:
        return next((r for r in revisions if same_revision(r, wanted)), None)
    for preferred in (qualified, "main"):
        hit = next((r for r in revisions if same_revision(r, preferred)), None)
        if hit:
            return hit
    return revisions[0] if revisions else None


def _children(path: Path) -> list[Path]:
    try:
        return sorted(p for p in path.iterdir() if p.is_dir())
    except OSError:
        return []


def _read(path: str | None) -> str:
    if not path:
        return ""
    if path == "-":
        return sys.stdin.read()
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _zrt_output(zrt: str | None, command: str, mode: str | None = None) -> str:
    """Read-only `zrt services` or `zrt models` output ("" when zrt is missing or fails); #537: `-m <mode>` for a ZRT
    in user or system mode."""
    if not zrt:
        return ""
    try:
        return subprocess.run([zrt, *(["-m", mode] if mode else []), command], capture_output=True, text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    """Command line for demo.sh. Each value is printed on its own line (an empty line for an unknown value).

      match --model ID --repo REF --models FILE [--proxy-json FILE] [--zrt PATH] [--zrt-mode user|system]
          the served ID, its revision and a revision note; exit 1 when the model is not served. The revision comes
          from the ID, else from ZRT's proxy registry or `zrt services`.
      ids --models FILE                 the served IDs
      note --served REV --qualified REV the revision note, or an empty line
      local --repo REF [--zrt PATH] [--zrt-mode user|system] [--store DIR] [--revision R]
          the revision of the downloaded copy to serve (`zrt models` and the cache directory); exit 1 when none
      shared --repo REF --store DIR [--revision R]
          #644: the revision of a copy in another account's cache (the system ZRT's, from user mode), "?" when the
          model's folder shows but cannot be listed (only without --revision); exit 1 when none
      services --model ID --repo REF --services FILE
          one line per `zrt services` row, tab-separated: 1 when it is this model (else 0), PID, status, endpoint,
          its loopback <endpoint>/v1 (else "-"), uptime in seconds, the served name (else the URI) (#535)
    FILE "-" is standard input.
    """
    parser = argparse.ArgumentParser(prog="model_ids.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("match")
    m.add_argument("--model", required=True)
    m.add_argument("--repo", default="")
    m.add_argument("--models", required=True)
    m.add_argument("--proxy-json")
    m.add_argument("--zrt")
    m.add_argument("--zrt-mode", choices=["user", "system"])
    i = sub.add_parser("ids")
    i.add_argument("--models", required=True)
    n = sub.add_parser("note")
    n.add_argument("--served", default="")
    n.add_argument("--qualified", default="")
    loc = sub.add_parser("local")
    loc.add_argument("--repo", required=True)
    loc.add_argument("--zrt")
    loc.add_argument("--zrt-mode", choices=["user", "system"])
    loc.add_argument("--store")
    loc.add_argument("--revision", default="")
    sh = sub.add_parser("shared")
    sh.add_argument("--repo", required=True)
    sh.add_argument("--store", required=True)
    sh.add_argument("--revision", default="")
    svc = sub.add_parser("services")
    svc.add_argument("--model", required=True)
    svc.add_argument("--repo", default="")
    svc.add_argument("--services", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "services":
        for s in parse_services(_read(args.services)):
            fields = ["1" if service_serves(s, args.model, args.repo or None) else "0", s.pid, s.status or "-",
                      s.endpoint or "-", loopback_api_url(s.endpoint) or "-", str(uptime_seconds(s.uptime)),
                      s.names[1] if len(s.names) > 1 else (s.names[0] if s.names else "-"),
                      # #702: the model URI, which `zrt service stop` takes
                      s.names[0] if s.names else "-"]
            print("\t".join(f.replace("\t", " ") for f in fields))
        return 0
    if args.cmd == "ids":
        print("\n".join(served_ids_from(_json(_read(args.models)))))
        return 0
    if args.cmd == "note":
        print(revision_note(args.served or None, args.qualified or None) or "")
        return 0
    if args.cmd == "shared":
        revisions = shared_revisions(args.repo, Path(args.store))
        known = [r for r in revisions if r != "?"]
        chosen = choose_local(known, split_ref(args.repo)[1], args.revision or None)
        if chosen is None and "?" in revisions and not args.revision:
            chosen = "?"
        if chosen is None:
            return 1
        print(chosen)
        return 0
    if args.cmd == "local":
        revisions = local_revisions(args.repo, _zrt_output(args.zrt, "models", args.zrt_mode),
                                    Path(args.store) if args.store else None)
        chosen = choose_local(revisions, split_ref(args.repo)[1], args.revision or None)
        if chosen is None:
            return 1
        print(chosen)
        return 0
    match = find_served(served_ids_from(_json(_read(args.models))), args.model, args.repo or None)
    if match is None:
        return 1
    revision = match.revision or revision_from_zrt(match.served_id, _json(_read(args.proxy_json)))
    if revision is None and args.zrt:
        revision = revision_from_zrt(match.served_id, services_text=_zrt_output(args.zrt, "services", args.zrt_mode))
    qualified = split_ref(args.repo)[1] if args.repo else None
    print(f"{match.served_id}\n{revision or ''}\n{revision_note(revision, qualified) or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
