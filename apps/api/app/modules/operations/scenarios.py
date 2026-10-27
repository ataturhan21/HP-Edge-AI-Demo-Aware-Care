"""M12 presenter scenario load/reset (R37, R39, R35).

Requires a presenter session from the presenter gateway (ADR-005 option A).
Loading first completes a reset of the presenter's previous demo actors, then
creates an isolated synthetic patient session and case; the route hands that
session to the browser as the patient cookie, so the patient site in the same
browser continues the loaded case while the presenter cookie stays untouched.
A pending or failed reset blocks a new load.

Mock mode: the scenario selects scripted fixture outcomes (ADR-007). Local mode (ADR-016): the scenario only supplies
a realistic synthetic concern and the red-flag checklist answer from `local_mode` in the fixture pack. The case then
takes the same gate as a patient-created case, and everything after loading (the reviewed questions, the red-flag
screen, the local model's guidance) runs live. A scenario whose point is a scripted outcome (`failure`) is not
available in local mode (404), because forcing it would fake the local AI.

#315/#316 (ADR-016 amendment, CHG-DEV-API-002):
- `reset` is optional in effect: `reset=false` adds the case to this presenter's live demo patient (a new session for the
  same demo actor), so several demos coexist and appear together in History; without a live demo patient a new one is
  created. A pending or failed reset still blocks.
- The response names the case `state` and the patient-site `next_path` to open, so O03 opens the patient tab directly.
- `prepare="result"` readies a quick demo ahead of time: a presenter-owned `scenario_prepare` job answers the reviewed
  questions with the scenario's synthetic answers (fixture `local_mode.quick`), confirms the review and starts
  guidance through the same services a patient uses, as the demo patient actor (every rule, check and audit path is
  the same). Local mode runs the live local model with unchanged validation, single repair and fail-closed handling;
  mock mode the scripted fixture outcome. When the result is the doctor list, the provider search runs after the
  guidance publishes. A failure leaves the case recoverable exactly as for a patient; nothing is substituted. The
  presenter reads only the prepare job (status and a content-free error code), never the patient's case content.

#358 (ADR-016 amendment 2, CHG-DEV-API-006): O03's one-click flows run one scenario live at the click (reset=false,
prepare=result) instead of preparing demos ahead. `urgency_input="written"` gives the case only the written concern,
with the red-flag checklist answered "none of these apply", exactly as a patient who writes the emergency in their own
words: the concern then takes createCase's red-flag screen (local mode: the device's model, `red_flag_screen`). A
match routes the case to urgent help at creation; no match leaves it at its questions; a screen that cannot run fails
the load closed (503 RED_FLAG_SCREEN_UNAVAILABLE) and creates nothing. Mock mode keeps the scenario's scripted outcome.

#396/#425 (CHG-DEV-API-007): a reset removes the demos of every presenter session of this presenter's browser. Each
presenter session has its own presenter actor, so a reset keyed to the current one left the demo cases of an ended
earlier session (same browser, same patient cookie) open while saying all were removed. The browser's lineage cookie
(`access/presenter.py`) ties its presenter actors together; demo actors keep their kind `demo:<presenter actor>`, and
patient guest actors or another presenter's demos are never touched. For the same reason the reset that blocks a new
demo is the lineage's last one, and `demo_state` reports it (and the demo cases still reachable) to every presenter view.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from app.core import idempotency
from app.core.db import dumps, iso, parse, utcnow
from app.core.errors import ApiError, not_found
from app.core.security import CURRENT_CONSENT_VERSION, SessionInfo, effective_expiry, hash_token, new_token
from app.modules.access.presenter import lineage_actors
from app.modules.access.schemas import CreateSessionRequest
from app.modules.access.service import _issue
from app.modules.cases.schemas import ConfirmedContextWrite
from app.modules.cases.service import _insert_context
from app.modules.operations.service import create_job, finish_job, record_event
from app.modules.privacy.service import _mark_deleting, _purge, release_jobs
from app.modules.safety import screen as rf_screen
from app.modules.safety.service import RED_FLAGS_KIND, GateDecision, check_red_flags, initial_gate

DESCRIBED_EVENT_CODE = "RED_FLAG_DESCRIBED"  # the content-free event code createCase records for a screened match


PREPARE_KIND = "scenario_prepare"
TERMINAL = {"succeeded", "failed", "stale", "cancelled"}
# #548: the guidance job each running prepare job waits for (memory only: a restart interrupts both jobs anyway).
_PREPARE_GUIDANCE: dict[str, str] = {}
# #548: the model task of the guidance job's step: the red-flag screen of the person's words, the draft (a second
# draft is the repair after a failed check) and the certainty review.
_STAGE_OF_TASK = {"red_flag_screen": "screening", "certainty_review": "checking"}


MAX_LIVE_CASES = 200


def _demo_kind(presenter_actor: str) -> str:
    return f"demo:{presenter_actor}"


def _marks(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def _lineage_demo_kinds(conn, presenter_actor: str) -> list[str]:
    """#396: the demo actor kinds of every presenter session of this presenter's browser."""
    return [_demo_kind(a) for a in lineage_actors(conn, presenter_actor)]


