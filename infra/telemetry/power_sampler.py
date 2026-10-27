#!/usr/bin/env python3
"""Read-only GPU power sampler for the W06 telemetry page (ADR-017). Host-side, standard library only.

Runs `nvidia-smi --query-gpu=power.draw` once per second and appends `epoch_ms,watts` lines to hourly files
`<out>/YYYYMMDDTHH.csv` (UTC), keeping 48 hours. The API reads these files to measure the GPU energy of each model call
(apps/api/app/runtime/metering.py). It only reads the GPU's reported power: it changes no ZRT, driver, CUDA or GPU
setting and needs no privileges.

Kept running by a user crontab line with flock (installed once; see the runbook):
    * * * * * flock -n <data_root>/telemetry/sampler.lock python3 <data_root>/telemetry/power_sampler.py \\
        --out <data_root>/data/local/power >> <data_root>/telemetry/sampler.log 2>&1
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

RETENTION_HOURS = 48


def parse_watts(line: str) -> float | None:
    """One `nvidia-smi --format=csv,noheader,nounits` power line; None for "[N/A]" or anything unexpected."""
    try:
        watts = float(line.strip().split(",")[0])
    except ValueError:
        return None
    return watts if 0 <= watts < 10_000 else None


def hour_file(out: Path, ts: float) -> Path:
    return out / (datetime.fromtimestamp(ts, UTC).strftime("%Y%m%dT%H") + ".csv")


def append(out: Path, ts: float, watts: float) -> None:
    with hour_file(out, ts).open("a") as f:
        f.write(f"{int(ts * 1000)},{watts:.2f}\n")


def prune(out: Path, now: float) -> None:
    oldest = datetime.fromtimestamp(now - RETENTION_HOURS * 3600, UTC).strftime("%Y%m%dT%H")
    for path in out.glob("*.csv"):
        if path.stem < oldest:
            path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--interval-ms", type=int, default=1000)
    ap.add_argument("--nvidia-smi", default="nvidia-smi")
    args = ap.parse_args(argv)
    # #152: the power folder sits inside the API's data directory; whatever this creates (folders and hourly files)
    # is private to this user, whatever the host's umask (the Fury's is 002).
    os.umask(0o077)
    args.out.mkdir(parents=True, exist_ok=True)
    os.chmod(args.out, 0o700)
    prune(args.out, time.time())
    cmd = [args.nvidia_smi, "--query-gpu=power.draw", "--format=csv,noheader,nounits", "-lms", str(args.interval_ms)]
    written = 0
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, bufsize=1) as proc:
        for line in proc.stdout:  # one line per sample; nvidia-smi paces the loop
            watts = parse_watts(line)
            if watts is None:
                continue
            now = time.time()
            append(args.out, now, watts)
            written += 1
            if written % 600 == 0:
                prune(args.out, now)
    print(f"{datetime.now(UTC).isoformat()} nvidia-smi exited ({proc.returncode}) after {written} samples",
          file=sys.stderr)
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
