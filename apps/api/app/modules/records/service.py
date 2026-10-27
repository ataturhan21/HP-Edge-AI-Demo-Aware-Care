"""M06 record processing (R18-R20): validated upload, restricted extraction job, fact review.

Validation runs in memory before any byte is stored (R18): declared type, file signature,
size, per-case file/page limits, encrypted/malformed PDFs, active PDF content and image
megapixels. Rejected bytes are never written and never reach a worker or model.

No PDF parser/OCR worker is installed. In mock mode the extraction job reads only the
bundled synthetic sample record, recognized by the SHA-256 of its exact bytes (ADR-009);
any other valid file finishes `failed` with EXTRACTION_UNAVAILABLE and its bytes are
deleted, so no fact is ever invented about a user's file. Local mode refuses uploads
(503) until a reviewed extraction worker exists.

Extracted facts are `unconfirmed` and invisible to case context, guidance and exports
until the user confirms or corrects them (R20). Corrections keep the exact source text.
A scripted sample fact may give a kind, value, units, reference range and page (R19).
Units and reference ranges are stored only when printed verbatim in the source text,
and a page only when it exists in the document; otherwise they stay unknown (null).
Every rejection message names a recovery: another file, or continuing without it.
"""
from __future__ import annotations

import hashlib
import os
import re
import struct
import unicodedata
import uuid
import zlib
from pathlib import Path
from typing import Any

from app.core import idempotency
from app.core.db import dumps, iso, utcnow
from app.core.errors import ApiError, not_found, state_conflict
from app.core.security import SessionInfo
from app.modules.cases import repository as cases_repo
from app.modules.operations.service import create_job, finish_job, record_event
from app.modules.safety.service import is_urgent_record_fixture

MAX_FILES = 3
# #397: records one session can hold across its consultations (each consultation still takes at most MAX_FILES).
MAX_SESSION_FILES = 30
MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 30
MAX_MEGAPIXELS = 40_000_000
ALLOWED = ("application/pdf", "image/png", "image/jpeg")
UPLOAD_STATES = {"intake"}
REVIEW_STATES = {"intake", "review", "reviewed", "guided"}
PDF_ACTIVE = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/RichMedia", b"/OpenAction")


def record_dir(ctx) -> Path:
    path = ctx.settings.data_dir / "records"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _reject(status: int, code: str, message: str) -> ApiError:
    return ApiError(status, code, message, field_errors=[{"field": "file", "code": code.lower(), "message": message}])


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def _pdf_pages(data: bytes) -> int:
    tail = data[-1024:]
    if b"%%EOF" not in tail or b"startxref" not in data:
        raise _reject(422, "RECORD_MALFORMED", "This file could not be read. Try a different PDF, PNG or JPEG.")
    if b"/Encrypt" in data:
        raise _reject(422, "RECORD_ENCRYPTED", "Password-protected PDFs cannot be read. Try a copy without a password.")
    if any(marker in data for marker in PDF_ACTIVE):
        raise _reject(422, "RECORD_ACTIVE_CONTENT",
                      "PDFs with scripts, attachments or actions are not accepted. Try a plain PDF, PNG or JPEG.")
    pages = len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", data))
    if pages < 1:
        raise _reject(422, "RECORD_MALFORMED", "This file could not be read. Try a different PDF, PNG or JPEG.")
    return pages


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Valid bit depths per PNG colour type (PNG spec 11.2.2): greyscale, truecolour, indexed, grey + alpha, RGBA.
PNG_DEPTHS = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}


def _png_pixels(data: bytes, malformed: ApiError) -> int:
    """#466 (R18): a PNG is read chunk by chunk before anything is stored. It needs an intact IHDR first (13 bytes, a
    width and height of at least 1, a valid depth and colour type), at least one image-data chunk, an IEND that ends
    the file, and a correct CRC on every chunk. Anything else is malformed (422) and uses up no record slot."""
    if not data.startswith(PNG_SIGNATURE):
        raise malformed
    i, kinds, width, height = len(PNG_SIGNATURE), [], 0, 0
    while i + 12 <= len(data):
        length = struct.unpack(">I", data[i:i + 4])[0]
        kind, body = data[i + 4:i + 8], data[i + 8:i + 8 + length]
        if length > 0x7FFFFFFF or i + 12 + length > len(data) or not kind.isalpha():
            raise malformed
        if struct.unpack(">I", data[i + 8 + length:i + 12 + length])[0] != zlib.crc32(kind + body):
            raise malformed
        if not kinds:
            if kind != b"IHDR" or length != 13:
                raise malformed
            width, height, depth, colour, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
            if (not 1 <= width <= 0x7FFFFFFF or not 1 <= height <= 0x7FFFFFFF or depth not in PNG_DEPTHS.get(colour, ())
                    or compression or filtering or interlace not in (0, 1)):
                raise malformed
        kinds.append(kind)
        i += 12 + length
        if kind == b"IEND":
            break
    if i != len(data) or not kinds or kinds[-1] != b"IEND" or b"IDAT" not in kinds:
        raise malformed
    return width * height


