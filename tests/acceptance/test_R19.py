"""R19 preserve document provenance: document ID, page, exact text; no inferred conversion. M06."""
import pytest

from records_helpers import SAMPLE, record_files, records, scripted_app, synthetic_pdf, upload, upload_ok

REQUIREMENT = "R19"


def test_sample_extraction_preserves_provenance(app, api):
    import hashlib
    api.start()
    case = api.new_case()
    job = upload_ok(api, case["id"], name="C:\\fake\\path\\Jordan_sample_record.pdf")
    assert job["status"] == "succeeded" and job["result_type"] == "document"
    listing = records(api, case["id"])
    doc = listing["documents"][0]
    assert doc["id"] == job["result_id"] and doc["status"] == "review"
    assert doc["original_display_name"] == "Jordan_sample_record.pdf"  # no client path retained
    assert doc["sha256"] == hashlib.sha256(SAMPLE).hexdigest() and doc["page_count"] == 1
    [fact] = listing["facts"]
    assert fact["provenance"] == "document" and fact["source_id"] == doc["id"] and fact["page"] == 1
    assert fact["original_text"] == "No medications listed in sample record"
    assert fact["units"] is None and fact["status"] == "unconfirmed"
    # Stored under an opaque generated key, not the client filename.
    [stored] = record_files(app)
    assert "Jordan" not in stored.name and stored.read_bytes() == SAMPLE


def test_duplicate_upload_with_same_key_returns_same_job(api):
    api.start()
    case = api.new_case()
    rev = api.case(case["id"])["case"]["revision"]
    headers = {"Idempotency-Key": "upload-key-0001"}
    kw = dict(files={"file": ("a.pdf", SAMPLE, "application/pdf")}, data={"expected_revision": str(rev)})
    first = api.req("POST", f"/cases/{case['id']}/records", headers=headers, **kw)
    second = api.req("POST", f"/cases/{case['id']}/records", headers=headers, **kw)
    assert first.status_code == second.status_code == 202 and first.json()["job_id"] == second.json()["job_id"]
    assert len(records(api, case["id"])["documents"]) == 1


def test_extraction_after_conflicting_edit_is_discarded(app, api):
    """A worker result computed for revision n is not installed after an edit to n+1."""
    api.start()
    case = api.new_case()
    ctx = app[0].state.ctx
    held = []
    ctx.jobs.submit, original = (lambda work: held.append(work)), ctx.jobs.submit
    try:
        r = upload(api, case["id"], SAMPLE)
        assert r.status_code == 202
    finally:
        ctx.jobs.submit = original
    api.ok("PATCH", f"/cases/{case['id']}", 200, "Case", json={"expected_revision": 1, "concern": "Edited concern."})
    held[0]()
    job = api.ok("GET", f"/jobs/{r.json()['job_id']}", 200, "Job")
    assert job["status"] == "stale" and job["error_code"] == "REVISION_CHANGED"
    assert records(api, case["id"])["facts"] == [] and record_files(app) == []


# Test-only synthetic lab report (two pages): printed values, units and intervals, plus unreadable and
# mis-scripted fields that must stay unknown. The bundled sample has no value, unit or interval.
LAB_FACTS = [
    {"fixture_id": "lab-glucose", "kind": "record:lab_result", "status": "unconfirmed", "page": 2,
     "original_text": "Fasting glucose 5.4 mmol/L (reference 3.9-5.5 mmol/L)", "value": 5.4, "units": "mmol/L",
     "reference_range": "3.9-5.5 mmol/L"},
    {"fixture_id": "lab-haemoglobin", "kind": "record:lab_result", "status": "unconfirmed", "page": 2,
     "original_text": "Haemoglobin 13.1 [unit illegible] (reference range smudged)", "value": 13.1},
    {"fixture_id": "lab-ferritin", "kind": "record:lab_result", "status": "unconfirmed", "page": 7,
     "original_text": "Ferritin 45 (ref 30-400)", "value": 45, "units": "ug/L", "reference_range": "30-400 ng/mL"},
]


@pytest.fixture
def lab(tmp_path):
    from fastapi.testclient import TestClient
    from conftest import Api
    data = synthetic_pdf("lab", pages=2)
    with TestClient(scripted_app(tmp_path, {"lab-report": (data, LAB_FACTS)})) as client:
        api = Api(client)
        api.start()
        case = api.new_case()
        job = upload_ok(api, case["id"], data, name="lab.pdf")
        assert job["status"] == "succeeded"
        listing = records(api, case["id"])
        yield api, case["id"], listing["documents"][0], {f["original_text"]: f for f in listing["facts"]}


def test_extracted_value_keeps_document_page_text_units_and_interval(lab):
    """T-R19-S01: the fact keeps document identity, page, exact text, printed unit and interval."""
    api, cid, doc, facts = lab
    glucose = facts[LAB_FACTS[0]["original_text"]]
    assert glucose["source_id"] == doc["id"] and doc["page_count"] == 2 and glucose["page"] == 2
    assert glucose["original_text"] == "Fasting glucose 5.4 mmol/L (reference 3.9-5.5 mmol/L)"
    assert glucose["units"] == "mmol/L" and glucose["reference_range"] == "3.9-5.5 mmol/L"
    assert glucose["kind"] == "record:lab_result" and glucose["status"] == "unconfirmed"
    # The interpreted value is a separate typed field; the source text is never replaced by it.
    assert glucose["value"] == 5.4 and isinstance(glucose["value"], float)
    assert glucose["value"] != glucose["original_text"]
    out = api.ok("PATCH", f"/cases/{cid}/facts/{glucose['id']}", 200, "FactReviewResponse",
                 json={"expected_revision": api.case(cid)["case"]["revision"], "action": "confirm"})
    confirmed = next(f for f in api.case(cid)["case"]["confirmed_context"] if f["id"] == glucose["id"])
    assert out["fact"] == confirmed
    assert (confirmed["value"], confirmed["units"], confirmed["reference_range"], confirmed["original_text"]) == (
        5.4, "mmol/L", "3.9-5.5 mmol/L", glucose["original_text"])


