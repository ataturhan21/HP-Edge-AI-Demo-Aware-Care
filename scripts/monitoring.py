#!/usr/bin/env python3
"""ADR-003 monthly monitoring: content-free usage counts and the monthly clinician sample (issue #63; R36, R38, R39).

Usage counts
  The API keeps content-free events (kind, operation, status, error code, duration; no text) and deletes them after 30
  days (R36). A once-a-month query would lose the start of the month, so `collect` saves the counts of every completed
  UTC day that is still fully inside the retention window. Run it at least every 25 days; weekly is recommended.
  Collected days are never overwritten. `report` builds a month from the saved days and states its coverage.

      python3 scripts/monitoring.py collect --db <data_root>/data/local/awarecare.sqlite3 \
          --store <data_root>/monitoring/local
      python3 scripts/monitoring.py report --store <data_root>/monitoring/local --month 2026-10 --out usage.json

  The database is opened read-only, and only the `events` table is read. The store holds aggregates only and lives
  outside Git and the images. Every count is operational usage of a synthetic demo, never outcome evidence (R39).

Clinician sample
  Each month a seeded synthetic sample goes through the app's own local path with the reviewed pathway's decision.
  The clinician grades it in a worksheet, and the grades give the month's satisfaction rate. A "wrong" grade on a
  borderline case is an ADR-003 re-review trigger.

      cd apps/api && uv run python ../../scripts/monitoring.py review-sample --month 2026-11 --out <dir>
      python3 scripts/monitoring.py review-worksheet --answers <dir>/answers.json --out <dir>/worksheet.html
      python3 scripts/monitoring.py review-score --answers <dir>/answers.json --grades <grades.json> --out review.json

  `review-sample` needs ZRT serving the selected model and runs from apps/api (it imports the app). The other
  subcommands use the standard library only.
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RETENTION = timedelta(days=30)        # privacy/service.py deletes events older than this
SAFETY_MARGIN = timedelta(hours=6)    # a day is collected only while it is still well inside retention
STORE_SCHEMA = "aware-care-usage-daily/1"
REPORT_SCHEMA = "aware-care-usage-month/1"
REVIEW_SCHEMA = "aware-care-monthly-review/1"
DEFAULT_CASES = ROOT / "evidence/clinical-review/2026-10-15/cases.json"
GRADES = ("correct", "acceptable", "wrong")
NOT_OUTCOME = ("Operational usage counts from content-free events (R38). All traffic in this demo is synthetic, "
               "including deployment checks and test journeys. These counts are not outcome evidence: none of them is "
               "an avoided visit, a saving or a clinical outcome (R39).")


# --- usage counts ----------------------------------------------------------------------------------------------

def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def collectable_days(now: datetime) -> list[date]:
    """Completed UTC days whose every event is still inside the retention window."""
    oldest = now - RETENTION + SAFETY_MARGIN
    first = (oldest + timedelta(days=1)).date() if oldest.time() != datetime.min.time() else oldest.date()
    days, day = [], first
    while datetime.combine(day + timedelta(days=1), datetime.min.time(), timezone.utc) <= now:
        days.append(day)
        day += timedelta(days=1)
    return days


def read_events(db: Path) -> list[sqlite3.Row]:
    """Only the content-free `events` table, opened read-only."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT ts, kind, operation_id, status, error_code, duration_ms FROM events").fetchall()
    finally:
        conn.close()


def aggregate_day(rows: list[sqlite3.Row]) -> dict[str, Any]:
    counts: Counter = Counter()
    errors: Counter = Counter()
    durations: list[float] = []
    for r in rows:
        counts[f"{r['kind']}|{r['operation_id'] or '-'}|{r['status']}"] += 1
        if r["error_code"]:
            errors[f"{r['kind']}|{r['error_code']}"] += 1
        if r["kind"] == "guidance_published" and r["duration_ms"] is not None:
            durations.append(round(float(r["duration_ms"]), 1))
    return {"events": dict(sorted(counts.items())), "errors": dict(sorted(errors.items())),
            "guidance_ms": sorted(durations)}


def load_store(store: Path) -> dict[str, Any]:
    path = store / "daily.json"
    if not path.exists():
        return {"schema": STORE_SCHEMA, "days": {}}
    data = json.loads(path.read_text())
    if data.get("schema") != STORE_SCHEMA:
        raise SystemExit(f"{path} is not a {STORE_SCHEMA} store")
    return data


