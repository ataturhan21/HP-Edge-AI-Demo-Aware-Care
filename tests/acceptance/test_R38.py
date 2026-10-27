"""R38 measured performance and failures, content-free: the W06 telemetry capture and aggregates (ADR-017). M12.

Local mode with the scripted model, wrapped by the real metering layer. Token counts come from a stand-in for the
`usage` ZRT reports; GPU power from stand-in sampler files (infra/telemetry/power_sampler.py writes the same format).
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import NO_RED_FLAGS, ROOT, Api, validate

REQUIREMENT = "R38"


class UsageModel:
    """The scripted LocalModel, reporting token usage like the ZRT adapter."""

    def __init__(self, model, prompt_tokens=2000, completion_tokens=600, fail=None):
        self.model, self.prompt_tokens, self.completion_tokens, self.fail = model, prompt_tokens, completion_tokens, fail

    async def generate_json_with_usage(self, task, prompt_version, snapshot, schema_id, timeout_s):
        if self.fail:
            raise self.fail
        out = await self.model.generate_json(task, prompt_version, snapshot, schema_id, timeout_s)
        return out, {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens}

    async def generate_json(self, *args):
        return (await self.generate_json_with_usage(*args))[0]

    async def health(self):
        return await self.model.health()

    async def manifest(self):
        return await self.model.manifest()


def write_power(power_dir: Path, watts=40.0, span_s=600):
    from datetime import UTC, datetime
    power_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for t in range(int(now) - 60, int(now) + span_s):
        name = datetime.fromtimestamp(t, UTC).strftime("%Y%m%dT%H") + ".csv"
        with (power_dir / name).open("a") as f:
            f.write(f"{t * 1000},{watts}\n")


def day_hour(days_ago: int, hour: int = 12) -> str:
    from datetime import UTC, datetime, timedelta
    return (datetime.now(UTC) - timedelta(days=days_ago)).strftime(f"%Y-%m-%dT{hour:02d}:00:00Z")


def as_yesterday(ctx) -> None:
    """Moves the activity recorded so far to noon yesterday (and the metering start to two days ago), as if it had
    happened then: for checks of the metered window (#124), which starts at the first whole metered hour."""
    yesterday = day_hour(1)
    with ctx.db.tx() as conn:
        conn.execute("UPDATE events SET ts=?", (yesterday,))
        conn.execute("UPDATE model_calls SET hour=?", (yesterday,))
        conn.execute("UPDATE jobs SET created_at=?", (yesterday,))
        conn.execute("UPDATE telemetry_meta SET value=? WHERE key LIKE 'release_started:%'", (day_hour(2),))


def metered(local, power=True, **usage):
    from app.runtime.metering import MeteredRuntime
    api, model, application = local
    ctx = application.state.ctx
    power_dir = ctx.settings.data_dir / "power"
    if power:
        write_power(power_dir)
    ctx.runtime = MeteredRuntime(UsageModel(model, **usage), ctx.db, "local", power_dir)
    return api, model, application


def test_each_model_call_is_metered_content_free_with_tokens_and_energy(local):
    from conftest import NO_RED_FLAGS
    api, model, application = metered(local)
    case = api.new_case("UNIQUE-SENTINEL-CONCERN about headaches.", context=[NO_RED_FLAGS])
    assert api.to_guided(case["id"])["status"] == "succeeded"
    calls = [c for c in model.calls]
    # #638: the page shows the current day live, so the consultation and its calls count at once.
    t = api.ok("GET", "/telemetry?period=24h", 200, "TelemetrySnapshot")
    assert t["ai_calls"]["total"] == len(calls)
    assert t["ai_calls"]["prompt_tokens"] == 2000 * len(calls) and t["ai_calls"]["completion_tokens"] == 600 * len(calls)
    assert t["energy"]["status"] == "measured" and t["energy"]["calls_with_energy"] == len(calls)
    assert t["energy"]["wh_total"] >= 0
    t7 = api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")
    assert t7["consultations"]["guided"] == 1 and t7["ai_calls"]["errors"] == 0
    assert t7["ai_calls"]["by_task"]["guidance"] == len([c for c in calls if c["task"] == "guidance"])
    assert t7["ai_calls"]["by_task"]["red_flag_screen"] == 2  # #153: the concern at creation, then before guidance
    # #271: the concern check (#154) is a task of its own, not "other".
    assert t7["ai_calls"]["by_task"]["concern_check"] == 1 and "other" not in t7["ai_calls"]["by_task"]
    assert t["identity"]["mode"] == "local" and t["identity"]["prompt_version"] == "guidance-local-5"
    text = str(t)
    assert "UNIQUE-SENTINEL" not in text and case["id"] not in text
    with application.state.ctx.db.read() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(model_calls)")]
        rows = conn.execute("SELECT * FROM model_calls").fetchall()
    assert not {"case_id", "actor_id", "text", "concern"} & set(cols)
    # #127: the total AI time (for a whole-system power assumption) is the sum of the recorded call durations.
    assert t["ai_calls"]["duration_ms_total"] == round(sum(r["duration_ms"] for r in rows), 1)
    assert all(r["hour"].endswith(":00:00Z") for r in rows)
    assert "UNIQUE-SENTINEL" not in repr([tuple(r) for r in rows])


def test_without_power_samples_energy_is_not_measured_never_estimated(local):
    from conftest import NO_RED_FLAGS
    api, _, application = metered(local, power=False)
    case = api.new_case(context=[NO_RED_FLAGS])
    assert api.to_guided(case["id"])["status"] == "succeeded"
    t = api.ok("GET", "/telemetry?period=24h", 200, "TelemetrySnapshot")
    assert t["ai_calls"]["total"] > 0
    assert t["energy"]["status"] == "not_measured" and t["energy"]["wh_total"] is None
    assert t["energy"]["sampler"]["status"] == "not_running"


def test_failures_repairs_and_busy_refusals_are_counted_separately(local):
    from app.core.errors import ApiError
    from conftest import NO_RED_FLAGS
    api, model, application = metered(local)
    ctx = application.state.ctx
    # A repaired publication: the first draft lacks a possible explanation (ADR-015), the repair succeeds.
    first = model.draft({"case": {"reviewed_urgency_decision": "self_care_candidate",
                                  "confirmed_facts": [{"id": "11111111-1111-4111-8111-111111111111", "answer": "a"}]}})
    model.outputs = [{**first, "claims": []}]
    case = api.new_case(context=[NO_RED_FLAGS])
    assert api.to_guided(case["id"])["status"] == "succeeded"
    # A transport failure: the call is counted as an error, and the case fails closed.
    ctx.runtime._inner.fail = RuntimeError("zrt down")
    other = api.new_case(context=[NO_RED_FLAGS])
    assert api.to_guided(other["id"])["status"] == "failed"
    ctx.runtime._inner.fail = None
    # A busy refusal (429) is counted, never hidden.
    def busy():
        raise ApiError(429, "QUEUE_FULL", "busy", retryable=True)
    ctx.jobs.admit_generation = busy
    third = api.new_case(context=[NO_RED_FLAGS])
    api.answer_all(third["id"])
    rev = api.case(third["id"])["case"]["revision"]
    api.ok("POST", f"/cases/{third['id']}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    assert api.req("POST", f"/cases/{third['id']}/guidance", key=True, json={"expected_revision": rev}).status_code == 429
    t = api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")
    assert t["consultations"]["guided"] == 1 and t["consultations"]["busy_refusals"] == 1
    assert t["ai_calls"]["errors"] >= 1
    # Breakdowns below 5 are withheld, but the events exist.
    assert t["consultations"]["repaired"] is None and t["consultations"]["fail_closed"] is None
    with ctx.db.read() as conn:
        kinds = {r["kind"] for r in conn.execute("SELECT kind FROM events")}
    assert {"guidance_repaired", "guidance_failed", "admission_refused"} <= kinds


def test_the_telemetry_read_is_public_no_store_and_validates_the_period(api):
    r = api.req("GET", "/telemetry")  # no session
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["period"]["key"] == "7d" and r.json()["identity"]["mode"] == "mock"
    assert r.json()["identity"]["model_manifest_id"] is None  # mock mode claims no model
    for period in ("24h", "7d", "release"):
        api.ok("GET", f"/telemetry?period={period}", 200, "TelemetrySnapshot")
    assert api.req("GET", "/telemetry?period=30d").status_code == 422


def test_since_this_release_counts_only_this_releases_calls(local, monkeypatch):
    from app.runtime.metering import MeteredRuntime
    from conftest import NO_RED_FLAGS
    api, model, application = metered(local)
    ctx = application.state.ctx
    monkeypatch.setenv("AWARECARE_APP_COMMIT", "previous-release")
    ctx.runtime = MeteredRuntime(ctx.runtime._inner, ctx.db, "local", ctx.settings.data_dir / "power")
    assert api.to_guided(api.new_case(context=[NO_RED_FLAGS])["id"])["status"] == "succeeded"
    monkeypatch.setenv("AWARECARE_APP_COMMIT", "this-release")
    from app.modules.operations.telemetry import record_release_start
    record_release_start(ctx.db)
    t = api.ok("GET", "/telemetry?period=release", 200, "TelemetrySnapshot")
    assert t["ai_calls"]["total"] == 0 and t["identity"]["app_commit"] == "this-release"
    assert api.ok("GET", "/telemetry?period=24h", 200, "TelemetrySnapshot")["ai_calls"]["total"] > 0


def test_per_consultation_figures_use_only_the_metered_window(local):
    """#124: consultations from before metering began (earlier releases) are counted as volume, but tokens and energy
    are only divided by the consultations guided since metering began."""
    import uuid
    from conftest import NO_RED_FLAGS
    api, model, application = metered(local)
    assert api.to_guided(api.new_case(context=[NO_RED_FLAGS])["id"])["status"] == "succeeded"
    as_yesterday(application.state.ctx)  # metering began two days ago; this consultation was guided yesterday
    earlier = day_hour(3)
    with application.state.ctx.db.tx() as conn:
        for _ in range(6):  # published by a release without telemetry: events exist, model calls do not
            conn.execute("INSERT INTO events (id, ts, kind, operation_id, status, mode) VALUES (?,?,?,?,?,?)",
                         (str(uuid.uuid4()), earlier, "guidance_published", "generateGuidance", "succeeded", "local"))
    t = api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")
    assert t["consultations"]["guided"] == 7
    assert t["metered"]["guided"] == 1 and t["metered"]["since"] > t["period"]["from"]


def test_the_fury_files_give_the_fury_identity_model_and_prices(tmp_path, monkeypatch):
    """ADR-018: the ZGX Fury's deploy configuration selects its own manifest, inventory and prices; the snapshot names
    the Fury, its qualified model and its like-for-like reference, and still validates against the contract."""
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.config import load_settings
    from app.main import create_app
    from conftest import ROOT, Api, LocalModel
    for name, file in (("AWARECARE_MODEL_MANIFEST", "model-manifest.json"),
                       ("AWARECARE_DEVICE_INVENTORY", "device-inventory.json"),
                       ("AWARECARE_TELEMETRY_PRICING", "telemetry-pricing.json")):
        monkeypatch.setenv(name, str(ROOT / "infra/fury" / file))
    settings = replace(load_settings(), mode="local", model_id="qwen3.8-flash-next-fp8", data_dir=tmp_path / "local")
    application = create_app(settings)
    with TestClient(application) as client:
        application.state.ctx.runtime = LocalModel()
        snap = Api(client).ok("GET", "/telemetry", 200, "TelemetrySnapshot")
    assert snap["identity"]["device"] == "HP ZGX Fury" and snap["identity"]["accelerator"] == "NVIDIA GB300"
    assert snap["identity"]["model_manifest_id"] == "qwen3.8-flash-next-fp8@236dfdf2-2026-10-17"
    assert snap["identity"]["qualification"]["result"] == "PASSED"
    reference = snap["pricing"]["cloud_references"][0]
    assert reference["model"] == "qwen3.8-flash" and reference["comparison"] == "like_for_like"
    assert snap["pricing"]["assumptions"]["device_price_usd"]["value"] == 100000


# #638 (ADR-017 amendment 6): the page shows the current day live; every window runs up to now.

def test_638_a_consultation_guided_in_the_current_hour_is_counted_at_once(local):
    """Before #638 a consultation guided today counted only after 00:00 UTC (#276) and its AI calls only after the hour
    had ended (#432). Now every period runs up to now, including the current hour, for outcomes and usage alike."""
    from datetime import UTC, datetime, timedelta
    from conftest import NO_RED_FLAGS, red_flags
    api, model, application = metered(local)
    periods = ("24h", "7d", "release")
    before = {p: api.ok("GET", f"/telemetry?period={p}", 200, "TelemetrySnapshot") for p in periods}
    case = api.new_case(context=[NO_RED_FLAGS])
    assert api.to_guided(case["id"])["status"] == "succeeded"
    api.new_case(context=[red_flags("RF04")])  # an urgent route, this hour
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    for period in periods:
        t = api.ok("GET", f"/telemetry?period={period}", 200, "TelemetrySnapshot")
        c, a = t["consultations"], t["ai_calls"]
        assert c["guided"] == before[period]["consultations"]["guided"] + 1, period
        assert c["urgent_routes"] is None, period  # one urgent route: below the threshold, withheld
        assert t["latency"]["samples"] == 1 and a["by_task"]["guidance"] >= 1, period
        assert a["total"] == len(model.calls) > before[period]["ai_calls"]["total"], period
        assert a["prompt_tokens"] > before[period]["ai_calls"]["prompt_tokens"], period
        # One window for outcomes and usage: from the period start's hour up to the end of the current hour.
        assert c["counted_to"] == a["counted_to"] == (hour + timedelta(hours=1)).strftime(fmt), period
        assert c["counted_from"] == a["counted_from"], period
    t24, t7 = (api.ok("GET", f"/telemetry?period={p}", 200, "TelemetrySnapshot")["consultations"] for p in ("24h", "7d"))
    assert t24["counted_from"] == (hour - timedelta(hours=24)).strftime(fmt)  # rolling windows ending now
    assert t7["counted_from"] == (hour - timedelta(days=7)).strftime(fmt)


def test_638_activity_outside_the_rolling_window_is_not_counted(local):
    """Last 24 hours is a rolling window: a consultation 2 days ago counts in Last 7 days but not in Last 24 hours."""
    api, _, application = metered(local, power=False)
    with application.state.ctx.db.tx() as conn:
        _consultation(conn, day_hour(2))
        _consultation(conn, day_hour(8))  # outside both windows
    assert api.ok("GET", "/telemetry?period=24h", 200, "TelemetrySnapshot")["consultations"]["guided"] == 0
    t7 = api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")
    assert t7["consultations"]["guided"] == 1 and t7["ai_calls"]["total"] == 1


def test_small_outcome_counts_stay_suppressed_in_daily_buckets(local):
    import uuid
    api, _, application = metered(local)

    def add(n, ts):
        with application.state.ctx.db.tx() as conn:
            for _ in range(n):
                conn.execute("INSERT INTO events (id, ts, kind, operation_id, status, mode) VALUES (?,?,?,?,?,?)",
                             (str(uuid.uuid4()), ts, "urgent_interrupt", "createCase", "urgent", "local"))
    add(4, day_hour(1))
    assert api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")["consultations"]["urgent_routes"] is None
    add(1, day_hour(2))
    assert api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")["consultations"]["urgent_routes"] == 5


# #271: telemetry counts only the running mode; the concern check is a known task.

def test_telemetry_counts_only_the_running_modes_activity(local, app):
    import uuid
    api, model, application = metered(local)
    with application.state.ctx.db.tx() as conn:  # mock activity in a shared data directory, recorded yesterday
        for kind in ("guidance_published", "urgent_interrupt", "admission_refused"):
            for _ in range(6):
                conn.execute("INSERT INTO events (id, ts, kind, operation_id, status, mode) VALUES (?,?,?,?,?,?)",
                             (str(uuid.uuid4()), day_hour(1), kind, "x", "succeeded", "mock"))
        for _ in range(6):
            conn.execute("INSERT INTO model_calls (id, hour, release, mode, task, prompt_version, outcome, "
                         "duration_ms, prompt_tokens, completion_tokens) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (str(uuid.uuid4()), day_hour(0, 0), None, "mock", "guidance", "guidance-mock-1", "ok", 5.0,
                          100, 10))
    t = api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")
    assert t["consultations"]["guided"] == 0 and t["consultations"]["busy_refusals"] == 0
    assert t["consultations"]["urgent_routes"] == 0 and t["ai_calls"]["total"] == 0
    assert t["ai_calls"]["prompt_tokens"] == 0
    # Every new event and job records the mode it ran in.
    from conftest import NO_RED_FLAGS
    api.to_guided(api.new_case(context=[NO_RED_FLAGS])["id"])
    with application.state.ctx.db.read() as conn:
        assert {r[0] for r in conn.execute("SELECT DISTINCT mode FROM events WHERE kind != 'x' AND "
                                           "operation_id != 'x'")} == {"local"}
        assert {r[0] for r in conn.execute("SELECT DISTINCT mode FROM jobs")} == {"local"}
    # The mock app (its own data directory) records "mock".
    mock_api = __import__("conftest").Api(app[1])
    mock_api.start()
    mock_api.new_case()
    with app[0].state.ctx.db.read() as conn:
        assert {r[0] for r in conn.execute("SELECT DISTINCT mode FROM events")} == {"mock"}


def test_concern_check_is_a_known_task():
    from app.modules.operations.telemetry import KNOWN_TASKS
    from app.modules.cases.concern_check import TASK
    assert TASK in KNOWN_TASKS


# #324: the snapshot names when outcome counting started, so the page can say that events written before the device
# recorded the running mode (#271) are not counted.

def _legacy_event(conn, ts, mode=None, kind="guidance_published"):
    import uuid
    conn.execute("INSERT INTO events (id, ts, kind, operation_id, status, mode) VALUES (?,?,?,?,?,?)",
                 (str(uuid.uuid4()), ts, kind, "generateGuidance", "succeeded", mode))


def test_outcome_counting_start_is_the_window_start_without_unrecorded_events(local):
    api, _, application = metered(local)
    with application.state.ctx.db.tx() as conn:
        _legacy_event(conn, day_hour(3), "local")
    for period in ("24h", "7d", "release"):
        c = api.ok("GET", f"/telemetry?period={period}", 200, "TelemetrySnapshot")["consultations"]
        assert c["counting_since"] == c["counted_from"], period


def test_outcome_counting_start_names_when_mode_recording_began(local):
    """Events from before mode recording (mode null) exist; the first event with a mode is three days ago at 13:00, so
    the 7-day window counts from then, and the 24-hour window (yesterday) from its own start."""
    api, _, application = metered(local)
    with application.state.ctx.db.tx() as conn:
        for _ in range(3):
            _legacy_event(conn, day_hour(5))  # written before the mode was recorded: never counted
        _legacy_event(conn, day_hour(3, 13), "local")
        _legacy_event(conn, day_hour(1, 9), "local")
    t7 = api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")["consultations"]
    assert t7["counting_since"] == day_hour(3, 13) > t7["counted_from"]
    assert t7["guided"] == 2  # the unrecorded events stay uncounted (ADR-017 amendment 3, unchanged)
    t24 = api.ok("GET", "/telemetry?period=24h", 200, "TelemetrySnapshot")["consultations"]
    assert t24["counting_since"] == t24["counted_from"]


def test_outcome_counting_start_may_be_today(local):
    """The deployed case of 2026-10-20: mode recording began at 00:00 today. #638: the window runs up to now, so the
    consultations since then count at once."""
    api, _, application = metered(local)
    with application.state.ctx.db.tx() as conn:
        _legacy_event(conn, day_hour(1))
        _legacy_event(conn, day_hour(0, 0), "local")
    c = api.ok("GET", "/telemetry?period=24h", 200, "TelemetrySnapshot")["consultations"]
    assert c["counting_since"] == day_hour(0, 0) < c["counted_to"]
    assert c["guided"] == 1
    with application.state.ctx.db.tx() as conn:
        conn.execute("DELETE FROM events WHERE mode IS NOT NULL")
    c = api.ok("GET", "/telemetry?period=24h", 200, "TelemetrySnapshot")["consultations"]
    assert c["counted_from"] < c["counting_since"] < c["counted_to"]  # no event with a mode yet: counting starts now


# QA of 2026-10-22 (v0.14.0-demo.1): T-01 (#398), T-13 (#441), S-03 (#432), T-04 (#437).

def _consultation(conn, hour, calls=1, prompt=10_000, completion=1_000, wh=0.5, ms=10_000.0, mode="local"):
    """One guided consultation in `hour` with its AI calls (content-free rows, as the app writes them). An event
    written before the device recorded the mode (#271) has none (`mode=None`); model calls always had one."""
    import uuid
    conn.execute("INSERT INTO events (id, ts, kind, operation_id, status, mode) VALUES (?,?,?,?,?,?)",
                 (str(uuid.uuid4()), hour, "guidance_published", "generateGuidance", "succeeded", mode))
    for _ in range(calls):
        conn.execute("INSERT INTO model_calls (id, hour, release, mode, task, prompt_version, outcome, duration_ms, "
                     "prompt_tokens, completion_tokens, energy_wh, power_samples) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (str(uuid.uuid4()), hour, None, "local", "guidance", "guidance-local-4", "ok", ms, prompt,
                      completion, wh, 10))


