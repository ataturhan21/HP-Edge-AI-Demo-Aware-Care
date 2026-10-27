"""R04 unknown profile facts: a skipped allergy answer is unknown, never 'no allergies'. M02/M03."""
REQUIREMENT = "R04"


def ctx_item(kind, value):
    return {"kind": kind, "value": value, "units": None, "origin": "user", "profile_revision": None}


def context(api, items):
    case = api.ok("POST", "/cases", 201, "Case", key=True, json={"concern": "Synthetic.", "confirmed_context": items})
    return {f["kind"]: f["value"] for f in case["confirmed_context"]}


def test_skipped_allergy_is_persisted_as_unknown(api):
    api.start()
    assert context(api, [])["allergy_status"] == "unknown"
    assert context(api, [ctx_item("age_years", 38)])["allergy_status"] == "unknown"


def test_explicit_unknown_values_are_kept_as_null(api):
    api.start()
    got = context(api, [ctx_item("age_years", None), ctx_item("history", None), ctx_item("medications", None),
                        ctx_item("allergy_status", "unknown")])
    assert got == {"age_years": None, "history": None, "medications": None, "allergy_status": "unknown"}


def test_explicit_denial_is_a_separate_value(api):
    api.start()
    assert context(api, [ctx_item("allergy_status", "none_reported")])["allergy_status"] == "none_reported"
    got = context(api, [ctx_item("allergy_status", "reported"), ctx_item("allergies", "Penicillin (fictional)")])
    assert got["allergy_status"] == "reported" and got["allergies"] == "Penicillin (fictional)"


def test_inconsistent_or_invalid_context_is_rejected(api):
    api.start()
    bad = [
        [ctx_item("allergy_status", "none")],
        [ctx_item("allergy_status", "none_reported"), ctx_item("allergies", "x")],
        [ctx_item("allergy_status", "reported")],
        [ctx_item("age_years", 12)],
        [ctx_item("age_years", True)],
        [ctx_item("age_years", 131)],
        [ctx_item("age_years", 40.5)],
        [ctx_item("allergy_status", "reported"), ctx_item("allergies", None)],
        [ctx_item("medications", "   ")],
        [ctx_item("history", "a"), ctx_item("history", "b")],
    ]
    for items in bad:
        r = api.req("POST", "/cases", key=True, json={"concern": "Synthetic.", "confirmed_context": items})
        assert r.status_code == 422 and r.json()["code"] == "VALIDATION_FAILED", (items, r.text)
    assert api.ok("GET", "/cases", 200, "CaseList")["items"] == []


def test_negative_and_positive_allergy_fixtures_persist_distinctly_with_confirmation_time(api):
    """T-R04-S02: none_reported and reported (with item and confirmation timestamp) never collapse into unknown."""
    from datetime import datetime
    api.start()
    negative = api.ok("POST", "/cases", 201, "Case", key=True, json={
        "concern": "Synthetic.", "confirmed_context": [ctx_item("allergy_status", "none_reported")]})
    positive = api.ok("POST", "/cases", 201, "Case", key=True, json={
        "concern": "Synthetic.", "confirmed_context": [ctx_item("allergy_status", "reported"),
                                                       ctx_item("allergies", "Fictional penicillin allergy")]})
    for case, expected in ((negative, "none_reported"), (positive, "reported")):
        stored = api.case(case["id"])["case"]["confirmed_context"]  # read back the stored representation
        facts = {f["kind"]: f for f in stored}
        assert facts["allergy_status"]["value"] == expected
        assert facts["allergy_status"]["confirmed_at"]
        datetime.fromisoformat(facts["allergy_status"]["confirmed_at"].replace("Z", "+00:00"))
    stored = {f["kind"]: f for f in api.case(positive["id"])["case"]["confirmed_context"]}
    assert stored["allergies"]["value"] == "Fictional penicillin allergy" and stored["allergies"]["confirmed_at"]


# QA 2026-10-19 (#261, #262, #305): wrong-typed or non-finite values are field errors (422) and nothing is stored.

def _raw(api, method, path, body: str, key: bool = False):
    """Sends a body as written: Python's JSON parser, like the API's, accepts the non-JSON literals NaN and Infinity."""
    return api.req(method, path, key=key, content=body, headers={"Content-Type": "application/json"})


def _stored_cases(api) -> int:
    return len(api.ok("GET", "/cases", 200, "CaseList")["items"])


