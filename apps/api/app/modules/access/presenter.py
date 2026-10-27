"""Presenter gateway assertions (M01; R03, R37; ADR-005 option A).

The gateway (one loopback-only listener reached through SSH forwarding) adds
`X-AwareCare-Presenter: v1.<unix-seconds>.<nonce-hex>.<hmac-sha256-hex>` to every
request it proxies under its presenter path `/presenter-api/` (#487, ADR-005
amendment; before, a second presenter port), using a key shared only with this
API. Under `/api/` it strips the header. The API trusts the role only when:
- a key is configured (no key: presenter access is disabled),
- the TCP peer is a trusted loopback gateway,
- the HMAC matches and the timestamp is within the freshness window, and
- for session creation, the nonce has not been used before (single use).
The header value is never logged.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from datetime import timedelta

from fastapi import Request

from app.core.db import iso, utcnow

HEADER = "X-AwareCare-Presenter"
WINDOW_SECONDS = 60
# #396 (CHG-DEV-API-007): an HttpOnly cookie of the presenter's browser that outlives each presenter session. Every
# presenter session started with it belongs to the same lineage, so Reset removes the demos of that browser's earlier
# presenter sessions too (an ended session's own actor is gone). Only its hash is stored; it authorizes nothing by itself.
LINEAGE_COOKIE = "awarecare_presenter_lineage"
LINEAGE_MAX_AGE = 7 * 24 * 3600
_LINEAGE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_FORMAT = re.compile(r"^v1\.(\d{1,12})\.([0-9a-f]{32})\.([0-9a-f]{64})$")


def sign(key: bytes, ts: int, nonce: str) -> str:
    """Build an assertion; used by tests and development gateways (the nginx gateway signs in njs)."""
    payload = f"v1.{ts}.{nonce}"
    return f"{payload}.{hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()}"


def _valid(request: Request, settings) -> tuple[bool, str | None]:
    key = settings.presenter_key
    raw = request.headers.get(HEADER)
    if not key or not raw:
        return False, None
    peer = request.client.host if request.client else None
    if peer not in settings.presenter_trusted_peers:
        return False, None
    match = _FORMAT.match(raw)
    if not match:
        return False, None
    ts, nonce, mac = int(match.group(1)), match.group(2), match.group(3)
    if abs(utcnow().timestamp() - ts) > WINDOW_SECONDS:
        return False, None
    expected = hmac.new(key, f"v1.{ts}.{nonce}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return False, None
    return True, nonce


def present(request: Request) -> bool:
    """True when the request carries any presenter assertion header (valid or not)."""
    return HEADER in request.headers


def verify(request: Request, settings) -> bool:
    """Fresh, authentic assertion from a trusted gateway (reusable within the window)."""
    return _valid(request, settings)[0]


def consume(conn, request: Request, settings) -> bool:
    """Like verify, but the nonce is single use: a replay is rejected. Call inside a transaction."""
    ok, nonce = _valid(request, settings)
    if not ok:
        return False
    now = utcnow()
    conn.execute("DELETE FROM presenter_nonces WHERE expires_at < ?", (iso(now),))
    if conn.execute("SELECT 1 FROM presenter_nonces WHERE nonce = ?", (nonce,)).fetchone():
        return False
    conn.execute("INSERT INTO presenter_nonces (nonce, expires_at) VALUES (?, ?)",
                 (nonce, iso(now + timedelta(seconds=2 * WINDOW_SECONDS))))
    return True


def lineage_token(request: Request) -> str | None:
    """The presenter browser's lineage token, when its cookie is well formed."""
    value = request.cookies.get(LINEAGE_COOKIE)
    return value if value and _LINEAGE.match(value) else None


def record_lineage(conn, presenter_actor: str, token: str) -> None:
    """Map a presenter actor to its browser's lineage (first mapping wins). Call inside a transaction."""
    from app.core.security import hash_token
    conn.execute("INSERT OR IGNORE INTO presenter_lineages (presenter_actor, lineage_hash, created_at) VALUES (?,?,?)",
                 (presenter_actor, hash_token(token), iso(utcnow())))


def lineage_actors(conn, presenter_actor: str) -> list[str]:
    """Every presenter actor of this presenter's browser lineage, itself included (itself only without a lineage)."""
    row = conn.execute("SELECT lineage_hash FROM presenter_lineages WHERE presenter_actor=?", (presenter_actor,)).fetchone()
    if row is None:
        return [presenter_actor]
    actors = [r["presenter_actor"] for r in conn.execute(
        "SELECT presenter_actor FROM presenter_lineages WHERE lineage_hash=?", (row["lineage_hash"],)).fetchall()]
    return actors if presenter_actor in actors else [*actors, presenter_actor]