def test_unreadable_unit_and_ambiguous_interval_stay_unknown(lab):
    """T-R19-S02: no unit or interval is inferred; the excerpt and page stay available for correction."""
    api, cid, doc, facts = lab
    haemoglobin = facts[LAB_FACTS[1]["original_text"]]
    assert haemoglobin["units"] is None and "reference_range" not in haemoglobin
    assert haemoglobin["page"] == 2 and haemoglobin["original_text"] == LAB_FACTS[1]["original_text"]
    # Scripted fields that are not printed verbatim, and a page the document does not have, are not stored.
    ferritin = facts[LAB_FACTS[2]["original_text"]]
    assert ferritin["units"] is None and "reference_range" not in ferritin and ferritin["page"] is None
    # A correction stores the user's unit separately; the excerpt and page remain for reference.
    rev = api.case(cid)["case"]["revision"]
    out = api.ok("PATCH", f"/cases/{cid}/facts/{haemoglobin['id']}", 200, "FactReviewResponse",
                 json={"expected_revision": rev, "action": "correct",
                       "corrected_value": {"value": 13.1, "units": "g/dL"}})
    assert out["fact"]["units"] == "g/dL" and out["fact"]["page"] == 2
    assert out["fact"]["original_text"] == LAB_FACTS[1]["original_text"]
    with api.c.app.state.ctx.db.read() as conn:
        review = conn.execute("SELECT prior_units, new_units FROM fact_reviews WHERE fact_id=?",
                              (haemoglobin["id"],)).fetchone()
    assert (review["prior_units"], review["new_units"]) == (None, "g/dL")


# #593 (QA 2026-10-26): an upload whose extraction could not be submitted answered 503 "Try again" but kept its 202 as
# the key's committed response, so the same-key retry replayed "queued" for a job that had already failed.

def test_593_a_same_key_retry_after_a_failed_submit_starts_the_extraction(app, api):
    from conftest import validate
    ctx = app[0].state.ctx
    api.start()
    cid = api.new_case()["id"]
    rev = api.case(cid)["case"]["revision"]
    headers = {"Idempotency-Key": "upload-key-0593"}
    kw = dict(files={"file": ("a.pdf", SAMPLE, "application/pdf")}, data={"expected_revision": str(rev)})

    def broken(work):
        raise RuntimeError("synthetic submit failure")
    ctx.jobs.submit, original = broken, ctx.jobs.submit
    try:
        first = api.req("POST", f"/cases/{cid}/records", headers=headers, **kw)
    finally:
        ctx.jobs.submit = original
    assert first.status_code == 503 and first.json()["code"] == "SERVICE_LIMITED" and first.json()["retryable"]
    assert record_files(app) == []
    retry = api.req("POST", f"/cases/{cid}/records", headers=headers, **kw)
    assert retry.status_code == 202, retry.text
    validate("UploadRecordResponse", retry.json())
    assert api.wait_job(retry.json()["job_id"])["status"] == "succeeded"
    # From here the key replays the accepted upload, as for any other committed creation.
    again = api.req("POST", f"/cases/{cid}/records", headers=headers, **kw)
    assert again.status_code == 202 and again.json() == retry.json()
    docs = {d["id"]: d["status"] for d in records(api, cid)["documents"]}
    # #628: the upload answered 503 was never accepted, so it is not listed (and uses no record slot).
    assert docs == {retry.json()["document"]["id"]: "review"}


# #628 (owner decision on #593): an upload answered with a server error was never accepted, so it uses none of the
# 3 record slots of a consultation nor of the session's records (#263, #397); only accepted uploads count.

def test_628_a_failed_submission_frees_its_record_slot_and_the_limit_still_holds_for_accepted_uploads(app, api,
                                                                                                    monkeypatch):
    from app.modules.records import service
    monkeypatch.setattr(service, "MAX_SESSION_FILES", 4)
    ctx = app[0].state.ctx

    def failed_upload(case_id):
        def broken(work):
            raise RuntimeError("synthetic submit failure")
        ctx.jobs.submit, original = broken, ctx.jobs.submit
        try:
            r = upload(api, case_id, SAMPLE)
        finally:
            ctx.jobs.submit = original
        assert r.status_code == 503 and r.json()["code"] == "SERVICE_LIMITED", r.text

    api.start()
    first = api.new_case()["id"]
    failed_upload(first)
    assert records(api, first)["documents"] == []  # nothing was accepted, so nothing is listed
    for n in range(3):  # the failed one took no slot: all 3 accepted uploads fit
        assert upload_ok(api, first, name=f"r{n}.pdf")["status"] == "succeeded"
    r = upload(api, first, SAMPLE)  # the limit still holds for accepted uploads
    assert r.status_code == 413 and r.json()["code"] == "RECORD_LIMIT" and "one consultation" in r.json()["message"]
    assert [d["status"] for d in records(api, first)["documents"]] == ["review"] * 3
    # The session limit (4 here) counts accepted uploads only, too.
    second = api.new_case()["id"]
    failed_upload(second)
    upload_ok(api, second)
    r = upload(api, second, SAMPLE)
    assert r.status_code == 413 and r.json()["code"] == "RECORD_LIMIT" and "one session" in r.json()["message"]
    assert len(record_files(app)) == 4