def test_non_finite_context_numbers_are_refused_on_create_and_edit_and_nothing_is_stored(api):
    """#261: Infinity and NaN used to be stored (500), and every later read of the case failed."""
    api.start()
    for kind, literal in (("weight_kg", "Infinity"), ("age_years", "NaN"), ("age_years", "-Infinity")):
        body = ('{"concern":"Headache","confirmed_context":[{"kind":"%s","value":%s,"units":null,"origin":"user",'
                '"profile_revision":null}]}' % (kind, literal))
        r = _raw(api, "POST", "/cases", body, key=True)
        assert r.status_code == 422 and r.json()["code"] == "VALIDATION_FAILED", (kind, literal, r.text)
        assert any(f["field"].startswith("confirmed_context.0.value") for f in r.json()["field_errors"])
    assert _stored_cases(api) == 0
    case = api.new_case()
    r = _raw(api, "PATCH", f"/cases/{case['id']}", '{"expected_revision":1,"confirmed_context":[{"kind":"weight_kg",'
             '"value":Infinity,"units":"kg","origin":"user","profile_revision":null}]}')
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_FAILED"
    read = api.case(case["id"])  # still readable, unchanged
    assert read["case"]["revision"] == 1 and "weight_kg" not in {f["kind"] for f in read["case"]["confirmed_context"]}


def test_a_non_finite_duration_answer_is_refused_and_the_case_stays_readable(api):
    """#261: saveAnswer. No mock question is a duration question, so the request model is checked on its own as well:
    the refusal happens before the question type is looked up."""
    from app.modules.intake.schemas import AnswerWrite
    from pydantic import ValidationError
    import pytest
    for amount in (float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            AnswerWrite.model_validate({"expected_revision": 1, "status": "answered",
                                        "value": {"amount": amount, "unit": "days"}})
    api.start()
    case = api.new_case()
    nq = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                json={"expected_revision": 1})
    r = _raw(api, "PUT", f"/cases/{case['id']}/answers/{nq['question']['id']}",
             '{"expected_revision":1,"status":"answered","value":{"amount":Infinity,"unit":"days"}}')
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_FAILED"
    assert api.case(case["id"])["case"]["revision"] == 1


def test_a_non_finite_fact_correction_is_refused_and_records_stay_readable(api):
    """#261: reviewFact correction."""
    from records_helpers import records, upload_ok
    api.start()
    case = api.new_case()
    upload_ok(api, case["id"])
    fact = records(api, case["id"])["facts"][0]
    rev = api.case(case["id"])["case"]["revision"]
    r = _raw(api, "PATCH", f"/cases/{case['id']}/facts/{fact['id']}",
             '{"expected_revision":%d,"action":"correct","corrected_value":{"value":Infinity,"units":null}}' % rev)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_FAILED"
    assert records(api, case["id"])["facts"][0]["status"] == "unconfirmed"
    assert api.case(case["id"])["case"]["revision"] == rev


def test_dumps_refuses_non_finite_values_as_a_backstop():
    """#261: even a value that slipped past the request models is never written."""
    import pytest
    from app.core.db import dumps
    for value in (float("inf"), float("nan"), {"a": [float("-inf")]}):
        with pytest.raises(ValueError):
            dumps(value)


def test_wrong_typed_context_values_are_field_errors_not_500(api):
    """#262: a list allergy status raised TypeError and a non-finite age OverflowError (500), on create and edit."""
    api.start()
    bad = [(ctx_item("allergy_status", ["reported"]), "confirmed_context.allergy_status"),
           (ctx_item("allergy_status", 3), "confirmed_context.allergy_status"),
           (ctx_item("age_years", "forty"), "confirmed_context.age_years"),
           (ctx_item("age_years", 40.5), "confirmed_context.age_years")]
    for item, field in bad:
        r = api.req("POST", "/cases", key=True, json={"concern": "Synthetic.", "confirmed_context": [item]})
        assert r.status_code == 422, (item, r.text)
        assert [f["field"] for f in r.json()["field_errors"]] == [field]
    assert _stored_cases(api) == 0
    case = api.new_case()
    for item, field in bad:
        r = api.req("PATCH", f"/cases/{case['id']}", json={"expected_revision": 1, "confirmed_context": [item]})
        assert r.status_code == 422 and [f["field"] for f in r.json()["field_errors"]] == [field], r.text
    assert api.case(case["id"])["case"]["revision"] == 1


def test_a_concern_of_only_whitespace_or_invisible_characters_is_empty(api):
    """#305 (server half): U+200B, U+2060, U+FEFF and other format or control characters alone are not a concern."""
    api.start()
    for concern in ("​", "⁠﻿", " ​‌‍\t", "  ", "\x00\x07"):
        r = api.req("POST", "/cases", key=True, json={"concern": concern, "confirmed_context": []})
        assert r.status_code == 422, repr(concern)
        assert r.json()["field_errors"][0]["field"] == "concern"
    assert _stored_cases(api) == 0
    case = api.new_case("Headache​ after work.")  # visible text with an invisible character is kept as written
    assert case["concern"] == "Headache​ after work."
    r = api.req("PATCH", f"/cases/{case['id']}", json={"expected_revision": 1, "concern": "﻿⁠"})
    assert r.status_code == 422 and r.json()["field_errors"][0]["field"] == "concern"
    assert api.case(case["id"])["case"]["concern"] == "Headache​ after work."