def _metering_since(ctx, value: str) -> None:
    with ctx.db.tx() as conn:
        conn.execute("UPDATE telemetry_meta SET value=? WHERE key LIKE 'release_started:%'", (value,))


def test_per_consultation_usage_divides_by_consultations_from_the_same_window(local):
    """#398 (T-01): four consultations, two yesterday and two this hour, each with one AI call of 10,000 in / 1,000 out
    / 0.5 Wh / 10 s; plus one AI call two weeks ago, outside the window. Per consultation it is 10,000 / 1,000 / 0.5 Wh
    / 10 s: the consultations and the calls divided by them come from the same hours, up to now (#638)."""
    import uuid
    from datetime import UTC, datetime
    api, _, application = metered(local, power=False)
    ctx = application.state.ctx
    _metering_since(ctx, day_hour(20))
    now_hour = datetime.now(UTC).strftime("%Y-%m-%dT%H:00:00Z")
    with ctx.db.tx() as conn:
        for hour in (day_hour(1, 10), day_hour(1, 15), now_hour, now_hour):
            _consultation(conn, hour)
        conn.execute("INSERT INTO model_calls (id, hour, release, mode, task, prompt_version, outcome, duration_ms, "
                     "prompt_tokens, completion_tokens) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (str(uuid.uuid4()), day_hour(14), None, "local", "guidance", "guidance-local-4", "ok", 9.0,
                      99_999, 9_999))
    t = api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")
    m = t["metered"]
    assert (m["guided"], m["ai_calls"]) == (4, 4)
    assert (m["prompt_tokens"] / m["guided"], m["completion_tokens"] / m["guided"]) == (10_000, 1_000)
    assert (m["wh_total"] / m["guided"], m["duration_ms_total"] / m["guided"]) == (0.5, 10_000)
    # One window for both, named: the outcome window up to now, from the first metered hour on.
    assert (m["from"], m["to"]) == (t["consultations"]["counted_from"], t["consultations"]["counted_to"])
    assert m["with_token_counts"] == m["calls_with_energy"] == 4


