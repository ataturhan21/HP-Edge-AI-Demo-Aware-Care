"""R20 require review of extracted facts; correction keeps the original source. M06/M03/M08."""
import json

import pytest

from records_helpers import SAMPLE, record_files, records, scripted_app, synthetic_pdf, upload_ok

REQUIREMENT = "R20"


def sample_fact(api, case_id: str) -> dict:
    upload_ok(api, case_id)
    return records(api, case_id)["facts"][0]


def review(api, case_id: str, fact_id: str, body: dict, status: int = 200):
    rev = api.case(case_id)["case"]["revision"]
    return api.ok("PATCH", f"/cases/{case_id}/facts/{fact_id}", status,
                  "FactReviewResponse" if status == 200 else "Error", json={"expected_revision": rev, **body})


def test_unconfirmed_fact_is_not_case_context_guidance_or_export(api):
    api.start()
    case = api.new_case()
    sample_fact(api, case["id"])
    read = api.case(case["id"])
    assert all(f["provenance"] != "document" for f in read["case"]["confirmed_context"])
    api.to_guided(case["id"])
    g = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")
    doc_fact_ids = {f["id"] for f in records(api, case["id"])["facts"]}
    assert not any(set(c["fact_ids"]) & doc_fact_ids for c in g["claims"])


def test_confirm_makes_fact_current_and_bumps_revision(api):
    api.start()
    case = api.new_case()
    fact = sample_fact(api, case["id"])
    before = api.case(case["id"])["case"]["revision"]
    out = review(api, case["id"], fact["id"], {"action": "confirm"})
    assert out["fact"]["status"] == "confirmed" and out["case_revision"] == before + 1
    assert out["next_action"] == "records"
    ctx = api.case(case["id"])["case"]["confirmed_context"]
    assert [f["id"] for f in ctx if f["provenance"] == "document"] == [fact["id"]]


def test_reject_unconfirmed_fact_changes_no_context(api):
    api.start()
    case = api.new_case()
    fact = sample_fact(api, case["id"])
    before = api.case(case["id"])["case"]["revision"]
    out = review(api, case["id"], fact["id"], {"action": "reject"})
    assert out["fact"]["status"] == "rejected" and out["case_revision"] == before
    assert all(f["provenance"] != "document" for f in api.case(case["id"])["case"]["confirmed_context"])


def test_correct_keeps_original_text_and_source_bytes(app, api):
    api.start()
    case = api.new_case()
    fact = sample_fact(api, case["id"])
    out = review(api, case["id"], fact["id"],
                 {"action": "correct", "corrected_value": {"value": "Takes a daily vitamin (fictional)", "units": None}})
    assert out["fact"]["status"] == "confirmed" and out["fact"]["value"] == "Takes a daily vitamin (fictional)"
    assert out["fact"]["original_text"] == "No medications listed in sample record"
    assert record_files(app)[0].read_bytes() == SAMPLE
    with app[0].state.ctx.db.read() as conn:
        rows = conn.execute("SELECT action, prior_value_json FROM fact_reviews").fetchall()
    assert [(r["action"], r["prior_value_json"]) for r in rows] == [
        ("correct", '"No medications listed in sample record"')]