def _image_pixels(media_type: str, data: bytes) -> int:
    malformed = _reject(422, "RECORD_MALFORMED", "This image could not be read. Try a different PDF, PNG or JPEG.")
    if media_type == "image/png":
        return _png_pixels(data, malformed)
    if not data.endswith(b"\xff\xd9"):
        raise malformed
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            raise malformed
        marker = data[i + 1]
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            if not width or not height:  # #466: an image without pixels is malformed, not a tiny image
                raise malformed
            return width * height
        i += 2 + length
    raise malformed


def validate(declared: str | None, data: bytes) -> tuple[str, int | None]:
    """R18 checks; returns (media_type, page_count). Raises before anything is stored."""
    if not data:
        raise _reject(422, "RECORD_MALFORMED", "The file is empty. Try a different PDF, PNG or JPEG.")
    if len(data) > MAX_BYTES:
        raise _reject(413, "RECORD_TOO_LARGE", "Files can be up to 10 MB. Try a smaller file.")
    if declared not in ALLOWED:
        raise _reject(415, "RECORD_TYPE_UNSUPPORTED",
                      "Only PDF, PNG or JPEG files are accepted. Try a file of one of these types.")
    if _sniff(data) != declared:
        raise _reject(415, "RECORD_TYPE_MISMATCH",
                      "The file content does not match its type. Try a different PDF, PNG or JPEG.")
    if declared == "application/pdf":
        return declared, _pdf_pages(data)
    if _image_pixels(declared, data) > MAX_MEGAPIXELS:
        raise _reject(413, "RECORD_TOO_LARGE", "Images can be up to 40 megapixels. Try a smaller image.")
    return declared, 1


def _display_name(name: str | None) -> str:
    base = (name or "record").replace("\\", "/").rsplit("/", 1)[-1]
    clean = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C").strip()
    return (clean or "record")[:255]


def document_public(row) -> dict[str, Any]:
    return {"id": row["id"], "actor_id": row["actor_id"], "case_id": row["case_id"],
            "original_display_name": row["display_name"], "media_type": row["media_type"],
            "byte_count": row["byte_count"], "page_count": row["page_count"], "sha256": row["sha256"],
            "status": row["status"], "created_at": row["created_at"], "expires_at": row["expires_at"]}


def list_records(ctx, session: SessionInfo, case_id: str) -> dict[str, Any]:
    with ctx.db.read() as conn:
        cases_repo.get_owned(conn, session.actor_id, case_id)
        docs = conn.execute("SELECT * FROM documents WHERE case_id=? AND actor_id=? ORDER BY created_at",
                            (case_id, session.actor_id)).fetchall()
        return {"documents": [document_public(d) for d in docs], "facts": cases_repo.document_facts(conn, case_id)}


