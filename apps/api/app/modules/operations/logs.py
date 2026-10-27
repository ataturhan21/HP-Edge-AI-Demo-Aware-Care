"""#548 getLogs: the presenter's debug Logs view (O01), newest first, content-free.

Reads what the service already keeps and adds no new store: the `jobs` table (kind, status, exact times, timings, typed
error code and the #538 rejection reasons), the content-free `events` (sessions, red-flag routing, concern checks, the
demo, guidance outcomes; kept to the hour, #275), the `model_calls` metering rows (task, outcome, duration, tokens;
hour only, ADR-017), the readiness changes this process observed and its recent API error responses (memory only).

Never in a reply: an actor, session or case ID, a token, a cookie, a header, a message, a concern, an answer or any
model text. Only codes, job IDs, statuses, counts and timings. Rows of the hour-only tables keep their hour; within one
hour they keep the order they were written in.

#577: the level, kind and text filters run here over every kept row (the tables keep 30 days of jobs and events and
90 days of model calls), not over the newest few hundred, and a page ends with an opaque `next_before` cursor that
asks for the rows after it ("Load older"). The search looks only at the content-free fields of each row.
"""
from __future__ import annotations

import base64
import binascii
import json
from collections import Counter
from datetime import datetime
from typing import Any

from app.core.db import iso, parse, utcnow
from app.modules.operations import service
from app.modules.operations.reasons import error_reason

LEVELS = ("ok", "warn", "fail", "info")
KINDS = ("job", "model", "guidance", "case", "session", "safety", "concern", "demo", "health", "error")
MAX_LIMIT = 500
MAX_QUERY = 100   # characters of the text search
MAX_CURSOR = 400  # characters of a `before` cursor

# Content-free event names by the kind the Logs view files them under.
EVENT_KINDS = {
    "session_started": "session", "session_rotated": "session", "session_ended": "session",
    "urgent_interrupt": "safety", "concern_screen_deferred": "safety",
    "concern_check_deferred": "concern", "concern_not_health": "concern",
    "guidance_requested": "guidance", "guidance_submit_failed": "guidance", "guidance_failed": "guidance",
    "guidance_rejection": "guidance", "guidance_published": "guidance", "guidance_repaired": "guidance",
    "guidance_level_raised": "guidance",
    "scenario_loaded": "demo", "scenario_prepared": "demo", "scenario_prepare_failed": "demo",
    "reset_requested": "demo", "reset_completed": "demo", "reset_failed": "demo",
    "admission_refused": "job", "job_interrupted": "job",
}
# Events that are worth a look though nothing failed: a retry, a routing, a refusal or a deferred check.
WARN_EVENTS = {"guidance_repaired", "urgent_interrupt", "guidance_level_raised"}


def _text(value: Any, limit: int = 120) -> str | None:
    return None if value is None else str(value)[:limit]


def _entry(*, id: str, at: str, precision: str, level: str, kind: str, source: str, name: str,
           status: str | None = None, code: str | None = None, duration_ms: float | None = None,
           reasons: list[str] | None = None, reason: str | None = None,
           detail: list[tuple[str, Any]] | None = None) -> dict[str, Any]:
    return {"id": id, "at": at, "precision": precision, "level": level, "kind": kind, "source": source,
            "name": name[:80], "status": _text(status, 40), "code": _text(code),
            "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
            "reasons": reasons[:20] if reasons else None, "reason": _text(reason, 1000),
            "detail": [{"label": k, "value": _text(v, 200) or ""} for k, v in (detail or []) if v is not None]}


def _job_level(status: str, code: str | None) -> str:
    if status == "succeeded":
        return "ok"
    if status in {"queued", "running"}:
        return "info"
    if code and code.startswith("RED_FLAG_DESCRIBED"):
        return "warn"  # the device's red-flag screen routed the case: a real result, not a failure
    return "warn" if status in {"stale", "cancelled"} else "fail"


