#!/usr/bin/env python3
"""Post-boot recovery check (#170): run once after the device starts, from the deploying user's crontab
(`@reboot`, installed once; see runbook §8). Records how long after boot each piece the demo needs came back:

- the model the current deployment uses, listed by ZRT (local mode only);
- the application's readiness through the gateway;
- both containers running (Docker restarts them: `--restart unless-stopped`);
- the power sampler (its cron keeper starts it) and the GitHub runner.

It also records the listening addresses that are not loopback and whether the clock is synchronised. It writes one
content-free JSON record, private to the user, to `<data root>/evidence/<UTC time>-boot-check.json`. It changes
nothing and never fails the boot. The deploy copies this file to `<data root>/ops/boot_check.py`.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

SCHEMA = "aware-care-boot-check/1"
ROOT = Path.home() / ".local" / "share" / "aware-care-demo"
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def get_json(url: str) -> dict | None:
    try:
        with NO_PROXY.open(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8")) if response.status == 200 else None
    except (OSError, ValueError):
        return None


def run_out(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def same_model(served: str, model: str | None) -> bool:
    """#528: ZRT lists our model by its label or, started without one, by its repository id (any case, any @revision,
    with or without hf:). This file runs on its own (copied to <data_root>/ops), so it compares the model's own name:
    the label is the lower-case repository name (qwen3.6-35b-a3b-fp8 for Qwen/Qwen3.6-35B-A3B-FP8)."""
    if not model:
        return False
    if served == model:
        return True
    def name(ref: str) -> str:
        ref = ref.strip()
        ref = ref[3:] if ref[:3].lower() == "hf:" else ref
        return ref.split("@")[0].rstrip("/").lower()
    return name(served).rsplit("/", 1)[-1] == name(model).rsplit("/", 1)[-1] and (
        "/" not in name(served) or "/" not in name(model) or name(served) == name(model))


def default_probes(current: dict, zrt: str, readiness: str) -> dict[str, Callable[[], bool]]:
    instance = current.get("instance", "aware-care-demo")
    model = current.get("model_id")

    def model_listed() -> bool:
        body = get_json(f"{zrt}/models") or {}
        return any(isinstance(m, dict) and isinstance(m.get("id"), str) and same_model(m["id"], model)
                   for m in body.get("data", []))

    def app_ready() -> bool:
        return (get_json(readiness) or {}).get("readiness") == "ready"

    def containers_running() -> bool:
        out = run_out("docker", "inspect", "-f", "{{.State.Running}}", f"{instance}-api", f"{instance}-web")
        return out.split() == ["true", "true"]

    def processes() -> list[tuple[str, str]]:
        return [tuple((line.split(None, 1) + [""])[:2]) for line in run_out("ps", "-eo", "comm=,args=").splitlines()]

    def sampler_running() -> bool:
        return any(comm == "python3" and "power_sampler.py --out" in args for comm, args in processes())

    def runner_running() -> bool:
        return any(comm.startswith("Runner.Listener") for comm, _ in processes())

    probes = {"app_ready": app_ready, "containers_running": containers_running,
              "power_sampler_running": sampler_running, "runner_running": runner_running}
    if current.get("mode") == "local" and model:
        probes = {"model_listed": model_listed, **probes}
    return probes


def non_loopback_listeners() -> list[str]:
    addresses = {line.split()[3] for line in run_out("ss", "-ltnH").splitlines() if len(line.split()) > 3}
    return sorted(a for a in addresses if not a.startswith(("127.", "[::1]", "[::ffff:127.")))


def clock_synchronised() -> str | None:
    return run_out("timedatectl", "show", "-p", "NTPSynchronized", "--value").strip() or None


def boot_time() -> float:
    return time.time() - float(Path("/proc/uptime").read_text().split()[0])


def run(root: Path, probes: dict[str, Callable[[], bool]], *, booted: float, timeout: float, interval: float,
        extra: Callable[[], dict] = lambda: {}) -> dict:
    """Poll every probe until all pass or `timeout` seconds have passed since boot; return the record."""
    current = json.loads((root / "state" / "current.json").read_text()) if (root / "state" / "current.json").exists() \
        else {}
    first_ok: dict[str, float | None] = {name: None for name in probes}
    while True:
        for name, probe in probes.items():
            if first_ok[name] is None and probe():
                first_ok[name] = round(time.time() - booted, 1)
        if all(v is not None for v in first_ok.values()) or time.time() - booted >= timeout:
            break
        time.sleep(interval)
    missing = sorted(name for name, v in first_ok.items() if v is None)
    record = {"schema": SCHEMA, "booted_at": utc(booted), "checked_at": utc(time.time()),
              "deployment": {k: current.get(k) for k in ("release_tag", "app_commit", "mode", "model_id")},
              "timeout_s": timeout, "seconds_after_boot": first_ok,
              "result": "PASSED" if not missing else "FAILED", "missing": missing, **extra(),
              "note": "Content-free post-boot record (#170). Device clocks may be unsynchronised (#171)."}
    folder = root / "evidence"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    path = folder / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-boot-check.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(record, indent=2) + "\n")
    record["path"] = str(path)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT, help="Data root (default %(default)s)")
    parser.add_argument("--zrt", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--readiness", default="http://127.0.0.1:8180/api/v1/health/ready")
    parser.add_argument("--timeout", type=float, default=1800.0, help="Seconds after boot to wait (default 30 min)")
    parser.add_argument("--interval", type=float, default=10.0)
    args = parser.parse_args()
    state = args.root / "state" / "current.json"
    current = json.loads(state.read_text()) if state.exists() else {}
    record = run(args.root, default_probes(current, args.zrt, args.readiness), booted=boot_time(),
                 timeout=args.timeout, interval=args.interval,
                 extra=lambda: {"non_loopback_listeners": non_loopback_listeners(),
                                "clock_synchronised": clock_synchronised()})
    print(json.dumps({k: record[k] for k in ("result", "missing", "seconds_after_boot", "path")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