def collect(db: Path, store: Path, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    data = load_store(store)
    by_day: dict[str, list[sqlite3.Row]] = {}
    for r in read_events(db):
        by_day.setdefault(_utc(r["ts"]).date().isoformat(), []).append(r)
    added = []
    for day in collectable_days(now):
        key = day.isoformat()
        if key in data["days"]:
            continue  # a saved day is final; later runs may see it partly purged
        data["days"][key] = {"collected_at": now.isoformat(timespec="seconds"), **aggregate_day(by_day.get(key, []))}
        added.append(key)
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = store / "daily.json.tmp"
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    tmp.replace(store / "daily.json")
    return {"added": added, "days_stored": len(data["days"]), "store": str(store / "daily.json")}


def _percentile(values: list[float], q: float) -> float | None:
    """Linear interpolation between closest ranks, the definition qualify_model.pct uses (#301), so the monthly
    report and the qualification gates give the same p50/p95 for the same values."""
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 3)


def _sum(events: dict[str, int], kind: str, status: str | None = None, operation: str | None = None) -> int:
    total = 0
    for key, n in events.items():
        k, op, st = key.split("|")
        if k == kind and (status is None or st == status) and (operation is None or op == operation):
            total += n
    return total


def _rejections(errors: Counter, place: bool) -> dict[str, int]:
    """#538: `guidance_rejection|<attempt>:<rule>[@<place>]` error counts, summed per rule (or rule and place)."""
    out: Counter = Counter()
    for key, n in errors.items():
        if key.startswith("guidance_rejection|"):
            item = key.split("|", 1)[1].split(":", 1)[-1]
            out[item if place else item.split("@", 1)[0]] += n
    return dict(sorted(out.items()))


def report(store: Path, month: str, mode: str | None = None) -> dict[str, Any]:
    first = date.fromisoformat(month + "-01")
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    days = [(first + timedelta(days=i)).isoformat() for i in range((nxt - first).days)]
    saved = load_store(store)["days"]
    present = [d for d in days if d in saved]
    events: Counter = Counter()
    errors: Counter = Counter()
    durations: list[float] = []
    for d in present:
        events.update(saved[d]["events"])
        errors.update(saved[d]["errors"])
        durations += saved[d]["guidance_ms"]
    ev = dict(events)
    created = _sum(ev, "case_created")
    published, failed = _sum(ev, "guidance_published"), _sum(ev, "guidance_failed")
    red_flag = _sum(ev, "urgent_interrupt", operation="createCase") + _sum(ev, "urgent_interrupt", operation="editCase")
    rate = lambda n, d: round(n / d, 3) if d else None  # noqa: E731
    return {
        "schema": REPORT_SCHEMA, "month": month, "mode": mode, "note": NOT_OUTCOME,
        "coverage": {"days_in_month": len(days), "days_collected": len(present),
                     "days_missing": [d for d in days if d not in saved]},
        "consultations": {
            "sessions_started": {"guest": _sum(ev, "session_started", "guest"),
                                 "presenter": _sum(ev, "session_started", "presenter")},
            "cases_created": created,
            "created_as": {s: _sum(ev, "case_created", s) for s in ("intake", "urgent", "limited")},
            "red_flag_urgent": red_flag,
            "red_flag_urgent_rate": rate(red_flag, created),
            # general-adult-3 (#79): red flags the screen found in the person's own words, by level.
            "red_flag_described": {k.split("|", 1)[1].removeprefix("RED_FLAG_DESCRIBED_").lower(): n
                                   for k, n in sorted(errors.items()) if k.startswith("urgent_interrupt|RED_FLAG_DESCRIBED_")},
            "limited_at_creation_rate": rate(_sum(ev, "case_created", "limited"), created),
            "questions_issued": _sum(ev, "question_issued"),
            "answers": {s: _sum(ev, "answer_saved", s) for s in ("answered", "unknown", "skipped")},
        },
        "guidance": {
            "requested": _sum(ev, "guidance_requested"), "published": published, "failed": failed,
            "failure_rate": rate(failed, published + failed),
            "failures_by_code": {k.split("|", 1)[1]: n for k, n in sorted(errors.items())
                                 if k.startswith("guidance_failed|")},
            # #538: why fail-closed results stopped: each rejected attempt's validator rule, and the rule with its place
            # ("third_person@actions[0].rationale"); content-free codes from the `guidance_rejection` events.
            "rejections_by_rule": _rejections(errors, place=False),
            "rejections_by_place": _rejections(errors, place=True),
            "total_ms": {"p50": _percentile(durations, 0.5), "p95": _percentile(durations, 0.95),
                         "max": max(durations) if durations else None, "samples": len(durations)},
        },
        "after_guidance": {"provider_searches": _sum(ev, "provider_search"), "exports": _sum(ev, "export_created")},
        "event_counts": dict(sorted(ev.items())),
    }