def _last_reset(conn, presenter_actor: str):
    """The last reset of this presenter's browser (#396, #425): it covers every demo of the lineage, so it decides
    whether a new demo may start, also after the presenter session that ran it ended."""
    actors = lineage_actors(conn, presenter_actor)
    return conn.execute(f"SELECT status, finished_at FROM jobs WHERE kind='reset' AND actor_id IN ({_marks(actors)}) "
                        "ORDER BY created_at DESC, rowid DESC LIMIT 1", actors).fetchone()


def _reset_blocker(conn, presenter_actor: str) -> None:
    last = _last_reset(conn, presenter_actor)
    if last is not None and last["status"] in {"queued", "running"}:
        raise ApiError(409, "RESET_PENDING", "A reset is still running.", retryable=True)
    if last is not None and last["status"] == "failed":
        raise ApiError(503, "RESET_FAILED", "The previous reset failed; repair it before loading a scenario.")


def demo_state(conn, presenter_actor: str, now=None) -> dict[str, Any]:
    """#425/#426: what every presenter view needs to show the demo truthfully after a reload, in another presenter tab
    or after a new presenter session: the lineage's last reset (a failed or running one blocks a new demo) and the IDs
    of its demo cases the patient tab can still open (a demo actor with a live session). Content-free: IDs and a status
    only, never a patient guest's case or another presenter's."""
    last = _last_reset(conn, presenter_actor)
    status = "none" if last is None else {"queued": "running", "running": "running", "failed": "failed",
                                          "succeeded": "succeeded"}.get(last["status"], "none")
    now = now or utcnow()
    kinds = _lineage_demo_kinds(conn, presenter_actor)
    live_actors = {r["actor_id"] for r in conn.execute(
        f"SELECT s.actor_id, s.last_seen_at, s.absolute_expires_at FROM sessions s JOIN actors a ON a.id = s.actor_id "
        f"WHERE a.kind IN ({_marks(kinds)}) AND a.deleting = 0 AND s.revoked = 0", kinds).fetchall()
        if now < parse(effective_expiry(r["last_seen_at"], r["absolute_expires_at"]))}
    case_ids = [r["id"] for a in sorted(live_actors) for r in conn.execute(
        "SELECT id FROM cases WHERE actor_id=? AND state != 'deleting' ORDER BY created_at DESC", (a,)).fetchall()]
    return {"reset_status": status, "reset_finished_at": last["finished_at"] if last is not None else None,
            "live_case_ids": case_ids[:MAX_LIVE_CASES]}