def _jobs(conn) -> list[dict[str, Any]]:
    out = []
    for r in conn.execute("SELECT id, kind, status, error_code, error_detail, created_at, started_at, finished_at, "
                          "queue_ms, inference_ms, validation_ms, total_ms FROM jobs ORDER BY created_at DESC").fetchall():
        at = r["finished_at"] or r["started_at"] or r["created_at"]
        duration = r["total_ms"]
        if duration is None and r["finished_at"]:
            duration = (parse(r["finished_at"]) - parse(r["created_at"])).total_seconds() * 1000
        reasons = json.loads(r["error_detail"]) if r["error_detail"] else None
        code = r["error_code"]
        if code and code.startswith("RED_FLAG_DESCRIBED"):
            code = "RED_FLAG_DESCRIBED"  # #275: the presenter learns that the device routed the case, not the level
        out.append(_entry(
            id=f"job:{r['id']}", at=at, precision="exact", level=_job_level(r["status"], code), kind="job",
            source="job", name=f"{r['kind']} job", status=r["status"], code=code, duration_ms=duration,
            reasons=reasons, reason=error_reason(r["error_code"], reasons) if r["status"] == "failed" else None,
            detail=[("job", r["id"]), ("created", r["created_at"]), ("started", r["started_at"]),
                                     ("finished", r["finished_at"]), ("queue ms", r["queue_ms"]),
                                     ("inference ms", r["inference_ms"]), ("validation ms", r["validation_ms"])]))
    return out


def _events(conn) -> list[dict[str, Any]]:
    out = []
    for r in conn.execute("SELECT rowid AS seq, id, ts, kind, operation_id, status, error_code, duration_ms FROM events "
                          "ORDER BY rowid DESC").fetchall():
        status = r["status"]
        level = ("fail" if status == "failed" else "warn" if status in {"refused", "deferred"} or r["kind"] in WARN_EVENTS
                 else "ok" if status in {"succeeded", "reviewed", "published"} else "info")
        out.append(_entry(
            id=f"event:{r['id']}", at=r["ts"], precision="hour", level=level,
            kind=EVENT_KINDS.get(r["kind"], "case"), source="event", name=r["kind"], status=status,
            code=r["error_code"], duration_ms=r["duration_ms"], detail=[("operation", r["operation_id"])])
            | {"_seq": r["seq"]})
    return out


def _model_calls(conn) -> list[dict[str, Any]]:
    out = []
    for r in conn.execute("SELECT rowid AS seq, id, hour, mode, task, prompt_version, outcome, duration_ms, "
                          "prompt_tokens, completion_tokens, energy_wh FROM model_calls ORDER BY rowid DESC").fetchall():
        out.append(_entry(
            id=f"model:{r['id']}", at=r["hour"], precision="hour", level="ok" if r["outcome"] == "ok" else "fail",
            kind="model", source="model_call", name=r["task"], status=r["outcome"], duration_ms=r["duration_ms"],
            detail=[("prompt", r["prompt_version"]), ("mode", r["mode"]), ("prompt tokens", r["prompt_tokens"]),
                    ("completion tokens", r["completion_tokens"]),
                    ("energy Wh", round(r["energy_wh"], 4) if r["energy_wh"] is not None else None)])
            | {"_seq": r["seq"]})
    return out


def _health(changes, now: str, state: str, mode: str, queued: int, active: int) -> list[dict[str, Any]]:
    tone = {"ready": "ok", "degraded": "warn"}.get
    out = [_entry(id=f"health:{c['at']}", at=c["at"], precision="exact", level=tone(c["readiness"], "fail"),
                  kind="health", source="health", name="readiness changed", status=c["readiness"],
                  detail=[("mode", c["mode"])]) for c in list(changes)]
    out.append(_entry(id=f"health:now:{now}", at=now, precision="exact", level=tone(state, "fail"), kind="health",
                      source="health", name="readiness now", status=state,
                      detail=[("mode", mode), ("queued", queued), ("active", active)]))
    return out


def _api_errors(errors) -> list[dict[str, Any]]:
    items = list(errors)
    return [_entry(id=f"error:{e['request_id'] or i}", at=e["at"], precision="exact",
                   level="fail" if e["status"] >= 500 else "warn", kind="error", source="api_error",
                   name=f"{e['method']} {e['route']}", status=str(e["status"]), code=e["code"],
                   detail=[("request", e["request_id"])])
            | {"_seq": i} for i, e in enumerate(items)]


