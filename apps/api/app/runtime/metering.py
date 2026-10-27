"""Content-free metering of model calls for the telemetry page (W06, ADR-017).

Every call through the runtime adapter is recorded as one `model_calls` row: the task, prompt version, outcome,
duration, the token counts ZRT reports, and the GPU energy measured during the call. No case, actor, text or exact time
is stored; the hour is the only time. Recording never changes the call's result: a recording failure is swallowed.

Energy comes from the host power sampler (infra/telemetry/power_sampler.py): it writes `nvidia-smi` power readings,
one per second, to hourly files `<data_dir>/power/YYYYMMDDTHH.csv` as `epoch_ms,watts`. The reading is the GPU's
reported power draw, not whole-system power. A call without enough samples around it gets no energy value
("not measured"), never an estimate.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

RETENTION_DAYS = 90
MAX_GAP_S = 3.0        # samples further apart than this do not count as a measurement
EDGE_TOLERANCE_S = 2.5  # the first and last sample must be this close to the call's start and end
MAX_TOKEN_COUNT = 2**63 - 1  # SQLite's largest INTEGER


def token_count(value: Any) -> int | None:
    """#605: a token count the runtime reported, when it is a genuine count SQLite can store: an integer (not a
    boolean) from 0 to MAX_TOKEN_COUNT. Anything else (negative, oversized, boolean, fractional or text) is unknown,
    None, never a number that would make the public totals negative or fail the call's record."""
    return value if type(value) is int and 0 <= value <= MAX_TOKEN_COUNT else None


def _hour(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:00:00Z")


def read_power(power_dir: Path, start: float, end: float) -> list[tuple[float, float]]:
    """Power samples (epoch seconds, watts) from start - tolerance to end + tolerance."""
    lo, hi = start - EDGE_TOLERANCE_S, end + EDGE_TOLERANCE_S
    samples: list[tuple[float, float]] = []
    hour = int(lo // 3600) * 3600
    while hour <= hi:
        path = power_dir / (datetime.fromtimestamp(hour, UTC).strftime("%Y%m%dT%H") + ".csv")
        try:
            lines = path.read_text().splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                ms, watts = line.split(",")
                t, w = int(ms) / 1000, float(watts)
            except ValueError:
                continue
            if lo <= t <= hi and 0 <= w < 10_000:
                samples.append((t, w))
        hour += 3600
    return sorted(samples)


def energy_wh(samples: list[tuple[float, float]], start: float, end: float) -> float | None:
    """Trapezoidal energy over [start, end] in watt-hours, or None when the samples do not cover the call."""
    if end <= start or len(samples) < 2:
        return None
    if samples[0][0] > start + EDGE_TOLERANCE_S or samples[-1][0] < end - EDGE_TOLERANCE_S:
        return None
    if any(b[0] - a[0] > MAX_GAP_S for a, b in zip(samples, samples[1:])):
        return None
    # Clip to the call, holding the edge readings flat over the small uncovered margin.
    points = [(start, samples[0][1])] + [(t, w) for t, w in samples if start < t < end] + [(end, samples[-1][1])]
    joules = sum((t2 - t1) * (w1 + w2) / 2 for (t1, w1), (t2, w2) in zip(points, points[1:]))
    return joules / 3600


class MeteredRuntime:
    """Wraps the runtime adapter (mock or ZRT); same interface, plus a content-free record of each model call."""

    def __init__(self, inner: Any, db: Any, mode: str, power_dir: Path):
        self._inner, self._db, self._mode, self._power_dir = inner, db, mode, power_dir
        self._release = os.environ.get("AWARECARE_APP_COMMIT") or None
        # #548: the model calls of this process, newest last, in memory only (task, start and end time, outcome; no
        # case, actor or text), so a presenter's quick flow can show which step the device's model is on.
        self._calls: deque[dict[str, Any]] = deque(maxlen=50)
        self._calls_lock = threading.Lock()

    def recent_calls(self) -> list[dict[str, Any]]:
        """#548: copies of the recent model calls of this process, oldest first: task, started/ended (epoch seconds;
        ended is None while the call runs) and outcome."""
        with self._calls_lock:
            return [dict(c) for c in self._calls]

    @property
    def inner(self) -> Any:
        """The wrapped adapter (mock or ZRT); never a substitute for the other."""
        return self._inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def health(self):
        return await self._inner.health()

    async def manifest(self):
        return await self._inner.manifest()

    async def generate_json(self, task: str, prompt_version: str, input_snapshot: Mapping[str, Any], schema_id: str,
                            timeout_s: float) -> Mapping[str, Any]:
        start, t0 = time.time(), time.perf_counter()
        usage: dict[str, Any] = {}
        outcome = "error"
        call = {"task": task, "started": start, "ended": None, "outcome": None}
        with self._calls_lock:
            self._calls.append(call)
        try:
            if hasattr(self._inner, "generate_json_with_usage"):
                output, usage = await self._inner.generate_json_with_usage(task, prompt_version, input_snapshot,
                                                                           schema_id, timeout_s)
            else:
                output = await self._inner.generate_json(task, prompt_version, input_snapshot, schema_id, timeout_s)
            outcome = "ok"
            return output
        finally:
            with self._calls_lock:
                call["ended"], call["outcome"] = time.time(), outcome
            self._record(task, prompt_version, outcome, start, (time.perf_counter() - t0) * 1000, usage or {})

    def _record(self, task: str, prompt_version: str, outcome: str, start: float, duration_ms: float,
                usage: dict[str, Any]) -> None:
        try:
            end = start + duration_ms / 1000
            samples = read_power(self._power_dir, start, end) if self._mode == "local" else []
            energy = energy_wh(samples, start, end)
            cutoff = (datetime.now(UTC) - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%dT%H:00:00Z")
            with self._db.tx() as conn:
                conn.execute("INSERT INTO model_calls (id, hour, release, mode, task, prompt_version, outcome, "
                             "duration_ms, prompt_tokens, completion_tokens, energy_wh, power_samples) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (str(uuid.uuid4()), _hour(start), self._release, self._mode, task, prompt_version,
                              outcome, round(duration_ms, 1), token_count(usage.get("prompt_tokens")),
                              token_count(usage.get("completion_tokens")), energy,
                              len(samples) if energy is not None else 0))
                conn.execute("DELETE FROM model_calls WHERE hour < ?", (cutoff,))
        except Exception:  # telemetry must never affect a consultation
            pass