def test_the_per_consultation_window_starts_with_outcome_counting_and_the_first_metered_hour(local):
    """#398: consultations before the outcome counting start (#324: events without a mode) are never counted, so their
    AI calls are not divided by the counted ones; and an hour in which metering began part-way is left out, because
    its consultations may have had calls that were never metered."""
    api, _, application = metered(local, power=False)
    ctx = application.state.ctx
    _metering_since(ctx, day_hour(6))
    with ctx.db.tx() as conn:
        _consultation(conn, day_hour(4), calls=3, mode=None)  # before the mode was recorded: never counted
        _consultation(conn, day_hour(3, 13))  # the first event with a mode: counting starts here
        _consultation(conn, day_hour(2, 9))
    t = api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")
    m = t["metered"]
    assert t["consultations"]["counting_since"] == m["from"] == day_hour(3, 13)
    assert (m["guided"], m["ai_calls"], m["prompt_tokens"]) == (2, 2, 20_000)  # before: 5 calls over 2 consultations
    # Metering began at 10:30 two days ago: the 10:00 hour is left out on both sides.
    _metering_since(ctx, day_hour(2, 10).replace(":00:00Z", ":30:00.000000Z"))
    with ctx.db.tx() as conn:
        conn.execute("DELETE FROM events WHERE mode IS NULL")
        _consultation(conn, day_hour(2, 10))
        _consultation(conn, day_hour(2, 11))
    m = api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")["metered"]
    assert m["from"] == day_hour(2, 11)
    assert (m["guided"], m["ai_calls"]) == (1, 1)