def _hour_of(at: str) -> str:
    return at[:13]


class BadCursor(ValueError):
    """A `before` value this module did not write."""


def _key(e: dict[str, Any]) -> tuple[str, bool, str, int, str]:
    """Newest first: by hour, then exact times before the hour-only rows of that hour, then the time and the write
    order, then the ID (so every row has its own place and a cursor never skips or repeats one)."""
    return _hour_of(e["at"]), e["precision"] == "exact", e["at"], e.get("_seq", 0), e["id"]


def encode_cursor(key: tuple[str, bool, str, int, str]) -> str:
    raw = json.dumps(list(key), separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(text: str) -> tuple[str, bool, str, int, str]:
    try:
        value = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise BadCursor() from exc
    types = (str, bool, str, int, str)
    if (not isinstance(value, list) or len(value) != 5
            or not all(type(v) is t for v, t in zip(value, types))):  # noqa: E721  (bool is not an int here)
        raise BadCursor()
    return tuple(value)  # type: ignore[return-value]


def _matches(e: dict[str, Any], text: str) -> bool:
    """The Logs view's search: the content-free fields of a row, case-insensitive (the same fields the view shows)."""
    fields = [e["name"], e["status"], e["code"], e["kind"], e["source"], e["reason"], *(e["reasons"] or []),
              *(f"{d['label']} {d['value']}" for d in e["detail"])]
    return any(v and text in v.lower() for v in fields)


def _sources_for(kind: str | None) -> set[str]:
    """The sources that can hold rows of this kind, so a kind filter reads only those tables."""
    if kind is None:
        return {"job", "event", "model_call", "health", "api_error"}
    out = {"job": {"job"}, "model": {"model_call"}, "health": {"health"}, "error": {"api_error"}}.get(kind, set())
    if kind == "job" or kind in EVENT_KINDS.values() or kind == "case":
        out = out | {"event"}
    return out


def logs_snapshot(ctx, *, since: datetime | None, level: str | list[str] | None, kind: str | None, limit: int,
                  q: str | None = None, before: tuple[str, bool, str, int, str] | None = None) -> dict[str, Any]:
    now = iso(utcnow())
    state = service.readiness(ctx)
    queued, active = ctx.jobs.snapshot()
    sources = _sources_for(kind)
    entries: list[dict[str, Any]] = []
    with ctx.db.read() as conn:
        if "job" in sources:
            entries += _jobs(conn)
        if "event" in sources:
            entries += _events(conn)
        if "model_call" in sources:
            entries += _model_calls(conn)
    if "health" in sources:
        entries += _health(ctx.health_changes, now, state, ctx.settings.mode, min(queued, 3), min(active, 1))
    if "api_error" in sources:
        entries += _api_errors(ctx.recent_errors)
    if since is not None:
        floor = iso(since)
        entries = [e for e in entries
                   if (e["at"] >= floor if e["precision"] == "exact" else _hour_of(e["at"]) >= _hour_of(floor))]
    if kind:
        entries = [e for e in entries if e["kind"] == kind]
    text = (q or "").strip().lower()
    if text:
        entries = [e for e in entries if _matches(e, text)]
    # #577: the level chips show how many kept rows of this kind and search each level has, whatever levels are shown.
    counts = Counter(e["level"] for e in entries)
    levels = {level} if isinstance(level, str) else set(level or ())
    if levels:
        entries = [e for e in entries if e["level"] in levels]
    total = len(entries)
    keyed = sorted(((_key(e), e) for e in entries), key=lambda pair: pair[0], reverse=True)
    if before is not None:
        keyed = [pair for pair in keyed if pair[0] < before]
    page = keyed[:limit]
    truncated = len(keyed) > limit
    kept = [e for _, e in page]
    for e in kept:
        e.pop("_seq", None)
    return {"observed_at": now, "mode": ctx.settings.mode, "readiness": state, "queue_depth": min(queued, 3),
            "active_jobs": min(active, 1), "entries": kept, "truncated": truncated,
            "next_before": encode_cursor(page[-1][0]) if truncated else None,
            "level_counts": {lv: counts.get(lv, 0) for lv in LEVELS}, "total": total}
