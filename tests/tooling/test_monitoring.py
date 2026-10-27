"""scripts/monitoring.py: ADR-003 monthly monitoring (issue #63; R36, R38, R39).

Usage counts must survive the API's 30-day event purge without ever reading content. The monthly sample must be
reproducible, and its score must raise the re-review flag on a borderline "wrong".
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import monitoring  # noqa: E402

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


def make_db(path: Path, events: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events (id TEXT PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, operation_id TEXT, "
                 "status TEXT NOT NULL, error_code TEXT, duration_ms REAL)")
    # A content table next to the events: the collector must never read it.
    conn.execute("CREATE TABLE cases (id TEXT, concern TEXT)")
    conn.execute("INSERT INTO cases VALUES ('c1', 'SECRET synthetic concern text')")
    for i, (ts, kind, op, status, err, ms) in enumerate(events):
        conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?)", (f"e{i}", ts, kind, op, status, err, ms))
    conn.commit()
    conn.close()


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "awarecare.sqlite3"
        self.store = self.dir / "store"

    def test_only_completed_days_inside_retention_are_collectable(self):
        days = monitoring.collectable_days(NOW)
        # Retention starts 2026-10-21T09:00Z; with the 6 h margin the first whole day is 2026-10-22.
        self.assertEqual(days[0], date(2026, 10, 22))
        self.assertEqual(days[-1], date(2026, 11, 19))  # today (11-20) is not complete

    def test_collect_counts_events_reads_no_content_and_never_overwrites_a_day(self):
        make_db(self.db, [
            ("2026-11-02T10:00:00Z", "case_created", "createCase", "intake", None, None),
            ("2026-11-02T10:01:00Z", "case_created", "createCase", "urgent", None, None),
            ("2026-11-02T10:01:00Z", "urgent_interrupt", "createCase", "urgent", None, None),
            ("2026-11-02T10:05:00Z", "guidance_published", "generateGuidance", "succeeded", None, 12000.04),
            ("2026-11-02T10:09:00Z", "guidance_failed", "generateGuidance", "failed", "OUTPUT_VALIDATION_FAILED", None),
            ("2026-11-20T08:00:00Z", "case_created", "createCase", "intake", None, None),  # today: not yet
        ])
        before = self.db.read_bytes()
        result = monitoring.collect(self.db, self.store, NOW)
        self.assertEqual(self.db.read_bytes(), before)  # opened read-only
        self.assertIn("2026-11-02", result["added"])
        self.assertNotIn("2026-11-20", result["added"])
        stored = (self.store / "daily.json").read_text()
        self.assertNotIn("SECRET", stored)
        day = json.loads(stored)["days"]["2026-11-02"]
        self.assertEqual(day["events"]["case_created|createCase|urgent"], 1)
        self.assertEqual(day["errors"], {"guidance_failed|OUTPUT_VALIDATION_FAILED": 1})
        self.assertEqual(day["guidance_ms"], [12000.0])
        # The API later purges events; a re-run must keep the saved counts.
        conn = sqlite3.connect(self.db)
        conn.execute("DELETE FROM events")
        conn.commit()
        conn.close()
        again = monitoring.collect(self.db, self.store, NOW)
        self.assertNotIn("2026-11-02", again["added"])
        self.assertEqual(json.loads((self.store / "daily.json").read_text())["days"]["2026-11-02"], day)

    def test_the_monthly_report_states_coverage_rates_and_that_it_is_not_outcome_evidence(self):
        make_db(self.db, [
            ("2026-11-02T10:00:00Z", "case_created", "createCase", "intake", None, None),
            ("2026-11-02T10:00:01Z", "case_created", "createCase", "intake", None, None),
            ("2026-11-02T10:00:02Z", "case_created", "createCase", "urgent", None, None),
            ("2026-11-02T10:00:02Z", "urgent_interrupt", "createCase", "urgent", None, None),
            ("2026-11-03T10:00:00Z", "case_created", "createCase", "limited", None, None),
            ("2026-11-03T10:00:00Z", "urgent_interrupt", "saveAnswer", "urgent", None, None),  # mock fixture trigger
            ("2026-11-03T10:05:00Z", "guidance_published", "generateGuidance", "succeeded", None, 10000.0),
            ("2026-11-03T10:06:00Z", "guidance_published", "generateGuidance", "succeeded", None, 14000.0),
            ("2026-11-03T10:07:00Z", "guidance_failed", "generateGuidance", "failed", "DEADLINE_EXCEEDED", None),
            ("2026-11-03T10:08:00Z", "urgent_interrupt", "generateGuidance", "urgent",
             "RED_FLAG_DESCRIBED_EMERGENCY", None),  # the red-flag screen (#79)
        ])
        monitoring.collect(self.db, self.store, NOW)
        r = monitoring.report(self.store, "2026-11", "local")
        self.assertIn("not outcome evidence", r["note"])
        self.assertIn("R39", r["note"])
        self.assertEqual(r["coverage"]["days_in_month"], 30)
        self.assertEqual(r["coverage"]["days_collected"], 19)  # 11-01 .. 11-19
        self.assertEqual(r["coverage"]["days_missing"][0], "2026-11-20")
        c = r["consultations"]
        self.assertEqual((c["cases_created"], c["red_flag_urgent"]), (4, 1))  # saveAnswer interrupt is no red flag
        self.assertEqual(c["created_as"], {"intake": 2, "urgent": 1, "limited": 1})
        self.assertEqual((c["red_flag_urgent_rate"], c["limited_at_creation_rate"]), (0.25, 0.25))
        self.assertEqual(c["red_flag_described"], {"emergency": 1})
        g = r["guidance"]
        self.assertEqual((g["published"], g["failed"], g["failure_rate"]), (2, 1, 0.333))
        self.assertEqual(g["failures_by_code"], {"DEADLINE_EXCEEDED": 1})
        self.assertEqual(g["total_ms"]["samples"], 2)

    def test_the_report_counts_why_guidance_failed_closed_by_rule_and_place(self):
        """#538: the content-free rejection events of a fail-closed job (one per rejected attempt's rule and place)."""
        make_db(self.db, [
            ("2026-11-03T10:07:00Z", "guidance_failed", "generateGuidance", "failed", "OUTPUT_VALIDATION_FAILED", None),
            ("2026-11-03T10:07:00Z", "guidance_rejection", "generateGuidance", "failed",
             "1:prohibited_certainty/definitive_diagnosis@claims[0].text", None),
            ("2026-11-03T10:07:00Z", "guidance_rejection", "generateGuidance", "failed",
             "2:prohibited_certainty/definitive_diagnosis@claims[0].text", None),
            ("2026-11-03T10:07:00Z", "guidance_rejection", "generateGuidance", "failed",
             "2:third_person@actions[2].rationale", None),
        ])
        monitoring.collect(self.db, self.store, NOW)
        g = monitoring.report(self.store, "2026-11", "local")["guidance"]
        self.assertEqual(g["failures_by_code"], {"OUTPUT_VALIDATION_FAILED": 1})
        self.assertEqual(g["rejections_by_rule"], {"prohibited_certainty/definitive_diagnosis": 2, "third_person": 1})
        self.assertEqual(g["rejections_by_place"], {"prohibited_certainty/definitive_diagnosis@claims[0].text": 2,
                                                    "third_person@actions[2].rationale": 1})

    def test_a_store_of_another_kind_is_refused(self):
        self.store.mkdir()
        (self.store / "daily.json").write_text(json.dumps({"schema": "something-else", "days": {}}))
        with self.assertRaises(SystemExit):
            monitoring.load_store(self.store)