def test_638_the_live_totals_move_with_each_call(local):
    """#432 held usage totals back to complete hours so polling could not tell an urgent route (one AI call) from a
    routine concern (two). #638 (owner decision, 27 Oct 2026): the page is live, so every call counts at once."""
    from conftest import NO_RED_FLAGS
    api, model, _ = metered(local)

    def total():
        return api.ok("GET", "/telemetry?period=24h", 200, "TelemetrySnapshot")["ai_calls"]["total"]
    seen = []
    for screen in ({"present": []}, {"present": ["RF19"]}):
        model.screen, calls, before = screen, len(model.calls), total()
        api.new_case("Synthetic QA concern.", context=[NO_RED_FLAGS])
        seen.append(total() - before)
        assert seen[-1] == len(model.calls) - calls
    assert seen == [2, 1]


def test_the_median_of_an_even_number_of_values_is_the_mean_of_the_middle_two(local):
    """#441 (T-13): two guidance jobs of 10 s and 30 s have a median of 20 s (before: 10 s). Percentiles interpolate
    linearly between closest ranks, as the ADR-002 qualification and the monthly report do."""
    import uuid
    from app.modules.operations.telemetry import _percentile
    assert _percentile([1000, 2000], 0.5) == 1500
    assert _percentile([1000, 2000, 3000, 4000], 0.5) == 2500
    assert _percentile([1000 * i for i in range(1, 7)], 0.5) == 3500
    assert _percentile([1000 * i for i in range(1, 9)], 0.5) == 4500
    assert _percentile([1000, 2000, 3000], 0.5) == 2000 and _percentile([7.0], 0.95) == 7.0
    assert _percentile([10_000, 30_000], 0.95) == 29_000 and _percentile([], 0.5) is None
    api, _, application = metered(local)
    with application.state.ctx.db.tx() as conn:
        for total in (10_000.0, 30_000.0):
            conn.execute("INSERT INTO jobs (id, actor_id, kind, status, created_at, queue_ms, total_ms, mode) "
                         "VALUES (?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), "a", "guidance", "succeeded",
                                                      day_hour(1), 2.0, total, "local"))
    latency = api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")["latency"]
    assert (latency["samples"], latency["total_ms_p50"], latency["queue_ms_p50"]) == (2, 20_000, 2.0)


def test_mock_mode_presents_no_network_check_of_a_model(api):
    """#437 (T-04): the network check belongs to the local model's qualification; mock mode runs no model, so the
    snapshot gives none (as it names no model or qualification there)."""
    t = api.ok("GET", "/telemetry", 200, "TelemetrySnapshot")
    assert t["identity"]["mode"] == "mock" and t["identity"]["qualification"] is None
    assert t["privacy"]["last_verified"] is None