# --- clinician sample ------------------------------------------------------------------------------------------

def sample_cases(cases: list[dict[str, Any]], month: str, size: int, borderline_share: float = 0.25) -> list[dict]:
    """A reproducible stratified sample for the month: the same month always gives the same cases."""
    if size < 1:  # #301: size 0 asked rng.sample for -1 common cases
        raise ValueError("the sample size must be at least 1")
    rng = random.Random(f"aware-care-monthly-review:{month}")
    common = [c for c in cases if c["kind"] == "common"]
    border = [c for c in cases if c["kind"] == "borderline"]
    n_border = min(len(border), max(1, round(size * borderline_share)))
    picked = rng.sample(border, n_border) + rng.sample(common, min(len(common), size - n_border))
    return sorted(picked, key=lambda c: (c["kind"] != "common", c["id"]))


def review_sample(month: str, size: int, out: Path, cases_path: Path, base_url: str, model_id: str) -> dict:
    """Generate the month's answers through the app's local path with the reviewed pathway (run from apps/api)."""
    import asyncio
    import time
    import uuid
    sys.path.insert(0, str(ROOT / "apps/api"))
    from app.config import load_settings
    from app.modules.guidance import local
    from app.modules.safety.pathway import load_registry
    from app.modules.safety.service import urgency_decision
    from app.runtime.zrt_provider import ZrtRuntimeAdapter

    settings = load_settings()
    pathway = load_registry(settings.pathways_dir)
    if pathway is None or not pathway.active():
        raise SystemExit("no active reviewed pathway; the monthly sample needs the package the app serves")
    manifest = json.loads(settings.model_manifest.read_text())
    adapter = ZrtRuntimeAdapter(base_url, model_id, settings.model_manifest)
    cases = sample_cases(json.loads(cases_path.read_text())["cases"], month, size)
    ns = uuid.uuid5(uuid.NAMESPACE_URL, f"aware-care-monthly-review:{month}")
    rows = []

    async def run() -> None:
        for c in cases:
            facts = [{"id": str(uuid.uuid5(ns, f"{c['id']}/{f['question']}")), "question": f["question"],
                      "answer": f["answer"]} for f in c["facts"]]
            # Every fact is answered and no red flag is ticked, so this is the pathway's policy (a) decision.
            decision = urgency_decision(pathway, answered=len(facts), gaps=0)
            inputs = local.LocalInputs(case_id=str(uuid.uuid5(ns, c["id"])), input_revision=1, concern=c["concern"],
                                       facts=facts, decision=decision)
            row: dict[str, Any] = {"id": c["id"], "kind": c["kind"], "concern": c["concern"],
                                   "facts": [[f["question"], f["answer"]] for f in c["facts"]]}
            t0 = time.perf_counter()
            try:
                result = await local.generate(adapter, inputs, settings.generation_deadline_seconds)
                g = local.to_guidance(inputs, result.draft, manifest_id=manifest["manifest_id"],
                                      created_at=datetime.now(timezone.utc).isoformat())
                row.update(result="published", attempts=result.attempts, reviews=result.reviews,
                           guidance={k: g[k] for k in ("case_summary", "urgency", "actions", "clinician_questions",
                                                       "escalation_advice", "uncertainties", "claims")})
            except local.LocalGenerationFailed as exc:
                row.update(result="fallback", failure=exc.code, attempts=exc.attempts)
            row["seconds"] = round(time.perf_counter() - t0, 2)
            rows.append(row)
            print(c["id"], row["result"], row.get("guidance", {}).get("urgency", {}).get("level"), row["seconds"],
                  flush=True)

    asyncio.run(run())
    doc = {"schema": REVIEW_SCHEMA, "month": month, "generated_at": datetime.now(timezone.utc).isoformat(),
           "model": manifest["manifest_id"], "prompt": local.PROMPT_VERSION, "prompt_sha256": local.PROMPT_SHA256,
           "pathway": pathway.version, "cases_source": str(cases_path.relative_to(ROOT)) if cases_path.is_relative_to(ROOT)
           else cases_path.name, "cases": rows}
    out.mkdir(parents=True, exist_ok=True)
    (out / "answers.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return {"answers": str(out / "answers.json"), "cases": len(rows),
            "published": sum(r["result"] == "published" for r in rows)}


