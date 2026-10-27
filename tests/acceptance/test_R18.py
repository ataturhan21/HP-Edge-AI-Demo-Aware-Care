"""R18 reject unsafe or oversized uploads before extraction; rejected bytes are never stored. M06."""
import re

import pytest

from records_helpers import PNG_1PX, SAMPLE, UNREADABLE, png, record_files, records, upload, upload_ok

REQUIREMENT = "R18"
# Every rejection names a safe recovery: another file, or continuing without it (T-R18-S01).
RECOVERY = re.compile(r"\b(Try a|continue without)\b")


def assert_safe_rejection(r, status: int, code: str) -> None:
    body = r.json()
    assert r.status_code == status and body["code"] == code, r.text
    assert [e["field"] for e in body["field_errors"]] == ["file"] and RECOVERY.search(body["message"]), body


def held(app, api, case_id: str) -> tuple:
    """Everything an upload could leave behind: stored bytes, document rows and extraction jobs."""
    with app[0].state.ctx.db.read() as conn:
        jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE kind='record_extraction'").fetchone()[0]
    return record_files(app), records(api, case_id)["documents"], jobs


@pytest.mark.parametrize("data,media_type,status,code", [
    (UNREADABLE, "application/pdf", 422, "RECORD_MALFORMED"),
    (b"", "application/pdf", 422, "RECORD_MALFORMED"),
    (SAMPLE, "text/plain", 415, "RECORD_TYPE_UNSUPPORTED"),
    (SAMPLE, "image/png", 415, "RECORD_TYPE_MISMATCH"),
    (b"MZ\x90\x00 not a pdf", "application/pdf", 415, "RECORD_TYPE_MISMATCH"),
    (SAMPLE.replace(b"/Type /Catalog", b"/Type /Catalog /Encrypt 9 0 R"), "application/pdf", 422, "RECORD_ENCRYPTED"),
    (SAMPLE.replace(b"/Type /Catalog", b"/Type /Catalog /OpenAction 9 0 R"), "application/pdf", 422,
     "RECORD_ACTIVE_CONTENT"),
    (b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024), "application/pdf", 413, "RECORD_TOO_LARGE"),
    (png(10_000, 10_000), "image/png", 413, "RECORD_TOO_LARGE"),
], ids=["truncated-pdf", "empty", "unsupported-type", "type-mismatch", "fake-signature", "encrypted-pdf",
        "active-content-pdf", "over-10mb", "over-40mp-image"])
def test_rejected_before_storage_or_extraction(app, api, data, media_type, status, code):
    api.start()
    case = api.new_case()
    r = upload(api, case["id"], data, media_type)
    assert_safe_rejection(r, status, code)
    assert record_files(app) == []
    assert records(api, case["id"])["documents"] == []
    with app[0].state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind='record_extraction'").fetchone()[0] == 0


def test_file_count_limit_is_three(app, api):
    """T-R18-S01: the 4th file is refused with a recovery and leaves no bytes, document or job behind."""
    api.start()
    case = api.new_case()
    upload_ok(api, case["id"], PNG_1PX, media_type="image/png", name="x.png")
    upload_ok(api, case["id"])
    upload_ok(api, case["id"])
    # Every accepted upload counts, including one that failed extraction (RecordList holds at most 3).
    assert len(records(api, case["id"])["documents"]) == 3
    before = held(app, api, case["id"])
    r = upload(api, case["id"], SAMPLE)
    assert_safe_rejection(r, 413, "RECORD_LIMIT")
    assert held(app, api, case["id"]) == before