def _reset_sync(ctx, presenter_actor: str, job_id: str, operation_id: str = "resetDemo") -> None:
    with ctx.db.tx() as conn:
        # #316: quick demos still being prepared for the removed cases end now; their late steps find no case. #396:
        # those of every presenter session of this browser, whose demos are all removed.
        presenters = lineage_actors(conn, presenter_actor)
        conn.execute(f"UPDATE jobs SET status='cancelled', error_code='RESET', finished_at=? WHERE kind=? AND "
                     f"status IN ('queued','running') AND actor_id IN ({_marks(presenters)})",
                     (iso(utcnow()), PREPARE_KIND, *presenters))
        kinds = [_demo_kind(a) for a in presenters]
        actors = [r["id"] for r in conn.execute(f"SELECT id FROM actors WHERE kind IN ({_marks(kinds)})",
                                                kinds).fetchall()]
        case_ids = [r["id"] for a in actors for r in conn.execute("SELECT id FROM cases WHERE actor_id=?", (a,))]
        _mark_deleting(conn, case_ids)
        for a in actors:
            conn.execute("UPDATE sessions SET revoked=1 WHERE actor_id=?", (a,))
    try:
        _purge(ctx, case_ids)
        with ctx.db.tx() as conn:
            for a in actors:
                conn.execute("DELETE FROM actors WHERE id=?", (a,))
            release_jobs(conn, actors)  # #440: the removed demo patients' job rows keep no link to them
            finish_job(conn, job_id, "succeeded", result_id=job_id, result_type="reset_receipt")
            record_event(conn, "reset_completed", "succeeded", operation_id=operation_id, actor_ref=presenter_actor)
    except Exception:
        with ctx.db.tx() as conn:
            finish_job(conn, job_id, "failed", error_code="RESET_FAILED")
            record_event(conn, "reset_failed", "failed", operation_id=operation_id, error_code="RESET_FAILED",
                         actor_ref=presenter_actor)


def reset(ctx, presenter: SessionInfo, key: str) -> dict[str, Any]:
    scope = f"actor:{presenter.actor_id}"
    with ctx.db.tx() as conn:
        replay = idempotency.lookup(conn, scope, "resetDemo", key, idempotency.request_hash("reset"))
        if replay:
            return replay.body
        job = create_job(conn, actor_id=presenter.actor_id, case_id=None, kind="reset", status="running")
        body = {"deletion_job_id": job["id"]}
        idempotency.store(conn, scope, "resetDemo", key, idempotency.request_hash("reset"), 202, body,
                          actor_id=presenter.actor_id, case_id=None)
        record_event(conn, "reset_requested", "running", operation_id="resetDemo", actor_ref=presenter.actor_id)
    try:
        ctx.jobs.submit(lambda: _reset_sync(ctx, presenter.actor_id, job["id"]))
    except Exception:  # #263: a committed reset is never left without a worker
        _reset_sync(ctx, presenter.actor_id, job["id"])
    return body


def _local_case(ctx, scenario: dict[str, Any], written: bool = False
                ) -> tuple[str, GateDecision, list[ConfirmedContextWrite], list[str]]:
    """Local mode (ADR-016): the scenario's synthetic concern, its gate and its red-flag checklist answer. `written`
    (#358): the checklist is answered "none of these apply", so only the written concern can route the case."""
    local = scenario.get("local_mode") or {}
    if not local.get("available"):
        raise not_found()
    flags = [] if written else list(local["red_flags"])
    check_red_flags(flags, ctx.pathway)
    if local.get("limited_reason") == "unsupported_scope":
        # The scope branch is chosen by the presenter, as in mock mode; no model is asked.
        gate = GateDecision("limited", "unsupported_scope")
    else:
        gate = initial_gate(ctx.settings.mode, scenario["id"], ctx.pathway, flags)
    checklist = ConfirmedContextWrite.model_validate({"kind": RED_FLAGS_KIND, "value": flags, "units": None,
                                                     "origin": "user", "profile_revision": None})
    return local["concern"], gate, [checklist], flags



# --- #316 quick demos: synthetic answers, prepared result and the screen to open ----------------------------------

# A09's default search (apps/web/src/screens/A09.tsx defaultCriteria); a scenario's `doctor_search` may require a plan.
DEFAULT_CRITERIA = {"location": {"location_id": None, "city": "Dallas", "region": "TX", "postal_code": None},
                    "radius_miles": 25, "specialty_ids": ["primary_care"], "exact_plan_id": None,
                    "required_verified_plan": False, "visit_type": "in_person", "language": None,
                    "required_language": False, "ranked_preferences": []}