def review_worksheet(answers: dict[str, Any], template: Path) -> str:
    cases = []
    for r in answers["cases"]:
        attempts = r.get("attempts") or []
        cases.append({"id": r["id"], "kind": r["kind"], "concern": r["concern"], "facts": r["facts"],
                      "guidance": r.get("guidance"), "failure": r.get("failure"), "seconds": r.get("seconds"),
                      "attempts": len(attempts) if isinstance(attempts, list) else attempts})
    data = {"month": answers["month"], "model": answers["model"], "pathway": answers["pathway"], "cases": cases}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return template.read_text().replace("__DATA__", blob)


def review_score(answers: dict[str, Any], grades: dict[str, Any]) -> dict[str, Any]:
    """Satisfaction rate = (correct + acceptable) / graded. A borderline "wrong" requires an ADR-003 re-review."""
    kinds = {r["id"]: r["kind"] for r in answers["cases"]}
    unknown = sorted(set(grades) - set(kinds))
    if unknown:
        raise SystemExit(f"grades for cases not in this sample: {unknown}")
    bad = sorted(k for k, g in grades.items() if g.get("grade") not in GRADES)
    if bad:
        raise SystemExit(f"invalid grades: {bad}")
    counts = Counter(g["grade"] for g in grades.values())
    graded = sum(counts.values())
    wrong = sorted(k for k, g in grades.items() if g["grade"] == "wrong")
    borderline_wrong = [k for k in wrong if kinds[k] == "borderline"]
    return {
        "schema": REVIEW_SCHEMA + "+score", "month": answers["month"], "model": answers["model"],
        "pathway": answers["pathway"], "cases": len(kinds), "graded": graded,
        "ungraded": sorted(set(kinds) - set(grades)),
        "grades": {g: counts.get(g, 0) for g in GRADES},
        "satisfaction_rate": round((counts["correct"] + counts["acceptable"]) / graded, 3) if graded else None,
        "wrong": wrong, "borderline_wrong": borderline_wrong,
        "rereview_required": bool(borderline_wrong),
        "complete": graded == len(kinds),
    }


# --- command line ----------------------------------------------------------------------------------------------

def _write(obj: dict[str, Any], out: str | None) -> None:
    text = json.dumps(obj, indent=1, ensure_ascii=False)
    if out:
        Path(out).write_text(text + "\n")
    print(text)


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("collect", help="save the counts of completed days still inside retention")
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--store", required=True, type=Path)
    p = sub.add_parser("report", help="build a month's usage report from the saved days")
    p.add_argument("--store", required=True, type=Path)
    p.add_argument("--month", required=True)
    p.add_argument("--mode", choices=["mock", "local"])
    p.add_argument("--out")
    p = sub.add_parser("review-sample", help="generate the month's synthetic sample through the local path")
    p.add_argument("--month", required=True)
    p.add_argument("--size", type=_positive_int, default=20)
    p.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--base-url", default="http://127.0.0.1:8080/v1")
    p.add_argument("--model-id", default="qwen3.6-35b-a3b-fp8")
    p = sub.add_parser("review-worksheet", help="build the grading page from a sample")
    p.add_argument("--answers", required=True, type=Path)
    p.add_argument("--template", type=Path, default=ROOT / "scripts/monitoring_worksheet.html")
    p.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("review-score", help="score the clinician's grades")
    p.add_argument("--answers", required=True, type=Path)
    p.add_argument("--grades", required=True, type=Path,
                   help="JSON object {case_id: {\"grade\": correct|acceptable|wrong, \"note\": ...}}")
    p.add_argument("--out")
    args = parser.parse_args(argv)
    if args.cmd == "collect":
        _write(collect(args.db, args.store), None)
    elif args.cmd == "report":
        _write(report(args.store, args.month, args.mode), args.out)
    elif args.cmd == "review-sample":
        _write(review_sample(args.month, args.size, args.out, args.cases, args.base_url, args.model_id), None)
    elif args.cmd == "review-worksheet":
        args.out.write_text(review_worksheet(json.loads(args.answers.read_text()), args.template))
        print(args.out)
    else:
        _write(review_score(json.loads(args.answers.read_text()), json.loads(args.grades.read_text())), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