# --- #397 (S-01, QA 2026-10-22): the concern screens of createCase and editCase pass central admission --------------
# QA (local mode, a fake ZRT taking 3 s per call): 12 and 30 concurrent createCase from ONE guest session all got 201
# with 12 and 30 model calls in flight; 80 held the 40 worker threads and another user's GET took 11.8 s.

FLOOD_CONCERN = "Synthetic QA concurrency case {}: mild headache."


class CountingModel:
    """The scripted LocalModel, counting concurrent model calls; each call waits for `gate` (open by default) and then
    takes `delay` seconds, like a busy runtime."""

    def __init__(self, model, delay: float = 0.0):
        self.model, self.delay = model, delay
        self.gate = threading.Event()
        self.gate.set()
        self.lock = threading.Lock()
        self.inflight = self.peak = 0

    async def generate_json(self, *args):
        with self.lock:
            self.inflight += 1
            self.peak = max(self.peak, self.inflight)
        try:
            self.gate.wait(10)
            time.sleep(self.delay)
            return await self.model.generate_json(*args)
        finally:
            with self.lock:
                self.inflight -= 1

    async def health(self):
        return await self.model.health()

    async def manifest(self):
        return await self.model.manifest()


def _create(api, i, key: str | None = None):
    headers = {"Idempotency-Key": key} if key else None
    return api.req("POST", "/cases", key=key is None, headers=headers,
                   json={"concern": FLOOD_CONCERN.format(i), "confirmed_context": [NO_RED_FLAGS]})


def _until(predicate, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, "condition not reached"
        time.sleep(0.01)


def _assert_busy(r) -> None:
    assert r.status_code == 429, (r.status_code, r.text)
    body = r.json()
    validate("Error", body)
    assert body["code"] == "QUEUE_FULL" and body["retryable"] is True and r.headers["Retry-After"] == "5"


def test_397_one_sessions_flood_is_refused_with_429_and_other_users_reads_stay_responsive(local):
    api, model, application = local
    ctx = application.state.ctx
    counting = ctx.runtime = CountingModel(model, delay=0.4)
    bystander = Api(TestClient(application))
    bystander.start()
    case = bystander.new_case("Synthetic QA bystander: sore throat.", context=[NO_RED_FLAGS])
    latencies, stop = [], threading.Event()

    def probe():
        while not stop.is_set():
            t0 = time.time()
            assert bystander.req("GET", f"/cases/{case['id']}").status_code == 200
            latencies.append(time.time() - t0)
            time.sleep(0.05)

    reader = threading.Thread(target=probe)
    reader.start()
    try:
        with ThreadPoolExecutor(max_workers=40) as pool:
            results = list(pool.map(lambda i: _create(api, i), range(40)))
    finally:
        stop.set()
        reader.join()
    created = [r for r in results if r.status_code == 201]
    refused = [r for r in results if r.status_code != 201]
    assert created and refused, [r.status_code for r in results]
    for r in refused:
        _assert_busy(r)
    assert counting.peak == 1, f"{counting.peak} model calls ran at once"
    assert max(latencies) < 1.0, f"a plain read took {max(latencies):.2f} s during the flood"
    with ctx.db.read() as conn:
        owned = conn.execute("SELECT COUNT(*) FROM cases WHERE actor_id=?", (created[0].json()["actor_id"],))
        assert owned.fetchone()[0] == len(created)
        refusals = conn.execute("SELECT COUNT(*) FROM events WHERE kind='admission_refused' AND "
                                "operation_id='createCase'").fetchone()[0]
    assert refusals == len(refused)  # counted for the telemetry page's busy refusals (ADR-017)


def test_397_distinct_sessions_queue_one_active_and_three_waiting_and_a_fifth_is_refused(local):
    api, model, application = local
    ctx = application.state.ctx
    counting = ctx.runtime = CountingModel(model)
    counting.gate.clear()
    sessions = [api] + [Api(TestClient(application)) for _ in range(4)]
    for s in sessions[1:]:
        s.start()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_create, s, i) for i, s in enumerate(sessions[:4])]
        _until(lambda: ctx.jobs.screening_snapshot()[0] == 4)
        _assert_busy(_create(sessions[4], 4))  # the lane is full: refused at once, nothing created
        counting.gate.set()
        assert [f.result().status_code for f in futures] == [201] * 4
    assert counting.peak == 1
    assert _create(sessions[4], 5).status_code == 201  # capacity is back


def test_397_a_duplicate_of_a_creation_in_the_lane_waits_and_replays_it(local):
    import uuid
    api, model, application = local
    ctx = application.state.ctx
    counting = ctx.runtime = CountingModel(model)
    counting.gate.clear()
    key = str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(_create, api, 0, key)
        _until(lambda: ctx.jobs.screening_snapshot()[0] == 1)
        duplicates = [pool.submit(_create, api, 0, key) for _ in range(3)]
        _until(lambda: ctx.jobs.screening_snapshot()[1] == 3)
        counting.gate.set()
        results = [first.result()] + [d.result() for d in duplicates]
    assert [r.status_code for r in results] == [201] * 4
    assert len({r.json()["id"] for r in results}) == 1
    assert [c["task"] for c in model.calls] == ["red_flag_screen", "concern_check"]  # screened once


def test_397_a_sessions_concern_edit_waits_its_turn_and_changes_nothing_when_refused(local):
    api, model, application = local
    ctx = application.state.ctx
    counting = ctx.runtime = CountingModel(model)
    case = api.new_case("Synthetic QA: earache.", context=[NO_RED_FLAGS])
    counting.gate.clear()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(_create, api, 1)
        _until(lambda: ctx.jobs.screening_snapshot()[0] == 1)
        edit = api.req("PATCH", f"/cases/{case['id']}", json={"expected_revision": 1, "concern": "Synthetic QA: ear"})
        _assert_busy(edit)
        counting.gate.set()
        assert pending.result().status_code == 201
    after = api.case(case["id"])["case"]
    assert after["revision"] == 1 and after["concern"] == "Synthetic QA: earache."
    api.ok("PATCH", f"/cases/{case['id']}", 200, "Case", json={"expected_revision": 1, "concern": "Synthetic QA: ear"})


def test_397_a_session_holds_a_bounded_number_of_consultations(app, api, monkeypatch):
    from app.modules.cases import service
    monkeypatch.setattr(service, "MAX_OPEN_CASES", 3)
    api.start()
    ids = [api.new_case(f"Synthetic concern {i}.")["id"] for i in range(3)]
    r = api.req("POST", "/cases", key=True, json={"concern": "One too many.", "confirmed_context": []})
    assert r.status_code == 409 and r.json()["code"] == "CASE_LIMIT" and "Delete one" in r.json()["message"]
    validate("Error", r.json())
    api.ok("DELETE", f"/cases/{ids[0]}?expected_revision=1", 202, "DeletionAccepted")
    api.new_case("Room again after a deletion.")