# The guidance job's sanitized codes that the presenter may see; anything else is reported generically. The urgent
# routing code drops its level (#275: the presenter learns that the device routed the case, not how urgent it is).
PRESENTER_CODES = {"OUTPUT_VALIDATION_FAILED", "GENERATION_FAILED", "MODEL_UNAVAILABLE", "MODEL_OUTPUT_INVALID",
                   "QUEUE_FULL", "INTERRUPTED",
                   "SERVICE_LIMITED", "TIMEOUT", "RUNTIME_UNAVAILABLE", "SUBMIT_FAILED", "REVISION_CHANGED",
                   "PREPARE_TIMEOUT", "CASE_DELETED"}


def quick_block(scenario: dict[str, Any]) -> dict[str, Any]:
    """The scenario's synthetic quick-demo input (fixture `local_mode.quick`). The question and choice IDs of the mock
    templates (fixtures/questions.json) and the reviewed general-adult templates are the same, so one block serves
    both modes. Synthetic input only: the clinical behaviour stays the reviewed pathway's."""
    return (scenario.get("local_mode") or {}).get("quick") or {}


def doctor_criteria(quick: dict[str, Any]) -> dict[str, Any] | None:
    search = quick.get("doctor_search")
    if not search:
        return None
    return {**DEFAULT_CRITERIA, "exact_plan_id": search.get("exact_plan_id"),
            "required_verified_plan": bool(search.get("required_verified_plan"))}


def next_path(case_id: str, state: str, prepare: str, quick: dict[str, Any]) -> str:
    """The patient-site path of the screen to open for a loaded case (#315); mirrors the web's screenForState. A case
    being prepared opens at its result screen (#316); a doctor result names the A10 search preset to run."""
    if state == "urgent":
        return f"/app/cases/{case_id}/urgent"
    if state == "limited":
        return "/app/limits"
    if prepare == "result":
        search = quick.get("doctor_search")
        if quick.get("result_view") == "doctors" and search:
            return f"/app/cases/{case_id}/doctors?preset={search['preset']}"
        return f"/app/cases/{case_id}/guidance"
    return f"/app/cases/{case_id}/questions"


def quick_value(question: dict[str, Any], answers: dict[str, Any]) -> Any:
    """The fixture's synthetic answer for this template, else a safe deterministic choice (first option, the scale's
    minimum, a neutral sentence, the shortest duration). save_answer still validates it against the issued question."""
    if question["template_id"] in answers:
        return answers[question["template_id"]]
    kind = question["response_type"]
    if kind == "single_choice":
        return question["choices"][0]["id"]
    if kind == "multiple_choice":
        return [next(c["id"] for c in question["choices"] if not c["exclusive"])]
    if kind == "scale":
        return question["constraints"]["minimum"]
    if kind == "duration":
        return {"amount": 1, "unit": question["constraints"]["allowed_units"][0]}
    return "Nothing else to add."


def _demo_session(ctx, session_id: str) -> SessionInfo:
    with ctx.db.read() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return SessionInfo(id=row["id"], actor_id=row["actor_id"], mode=row["mode"], role=row["role"],
                       consent_version=row["consent_version"], consent_at=row["consent_at"],
                       adult_eligible=bool(row["adult_eligible"]), created_at=row["created_at"],
                       last_seen_at=row["last_seen_at"],
                       expires_at=effective_expiry(row["last_seen_at"], row["absolute_expires_at"]),
                       csrf_token=row["csrf_token"])


def _finish_prepare(ctx, presenter_actor: str, job_id: str, error_code: str | None,
                    error_detail: list[str] | None = None) -> None:
    _PREPARE_GUIDANCE.pop(job_id, None)
    with ctx.db.tx() as conn:
        if error_code is None:
            finish_job(conn, job_id, "succeeded", result_id=job_id, result_type="prepare_receipt")
            record_event(conn, "scenario_prepared", "succeeded", operation_id="loadScenario", actor_ref=presenter_actor)
        else:
            finish_job(conn, job_id, "failed", error_code=error_code, error_detail=error_detail)
            record_event(conn, "scenario_prepare_failed", "failed", operation_id="loadScenario",
                         error_code=error_code, actor_ref=presenter_actor)


