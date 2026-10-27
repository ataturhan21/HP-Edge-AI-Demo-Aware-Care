"""SQLite persistence with serialized writes (single-device demo store).

All health rows carry an ownership chain to an actor. Writes run inside one
process-wide lock plus an IMMEDIATE transaction, which is the single-writer
equivalent of a case row lock required by spec/engineering/02-state-and-intake.md.
A multi-process deployment needs a different coordination mechanism.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS actors (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at TEXT NOT NULL,
  deletion_generation INTEGER NOT NULL DEFAULT 0, deleting INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE, csrf_token TEXT NOT NULL, mode TEXT NOT NULL, role TEXT NOT NULL,
  consent_version TEXT NOT NULL, consent_at TEXT NOT NULL, adult_eligible INTEGER NOT NULL,
  created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, absolute_expires_at TEXT NOT NULL,
  revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL CHECK (revision >= 1), state TEXT NOT NULL, concern TEXT NOT NULL,
  issued_slots INTEGER NOT NULL DEFAULT 0 CHECK (issued_slots BETWEEN 0 AND 10),
  reviewed_revision INTEGER, latest_guidance_id TEXT, scenario_id TEXT NOT NULL,
  limited_reason TEXT, generation_attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT, urgent_level TEXT,
  urgent_rule_ids TEXT, urgent_revision INTEGER);
CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, value_json TEXT NOT NULL, units TEXT, provenance TEXT NOT NULL,
  source_id TEXT, page INTEGER, status TEXT NOT NULL, original_text TEXT, confirmed_at TEXT,
  reference_range TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  display_name TEXT NOT NULL, media_type TEXT NOT NULL, byte_count INTEGER NOT NULL, page_count INTEGER,
  sha256 TEXT NOT NULL, status TEXT NOT NULL, storage_key TEXT, input_revision INTEGER NOT NULL,
  error_code TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fact_reviews (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE, fact_id TEXT NOT NULL,
  action TEXT NOT NULL, prior_value_json TEXT NOT NULL, new_value_json TEXT, prior_units TEXT, new_units TEXT,
  case_revision INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS questions (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  slot INTEGER NOT NULL CHECK (slot BETWEEN 1 AND 10), template_id TEXT NOT NULL,
  pathway_version TEXT NOT NULL, issued_revision INTEGER NOT NULL, status TEXT NOT NULL,
  UNIQUE (case_id, slot));
CREATE TABLE IF NOT EXISTS answers (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  question_id TEXT NOT NULL UNIQUE REFERENCES questions(id) ON DELETE CASCADE,
  status TEXT NOT NULL, value_json TEXT NOT NULL, revision INTEGER NOT NULL, submitted_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, case_id TEXT, input_revision INTEGER,
  reviewed_revision INTEGER, kind TEXT NOT NULL, status TEXT NOT NULL, result_id TEXT, result_type TEXT,
  error_code TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  queue_ms REAL, inference_ms REAL, validation_ms REAL, total_ms REAL, deletion_generation INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS guidance (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  input_revision INTEGER NOT NULL, body_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provider_searches (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  input_revision INTEGER NOT NULL, criteria_version INTEGER NOT NULL, result_json TEXT NOT NULL,
  created_at TEXT NOT NULL, current INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS exports (
  id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  input_revision INTEGER NOT NULL, guidance_id TEXT NOT NULL, storage_key TEXT NOT NULL,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS idempotency (
  scope TEXT NOT NULL, operation TEXT NOT NULL, key TEXT NOT NULL, request_hash TEXT NOT NULL,
  status_code INTEGER NOT NULL, response_json TEXT NOT NULL, headers_json TEXT NOT NULL,
  actor_id TEXT, case_id TEXT, created_at TEXT NOT NULL, PRIMARY KEY (scope, operation, key));
CREATE TABLE IF NOT EXISTS settings (
  actor_id TEXT PRIMARY KEY REFERENCES actors(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL, saved_retention_days INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS delete_tokens (
  token_hash TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tombstones (
  scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL, generation INTEGER NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (scope_kind, scope_id));
CREATE TABLE IF NOT EXISTS presenter_nonces (
  nonce TEXT PRIMARY KEY, expires_at TEXT NOT NULL);
-- #396 (CHG-DEV-API-007): the presenter browser each presenter actor belongs to (the hash of its lineage cookie), so a
-- reset also covers the demos of that browser's earlier presenter sessions. No foreign key: an ended presenter
-- session's actor is deleted, and its demos must still be found.
CREATE TABLE IF NOT EXISTS presenter_lineages (
  presenter_actor TEXT PRIMARY KEY, lineage_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS presenter_lineages_by_hash ON presenter_lineages (lineage_hash);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, operation_id TEXT,
  status TEXT NOT NULL, error_code TEXT, duration_ms REAL, actor_ref TEXT);
-- W06 telemetry (ADR-017): one row per model call, content-free (no case, actor, text or exact time; hour only).
CREATE TABLE IF NOT EXISTS model_calls (
  id TEXT PRIMARY KEY, hour TEXT NOT NULL, release TEXT, mode TEXT NOT NULL, task TEXT NOT NULL,
  prompt_version TEXT, outcome TEXT NOT NULL, duration_ms REAL NOT NULL, prompt_tokens INTEGER,
  completion_tokens INTEGER, energy_wh REAL, power_samples INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS telemetry_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse(ts: str | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def hour(dt: datetime | None = None) -> str:
    """#275: the hour an operational event happened, the only time it keeps (as `model_calls` already does)."""
    return (dt or utcnow()).astimezone(UTC).strftime("%Y-%m-%dT%H:00:00Z")