def test_page_limit_is_thirty_per_case(app, api):
    """T-R18-S01: a record over the 30-page budget is refused with a recovery and nothing is kept."""
    api.start()
    case = api.new_case()
    upload_ok(api, case["id"])  # 1 page held
    before = held(app, api, case["id"])
    thirty = SAMPLE + b"\n" + b"<< /Type /Page >>\n" * 29 + b"%%EOF\n"  # 30 page objects: 31 in total
    r = upload(api, case["id"], thirty)
    assert_safe_rejection(r, 413, "RECORD_PAGE_LIMIT")
    assert held(app, api, case["id"]) == before
    thirty_one = SAMPLE + b"\n" + b"<< /Type /Page >>\n" * 30 + b"%%EOF\n"  # 31 page objects in one file
    other = api.new_case()
    assert_safe_rejection(upload(api, other["id"], thirty_one), 413, "RECORD_PAGE_LIMIT")
    assert held(app, api, other["id"])[1:] == ([], before[2])


def test_unprocessable_valid_file_fails_visibly_and_bytes_are_removed(app, api):
    api.start()
    case = api.new_case()
    job = upload_ok(api, case["id"], PNG_1PX, media_type="image/png", name="scan.png")
    assert job["status"] == "failed" and job["error_code"] == "EXTRACTION_UNAVAILABLE"
    listing = records(api, case["id"])
    assert listing["documents"][0]["status"] == "failed" and listing["facts"] == []
    assert record_files(app) == []


def test_upload_requires_current_revision_and_intake_state(api):
    api.start()
    case = api.new_case()
    assert upload(api, case["id"], SAMPLE, revision=7).status_code == 409
    api.to_guided(case["id"])
    r = upload(api, case["id"], SAMPLE)
    assert r.status_code == 409 and r.json()["code"] == "STATE_CONFLICT"


def test_local_mode_refuses_uploads_without_storing(tmp_path):
    from dataclasses import replace

    from conftest import Api
    from fastapi.testclient import TestClient

    from app.config import load_settings
    from app.main import create_app
    settings = replace(load_settings(), mode="local", data_dir=tmp_path / "d")
    with TestClient(create_app(settings)) as client:
        api = Api(client)
        api.start()
        # Local mode cannot create a usable case without a reviewed pathway, but it still owns the case row.
        case = api.new_case()
        r = upload(api, case["id"], SAMPLE)
        assert r.status_code == 503 and r.json()["code"] == "SERVICE_LIMITED"
        assert not (tmp_path / "d" / "records").exists() or not any((tmp_path / "d" / "records").iterdir())


# --- #466 (S-10, QA 2026-10-22): malformed PNGs are refused before storage and use up no record slot ---------------

@pytest.mark.parametrize("data", [
    png(0, 0, idat=False), png(1, 0, idat=False), png(100, 100, idat=False, ihdr_crc=0),
    png(0, 0), png(1, 0), png(0, 7), png(100, 100, ihdr_crc=0), png(2, 2, idat=False), png(2, 2) + b"trailing",
    png(2, 2)[:-12], PNG_1PX.replace(b"IDAT", b"IDAX"),
], ids=["0x0-no-idat", "1x0-no-idat", "bad-ihdr-crc-no-idat", "0x0", "1x0", "0x7", "bad-ihdr-crc", "no-idat",
        "data-after-iend", "no-iend", "bad-chunk-crc"])
def test_466_a_malformed_png_is_refused_before_storage_and_uses_no_record_slot(app, api, data):
    api.start()
    case = api.new_case()
    assert_safe_rejection(upload(api, case["id"], data, "image/png", "scan.png"), 422, "RECORD_MALFORMED")
    assert held(app, api, case["id"]) == ([], [], 0)


def test_466_after_three_malformed_pngs_the_sample_record_is_still_accepted(app, api):
    """QA: three malformed PNGs were stored (202) and used up the 3-record limit, so the real sample was refused."""
    api.start()
    case = api.new_case()
    for data in (png(0, 0, idat=False), png(1, 0, idat=False), png(100, 100, idat=False, ihdr_crc=0)):
        assert upload(api, case["id"], data, "image/png", "scan.png").status_code == 422
    assert upload_ok(api, case["id"])["status"] == "succeeded"
    assert upload_ok(api, case["id"], PNG_1PX, media_type="image/png", name="x.png")["status"] == "failed"
    assert len(records(api, case["id"])["documents"]) == 2  # the malformed ones took no slot