def _wait_guidance(ctx, job_id: str, prepare_job_id: str) -> tuple[str, str | None]:
    """Wait for the demo patient's guidance job; stop early when a reset cancelled the prepare job or at shutdown."""
    cap = time.monotonic() + ctx.settings.generation_deadline_seconds * 4 + 60  # a full queue ahead, then this job
    while True:
        with ctx.db.read() as conn:
            job = conn.execute("SELECT status, error_code FROM jobs WHERE id=?", (job_id,)).fetchone()
            mine = conn.execute("SELECT status FROM jobs WHERE id=?", (prepare_job_id,)).fetchone()
        if job is None or job["status"] in TERMINAL:
            return (job["status"], job["error_code"]) if job else ("cancelled", "CASE_DELETED")
        if mine is None or mine["status"] in TERMINAL:
            return "cancelled", "RESET"
        if ctx.jobs.stopping.is_set():
            return "failed", "INTERRUPTED"
        if time.monotonic() > cap:
            return "failed", "PREPARE_TIMEOUT"
        time.sleep(0.1)


def prepare_stage(ctx, job: dict[str, Any]) -> str | None:
    """#548: the step a running quick demo is on, from real state only, for the presenter's progress dialog:
    "preparing" (the synthetic answers are being saved), "queued" (its guidance job waits for the device), then, from
    the device's model calls since the guidance job started: "screening" (the red-flag screen of the person's words),
    "writing" (the draft), "rewriting" (the one repair draft after a failed check) and "checking" (the draft's checks
    and the certainty review), and "finishing" (the guidance is done; the doctor search runs). None for any other job
    or a finished one. Content-free: a step name, never the case or the model's text. The device's model serves one
    guidance job at a time (central admission), so the calls since this guidance job started are its own; a concern
    screen of another session in that window could show as "screening" for a moment."""
    if job.get("kind") != PREPARE_KIND or job.get("status") not in {"queued", "running"}:
        return None
    guidance_id = _PREPARE_GUIDANCE.get(job["id"])
    if guidance_id is None:
        return "preparing"
    with ctx.db.read() as conn:
        row = conn.execute("SELECT status, started_at FROM jobs WHERE id=?", (guidance_id,)).fetchone()
    if row is None or row["status"] == "queued" or not row["started_at"]:
        return "queued"
    if row["status"] in TERMINAL:
        return "finishing"
    recent = getattr(ctx.runtime, "recent_calls", None)
    since = parse(row["started_at"]).timestamp() - 0.5  # the job's start is stored to the microsecond
    calls = [c for c in (recent() if callable(recent) else []) if c["started"] >= since]
    if not calls:
        return "preparing"
    last = calls[-1]
    if last["task"] == "guidance":
        if last["ended"] is not None:
            return "checking"  # the draft is in; the validator (and perhaps the certainty review) checks it
        return "rewriting" if sum(c["task"] == "guidance" for c in calls) > 1 else "writing"
    return _STAGE_OF_TASK.get(last["task"], "checking")


def _presenter_code(code: str | None) -> str:
    if code and code.startswith("RED_FLAG_DESCRIBED"):
        return "RED_FLAG_DESCRIBED"
    return code if code in PRESENTER_CODES else "GENERATION_FAILED"