class ReviewTest(unittest.TestCase):
    cases = json.loads(monitoring.DEFAULT_CASES.read_text())["cases"]

    def test_the_monthly_sample_is_reproducible_stratified_and_changes_by_month(self):
        a = monitoring.sample_cases(self.cases, "2026-11", 20)
        self.assertEqual([c["id"] for c in a], [c["id"] for c in monitoring.sample_cases(self.cases, "2026-11", 20)])
        self.assertEqual(len(a), 20)
        self.assertEqual(sum(c["kind"] == "borderline" for c in a), 5)
        self.assertNotEqual([c["id"] for c in a], [c["id"] for c in monitoring.sample_cases(self.cases, "2026-12", 20)])

    def answers(self):
        return {"month": "2026-11", "model": "m", "pathway": "general-adult-1",
                "cases": [{"id": "C01", "kind": "common", "concern": "x", "facts": [["Age", "40"]], "seconds": 1,
                           "attempts": [{}], "guidance": None, "failure": "OUTPUT_VALIDATION_FAILED"},
                          {"id": "B01", "kind": "borderline", "concern": "</script><b>y", "facts": [], "seconds": 1,
                           "attempts": [{}, {}]}]}

    def test_score_gives_the_satisfaction_rate_and_flags_a_borderline_wrong(self):
        s = monitoring.review_score(self.answers(), {"C01": {"grade": "acceptable"}, "B01": {"grade": "wrong"}})
        self.assertEqual((s["satisfaction_rate"], s["borderline_wrong"], s["rereview_required"]), (0.5, ["B01"], True))
        s = monitoring.review_score(self.answers(), {"C01": {"grade": "wrong"}})
        self.assertEqual((s["rereview_required"], s["complete"], s["ungraded"]), (False, False, ["B01"]))
        with self.assertRaises(SystemExit):
            monitoring.review_score(self.answers(), {"C01": {"grade": "great"}})
        with self.assertRaises(SystemExit):
            monitoring.review_score(self.answers(), {"X99": {"grade": "correct"}})

    def test_the_october_baseline_is_the_adr_003_review(self):
        review = json.loads((ROOT / "evidence/clinical-review/2026-10-15/review.json").read_text())
        answers = {"month": "2026-10", "model": "qwen3.6-35b-a3b-fp8@95a723d0", "pathway": "general-adult-1",
                   "cases": [{"id": g["id"], "kind": g["kind"]} for g in review["grades"]]}
        s = monitoring.review_score(answers, {g["id"]: {"grade": g["grade"]} for g in review["grades"]})
        self.assertEqual((s["graded"], s["satisfaction_rate"], s["rereview_required"]), (50, 1.0, False))

    def test_the_worksheet_embeds_the_sample_safely(self):
        page = monitoring.review_worksheet(self.answers(), ROOT / "scripts/monitoring_worksheet.html")
        self.assertNotIn("__DATA__", page)
        self.assertNotIn("</script><b>", page)  # case text cannot close the data block
        data = page.split('id="review-data">', 1)[1].split("</script>", 1)[0].replace("<\\/", "</")
        parsed = json.loads(data)
        self.assertEqual([c["attempts"] for c in parsed["cases"]], [1, 2])
        self.assertEqual(parsed["pathway"], "general-adult-1")


if __name__ == "__main__":
    unittest.main()
