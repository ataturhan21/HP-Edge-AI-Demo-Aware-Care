"""M12 telemetry (W06, ADR-017; R38, R39, R34): content-free aggregates of what the local AI did on this device.

Measured: model calls, the token counts ZRT reported, call and job timings, GPU energy from the host power sampler,
consultation outcomes from content-free events, and busy refusals. Every value is an aggregate over a period; there is
no case, actor, text or exact time. Outcome breakdowns below SUPPRESS_BELOW are withheld (null).

#638 (ADR-017 amendment 6, owner decision of 27 Oct 2026): the page shows the current day live. Every figure counts up
to now: outcome figures (consultations guided, urgent routes, repairs, fail-closed results, busy refusals, AI calls by
task and errored calls, guidance latency) and usage totals (AI calls, tokens, AI time, call timings and energy) count
the same whole hours, from the hour the period starts in up to and including the current hour (event and call times
keep the hour only, #275, so "up to now" is every hour before the next whole hour). Last 24 hours and Last 7 days are
rolling windows ending now; Since this release runs from the release start to now. This replaces the complete-UTC-day
outcome window of #276 (amendment 3) and the complete-hour usage window of #432 (amendment 5). Outcome breakdowns
below SUPPRESS_BELOW stay withheld. #271: every query counts only the running mode's rows.

#398 (ADR-017 amendment 5): per-consultation figures divide usage by consultations from the SAME window: `metered`
sums the AI calls, tokens, AI time and energy of the hours in which the consultations it counts were guided (the
outcome window, from the outcome counting start (#324) and from the first whole metered hour on).

Not measured here, by design: anything about cloud services (no cloud call is ever made to compare) and any healthcare
outcome (R39). The page estimates cloud-equivalent cost from these measurements and the reviewed list prices in
infra/telemetry-pricing.json; the API only reports measurements, prices and assumptions.
"""
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.db import iso, utcnow

PERIODS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "release": None}
SUPPRESS_BELOW = 5
OUTCOME_EVENTS = {"guidance_published": "guided", "guidance_failed": "fail_closed",
                  "guidance_repaired": "repaired", "urgent_interrupt": "urgent_routes",
                  "admission_refused": "busy_refusals"}
SAMPLER_FRESH_S = 15
KNOWN_TASKS = {"guidance", "red_flag_screen", "certainty_review", "concern_check"}


def _release() -> str:
    return os.environ.get("AWARECARE_APP_COMMIT") or "unrecorded"


def record_release_start(db) -> None:
    """The first start of this release on the device, for the "since this release" period."""
    with db.tx() as conn:
        conn.execute("INSERT OR IGNORE INTO telemetry_meta (key, value) VALUES (?, ?)",
                     (f"release_started:{_release()}", iso(utcnow())))


def _hour(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:00:00Z")


def _percentile(values: list[float], q: float) -> float | None:
    """#441: linear interpolation between closest ranks, the definition the ADR-002 qualification (qualify_model.pct)
    and the monthly report (scripts/monitoring.py) use, so the median of an even number of values is the mean of the
    two middle ones (before: Python's round-half-to-even picked the lower or the upper one)."""
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1)


def _suppress(n: int) -> int | None:
    return n if n == 0 or n >= SUPPRESS_BELOW else None