def _prepare_result(ctx, presenter_actor: str, job_id: str, session_id: str, case_id: str,
                    scenario: dict[str, Any]) -> None:
    """The quick demo's path as the demo patient actor, through the patient services (same rules and audit)."""
    from app.modules.cases import service as cases
    from app.modules.cases.schemas import ReviewRequest
    from app.modules.guidance import service as guidance
    from app.modules.intake import service as intake
    from app.modules.intake.schemas import AnswerWrite
    from app.modules.providers import service as providers
    from app.modules.providers.schemas import ProviderCriteria

    quick = quick_block(scenario)
    answers = quick.get("answers") or {}
    try:
        demo = _demo_session(ctx, session_id)
        revision = cases.read_case(ctx, demo, case_id)["case"]["revision"]
        for _ in range(intake.MAX_SLOTS + 1):
            step = intake.next_question(ctx, demo, case_id, revision, str(uuid.uuid4()))
            if step["kind"] == "review_required":
                break
            question = step["question"]
            try:
                body = AnswerWrite.model_validate({"expected_revision": revision, "status": "answered",
                                                   "value": quick_value(question, answers)})
                revision = intake.save_answer(ctx, demo, case_id, question["id"], body)["case_revision"]
            except (ApiError, ValueError):
                return _finish_prepare(ctx, presenter_actor, job_id, "QUICK_ANSWER_INVALID")
        revision = cases.confirm_review(ctx, demo, case_id, ReviewRequest(expected_revision=revision,
                                                                           facts_confirmed=True))["revision"]
        started = guidance.start_generation(ctx, demo, case_id, revision, str(uuid.uuid4()))
        # #567: kept until the prepare job finishes (_finish_prepare), so the doctor search after the guidance reports
        # "finishing" instead of falling back to "preparing"
        _PREPARE_GUIDANCE[job_id] = started["id"]
        status, code = _wait_guidance(ctx, started["id"], job_id)
        if status != "succeeded":
            # The case stays as the guidance service left it (limited with a retry, urgent, or reviewed when refused),
            # exactly as for a patient; nothing is substituted. #538: the presenter's job carries the guidance job's
            # content-free rejection reasons (rule codes and places), so a failed quick demo can be diagnosed.
            with ctx.db.read() as conn:
                row = conn.execute("SELECT error_detail FROM jobs WHERE id=?", (started["id"],)).fetchone()
            detail = json.loads(row["error_detail"]) if row and row["error_detail"] else None
            return _finish_prepare(ctx, presenter_actor, job_id, "RESET" if code == "RESET" else _presenter_code(code),
                                   detail)
        criteria = doctor_criteria(quick)
        if criteria is not None:
            try:
                providers.search(ctx, demo, case_id, revision, ProviderCriteria.model_validate(criteria))
            except ApiError as exc:
                # Urgent guidance offers no doctor matching (#269); the guidance itself stays published.
                return _finish_prepare(ctx, presenter_actor, job_id,
                                       "DOCTOR_MATCHING_NOT_OFFERED" if exc.code == "STATE_CONFLICT" else exc.code)
        _finish_prepare(ctx, presenter_actor, job_id, None)
    except ApiError as exc:
        code = {"NOT_FOUND": "CASE_DELETED", "SESSION_REQUIRED": "CASE_DELETED"}.get(exc.code, exc.code)
        _finish_prepare(ctx, presenter_actor, job_id, code if code in PRESENTER_CODES | {
            "STATE_CONFLICT", "REVISION_CONFLICT"} else "PREPARE_FAILED")
    except Exception:  # noqa: BLE001  (a prepare job always ends; the case keeps whatever state it reached)
        _finish_prepare(ctx, presenter_actor, job_id, "PREPARE_FAILED")


def _live_demo_actor(conn, presenter_actor: str) -> str | None:
    """This presenter's demo patient with a session that is still valid (#316, reset=false); #396: of any presenter
    session of this browser, so the patient tab keeps one demo patient across presenter sessions. An actor whose
    sessions all ended is never revived: the retention sweep removes its data."""
    now = utcnow()
    kinds = _lineage_demo_kinds(conn, presenter_actor)
    rows = conn.execute("SELECT s.actor_id, s.last_seen_at, s.absolute_expires_at, a.created_at FROM sessions s "
                        f"JOIN actors a ON a.id = s.actor_id WHERE a.kind IN ({_marks(kinds)}) AND a.deleting=0 "
                        "AND s.revoked=0 ORDER BY a.created_at DESC", kinds).fetchall()
    for r in rows:
        if now < parse(effective_expiry(r["last_seen_at"], r["absolute_expires_at"])):
            return r["actor_id"]
    return None