def test_397_a_session_can_request_a_bounded_number_of_summaries(app, api, monkeypatch):
    from app.modules.exports import service
    monkeypatch.setattr(service, "MAX_EXPORTS_PER_TTL", 2)
    api.start()
    cid = api.new_case()["id"]
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    body = {"expected_revision": rev, "user_reviewed": True}
    for _ in range(2):
        api.wait_job(api.ok("POST", f"/cases/{cid}/exports", 202, "Job", key=True, json=body)["id"])
    r = api.req("POST", f"/cases/{cid}/exports", key=True, json=body)
    assert r.status_code == 429 and r.json()["code"] == "EXPORT_LIMIT", r.text
    validate("Error", r.json())
    assert 1 <= int(r.headers["Retry-After"]) <= 15 * 60
    assert len(list((app[0].state.ctx.settings.data_dir / "exports").iterdir())) == 2


def test_397_a_session_holds_a_bounded_number_of_records(app, api, monkeypatch):
    from records_helpers import SAMPLE, record_files, upload, upload_ok
    from app.modules.records import service
    monkeypatch.setattr(service, "MAX_SESSION_FILES", 2)
    api.start()
    first = api.new_case()["id"]
    upload_ok(api, first)
    upload_ok(api, first, name="second.pdf")
    stored = record_files(app)
    second = api.new_case()["id"]
    r = upload(api, second, SAMPLE)
    assert r.status_code == 413 and r.json()["code"] == "RECORD_LIMIT" and "one session" in r.json()["message"]
    assert record_files(app) == stored


def test_a_fail_closed_job_keeps_its_content_free_rejection_reasons_and_telemetry_counts_them_by_rule(local):
    """#538 (app-05): 9-15% of guidance jobs on the Nano failed closed and nothing said why. The job keeps each rejected
    attempt's rule and place (Job.error_detail), one content-free event per reason, and the telemetry page counts them
    by rule (never the place or any text), suppressed below 5 like every breakdown."""
    from conftest import NO_RED_FLAGS
    api, model, application = local
    ctx = application.state.ctx
    model.override = {"claims": [
        {"text": "You have no urgent warning signs.", "kind": "case_fact", "fact_ids": [], "evidence_ids": []},
        {"text": "A sore throat is often linked to dry air.", "kind": "clinical", "fact_ids": [], "evidence_ids": []}]}
    model.unsafe_phrases, model.unsafe_category = ("You have no urgent",), "definitive_diagnosis"
    for _ in range(3):
        job = api.to_guided(api.new_case(context=[NO_RED_FLAGS])["id"])
        assert (job["status"], job["error_code"]) == ("failed", "OUTPUT_VALIDATION_FAILED")
        assert job["error_detail"] == ["1:prohibited_certainty/definitive_diagnosis@claims[0].text",
                                       "2:prohibited_certainty/definitive_diagnosis@claims[0].text"]
        validate("Job", job)
    with ctx.db.read() as conn:
        items = [r["error_code"] for r in conn.execute("SELECT error_code FROM events WHERE kind='guidance_rejection'")]
    assert len(items) == 6 and not any("warning" in i or "throat" in i for i in items)
    t = api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")
    assert t["consultations"]["fail_closed_reasons"] == [{"rule": "prohibited_certainty/definitive_diagnosis",
                                                           "count": 6}]
    # A published job carries no reasons.
    model.override, model.unsafe_phrases = {}, ()
    assert api.to_guided(api.new_case(context=[NO_RED_FLAGS])["id"])["error_detail"] is None


def test_a_rejection_reason_below_the_suppression_threshold_is_withheld(local):
    from conftest import NO_RED_FLAGS
    api, model, application = local
    model.override = {"claims": []}  # no possible explanation (ADR-015), twice
    assert api.to_guided(api.new_case(context=[NO_RED_FLAGS])["id"])["error_detail"] == [
        "1:no_possible_explanation", "2:no_possible_explanation"]
    t = api.ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")
    assert t["consultations"]["fail_closed_reasons"] == [{"rule": "no_possible_explanation", "count": None}]


# ------------------------------------------------------------------ #537: any NVIDIA machine


def test_537_the_manifest_of_another_catalogue_model_is_selected_by_its_label():
    """The configured manifest (the Nano's, the image default) keeps describing the Nano's model; any other catalogue
    model, under any of the names ZRT serves it by, gets its catalogue entry's manifest; an unknown model the
    configured one."""
    from dataclasses import replace as _replace

    from app.config import load_settings
    base = load_settings()
    nano = json.loads((ROOT / "infra/model-manifest.json").read_text())["manifest_id"]
    fury = json.loads((ROOT / "infra/fury/model-manifest.json").read_text())["manifest_id"]
    for model_id, expected in (("qwen3.6-35b-a3b-fp8", nano), ("Qwen/Qwen3.6-35B-A3B-FP8@main", nano),
                               ("qwen3.8-flash-next-fp8", fury), ("qwen3-14b-fp8", "qwen3-14b-fp8@9a283b4a-candidate"),
                               ("hf:Qwen/Qwen3-8B-FP8@main", "qwen3-8b-fp8@220b46e3-candidate"),
                               ("some-other-model", nano), (None, nano)):
        assert _replace(base, model_id=model_id).manifest()["manifest_id"] == expected, model_id
    fury_settings = _replace(base, model_id="qwen3.8-flash-next-fp8",
                             model_manifest=ROOT / "infra/fury/model-manifest.json")
    assert fury_settings.manifest()["manifest_id"] == fury


def test_537_another_machine_shows_its_own_device_and_the_candidate_model(tmp_path):
    """On an HP Z8 (2x RTX PRO 5000) serving the 14B candidate: O01 and W06 name the Z8 from its detected inventory and
    the candidate's manifest, claim no runtime qualification, and the neutral prices pass the contract."""
    from dataclasses import replace as _replace

    from app.config import load_settings
    from app.main import create_app
    from app.runtime import hardware
    from conftest import TEST_PRESENTER_KEY, LocalModel
    product = "HP Z8 Fury G5 Workstation Desktop PC"
    gpus = [hardware.Gpu(i, "NVIDIA RTX PRO 5000 72GB Blackwell", 73728, "12.0") for i in (0, 1)]
    hw = hardware.Hardware(product, *hardware.safe_names(product), "x86_64", "linux/amd64", gpus, "580.95.05", "13.0",
                           "/usr/local/cuda-13.0", "13.0", 251.4, "discrete", False, 144.0)
    (tmp_path / "device-inventory.json").write_text(json.dumps(hardware.inventory(hw, "2026-10-26")))
    base_prices = json.loads((ROOT / "infra/telemetry-pricing.json").read_text())
    (tmp_path / "telemetry-pricing.json").write_text(json.dumps(hardware.pricing("qwen3-14b-fp8", base_prices)))
    settings = _replace(load_settings(), mode="local", model_id="qwen3-14b-fp8", data_dir=tmp_path / "local",
                        device_inventory=tmp_path / "device-inventory.json",
                        telemetry_pricing=tmp_path / "telemetry-pricing.json",
                        presenter_key=TEST_PRESENTER_KEY, presenter_trusted_peers=("testclient",))
    application = create_app(settings)
    with TestClient(application):
        application.state.ctx.runtime = LocalModel()
        presenter = Api(TestClient(application), presenter=True)
        presenter.start()
        snap = presenter.ok("GET", "/presenter/runtime", 200, "RuntimeSnapshot")
        assert snap["model_manifest_id"] == "qwen3-14b-fp8@9a283b4a-candidate"
        assert snap["device_inventory_id"] == "detected-hp-z8-fury-g5-workstation-desktop-pc-2026-10-26"
        assert snap["runtime_version"] is None and snap["runtime_qualified_on"] is None
        t = presenter.ok("GET", "/telemetry?period=24h", 200, "TelemetrySnapshot")
    identity = t["identity"]
    assert identity["device"] == product and identity["accelerator"] == "2x NVIDIA RTX PRO 5000 72GB Blackwell"
    assert identity["model_manifest_id"] == "qwen3-14b-fp8@9a283b4a-candidate" and identity["qualification"] is None
    prices = t["pricing"]
    assert prices["assumptions"]["device_price_usd"]["value"] == 0
    assert all(r["comparison"] == "frontier" for r in prices["cloud_references"])
    assert sum(r["default"] for r in prices["cloud_references"]) == 1