def upload_record(ctx, session: SessionInfo, case_id: str, expected_revision: int, key: str,
                  declared: str | None, filename: str | None, data: bytes) -> dict[str, Any]:
    with ctx.db.read() as conn:
        cases_repo.get_owned(conn, session.actor_id, case_id)
    if ctx.settings.mode != "mock":
        raise ApiError(503, "SERVICE_LIMITED",
                       "Record reading is not available in this build. You can skip this optional step.")
    sha = hashlib.sha256(data).hexdigest()
    req_hash = idempotency.request_hash(case_id, expected_revision, sha)
    scope = f"actor:{session.actor_id}"
    target: Path | None = None
    try:
        with ctx.db.tx() as conn:
            replay = idempotency.lookup(conn, scope, f"uploadRecord:{case_id}", key, req_hash)
            if replay:
                return replay.body
            row = cases_repo.get_owned(conn, session.actor_id, case_id)
            cases_repo.check_revision(row, expected_revision)
            if row["state"] not in UPLOAD_STATES:
                raise state_conflict(current_revision=row["revision"])
            media_type, pages = validate(declared, data)
            # Count/page capacity is reserved inside the same serialized transaction (no concurrent bypass).
            # Every accepted upload counts toward the 3-file limit (RecordList lists at most 3 documents), including one
            # whose extraction failed later; an upload answered 503 was never accepted and has no row (#628). Only
            # records still held count toward the 30-page budget.
            held = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN status NOT IN ('failed','rejected') "
                                "THEN page_count ELSE 0 END),0) AS p FROM documents WHERE case_id=?",
                                (case_id,)).fetchone()
            if held["n"] >= MAX_FILES:
                raise _reject(413, "RECORD_LIMIT",
                              "Up to 3 records can be added to one consultation. You can continue without this one.")
            if conn.execute("SELECT COUNT(*) FROM documents WHERE actor_id=?",
                            (session.actor_id,)).fetchone()[0] >= MAX_SESSION_FILES:
                raise _reject(413, "RECORD_LIMIT", f"Up to {MAX_SESSION_FILES} records can be added in one session. "
                                                   "You can continue without this one.")
            if held["p"] + (pages or 0) > MAX_PAGES:
                raise _reject(413, "RECORD_PAGE_LIMIT",
                              "Records can have up to 30 pages in total. Try a shorter record or continue without it.")
            doc_id, storage_key = str(uuid.uuid4()), uuid.uuid4().hex
            # #272: the validated bytes are written before the row commits, inside the same serialized transaction,
            # and removed if it rolls back. A deletion can only see the row once the file exists, so it always
            # removes both; no file is ever left without a row.
            target = record_dir(ctx) / storage_key
            _write_private(target, data)
            conn.execute("INSERT INTO documents (id, actor_id, case_id, display_name, media_type, byte_count, "
                         "page_count, sha256, status, storage_key, input_revision, created_at, expires_at) "
                         "VALUES (?,?,?,?,?,?,?,?,'queued',?,?,?,?)",
                         (doc_id, session.actor_id, case_id, _display_name(filename), media_type, len(data), pages,
                          sha, storage_key, row["revision"], iso(utcnow()), session.expires_at))
            job = create_job(conn, actor_id=session.actor_id, case_id=case_id, kind="record_extraction",
                             input_revision=row["revision"])
            doc = document_public(conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())
            result = {"document": doc, "job_id": job["id"]}
            idempotency.store(conn, scope, f"uploadRecord:{case_id}", key, req_hash, 202, result,
                              actor_id=session.actor_id, case_id=case_id)
            record_event(conn, "record_uploaded", "queued", operation_id="uploadRecord")
    except BaseException:
        if target is not None:
            target.unlink(missing_ok=True)
        raise
    try:
        ctx.jobs.submit(lambda: _extract(ctx, job["id"], doc_id, case_id, session.actor_id, row["revision"],
                                         storage_key))
    except Exception:
        # #263: no worker will read these bytes: the job fails visibly and no unprocessed bytes are kept (R18).
        # #593: the 202 stored for this key was never returned; drop it so a retry with the same key starts afresh
        # instead of replaying "queued" for this failed job (as a failed export or guidance submit does).
        # #628 (owner decision): the upload answered 503 was never accepted, so its document is removed as well: it is
        # not listed and uses none of the consultation's or the session's record slots (only accepted uploads count).
        with ctx.db.tx() as conn:
            conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
            finish_job(conn, job["id"], "failed", error_code="SUBMIT_FAILED")
            conn.execute("DELETE FROM idempotency WHERE scope=? AND operation=? AND key=?",
                         (scope, f"uploadRecord:{case_id}", key))
        target.unlink(missing_ok=True)
        raise ApiError(503, "SERVICE_LIMITED", "The record could not be processed. Try again or continue without it.",
                       retryable=True) from None
    return result


def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def _extract(ctx, job_id: str, doc_id: str, case_id: str, actor_id: str, revision: int,
             storage_key: str | None = None) -> None:
    with ctx.db.tx() as conn:
        conn.execute("UPDATE jobs SET status='running', started_at=? WHERE id=? AND status='queued'",
                     (iso(utcnow()), job_id))
        doc = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if doc is not None:
            conn.execute("UPDATE documents SET status='processing' WHERE id=? AND status='queued'", (doc_id,))
    # #272: the bytes are removed by their key even when the row is already gone (a deletion raced the upload).
    key = doc["storage_key"] if doc is not None and doc["storage_key"] else storage_key
    path = record_dir(ctx) / key if key else None
    sample = ctx.fixtures.record_samples.get(doc["sha256"]) if doc is not None and ctx.fixtures else None
    with ctx.db.tx() as conn:
        case = conn.execute("SELECT * FROM cases WHERE id=? AND actor_id=?", (case_id, actor_id)).fetchone()
        current = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if case is None or case["state"] in {"deleting", "deleted"} or current is None:
            finish_job(conn, job_id, "cancelled", error_code="CASE_DELETED")
            if path:
                path.unlink(missing_ok=True)
            return
        if case["revision"] != revision:
            conn.execute("UPDATE documents SET status='failed', error_code='REVISION_CHANGED', storage_key=NULL "
                         "WHERE id=?", (doc_id,))
            finish_job(conn, job_id, "stale", error_code="REVISION_CHANGED")
            if path:
                path.unlink(missing_ok=True)
            return
        if sample is None:
            # No extractor for arbitrary files: fail visibly and keep no unprocessable health bytes.
            conn.execute("UPDATE documents SET status='failed', error_code='EXTRACTION_UNAVAILABLE', storage_key=NULL "
                         "WHERE id=?", (doc_id,))
            finish_job(conn, job_id, "failed", error_code="EXTRACTION_UNAVAILABLE")
            record_event(conn, "record_extraction", "failed", error_code="EXTRACTION_UNAVAILABLE")
            if path:
                path.unlink(missing_ok=True)
            return
        for fact in sample["facts"]:
            kind, value, units, reference, page = _scripted(fact, current["page_count"])
            conn.execute("INSERT INTO facts (id, case_id, kind, value_json, units, provenance, source_id, page, "
                         "status, original_text, confirmed_at, reference_range) "
                         "VALUES (?,?,?,?,?,'document',?,?,'unconfirmed',?,NULL,?)",
                         (str(uuid.uuid4()), case_id, kind, dumps(value), units, doc_id, page, fact["original_text"],
                          reference))
        conn.execute("UPDATE documents SET status='review' WHERE id=?", (doc_id,))
        finish_job(conn, job_id, "succeeded", result_id=doc_id, result_type="document")
        record_event(conn, "record_extraction", "succeeded")