def _screen_written(ctx, presenter_actor: str, concern: str) -> list[str]:
    """#358: createCase's screen of the written concern (#153), run on the device's model in local mode. Fails closed:
    a screen that could not run creates nothing (the presenter sees the content-free code). #397: through the
    central admission's screening lane, like createCase (429 QUEUE_FULL with Retry-After when it is full)."""
    with ctx.jobs.screening(presenter_actor, None, ctx.settings.concern_screen_timeout_seconds):
        described, deferred = rf_screen.screen_concern(ctx, concern)
    if deferred:
        raise ApiError(503, "RED_FLAG_SCREEN_UNAVAILABLE",
                       "The local AI's warning-sign screen did not answer; nothing was created.", retryable=True)
    return described


def load(ctx, presenter: SessionInfo, scenario_id: str, key: str, reset: bool = True,
         prepare: str = "start", urgency_input: str = "checklist") -> tuple[dict[str, Any], str]:
    """Return (ScenarioLoaded body, demo patient session token for the patient cookie).

    #435: the load spans two transactions (the reset and the written concern's screen run between them), so it runs
    serialized per Idempotency-Key: a concurrent duplicate waits for the first and replays its 201 response, instead of
    missing the lookup and failing on the store (500) or finding the first one's reset pending (409)."""
    try:
        with idempotency.serialized(f"actor:{presenter.actor_id}", "loadScenario", key):
            return _load(ctx, presenter, scenario_id, key, reset, prepare, urgency_input)
    except ApiError as exc:
        if exc.status == 429:  # the busy refusal, counted content-free (ADR-017)
            with ctx.db.tx() as conn:
                record_event(conn, "admission_refused", "refused", operation_id="loadScenario", error_code=exc.code,
                             actor_ref=presenter.actor_id)
        raise