def test_review_validation_revision_and_ownership(api, other):
    api.start()
    case = api.new_case()
    fact = sample_fact(api, case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    path = f"/cases/{case['id']}/facts/{fact['id']}"
    assert api.req("PATCH", path, json={"expected_revision": rev, "action": "correct"}).status_code == 422
    assert api.req("PATCH", path, json={"expected_revision": rev, "action": "confirm",
                                        "corrected_value": {"value": "x", "units": None}}).status_code == 422
    assert api.req("PATCH", path, json={"expected_revision": rev + 5, "action": "confirm"}).status_code == 409
    other.start()
    assert other.req("PATCH", path, json={"expected_revision": rev, "action": "confirm"}).status_code == 404
    assert other.req("GET", f"/cases/{case['id']}/records").status_code == 404
    unknown = f"/cases/{case['id']}/facts/00000000-0000-4000-8000-000000000000"
    assert api.req("PATCH", unknown, json={"expected_revision": rev, "action": "confirm"}).status_code == 404


def test_confirmed_record_fact_after_guidance_invalidates_it(api):
    api.start()
    case = api.new_case()
    fact = sample_fact(api, case["id"])
    api.to_guided(case["id"])
    out = review(api, case["id"], fact["id"], {"action": "confirm"})
    assert out["next_action"] == "intake"
    read = api.case(case["id"])
    assert read["case"]["state"] == "intake" and read["case"]["latest_guidance_id"] is None
    assert api.req("GET", f"/cases/{case['id']}/guidance").status_code == 409


# Test-only synthetic record samples (the bundled sample has a single medication fact).
ALLERGY = {"fixture_id": "allergy", "kind": "record:allergies", "status": "unconfirmed",
           "original_text": "Allergy: penicillin (rash) - synthetic", "value": "Penicillin"}
MEDICATION = {"fixture_id": "medication", "kind": "record:medications", "status": "unconfirmed",
              "original_text": "Ibuprofen 200 mg as needed - synthetic", "value": "Ibuprofen 200 mg as needed"}
URGENT = {"fixture_id": "urgent", "kind": "fixture:urgent_signal", "status": "unconfirmed",
          "original_text": "Synthetic urgent finding (demo fixture)", "value": "Synthetic urgent finding"}
FILES = {"allergy-report": (synthetic_pdf("allergy"), [ALLERGY]),
         "mixed-report": (synthetic_pdf("mixed"), [ALLERGY, MEDICATION]),
         "urgent-report": (synthetic_pdf("urgent"), [URGENT, MEDICATION])}


@pytest.fixture
def scripted(tmp_path):
    from fastapi.testclient import TestClient
    from conftest import Api
    with TestClient(scripted_app(tmp_path, FILES)) as client:
        api = Api(client)
        api.start()
        yield client.app, api


def add(api, case_id: str, sample: str) -> dict:
    """Upload a scripted sample; returns its facts by kind."""
    assert upload_ok(api, case_id, FILES[sample][0], name=f"{sample}.pdf")["status"] == "succeeded"
    return {f["kind"]: f for f in records(api, case_id)["facts"] if f["source_id"]}


def export_bytes(api, case_id: str) -> bytes:
    rev = api.case(case_id)["case"]["revision"]
    job = api.ok("POST", f"/cases/{case_id}/exports", 202, "Job", key=True,
                 json={"expected_revision": rev, "user_reviewed": True})
    done = api.wait_job(job["id"])
    assert done["status"] == "succeeded"
    return api.req("GET", f"/exports/{done['result_id']}/download").content


def test_unconfirmed_allergy_is_surfaced_at_review_and_generation_but_never_used(scripted):
    """T-R20-S01: the pending allergy is listed for review and reported in guidance, never used as history."""
    _, api = scripted
    cid = api.new_case()["id"]
    allergy = add(api, cid, "allergy-report")["record:allergies"]
    assert allergy["status"] == "unconfirmed" and allergy["value"] == "Penicillin"
    assert all(f["id"] != allergy["id"] for f in api.case(cid)["case"]["confirmed_context"])
    job = api.to_guided(cid)
    assert job["status"] == "succeeded"
    guidance = api.ok("GET", f"/cases/{cid}/guidance", 200, "Guidance")
    assert "1 fact from your records was not reviewed, so it was not used." in guidance["uncertainties"]
    assert not any(allergy["id"] in c["fact_ids"] for c in guidance["claims"])
    assert "enicillin" not in json.dumps(guidance)
    pdf = export_bytes(api, cid)
    assert b"1 fact from your records was not reviewed" in pdf and b"enicillin" not in pdf
    # The fact is still listed for review, unchanged.
    assert records(api, cid)["facts"][0]["status"] == "unconfirmed"


def test_correct_one_fact_and_reject_another_in_one_case(scripted):
    """T-R20-S02: correction is stored apart from the untouched source; the rejected fact is never used."""
    application, api = scripted
    cid = api.new_case()["id"]
    facts = add(api, cid, "mixed-report")
    allergy, medication = facts["record:allergies"], facts["record:medications"]
    before = api.case(cid)["case"]["revision"]
    out = review(api, cid, allergy["id"], {"action": "correct",
                                           "corrected_value": {"value": "Amoxicillin", "units": None}})
    assert out["case_revision"] == before + 1 and out["fact"]["value"] == "Amoxicillin"
    assert out["fact"]["original_text"] == ALLERGY["original_text"]
    rejected = review(api, cid, medication["id"], {"action": "reject"})
    assert rejected["fact"]["status"] == "rejected" and rejected["case_revision"] == before + 1
    stored = sorted(p.read_bytes() for p in (application.state.ctx.settings.data_dir / "records").iterdir())
    assert stored == [FILES["mixed-report"][0]]
    with application.state.ctx.db.read() as conn:
        rows = conn.execute("SELECT fact_id, action, prior_value_json, new_value_json FROM fact_reviews "
                            "ORDER BY created_at").fetchall()
    assert [tuple(r) for r in rows] == [(allergy["id"], "correct", '"Penicillin"', '"Amoxicillin"'),
                                        (medication["id"], "reject", json.dumps(MEDICATION["value"]),
                                         json.dumps(MEDICATION["value"]))]
    context = api.case(cid)["case"]["confirmed_context"]
    assert [f["value"] for f in context if f["provenance"] == "document"] == ["Amoxicillin"]
    api.to_guided(cid)
    guidance = api.ok("GET", f"/cases/{cid}/guidance", 200, "Guidance")
    assert "Ibuprofen" not in json.dumps(guidance) and not any("from your records" in u
                                                                for u in guidance["uncertainties"])
    assert b"Ibuprofen" not in export_bytes(api, cid)


@pytest.mark.parametrize("action", ["confirm", "correct"])
def test_confirming_or_correcting_a_record_fact_reruns_the_urgency_check(scripted, action):
    """T-R20-S02 / R15: confirmation or correction re-runs the safety check; a fixture urgent fact interrupts."""
    application, api = scripted
    cid = api.new_case()["id"]
    facts = add(api, cid, "urgent-report")
    urgent, medication = facts["fixture:urgent_signal"], facts["record:medications"]
    # An ordinary confirmation re-runs the check, finds nothing urgent and returns the case to intake.
    before = api.case(cid)["case"]["revision"]
    ordinary = review(api, cid, medication["id"], {"action": "confirm"})
    assert ordinary["next_action"] == "records" and ordinary["case_revision"] == before + 1
    assert api.case(cid)["case"]["state"] == "intake"
    # Rejecting the urgent fixture fact does not use it.
    assert review(api, cid, urgent["id"], {"action": "reject"})["case_revision"] == before + 1
    assert api.case(cid)["case"]["state"] == "intake"
    body = {"action": "correct", "corrected_value": {"value": "Synthetic urgent finding", "units": None}} \
        if action == "correct" else {"action": "confirm"}
    out = review(api, cid, urgent["id"], body)
    assert out["next_action"] == "urgent" and out["case_revision"] == before + 2
    read = api.case(cid)
    assert read["case"]["state"] == "urgent" and "view_urgent" in read["allowed_actions"]
    assert "next_question" not in read["allowed_actions"] and "generate_guidance" not in read["allowed_actions"]
    rev = read["case"]["revision"]
    assert api.req("POST", f"/cases/{cid}/questions/next", key=True, json={"expected_revision": rev}).status_code == 409
    assert api.req("POST", f"/cases/{cid}/guidance", key=True, json={"expected_revision": rev}).status_code == 409
    with application.state.ctx.db.read() as conn:
        events = conn.execute("SELECT operation_id FROM events WHERE kind='urgent_interrupt'").fetchall()
    assert [e["operation_id"] for e in events] == ["reviewFact"]