# ------------------------------------------------------------------ #548: the presenter's Logs view (getLogs)


def test_548_logs_are_for_presenters_only(app, api, presenter):
    """getLogs runs under require_presenter: no session is 401, a patient session (or a presenter cookie that did not
    come through the presenter gateway) is 403; the presenter reads a LogsSnapshot."""
    from fastapi.testclient import TestClient as _Client
    anonymous = _Client(app[0]).get("/api/v1/presenter/logs")
    assert anonymous.status_code == 401
    api.start()
    assert api.req("GET", "/presenter/logs").json()["code"] == "PRESENTER_REQUIRED"
    assert Api(presenter.c).req("GET", "/presenter/logs").status_code in {401, 403}  # same browser, patient gateway
    body = presenter.ok("GET", "/presenter/logs", 200, "LogsSnapshot")
    assert body["readiness"] == "ready" and body["mode"] == "mock" and body["entries"]
    assert body["entries"][0]["kind"] == "health" or body["entries"][0]["at"] >= body["entries"][-1]["at"]


def test_548_logs_show_jobs_with_rejection_reasons_model_calls_events_and_api_errors_newest_first(local_presenter):
    from fastapi.testclient import TestClient as _Client
    from conftest import NO_RED_FLAGS
    presenter, model, application = local_presenter
    patient = Api(_Client(application))
    patient.start()
    model.override = {"claims": []}  # no possible explanation (ADR-015), twice: the job fails closed
    failed = patient.to_guided(patient.new_case(context=[NO_RED_FLAGS])["id"])
    assert failed["status"] == "failed"
    patient.req("GET", f"/cases/{failed['id']}")  # an unknown case: a 404 the logs keep by route template
    body = presenter.ok("GET", "/presenter/logs", 200, "LogsSnapshot")
    entries = body["entries"]
    job = next(e for e in entries if e["id"] == f"job:{failed['id']}")
    assert (job["level"], job["kind"], job["status"], job["code"]) == ("fail", "job", "failed", failed["error_code"])
    assert job["reasons"] == ["1:no_possible_explanation", "2:no_possible_explanation"]
    assert job["reason"] == failed["error_reason"] and job["reason"].endswith("Nothing was published.")  # #550
    assert job["duration_ms"] is not None and job["precision"] == "exact"
    kinds = {e["kind"] for e in entries}
    assert {"job", "session", "guidance", "health", "error"} <= kinds
    error = next(e for e in entries if e["kind"] == "error" and e["status"] == "404")
    assert error["name"] == "GET /cases/{case_id}" and error["level"] == "warn" and failed["id"] not in error["name"]
    rejection = next(e for e in entries if e["name"] == "guidance_rejection")
    assert rejection["level"] == "fail" and rejection["precision"] == "hour"
    # Newest first: exact times descend; every hour-only row sits in or below the newest hour.
    exact = [e["at"] for e in entries if e["precision"] == "exact"]
    assert exact == sorted(exact, reverse=True)


def test_548_logs_filter_by_level_kind_since_and_limit(app, api, presenter):
    api.start()
    api.new_case()
    api.req("GET", "/cases/00000000-0000-4000-8000-000000000000")  # 404, a warning
    every = presenter.ok("GET", "/presenter/logs", 200, "LogsSnapshot")["entries"]
    assert len(every) > 3
    for level in ("ok", "warn", "fail", "info"):
        got = presenter.ok("GET", f"/presenter/logs?level={level}", 200, "LogsSnapshot")["entries"]
        assert all(e["level"] == level for e in got)
    sessions = presenter.ok("GET", "/presenter/logs?kind=session", 200, "LogsSnapshot")["entries"]
    assert sessions and all(e["kind"] == "session" for e in sessions)
    two = presenter.ok("GET", "/presenter/logs?limit=2", 200, "LogsSnapshot")
    assert len(two["entries"]) == 2 and two["truncated"] is True
    future = presenter.ok("GET", "/presenter/logs?since=2999-01-01T00:00:00Z", 200, "LogsSnapshot")
    assert future["entries"] == []
    for bad in ("level=red", "kind=secrets", "limit=0", "limit=501", "since=yesterday"):
        assert presenter.req("GET", f"/presenter/logs?{bad}").status_code == 422


def test_548_logs_carry_no_secret_token_identity_or_free_text(app, api, presenter):
    """Content-free like the tables they read: no session token, CSRF token, cookie, actor, session or case ID, and
    no concern or answer text."""
    concern = "Zebra-striped headaches after kite surfing."
    api.start()
    case = api.new_case(concern=concern)
    api.answer_all(case["id"])
    text = json.dumps(presenter.ok("GET", "/presenter/logs?limit=500", 200, "LogsSnapshot"))
    secrets = [concern, "Zebra", "No changes yet.", case["id"], api.csrf, presenter.csrf]
    secrets += [c.value for c in list(api.c.cookies.jar) + list(presenter.c.cookies.jar)]
    with app[0].state.ctx.db.read() as conn:
        secrets += [r["id"] for r in conn.execute("SELECT id FROM actors")]
        secrets += [r["id"] for r in conn.execute("SELECT id FROM sessions")]
        secrets += [r["token_hash"] for r in conn.execute("SELECT token_hash FROM sessions")]
    leaked = [s for s in secrets if s and s in text]
    assert not leaked, leaked


# ------------------------------------------------------------------ #577: the Logs filters search every kept row