def _read_json(path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _sampler_status(power_dir) -> dict[str, Any]:
    now = time.time()
    path = power_dir / (datetime.fromtimestamp(now, UTC).strftime("%Y%m%dT%H") + ".csv")
    try:
        last = path.read_text().splitlines()[-1]
        age = now - int(last.split(",")[0]) / 1000
    except (OSError, IndexError, ValueError):
        return {"status": "not_running", "last_sample_age_s": None}
    return {"status": "active" if age <= SAMPLER_FRESH_S else "not_running", "last_sample_age_s": round(age, 1)}


def _identity(ctx) -> dict[str, Any]:
    from app.modules.guidance import local
    manifest = ctx.settings.manifest()
    inventory = _read_json(ctx.settings.device_inventory).get("device", {})
    runtime = manifest.get("runtime", {})
    requal = (manifest.get("qualification", {}).get("runtime_requalifications") or [{}])[-1]
    local_mode = ctx.settings.mode == "local"
    return {
        "mode": ctx.settings.mode,
        "app_commit": os.environ.get("AWARECARE_APP_COMMIT") or None,
        "device": inventory.get("product_name"),
        "accelerator": inventory.get("gpu_name"),
        "runtime": (f"ZRT {runtime.get('zrt_version_observed')} ({runtime.get('internal_engine')} "
                    f"{runtime.get('internal_engine_version')})") if local_mode and runtime else None,
        "model_manifest_id": manifest.get("manifest_id") if local_mode else None,
        "prompt_version": local.PROMPT_VERSION if local_mode else None,
        "qualification": {"result": requal.get("result"), "date": requal.get("date"),
                          "reference": requal.get("reference")} if local_mode and requal else None,
    }


def _privacy(ctx) -> dict[str, Any]:
    manifest = ctx.settings.manifest()
    requal = (manifest.get("qualification", {}).get("runtime_requalifications") or [{}])[-1]
    egress = requal.get("egress") or {}
    return {
        "patient_data_sent_off_device_bytes": 0,
        "cloud_inference_calls": 0,
        "basis": ("Architecture: the only model endpoint is ZRT on the device's loopback (ADR-002), with no cloud or "
                  "mock fallback in local mode; the browser loads no third-party script and sends no patient data "
                  "off the device (ADR-014, R34)."),
        # #437: the network check belongs to the local model's qualification; mock mode runs no model, so it is not
        # presented as a measurement of a mock deployment (as identity names no model there).
        "last_verified": {"date": requal.get("date"), "method": egress.get("method"), "samples": egress.get("samples"),
                          "non_loopback": egress.get("non_loopback"), "reference": requal.get("reference")}
                         if egress and ctx.settings.mode == "local" else None,
    }


def _hour_after(dt: datetime) -> str:
    """#638: the end of a window that runs up to now: the whole hour after the one `dt` is in, so the current hour
    (where every event and call of the last minutes is recorded) is counted."""
    return _hour(dt.astimezone(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))


def _next_hour(dt: datetime) -> str:
    """The first whole hour at or after `dt`: model calls before metering began were never recorded, so a
    per-consultation window starts at a whole metered hour."""
    whole = dt.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return _hour(whole if whole == dt else whole + timedelta(hours=1))


def _usage(calls) -> dict[str, Any]:
    """Token, time and energy sums over model-call rows (the same rule for the live totals and the metered window)."""
    with_tokens = [c for c in calls if c["prompt_tokens"] is not None and c["completion_tokens"] is not None]
    with_energy = [c for c in calls if c["energy_wh"] is not None]
    return {
        "ai_calls": len(calls),
        "with_token_counts": len(with_tokens),
        "prompt_tokens": sum(c["prompt_tokens"] for c in with_tokens),
        "completion_tokens": sum(c["completion_tokens"] for c in with_tokens),
        "duration_ms_total": round(sum(c["duration_ms"] for c in calls), 1),
        "calls_with_energy": len(with_energy),
        "wh_total": round(sum(c["energy_wh"] for c in with_energy), 4) if with_energy else None,
    }


def telemetry_snapshot(ctx, period: str) -> dict[str, Any]:
    now = utcnow()
    release = _release()
    mode = ctx.settings.mode
    with ctx.db.read() as conn:
        if period == "release":
            row = conn.execute("SELECT value FROM telemetry_meta WHERE key=?", (f"release_started:{release}",)).fetchone()
            start = datetime.fromisoformat(row["value"].replace("Z", "+00:00")) if row else now
        else:
            start = now - PERIODS[period]
        since = iso(start)
        # #638: one live window for every figure: the whole hours from the period start up to and including the
        # current hour (events and model calls keep the hour only, #275).
        live_lo, live_hi = _hour(start), _hour_after(now)
        out_lo, out_hi = live_lo, live_hi
        # Model calls are metered from the first start of a telemetry release on (ADR-017, #124).
        first = conn.execute("SELECT MIN(value) AS v FROM telemetry_meta WHERE key LIKE 'release_started:%'").fetchone()
        metering_start = datetime.fromisoformat(first["v"].replace("Z", "+00:00")) if first and first["v"] else now
        metered_since = max(start, metering_start)
        # #324: rows written before events recorded the running mode (#271) carry none and are never counted. When the
        # data directory has such rows, outcome counting really starts at the first event that carries a mode (an
        # hour, like every event time), so the page can say so; otherwise it starts with the outcome window.
        legacy = conn.execute("SELECT 1 FROM events WHERE mode IS NULL LIMIT 1").fetchone() is not None
        first_moded = conn.execute("SELECT MIN(ts) FROM events WHERE mode IS NOT NULL").fetchone()[0] if legacy else None
        # Legacy rows but no event with a mode yet: counting starts no later than now.
        counting_since = max(out_lo, first_moded) if first_moded else (_hour(now) if legacy else out_lo)
        # #398: the per-consultation window. Consultations and the AI calls divided by them come from the same whole
        # hours: the outcome window up to now (#638), from the outcome counting start (#324) and from the first whole
        # metered hour (#124) on. Both tables are filtered alike (running mode, no release filter, as the events have
        # none), so no figure divides one window's usage by another window's consultations.
        per_lo = max(out_lo, counting_since, _next_hour(metering_start))
        metered_guided = conn.execute("SELECT COUNT(*) FROM events WHERE kind='guidance_published' AND mode=? "
                                      "AND ts >= ? AND ts < ?", (mode, per_lo, out_hi)).fetchone()[0]
        metered_calls = conn.execute("SELECT * FROM model_calls WHERE mode=? AND hour >= ? AND hour < ?",
                                     (mode, per_lo, out_hi)).fetchall()
        events = {kind: 0 for kind in OUTCOME_EVENTS}
        for r in conn.execute("SELECT kind, COUNT(*) AS n FROM events WHERE mode=? AND ts >= ? AND ts < ? AND kind IN "
                              "(%s) GROUP BY kind" % ",".join("?" * len(OUTCOME_EVENTS)),
                              (mode, out_lo, out_hi, *OUTCOME_EVENTS)):
            events[r["kind"]] = r["n"]
        if period == "release":
            calls = conn.execute("SELECT * FROM model_calls WHERE mode=? AND release IS ? AND hour >= ? AND hour < ?",
                                 (mode, os.environ.get("AWARECARE_APP_COMMIT") or None, live_lo, live_hi)).fetchall()
        else:
            calls = conn.execute("SELECT * FROM model_calls WHERE mode=? AND hour >= ? AND hour < ?",
                                 (mode, live_lo, live_hi)).fetchall()
        # Calls in the outcome window (#638: up to now), for the breakdown by task and the errors.
        day_calls = conn.execute("SELECT task, outcome FROM model_calls WHERE mode=? AND hour >= ? AND hour < ?"
                                 + (" AND release IS ?" if period == "release" else ""),
                                 (mode, out_lo, out_hi)
                                 + ((os.environ.get("AWARECARE_APP_COMMIT") or None,) if period == "release" else ())
                                 ).fetchall()
        # #538: the rule of each rejected attempt of a fail-closed result ("2:third_person@actions[0].rationale" counts
        # as third_person): rule codes only, over the same hours as fail_closed.
        reasons: dict[str, int] = {}
        for r in conn.execute("SELECT error_code FROM events WHERE kind='guidance_rejection' AND mode=? AND ts >= ? "
                              "AND ts < ?", (mode, out_lo, out_hi)):
            rule = (r["error_code"] or "").split(":", 1)[-1].split("@", 1)[0] or "unknown"
            reasons[rule] = reasons.get(rule, 0) + 1
        jobs = conn.execute("SELECT queue_ms, total_ms FROM jobs WHERE kind='guidance' AND status='succeeded' "
                            "AND total_ms IS NOT NULL AND mode=? AND created_at >= ? AND created_at < ?",
                            (mode, out_lo, out_hi)).fetchall()
    ok = [c for c in calls if c["outcome"] == "ok"]
    with_tokens = [c for c in calls if c["prompt_tokens"] is not None and c["completion_tokens"] is not None]
    live = _usage(calls)
    by_task: dict[str, int] = {}
    for c in day_calls:
        task = c["task"] if c["task"] in KNOWN_TASKS else "other"
        by_task[task] = by_task.get(task, 0) + 1
    decode_ms = sum(c["duration_ms"] for c in with_tokens if c["outcome"] == "ok")
    decode_tokens = sum(c["completion_tokens"] for c in with_tokens if c["outcome"] == "ok")
    guided = events["guidance_published"]
    return {
        "generated_at": iso(now),
        "period": {"key": period, "from": since, "to": iso(now),
                   "days": round(max((now - start).total_seconds(), 0) / 86400, 4)},
        "identity": _identity(ctx),
        # #398: `guided` and the usage beside it count the same whole hours [from, to); per-consultation figures divide
        # only these. `since` stays the start of metering within the period, for the live totals.
        "metered": {"since": iso(metered_since), "guided": metered_guided,
                    "from": per_lo if per_lo < out_hi else out_hi, "to": out_hi, **_usage(metered_calls)},
        "consultations": {
            "guided": guided,
            "fail_closed": _suppress(events["guidance_failed"]),
            "fail_closed_reasons": [{"rule": rule, "count": _suppress(n)} for rule, n in sorted(reasons.items())],
            "repaired": _suppress(events["guidance_repaired"]),
            "urgent_routes": _suppress(events["urgent_interrupt"]),
            "busy_refusals": events["admission_refused"],
            "suppressed_below": SUPPRESS_BELOW,
            # #638: the whole hours these outcome figures cover, [counted_from, counted_to); counted_to is the end of
            # the current hour, so the figures run up to now.
            "counted_from": out_lo,
            "counted_to": out_hi,
            # #324: when outcome counting started (mode recording began after the window start).
            "counting_since": counting_since,
        },
        "ai_calls": {
            "total": live["ai_calls"],
            # #638: the whole hours the usage totals count, up to and including the current hour.
            "counted_from": live_lo,
            "counted_to": live_hi,
            "by_task": dict(sorted(by_task.items())),
            "errors": len([c for c in day_calls if c["outcome"] != "ok"]),
            "with_token_counts": live["with_token_counts"],
            "prompt_tokens": live["prompt_tokens"],
            "completion_tokens": live["completion_tokens"],
            "duration_ms_p50": _percentile([c["duration_ms"] for c in ok], 0.5),
            "duration_ms_p95": _percentile([c["duration_ms"] for c in ok], 0.95),
            # Total model time, so a whole-system power assumption can be applied (#127; the Nano reports GPU only).
            "duration_ms_total": live["duration_ms_total"],
            "output_tokens_per_second": round(decode_tokens / (decode_ms / 1000), 1) if decode_ms > 0 else None,
        },
        "latency": {
            "samples": len(jobs),
            "total_ms_p50": _percentile([j["total_ms"] for j in jobs], 0.5),
            "total_ms_p95": _percentile([j["total_ms"] for j in jobs], 0.95),
            "queue_ms_p50": _percentile([j["queue_ms"] for j in jobs if j["queue_ms"] is not None], 0.5),
        },
        "energy": {
            "status": "measured" if live["calls_with_energy"] else "not_measured",
            "source": "nvidia-smi power.draw: the GPU's reported power, not whole-system power",
            "calls_with_energy": live["calls_with_energy"],
            "wh_total": live["wh_total"],
            "sampler": _sampler_status(ctx.settings.data_dir / "power") if ctx.settings.mode == "local"
            else {"status": "not_running", "last_sample_age_s": None},
        },
        "privacy": _privacy(ctx),
        "pricing": _read_json(ctx.settings.telemetry_pricing) or None,
        "outcomes": {"status": "NOT_MEASURED",
                     "note": ("Healthcare outcomes such as avoided visits or staff time are not measured; synthetic "
                              "demo runs are never counted as savings (R39).")},
    }