def _load(ctx, presenter: SessionInfo, scenario_id: str, key: str, reset: bool, prepare: str,
          urgency_input: str) -> tuple[dict[str, Any], str]:
    if scenario_id not in ctx.fixtures.scenarios:
        raise not_found()
    scenario = ctx.fixtures.scenarios[scenario_id]
    written = urgency_input == "written" and ctx.settings.mode == "local"
    if ctx.settings.mode == "local":
        concern, gate, context, flags = _local_case(ctx, scenario, written)
    else:
        # Mock mode: the scenario's scripted outcome, whichever input is named (ADR-007; labelled scripted).
        concern, gate, context, flags = scenario["concern"], initial_gate(ctx.settings.mode, scenario_id), [], []
    scope = f"actor:{presenter.actor_id}"
    # The request of earlier releases ({"reset": true}) keeps its idempotency hash, and so does every request of
    # #316 that names no urgency input.
    if (reset, prepare, urgency_input) == (True, "start", "checklist"):
        req_hash = idempotency.request_hash(scenario_id)
    elif urgency_input == "checklist":
        req_hash = idempotency.request_hash(scenario_id, reset, prepare)
    else:
        req_hash = idempotency.request_hash(scenario_id, reset, prepare, urgency_input)
    with ctx.db.tx() as conn:
        replay = idempotency.lookup(conn, scope, "loadScenario", key, req_hash)
        if replay:
            # Response was lost: rotate the demo session token so this browser can still use the loaded case.
            row = conn.execute("SELECT id FROM sessions WHERE id=? AND revoked=0",
                               (replay.body["session"]["id"],)).fetchone()
            if row is None:
                raise ApiError(409, "IDEMPOTENCY_CONFLICT", "That demo session has ended. Load the scenario again.")
            token = new_token()
            conn.execute("UPDATE sessions SET token_hash=? WHERE id=?", (hash_token(token), row["id"]))
            return replay.body, token
        _reset_blocker(conn, presenter.actor_id)
        job = create_job(conn, actor_id=presenter.actor_id, case_id=None, kind="reset", status="running") if reset \
            else None
    if job is not None:
        _reset_sync(ctx, presenter.actor_id, job["id"], operation_id="loadScenario")
    # #358: the written concern's screen runs outside any transaction (a model call), after a replay was ruled out.
    described = _screen_written(ctx, presenter.actor_id, concern) if written and gate.state == "intake" else []
    if described:
        gate = GateDecision("urgent")
    quick = quick_block(scenario)
    prepared = prepare == "result" and gate.state == "intake"
    with ctx.db.tx() as conn:
        _reset_blocker(conn, presenter.actor_id)
        actor_id = None if reset else _live_demo_actor(conn, presenter.actor_id)
        if actor_id is None:
            actor_id = str(uuid.uuid4())
            conn.execute("INSERT INTO actors (id, kind, created_at) VALUES (?,?,?)",
                         (actor_id, _demo_kind(presenter.actor_id), iso(utcnow())))
        issued, token, _ = _issue(conn, actor_id, CreateSessionRequest(
            mode="guest", consent_version=CURRENT_CONSENT_VERSION, adult_eligible=True))
        session_row = conn.execute("SELECT * FROM sessions WHERE id=?", (issued["session_id"],)).fetchone()
        case_id = str(uuid.uuid4())
        now = iso(utcnow())
        if described:
            # As createCase records a screened match (#87, #153): the level and the IDs behind it, with revision 1.
            conn.execute("INSERT INTO cases (id, actor_id, revision, state, concern, scenario_id, limited_reason, "
                         "created_at, updated_at, urgent_level, urgent_rule_ids, urgent_revision) "
                         "VALUES (?,?,1,'urgent',?,?,NULL,?,?,?,?,1)",
                         (case_id, actor_id, concern, scenario_id, now, now,
                          rf_screen.highest_level(ctx.pathway, described), dumps(sorted(described))))
        else:
            conn.execute("INSERT INTO cases (id, actor_id, revision, state, concern, scenario_id, limited_reason, "
                         "created_at, updated_at, urgent_level) VALUES (?,?,1,?,?,?,?,?,?,?)",
                         (case_id, actor_id, gate.state, concern, scenario_id, gate.limited_reason, now, now,
                          rf_screen.ticked_level(ctx.pathway, flags) if gate.state == "urgent" else None))
        _insert_context(conn, case_id, context)
        prepare_job = create_job(conn, actor_id=presenter.actor_id, case_id=None, kind=PREPARE_KIND,
                                 status="running") if prepared else None
        session = {"id": session_row["id"], "actor_id": actor_id, "mode": "guest", "role": "patient",
                   "consent_version": session_row["consent_version"], "consent_at": session_row["consent_at"],
                   "adult_eligible": True, "created_at": session_row["created_at"],
                   "last_seen_at": session_row["last_seen_at"],
                   # #269: the effective expiry (the earlier of the idle and absolute limits), as every session reports
                   "expires_at": effective_expiry(session_row["last_seen_at"], session_row["absolute_expires_at"])}
        body = {"session": session, "case_id": case_id, "scenario_id": scenario_id, "synthetic": True,
                "state": gate.state, "next_path": next_path(case_id, gate.state, prepare, quick),
                "prepare_job_id": prepare_job["id"] if prepare_job else None}
        idempotency.store(conn, scope, "loadScenario", key, req_hash, 201, body,
                          actor_id=presenter.actor_id, case_id=None)
        record_event(conn, "scenario_loaded", "succeeded", operation_id="loadScenario", actor_ref=presenter.actor_id)
        if flags:
            record_event(conn, "urgent_interrupt", "urgent", operation_id="loadScenario", actor_ref=presenter.actor_id)
        if described:
            record_event(conn, "urgent_interrupt", "urgent", operation_id="loadScenario",
                         error_code=DESCRIBED_EVENT_CODE, actor_ref=presenter.actor_id)
    if prepare_job is not None:
        work = lambda: _prepare_result(ctx, presenter.actor_id, prepare_job["id"], session_row["id"],  # noqa: E731
                                       case_id, scenario)
        try:
            ctx.jobs.submit_prepare(work)
        except Exception:  # a committed prepare job is never left without a worker
            _finish_prepare(ctx, presenter.actor_id, prepare_job["id"], "SUBMIT_FAILED")
    return body, token