def _scripted(fact: dict[str, Any], page_count: int | None) -> tuple[str, Any, str | None, str | None, int | None]:
    """(kind, value, units, reference_range, page) of a scripted sample fact; never inferred (R19)."""
    text = fact["original_text"]

    def printed(field: str) -> str | None:
        value = fact.get(field)
        return value if isinstance(value, str) and value and value in text else None

    page = fact.get("page", 1)
    valid_page = isinstance(page, int) and not isinstance(page, bool) and 1 <= page <= (page_count or 1)
    return (fact.get("kind", "record:medications"), fact.get("value", text), printed("units"),
            printed("reference_range"), page if valid_page else None)


def review_fact(ctx, session: SessionInfo, case_id: str, fact_id: str, expected_revision: int, action: str,
                corrected: dict[str, Any] | None) -> dict[str, Any]:
    with ctx.db.tx() as conn:
        row = cases_repo.get_owned(conn, session.actor_id, case_id)
        fact = conn.execute("SELECT * FROM facts WHERE id=? AND case_id=? AND provenance='document' AND active=1",
                            (fact_id, case_id)).fetchone()
        if fact is None:
            raise not_found()
        cases_repo.check_revision(row, expected_revision)
        if row["state"] not in REVIEW_STATES:
            raise state_conflict(current_revision=row["revision"])
        prior_value, prior_units = fact["value_json"], fact["units"]
        new_value, new_units = prior_value, prior_units
        if action == "confirm":
            status = "confirmed"
        elif action == "reject":
            status = "rejected"
        else:
            status, new_value, new_units = "confirmed", dumps(corrected["value"]), corrected["units"]
        now = iso(utcnow())
        # Confirmed context changes only when the fact enters or leaves the confirmed set, or its value changes.
        context_changed = status == "confirmed" or fact["status"] == "confirmed"
        # Safety recheck on every confirmed or corrected record fact (R15): mock honors only the fixture kind.
        urgent = status == "confirmed" and is_urgent_record_fixture(ctx.settings.mode, fact["kind"])
        new_state = "urgent" if urgent else "intake"
        revision = cases_repo.bump_clinical_revision(conn, row, new_state) if context_changed else row["revision"]
        # The exact source text (original_text) and the stored bytes are never rewritten.
        conn.execute("UPDATE facts SET status=?, value_json=?, units=?, confirmed_at=? WHERE id=?",
                     (status, new_value, new_units, now if status == "confirmed" else None, fact_id))
        conn.execute("INSERT INTO fact_reviews (id, case_id, fact_id, action, prior_value_json, new_value_json, "
                     "prior_units, new_units, case_revision, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (str(uuid.uuid4()), case_id, fact_id, action, prior_value, new_value, prior_units, new_units,
                      revision, now))
        record_event(conn, "fact_reviewed", action, operation_id="reviewFact")
        if urgent:
            record_event(conn, "urgent_interrupt", "urgent", operation_id="reviewFact")
        updated = cases_repo.fact_public(conn.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone())
        refreshed = conn.execute("SELECT state, issued_slots FROM cases WHERE id=?", (case_id,)).fetchone()
        next_action = "urgent" if urgent else "records" if refreshed["issued_slots"] == 0 else "intake"
        return {"fact": updated, "case_revision": revision, "next_action": next_action}
