"""M12 operations: job admission/execution, content-free events, readiness, runtime truth.

Requirements R37-R40 (plus R17 readiness, R26/R27 job lifecycle, R38 timing).
The generation admission limit (1 active + N queued) is enforced per process;
running more than one API process requires central coordination (not built).
#397: the concern screens that createCase, editCase and a written-urgency scenario load run on the same runtime pass
the same central admission, in their own lane (`screening`), with the same bounds and the same 429 + Retry-After.
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any, Callable, Hashable, Iterator

from app.core.db import Database, dumps, hour, iso, utcnow
from app.core.errors import ApiError, not_found

JOB_TERMINAL = {"succeeded", "failed", "stale", "cancelled"}


def record_event(conn, kind: str, status: str, *, operation_id: str | None = None,
                 error_code: str | None = None, duration_ms: float | None = None, actor_ref: str | None = None) -> None:
    """Content-free operational event: no names, symptoms, values, filenames or URLs. `actor_ref` is set only for
    presenter actions (ADR-005 rule 5): the presenter's opaque actor ID, never a patient's.

    #275 (R36): the time is kept to the hour only, so an event cannot be tied to one person's session window; the
    30-day retention still compares these hours. #271: the running mode is recorded for the telemetry page."""
    conn.execute("INSERT INTO events (id, ts, kind, operation_id, status, error_code, duration_ms, actor_ref, mode) "
                 "VALUES (?,?,?,?,?,?,?,?,?)",
                 (str(uuid.uuid4()), hour(), kind, operation_id, status, error_code, duration_ms, actor_ref,
                  getattr(conn, "mode", None)))


def job_public(row) -> dict[str, Any]:
    from app.modules.operations.reasons import error_reason
    detail = json.loads(row["error_detail"]) if row["error_detail"] else None
    return {"id": row["id"], "actor_id": row["actor_id"], "case_id": row["case_id"],
            "input_revision": row["input_revision"], "kind": row["kind"], "status": row["status"],
            "result_id": row["result_id"], "error_code": row["error_code"], "created_at": row["created_at"],
            "finished_at": row["finished_at"], "result_type": row["result_type"],
            # #538: the content-free rejection reasons of a failed guidance job (and of the quick demo waiting on it)
            "error_detail": detail,
            # #550: the same reasons in plain words, for the presenter's failure message and the logs view
            "error_reason": error_reason(row["error_code"], detail) if row["status"] == "failed" else None,
            # #548: the step a running quick demo is on (routes.get_job fills it for a presenter's prepare job)
            "stage": None}