# --- #433 (R04, R14): a client supplies profile context only ---------------------------------------------------------
# Answer facts are written by saveAnswer, fixture signals by the A05 trigger, record facts by the record review. A
# client item in those namespaces was counted as an answered question ("You answered 1 intake question(s)" with every
# question unknown) and could never be removed by a later context edit.

FORGED = [ctx_item("answer:forged", "yes"), ctx_item("fixture:urgent_signal", "client-made"),
          ctx_item("record:medications", "client-made")]


def test_reserved_answer_fixture_and_record_kinds_are_refused_on_create_and_edit(api):
    from conftest import NO_RED_FLAGS
    api.start()
    for forged in FORGED:
        r = api.req("POST", "/cases", key=True, json={"concern": "Synthetic.", "confirmed_context": [NO_RED_FLAGS,
                                                                                                   forged]})
        assert r.status_code == 422, (forged["kind"], r.text)
        body = r.json()
        assert body["code"] == "VALIDATION_FAILED"
        assert body["field_errors"][0]["field"] == "confirmed_context.kind"
        assert body["field_errors"][0]["code"] == "reserved"
    assert _stored_cases(api) == 0
    case = api.new_case(context=[NO_RED_FLAGS])
    for forged in FORGED:
        r = api.req("PATCH", f"/cases/{case['id']}", json={"expected_revision": case["revision"],
                                                            "confirmed_context": [forged]})
        assert r.status_code == 422 and r.json()["field_errors"][0]["code"] == "reserved", forged["kind"]
    read = api.case(case["id"])["case"]
    assert read["revision"] == case["revision"]
    assert not [f for f in read["confirmed_context"] if f["kind"].split(":")[0] in ("answer", "fixture", "record")]


def test_with_every_question_unknown_no_answer_is_counted_and_a_context_edit_replaces_the_client_context(api):
    """#433: zero answered questions stay undetermined with no "You answered N" claim (R14, #268); a later context
    edit replaces everything the client gave."""
    from conftest import NO_RED_FLAGS
    api.start()
    case = api.new_case(context=[NO_RED_FLAGS, ctx_item("history", "Synthetic history.")])
    rev = case["revision"]
    while True:
        nq = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                    json={"expected_revision": rev})
        if nq["kind"] == "review_required":
            break
        rev = api.ok("PUT", f"/cases/{case['id']}/answers/{nq['question']['id']}", 200, "SaveAnswerResponse",
                     json={"expected_revision": rev, "status": "unknown", "value": None})["case_revision"]
    edited = api.ok("PATCH", f"/cases/{case['id']}", 200, "Case",
                    json={"expected_revision": rev, "confirmed_context": [NO_RED_FLAGS, ctx_item("age_years", 40)]})
    client = {f["kind"] for f in edited["confirmed_context"] if f["source_id"] is None}
    assert client == {"red_flags", "age_years", "allergy_status"}  # the history item was replaced
    job = api.to_guided(case["id"])
    assert job["status"] == "succeeded"
    g = api.ok("GET", f"/cases/{case['id']}/guidance", 200, "Guidance")
    assert g["urgency"]["level"] == "undetermined"
    assert not [c for c in g["claims"] if c["text"].startswith("You answered")]


def test_only_answers_to_issued_questions_are_counted():
    """#433 defence in depth: an `answer:` fact without its question as source is never an answered question."""
    from app.modules.guidance.service import intake_answers
    facts = [{"kind": "answer:Q01", "value": "a", "source_id": "q-1", "provenance": "user"},
             {"kind": "answer:Q02", "value": None, "source_id": "q-2", "provenance": "user"},
             {"kind": "answer:forged", "value": "yes", "source_id": None, "provenance": "user"}]
    answered, unknown = intake_answers(facts)
    assert [f["kind"] for f in answered] == ["answer:Q01"] and [f["kind"] for f in unknown] == ["answer:Q02"]


def test_a_concern_of_only_blank_looking_characters_is_empty(api):
    """#452: the other default-ignorable characters (U+00AD soft hyphen, U+200E/U+200F marks, U+180E, U+034F, variation
    selectors), the Braille blank U+2800 and the Hangul fillers U+3164, U+115F, U+1160 and U+FFA0 alone are not a
    concern either; each is the field error `empty`, as on A03."""
    api.start()
    for concern in ("\u00ad", "\u200e\u200f", "\u180e", "\u2800", "\u3164", "\u115f\u1160", "\uffa0",
                    "\u034f\ufe0f", " \u2800 \u3164 "):
        r = api.req("POST", "/cases", key=True, json={"concern": concern, "confirmed_context": []})
        assert r.status_code == 422, repr(concern)
        assert r.json()["field_errors"][0] == {"field": "concern", "code": "empty", "message": "Required."}
    assert _stored_cases(api) == 0
    assert api.new_case("Rash \u2800 since Monday.")["concern"] == "Rash \u2800 since Monday."  # visible text is kept