def _seed_old_failure_behind_newer_rows(ctx) -> str:
    """A failed job two days old behind 600 newer succeeded jobs and 600 newer events: older than the newest 500 rows
    of every table and of the whole log."""
    import uuid
    from datetime import timedelta
    from app.core.db import iso, utcnow
    failed = str(uuid.uuid4())
    old, newer = utcnow() - timedelta(days=2), utcnow() - timedelta(days=1)
    with ctx.db.tx() as conn:
        conn.execute("INSERT INTO jobs (id, actor_id, kind, status, error_code, created_at, started_at, finished_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", (failed, "seeded", "guidance", "failed", "OUTPUT_VALIDATION_FAILED",
                                                  iso(old), iso(old), iso(old + timedelta(seconds=20))))
        for i in range(600):
            at = iso(newer + timedelta(seconds=i))
            conn.execute("INSERT INTO jobs (id, actor_id, kind, status, created_at, started_at, finished_at) "
                         "VALUES (?,?,?,?,?,?,?)", (str(uuid.uuid4()), "seeded", "guidance", "succeeded", at, at, at))
            conn.execute("INSERT INTO events (id, ts, kind, operation_id, status) VALUES (?,?,?,?,?)",
                         (str(uuid.uuid4()), at[:13] + ":00:00Z", "session_started", "createSession", "succeeded"))
    return failed


def test_577_a_failure_older_than_the_newest_500_rows_is_found_by_level_kind_and_search(app, api, presenter):
    failed = f"job:{_seed_old_failure_behind_newer_rows(app[0].state.ctx)}"
    for query in ("level=fail", "level=fail&kind=job", "kind=job&level=warn&level=fail", "q=output_validation",
                  f"q={failed[4:12]}&level=fail"):
        body = presenter.ok("GET", f"/presenter/logs?limit=500&{query}", 200, "LogsSnapshot")
        assert failed in [e["id"] for e in body["entries"]], query
    fails = presenter.ok("GET", "/presenter/logs?level=fail", 200, "LogsSnapshot")
    assert all(e["level"] == "fail" for e in fails["entries"]) and fails["total"] == len(fails["entries"])
    # The level counts cover every kept row of the kind and search, whatever levels are asked for.
    counts = presenter.ok("GET", "/presenter/logs?kind=job&level=ok&limit=1", 200, "LogsSnapshot")
    assert counts["level_counts"]["fail"] >= 1 and counts["level_counts"]["ok"] >= 600
    assert counts["total"] == counts["level_counts"]["ok"] and counts["truncated"] is True
    nothing = presenter.ok("GET", "/presenter/logs?q=nothing+like+this", 200, "LogsSnapshot")
    assert nothing["entries"] == [] and nothing["total"] == 0 and nothing["next_before"] is None


def test_577_load_older_pages_through_every_kept_row_once_newest_first(app, api, presenter):
    failed = f"job:{_seed_old_failure_behind_newer_rows(app[0].state.ctx)}"
    first = presenter.ok("GET", "/presenter/logs?limit=500", 200, "LogsSnapshot")
    assert failed not in [e["id"] for e in first["entries"]] and first["truncated"] and first["next_before"]
    seen, page = [], first
    while True:
        seen += [e["id"] for e in page["entries"]]
        if not page["next_before"]:
            break
        page = presenter.ok("GET", f"/presenter/logs?limit=500&before={page['next_before']}", 200, "LogsSnapshot")
    assert failed in seen and len(seen) == len(set(seen)) >= 1201
    assert len(seen) == first["total"] == sum(first["level_counts"].values())
    exact = [e for e in seen if e.startswith("job:")]
    assert exact[-1] == failed  # the oldest job comes last
    for bad in ("before=not-a-cursor", "before=" + "x" * 600, "q=" + "x" * 101):
        assert presenter.req("GET", f"/presenter/logs?{bad}").status_code == 422, bad


# #605 (QA 2026-10-26): the token counts in ZRT's optional `usage` were kept whenever they were Python ints. Negative
# counts made the public token totals and output speed negative, booleans were stored as 1 and 0, and a count past
# SQLite's 64-bit integers failed the INSERT, which the metering swallowed, so the model call was not recorded at all.
ZRT_LABEL = "qwen3.6-35b-a3b-fp8"


def _zrt_reporting(monkeypatch, usage):
    """A ZRT stand-in on an httpx MockTransport (no network, no model): it serves ZRT_LABEL and answers every chat
    request with the JSON object `{}` and this `usage`."""
    import httpx
    from app.runtime import zrt_provider

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [{"id": ZRT_LABEL, "object": "model"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": usage})

    real = httpx.AsyncClient
    monkeypatch.setattr(zrt_provider.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize(("usage", "stored"), [
    ({"prompt_tokens": -7, "completion_tokens": -3}, (None, None)),
    ({"prompt_tokens": True, "completion_tokens": False}, (None, None)),
    ({"prompt_tokens": 2**80, "completion_tokens": 2**80}, (None, None)),
    ({"prompt_tokens": 2**63, "completion_tokens": 7}, (None, 7)),
    ({"prompt_tokens": 1.5, "completion_tokens": "3"}, (None, None)),
    ({"prompt_tokens": 2**63 - 1, "completion_tokens": 0}, (2**63 - 1, 0)),
    ({"prompt_tokens": 12, "completion_tokens": 5}, (12, 5)),
    ({}, (None, None)),
])
def test_605_malformed_zrt_usage_is_not_counted_and_the_call_is_still_recorded(tmp_path, monkeypatch, usage, stored):
    import asyncio
    from dataclasses import replace
    from app.config import load_settings
    from app.main import create_app
    _zrt_reporting(monkeypatch, usage)
    settings = replace(load_settings(), mode="local", model_id=ZRT_LABEL, data_dir=tmp_path / "d")
    with TestClient(create_app(settings)) as client:
        ctx = client.app.state.ctx  # the real ZRT adapter inside the real metering layer
        out, counts = asyncio.run(ctx.runtime.inner.generate_json_with_usage("concern_check", "p1", {}, "S", 5))
        assert (out, counts) == ({}, {"prompt_tokens": stored[0], "completion_tokens": stored[1]})  # the adapter alone
        assert asyncio.run(ctx.runtime.generate_json("concern_check", "p1", {"text": "x"}, "S", 5)) == {}
        with ctx.db.read() as conn:
            rows = [tuple(r) for r in conn.execute("SELECT outcome, prompt_tokens, completion_tokens FROM model_calls")]
        assert rows == [("ok", *stored)]
        t = Api(client).ok("GET", "/telemetry?period=7d", 200, "TelemetrySnapshot")  # nonnegative, as the schema says
    counted = stored if None not in stored else (0, 0)  # only a call with both counts adds tokens
    assert t["ai_calls"]["total"] == 1
    assert (t["ai_calls"]["prompt_tokens"], t["ai_calls"]["completion_tokens"]) == counted


def test_605_the_metering_records_the_call_whatever_counts_a_runtime_reports(local):
    """The metering layer is the boundary before the database: it keeps the call whatever counts the runtime reported."""
    import asyncio
    _, _, application = metered(local, power=False, prompt_tokens=2**80, completion_tokens=-1)
    ctx = application.state.ctx
    assert asyncio.run(ctx.runtime.generate_json("concern_check", "p1", {"text": "x"}, "S", 5))
    with ctx.db.read() as conn:
        rows = [tuple(r) for r in conn.execute("SELECT outcome, prompt_tokens, completion_tokens FROM model_calls")]
    assert rows == [("ok", None, None)]