def create_job(conn, *, actor_id: str, case_id: str | None, kind: str, input_revision: int | None = None,
               reviewed_revision: int | None = None, status: str = "queued") -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    conn.execute("INSERT INTO jobs (id, actor_id, case_id, input_revision, reviewed_revision, kind, status, "
                 "created_at, mode) VALUES (?,?,?,?,?,?,?,?,?)",
                 (job_id, actor_id, case_id, input_revision, reviewed_revision, kind, status, iso(utcnow()),
                  getattr(conn, "mode", None)))
    return job_public(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def finish_job(conn, job_id: str, status: str, *, result_id: str | None = None, result_type: str | None = None,
               error_code: str | None = None, timings: dict[str, float] | None = None,
               error_detail: list[str] | None = None) -> None:
    """`error_detail` (#538): content-free reasons only, rule codes and places such as
    "1:third_person@actions[0].rationale", never case or model text."""
    timings = timings or {}
    conn.execute("UPDATE jobs SET status=?, result_id=?, result_type=?, error_code=?, finished_at=?, "
                 "queue_ms=?, inference_ms=?, validation_ms=?, total_ms=?, error_detail=? WHERE id=? AND status NOT IN "
                 "('succeeded','failed','stale','cancelled')",
                 (status, result_id, result_type, error_code, iso(utcnow()), timings.get("queue_ms"),
                  timings.get("inference_ms"), timings.get("validation_ms"), timings.get("total_ms"),
                  dumps(error_detail) if error_detail else None, job_id))


def get_job(db: Database, actor_id: str, job_id: str) -> dict[str, Any]:
    with db.read() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=? AND actor_id=?", (job_id, actor_id)).fetchone()
    if row is None:
        raise not_found()
    return job_public(row)


class JobRunner:
    """Bounded executor. Generation work passes application-wide admission control."""

    def __init__(self, active_limit: int, queued_limit: int, retry_after_s: int):
        self._active_limit = active_limit
        self._capacity = active_limit + queued_limit
        self._retry_after = retry_after_s
        self._lock = threading.Lock()
        self._inflight = 0
        self._active = 0
        self._slots = threading.Semaphore(active_limit)
        self._generation = ThreadPoolExecutor(max_workers=self._capacity, thread_name_prefix="gen")
        self._background = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bg")
        # #316: presenter quick-demo preparation waits for its guidance job, so it has its own workers and never holds
        # a reset or deletion worker; `stopping` ends those waits at shutdown.
        self._prepare = ThreadPoolExecutor(max_workers=2, thread_name_prefix="prep")
        self.stopping = threading.Event()
        # #397: the screening lane. The concern screens (red-flag screen and concern check of a new or edited concern)
        # run inside the request, so the lane bounds how many requests may hold a worker thread for a model call: one
        # screening at a time on the runtime plus `queued_limit` waiting for it, at most one per actor (a session's
        # second concurrent screening is refused, so one session cannot fill the lane), and a refusal is the same 429
        # QUEUE_FULL with Retry-After as for guidance. A duplicate of a request in the lane (same idempotency key)
        # waits for it and then replays its response instead of calling the model again.
        self._screen_capacity = self._capacity
        self._screen_slot = threading.Semaphore(active_limit)
        self._screen_inflight = 0
        self._screen_actors: set[str] = set()
        self._screen_keys: dict[Hashable, threading.Event] = {}
        self._screen_waiters = 0

    def busy(self) -> ApiError:
        return ApiError(429, "QUEUE_FULL", "The local runtime is busy. Try again shortly.",
                        retryable=True, headers={"Retry-After": str(self._retry_after)})

    def admit_generation(self) -> None:
        with self._lock:
            if self._inflight >= self._capacity:
                raise self.busy()
            self._inflight += 1

    @contextmanager
    def screening(self, actor_id: str, key: Hashable | None, wait_s: float) -> Iterator[bool]:
        """Admit one request's concern screens (#397). Yields True once the request holds the lane's active slot: the
        caller runs its model calls and commits inside the block. Yields False to a duplicate of a request already in
        the lane (same `key`) after that request has finished: the caller replays its stored response. Raises 429
        QUEUE_FULL when the lane is full, when the actor already has a screening in the lane, or when the slot does not
        come free within `wait_s` seconds."""
        with self._lock:
            done = self._screen_keys.get(key) if key is not None else None
            if done is not None:
                if self._screen_waiters >= self._screen_capacity:
                    raise self.busy()
                self._screen_waiters += 1
            elif self._screen_inflight >= self._screen_capacity or actor_id in self._screen_actors:
                raise self.busy()
            else:
                self._screen_inflight += 1
                self._screen_actors.add(actor_id)
                if key is not None:
                    self._screen_keys[key] = threading.Event()
        if done is not None:
            try:
                done.wait(wait_s * 3)  # the first request's queue wait and its two bounded model calls
            finally:
                with self._lock:
                    self._screen_waiters -= 1
            yield False
            return
        try:
            if not self._screen_slot.acquire(timeout=wait_s):
                raise self.busy()
            try:
                yield True
            finally:
                self._screen_slot.release()
        finally:
            with self._lock:
                self._screen_inflight -= 1
                self._screen_actors.discard(actor_id)
                if key is not None:
                    self._screen_keys.pop(key).set()

    def screening_snapshot(self) -> tuple[int, int]:
        """(requests in the screening lane, duplicates waiting for one); for tests and diagnostics."""
        with self._lock:
            return self._screen_inflight, self._screen_waiters

    def release_generation(self) -> None:
        """#263: give back an admitted slot whose job was never submitted (the request failed after admission)."""
        with self._lock:
            self._inflight = max(0, self._inflight - 1)

    def submit_generation(self, work: Callable[[float], None]) -> None:
        enqueued = time.perf_counter()

        def run() -> None:
            try:
                with self._slots:
                    with self._lock:
                        self._active += 1
                    try:
                        work((time.perf_counter() - enqueued) * 1000)
                    finally:
                        with self._lock:
                            self._active -= 1
            finally:
                with self._lock:
                    self._inflight -= 1

        try:
            self._generation.submit(run)
        except BaseException:
            self.release_generation()  # #263: a failed submit never keeps admission capacity
            raise

    def submit(self, work: Callable[[], None]) -> None:
        self._background.submit(work)

    def submit_prepare(self, work: Callable[[], None]) -> None:
        self._prepare.submit(work)

    def snapshot(self) -> tuple[int, int]:
        with self._lock:
            return max(0, self._inflight - self._active), self._active

    def shutdown(self) -> None:
        self.stopping.set()
        self._generation.shutdown(wait=True)
        self._prepare.shutdown(wait=True)
        self._background.shutdown(wait=True)


INTERRUPTED = "INTERRUPTED"


def recover_interrupted(ctx) -> None:
    """#263: at startup no worker is running, so no job can still be queued or running. The job runner lives in memory
    only, and a restart drops its work. Every non-terminal job is settled before the API serves a request:

    - guidance and export jobs fail with INTERRUPTED; a case left `generating` becomes `limited` with
      `generation_failed_recoverable`, so the person is offered a retry (answers are kept);
    - extraction jobs fail, their queued documents fail and the stored bytes are removed (R18: no unprocessed bytes
      are kept);
    - a presenter quick-demo preparation (scenario_prepare, #316) fails with INTERRUPTED like guidance; its case keeps
      the state it reached;
    - deletion and presenter reset jobs are run again to completion, because access is already blocked by the
      tombstone and the purge must finish (R35).
    """
    from app.modules.cases import repository as cases_repo
    from app.modules.operations import scenarios
    from app.modules.privacy import service as privacy
    from app.modules.records.service import record_dir

    with ctx.db.tx() as conn:
        pending = conn.execute("SELECT * FROM jobs WHERE status IN ('queued','running')").fetchall()
        reruns = [(r["id"], r["kind"], r["actor_id"]) for r in pending if r["kind"] in {"deletion", "reset"}]
        for r in pending:
            if r["kind"] not in {"deletion", "reset"}:
                finish_job(conn, r["id"], "failed", error_code=INTERRUPTED)
                record_event(conn, "job_interrupted", "failed", error_code=INTERRUPTED)
        for case in conn.execute("SELECT id FROM cases WHERE state='generating'").fetchall():
            cases_repo.set_state(conn, case["id"], "limited", limited_reason="generation_failed_recoverable")
        docs = conn.execute("SELECT id, storage_key FROM documents WHERE status IN ('queued','processing')").fetchall()
        for d in docs:
            conn.execute("UPDATE documents SET status='failed', error_code=?, storage_key=NULL WHERE id=?",
                         (INTERRUPTED, d["id"]))
    for d in docs:
        if d["storage_key"]:
            (record_dir(ctx) / d["storage_key"]).unlink(missing_ok=True)
    for job_id, kind, actor_id in reruns:
        if kind == "reset":
            scenarios._reset_sync(ctx, actor_id, job_id)
            continue
        with ctx.db.read() as conn:
            case_ids = [r["id"] for r in conn.execute("SELECT id FROM cases WHERE state='deleting'").fetchall()]
            actors = [r["id"] for r in conn.execute("SELECT id FROM actors WHERE id=? AND deleting=1", (actor_id,))]
        privacy._run_deletion(ctx, job_id, case_ids, actors[0] if actors else None)


def storage_writable(data_dir) -> bool:
    try:
        probe = data_dir / f".probe-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        return False


def readiness(ctx) -> str:
    state = _readiness(ctx)
    # #548: each change of readiness this process observed (time and state only), for the presenter's Logs view.
    changes = getattr(ctx, "health_changes", None)
    if changes is not None and (not changes or changes[-1]["readiness"] != state):
        changes.append({"at": iso(utcnow()), "readiness": state, "mode": ctx.settings.mode})
    return state


def _readiness(ctx) -> str:
    if not ctx.db.ping() or not storage_writable(ctx.settings.data_dir):
        return "unavailable"
    if ctx.settings.mode == "mock":
        return "ready" if ctx.fixtures is not None else "unavailable"
    # Local mode requires the active reviewed pathway (ADR-003). No evidence corpus is approved for the demo
    # (ADR-004), so clinical explanations stay suppressed rather than blocking guidance. A model that ZRT does not
    # serve degrades the service: cases can start, and generation fails visibly with a retry.
    if ctx.pathway is None or not ctx.pathway.active():
        return "unavailable"
    try:
        health = asyncio.run(ctx.runtime.health())
    except Exception:  # an unreachable runtime is reported, never assumed ready
        return "degraded"
    if health.get("status") == "ready":
        return "ready"
    # No configured model can never produce guidance; an unreachable or unserved model may come back.
    return "unavailable" if health.get("reason_code") == "MODEL_ID_UNSET" else "degraded"


def timing_summary(db: Database, mode: str | None = None) -> dict[str, Any]:
    """Median timings of the last 50 succeeded guidance jobs of the running mode (#271: a data directory that served
    both modes never mixes them). #428 (R38): mock mode runs no model, so it has no inference time to report; its
    queue, validation and total times are the scripted pipeline's own and O01 labels them so."""
    return _timings(db, mode)[0]


def _timings(db: Database, mode: str | None) -> tuple[dict[str, Any], str | None]:
    with db.read() as conn:
        rows = conn.execute("SELECT queue_ms, inference_ms, validation_ms, total_ms, finished_at FROM jobs WHERE "
                            "kind='guidance' AND status='succeeded' AND total_ms IS NOT NULL AND (? IS NULL OR mode=?) "
                            "ORDER BY finished_at DESC LIMIT 50", (mode, mode)).fetchall()
    if not rows:
        return ({"sample_count": 0, "queue_ms": None, "retrieval_ms": None, "inference_ms": None,
                 "validation_ms": None, "total_ms": None}, None)

    # #588: the mathematical median; of an even number of samples, the mean of the two middle ones (before: the upper).
    def median(key: str) -> float | None:
        values = [r[key] for r in rows if r[key] is not None]
        return statistics.median(values) if values else None

    return ({"sample_count": len(rows), "queue_ms": median("queue_ms"), "retrieval_ms": None,
             "inference_ms": None if mode == "mock" else median("inference_ms"),
             "validation_ms": median("validation_ms"), "total_ms": median("total_ms")}, rows[0]["finished_at"])


def _read_json(path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def manifest_id(ctx) -> str | None:
    value = ctx.settings.manifest().get("manifest_id")
    return value if isinstance(value, str) and value else None


def _text(value: Any, limit: int = 100) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= limit else None


def runtime_snapshot(ctx, presenter_actor: str) -> dict[str, Any]:
    """O01 (R37, R38). #429: every value says where it comes from and when it was observed: `observed_at` for what
    this request checked (readiness, which in local mode asks ZRT whether the configured model is served, and the
    queue); the device inventory with the date it was recorded; in local mode the serving runtime's versions from the
    model manifest with the date of its last passed (re-)qualification; the newest timing sample's finish time."""
    observed_at = iso(utcnow())
    inventory = _read_json(ctx.settings.device_inventory)
    inventory_id = _text(inventory.get("inventory_id")) or "unverified"
    local = ctx.settings.mode == "local"
    manifest = ctx.settings.manifest() if local else {}
    runtime = manifest.get("runtime") if isinstance(manifest.get("runtime"), dict) else {}
    requals = (manifest.get("qualification") or {}).get("runtime_requalifications") if isinstance(
        manifest.get("qualification"), dict) else None
    # The last re-qualification that passed on this runtime (a failed one does not vouch for it).
    passed = [r for r in requals if isinstance(r, dict) and str(r.get("result", "")).startswith("PASSED")] \
        if isinstance(requals, list) else []
    requal = passed[-1] if passed else {}
    zrt, engine, engine_version = (_text(runtime.get(k), 40) for k in (
        "zrt_version_observed", "internal_engine", "internal_engine_version"))
    runtime_version = (f"ZRT {zrt}" + (f" ({engine} {engine_version})" if engine and engine_version else "")
                       ) if zrt else None
    from app.modules.operations.scenarios import demo_state
    with ctx.db.read() as conn:
        demo = demo_state(conn, presenter_actor)
    timings, timings_at = _timings(ctx.db, ctx.settings.mode)
    queued, active = ctx.jobs.snapshot()
    return {
        "device_inventory_id": inventory_id,
        "device_inventory_observed_on": _text(inventory.get("observed_on"), 10) if inventory_id != "unverified"
        else None,
        "model_manifest_id": manifest_id(ctx) if local else None,
        "runtime_version": runtime_version,
        "runtime_qualified_on": _text(requal.get("date"), 10) if runtime_version else None,
        "app_commit": os.environ.get("AWARECARE_APP_COMMIT") or None,
        "spec_version": "2.0",
        "corpus_version": None,
        "directory_version": ctx.fixtures.directory_version if ctx.fixtures else None,
        "readiness": readiness(ctx),
        "queue_depth": min(queued, 3),
        "active_jobs": min(active, 1),
        "observed_at": observed_at,
        "timing_summary": timings,
        "timings_latest_at": timings_at,
        "retrieval_mode": "unavailable" if local else "local",
        "mode": ctx.settings.mode,
        "demo": demo,
    }


def pathway_summary(pathway) -> str:
    if pathway is None:
        return "No reviewed clinical pathway is enabled; local guidance is unavailable."
    expiry = pathway.expires_at.date().isoformat()
    if not pathway.active():
        return (f"Pathway {pathway.version} is not active (expired or not approved; expiry {expiry}); "
                "local guidance is unavailable.")
    return f"Reviewed pathway {pathway.version} is enabled (ADR-003); expires {expiry}."


def controls(ctx) -> dict[str, Any]:
    unverified = "No executed evidence recorded for this build."
    items = [
        {"control_id": cid, "status": "unverified", "checked_at": None, "evidence_id": None, "summary": text}
        for cid, text in [
            ("CTRL-NO-CLOUD-FALLBACK", "Configuration rejects cloud fallback; network egress not yet verified. " + unverified),
            ("CTRL-CORPUS-REVIEW", "No approved evidence corpus is registered; possible explanations come from the model's "
                                "general medical knowledge and are marked as such (ADR-015)."),
            ("CTRL-PATHWAY-REVIEW", pathway_summary(ctx.pathway)),
            ("CTRL-OUTBOUND-GATEWAY", "No outbound gateway is implemented; this build makes no outbound lookups."),
            ("CTRL-LOG-REDACTION", "Events table stores content-free fields only. " + unverified),
        ]
    ]
    return {"items": items, "outbound_events": []}
