"""Idempotency-Key handling for retryable creations (spec/api/README.md).

Keys scope to (actor or pre-session scope, operation, key) with a canonical
request hash for 24 hours. Same key + same payload replays the committed
response; a changed payload returns 409 IDEMPOTENCY_CONFLICT. The lookup and
the work it guards share one serialized transaction so duplicates serialize.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Iterator

from fastapi import Request

from app.core.db import dumps, iso, parse, utcnow
from app.core.errors import ApiError

TTL = timedelta(hours=24)


def request_hash(*parts: Any) -> str:
    digest = hashlib.sha256()
    for part in parts:
        if isinstance(part, bytes):
            digest.update(part)
        else:
            digest.update(dumps(part).encode())
        digest.update(b"\x00")
    return digest.hexdigest()


def require_key(request: Request) -> str:
    key = request.headers.get("Idempotency-Key", "")
    if not (8 <= len(key) <= 200) or not key.isascii():
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "A valid Idempotency-Key header is required.")
    return key


@dataclass
class Replay:
    status_code: int
    body: Any
    headers: dict[str, str]


def lookup(conn: sqlite3.Connection, scope: str, operation: str, key: str, req_hash: str) -> Replay | None:
    row = conn.execute("SELECT * FROM idempotency WHERE scope=? AND operation=? AND key=?",
                       (scope, operation, key)).fetchone()
    if row is None:
        return None
    if utcnow() - parse(row["created_at"]) > TTL:
        conn.execute("DELETE FROM idempotency WHERE scope=? AND operation=? AND key=?", (scope, operation, key))
        return None
    if row["request_hash"] != req_hash:
        raise ApiError(409, "IDEMPOTENCY_CONFLICT", "This request key was already used with different content.")
    return Replay(row["status_code"], json.loads(row["response_json"]), json.loads(row["headers_json"]))


def store(conn: sqlite3.Connection, scope: str, operation: str, key: str, req_hash: str, status_code: int,
          body: Any, *, actor_id: str | None, case_id: str | None, headers: dict[str, str] | None = None) -> None:
    conn.execute(
        "INSERT INTO idempotency (scope, operation, key, request_hash, status_code, response_json, headers_json, "
        "actor_id, case_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (scope, operation, key, req_hash, status_code, dumps(body), dumps(headers or {}), actor_id, case_id,
         iso(utcnow())))


_KEY_GUARD = threading.Lock()
_KEY_LOCKS: dict[tuple[str, str, str], list] = {}  # (scope, operation, key) -> [lock, holders and waiters]


@contextmanager
def serialized(scope: str, operation: str, key: str) -> Iterator[None]:
    """#435: run one keyed operation at a time. An operation whose work spans more than one transaction (a presenter
    scenario load: lookup, reset and screen, then the store) holds this around the whole of it, so a concurrent
    duplicate waits and then finds the stored response, instead of missing the lookup and failing on the store. The
    API is one process (the database lock is process-wide too); different keys never wait for each other."""
    ident = (scope, operation, key)
    with _KEY_GUARD:
        entry = _KEY_LOCKS.setdefault(ident, [threading.Lock(), 0])
        entry[1] += 1
    try:
        with entry[0]:
            yield
    finally:
        with _KEY_GUARD:
            entry[1] -= 1
            if entry[1] == 0:
                _KEY_LOCKS.pop(ident, None)