def dumps(value: Any) -> str:
    # #261: never store NaN or Infinity. They are not JSON, and every later read of the row would fail with a 500.
    # Request models refuse them first (422); this is the backstop, raised before anything is committed.
    return json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False)


class ModeConnection(sqlite3.Connection):
    """A connection that knows the running mode (#271), so content-free events and jobs record it and the telemetry
    page can count only the running mode's activity when a data directory has served both modes."""

    mode: str | None = None


class Database:
    def __init__(self, path: Path, mode: str | None = None):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, factory=ModeConnection)
        self._conn.mode = mode
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        # #274 (R35): deleted rows are overwritten with zeros instead of staying in freed pages.
        self._conn.execute("PRAGMA secure_delete=ON")
        self._conn.executescript(SCHEMA)
        # #156 (ADR-005 rule 5): presenter actions record the presenter actor ID. Databases created before carry no
        # such column; add it in place (nullable, so existing rows stay valid).
        if "actor_ref" not in {r["name"] for r in self._conn.execute("PRAGMA table_info(events)")}:
            self._conn.execute("ALTER TABLE events ADD COLUMN actor_ref TEXT")
        # #153: the reviewed level of the red flag that routed a case to urgent help (null otherwise).
        if "urgent_level" not in {r["name"] for r in self._conn.execute("PRAGMA table_info(cases)")}:
            self._conn.execute("ALTER TABLE cases ADD COLUMN urgent_level TEXT")
        # #87 (T-R15-S02): the approved red-flag IDs that routed a case to urgent help, ticked or matched by the screen
        # in the person's words, with the input revision they were matched at. Internal only: never shown or sent, and
        # deleted with the case. Databases created before carry neither column; add them in place.
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(cases)")}
        if "urgent_rule_ids" not in cols:
            self._conn.execute("ALTER TABLE cases ADD COLUMN urgent_rule_ids TEXT")
        if "urgent_revision" not in cols:
            self._conn.execute("ALTER TABLE cases ADD COLUMN urgent_revision INTEGER")
        # #271: the mode an event or job ran in (null for rows written before the column existed; never counted).
        for table in ("events", "jobs"):
            if "mode" not in {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN mode TEXT")
        # #538: why a failed job failed, content-free (a JSON list of rule codes and places, e.g.
        # "2:prohibited_certainty/rules_out_risk@claims[1].text"); null for jobs that carry none or predate the column.
        if "error_detail" not in {r["name"] for r in self._conn.execute("PRAGMA table_info(jobs)")}:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN error_detail TEXT")

    @property
    def mode(self) -> str | None:
        return self._conn.mode

    def checkpoint(self) -> None:
        """#274 (R35): after a purge, move the write-ahead log into the database and truncate it, so deleted health
        text does not survive in the WAL file. With secure_delete the freed pages are already zeroed."""
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Serialized write transaction; rolls back on any exception."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    def ping(self) -> bool:
        try:
            with self.read() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def close(self) -> None:
        with self._lock:
            self._conn.close()
