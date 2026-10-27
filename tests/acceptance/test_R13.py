"""R13 answers are validated against the issued question type and persisted with the right type. M04."""
import pytest

REQUIREMENT = "R13"


def issue_until(api, cid, template_id):
    rev = api.case(cid)["case"]["revision"]
    while True:
        q = api.ok("POST", f"/cases/{cid}/questions/next", 200, "NextQuestionResponse", key=True,
                   json={"expected_revision": rev})["question"]
        if q["template_id"] == template_id:
            return q, rev
        rev = api.ok("PUT", f"/cases/{cid}/answers/{q['id']}", 200, "SaveAnswerResponse",
                     json={"expected_revision": rev, "status": "skipped", "value": None})["case_revision"]


@pytest.mark.parametrize("template,good,stored,bad", [
    ("Q01", "Q01-O02", "One to four weeks ago", ["Q04-O01", ["Q01-O01"], 2, "One to four weeks ago"]),
    ("Q03", 0, 0, [11, -1, True, "4", 4.5]),
    ("Q04", ["Q04-O01", "Q04-O02"], ["After long screen sessions", "After missed meals"],
     [[], ["Q04-O01", "Q04-O01"], ["Q04-O04", "Q04-O01"], "Q04-O01"]),
    ("Q05", "  Rested more.  ", "Rested more.", ["   ", "x" * 2001, 5, ["a"]]),
])
def test_typed_answers(api, template, good, stored, bad):
    api.start()
    cid = api.new_case()["id"]
    q, rev = issue_until(api, cid, template)
    for value in bad:
        r = api.req("PUT", f"/cases/{cid}/answers/{q['id']}", json={"expected_revision": rev, "status": "answered",
                                                                    "value": value})
        assert r.status_code == 422, (value, r.text)
    assert api.case(cid)["case"]["revision"] == rev  # rejected answers write nothing
    api.ok("PUT", f"/cases/{cid}/answers/{q['id']}", 200, "SaveAnswerResponse",
           json={"expected_revision": rev, "status": "answered", "value": good})
    fact = next(f for f in api.case(cid)["case"]["confirmed_context"] if f["kind"] == f"answer:{template}")
    assert fact["value"] == stored and type(fact["value"]) is type(stored)


def test_unknown_and_skipped_are_null_not_zero(api):
    api.start()
    cid = api.new_case()["id"]
    q, rev = issue_until(api, cid, "Q03")
    r = api.req("PUT", f"/cases/{cid}/answers/{q['id']}", json={"expected_revision": rev, "status": "unknown",
                                                                "value": 0})
    assert r.status_code == 422
    api.ok("PUT", f"/cases/{cid}/answers/{q['id']}", 200, "SaveAnswerResponse",
           json={"expected_revision": rev, "status": "unknown", "value": None})
    fact = next(f for f in api.case(cid)["case"]["confirmed_context"] if f["kind"] == "answer:Q03")
    assert fact["value"] is None


def test_duration_type_validation():
    """No fixture template uses duration; validate the type contract with a synthetic template."""
    from app.core.errors import ApiError
    from app.modules.intake.schemas import AnswerWrite
    from app.modules.intake.service import _validate
    template = {"response_type": "duration", "unknown_allowed": True, "skip_allowed": True}
    stored, shown = _validate(template, AnswerWrite(expected_revision=1, status="answered",
                                                    value={"amount": 3, "unit": "days"}))
    assert stored == {"amount": 3.0, "unit": "days"} and shown == "3 days"
    with pytest.raises(ApiError):
        _validate(template, AnswerWrite(expected_revision=1, status="answered", value="3 days"))
    with pytest.raises(ValueError):
        AnswerWrite(expected_revision=1, status="answered", value={"amount": -1, "unit": "days"})


# Test-only synthetic duration template: the bundled fixture pack has none (R13 needs one issued end to end).
DURATION_TEMPLATE = {
    "id": "QT-DUR", "template_id": "QT-DUR", "text": "How long has this been going on?", "type": "duration",
    "response_type": "duration", "why": "Synthetic test template.", "purpose": "acceptance test only",
    "required": False, "unknown_allowed": True, "skip_allowed": True,
    "constraints": {"allowed_units": ["days", "weeks", "months"]},
}
ORDER = ["Q01", "QT-DUR", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08", "Q09", "Q10"]
VALID = {"Q01": ("Q01-O02", "Q01-O02"), "QT-DUR": ({"amount": 3, "unit": "weeks"}, {"amount": 3.0, "unit": "weeks"}),
         "Q03": (0, 0), "Q04": (["Q04-O01", "Q04-O02"], ["Q04-O01", "Q04-O02"]),
         "Q05": ("  Rested more.  ", "Rested more.")}


@pytest.fixture
def typed(tmp_path):
    """An app whose routine scenario issues single, duration, scale, multi and text questions in that order."""
    import json
    import shutil
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.config import load_settings
    from app.main import create_app
    from conftest import ROOT, Api
    pack = tmp_path / "fixtures"
    shutil.copytree(ROOT / "fixtures", pack)
    questions = json.loads((pack / "questions.json").read_text())
    questions["questions"].append(DURATION_TEMPLATE)
    (pack / "questions.json").write_text(json.dumps(questions))
    scenarios = json.loads((pack / "scenarios.json").read_text())
    next(s for s in scenarios["scenarios"] if s["id"] == "routine")["question_template_ids"] = ORDER
    (pack / "scenarios.json").write_text(json.dumps(scenarios))
    application = create_app(replace(load_settings(), data_dir=tmp_path / "data", fixtures_dir=pack))
    with TestClient(application) as client:
        api = Api(client)
        api.start()
        yield application, api


def stored_answer(application, question_id: str):
    import json
    with application.state.ctx.db.read() as conn:
        rows = conn.execute("SELECT status, value_json FROM answers WHERE question_id=?", (question_id,)).fetchall()
        facts = conn.execute("SELECT value_json FROM facts WHERE source_id=? AND active=1", (question_id,)).fetchall()
    assert len(rows) == 1 and len(facts) == 1  # exactly one current answer and one current fact per question
    return rows[0]["status"], json.loads(rows[0]["value_json"]), json.loads(facts[0]["value_json"])


def issue_next(api, cid, rev):
    return api.ok("POST", f"/cases/{cid}/questions/next", 200, "NextQuestionResponse", key=True,
                  json={"expected_revision": rev})["question"]


def save(api, cid, qid, rev, status, value):
    return api.ok("PUT", f"/cases/{cid}/answers/{qid}", 200, "SaveAnswerResponse",
                  json={"expected_revision": rev, "status": status, "value": value})["case_revision"]


def test_issued_types_persist_typed_values_and_duration_units(typed):
    """T-R13-S01: every response type, including duration, is issued, saved and stored with its schema type."""
    application, api = typed
    cid = api.new_case()["id"]
    rev, issued = 1, {}
    for template in ORDER[:5]:
        q = issue_next(api, cid, rev)
        assert q["template_id"] == template
        issued[template] = q
        rev = save(api, cid, q["id"], rev, "answered", VALID[template][0])
    assert issued["QT-DUR"]["response_type"] == "duration"
    assert issued["QT-DUR"]["constraints"]["allowed_units"] == ["days", "weeks", "months"]
    for template, q in issued.items():
        status, value, _ = stored_answer(application, q["id"])
        expected = VALID[template][1]
        assert status == "answered" and value == expected and type(value) is type(expected)
    assert stored_answer(application, issued["QT-DUR"]["id"])[2] == "3 weeks"
    # Separate unknown and skipped responses store no value; the missing scale is null, not zero.
    q6 = issue_next(api, cid, rev)
    rev = save(api, cid, q6["id"], rev, "unknown", None)
    q7 = issue_next(api, cid, rev)
    rev = save(api, cid, q7["id"], rev, "skipped", None)
    rev = save(api, cid, issued["Q03"]["id"], rev, "skipped", None)
    assert stored_answer(application, q6["id"]) == ("unknown", None, None)
    assert stored_answer(application, q7["id"]) == ("skipped", None, None)
    assert stored_answer(application, issued["Q03"]["id"]) == ("skipped", None, None)


def test_edits_keep_exactly_one_current_answer_per_question(typed):
    """T-R13-S01: repeated edits replace the current answer; no question ever has two current answers."""
    application, api = typed
    cid = api.new_case()["id"]
    q1 = issue_next(api, cid, 1)
    rev = save(api, cid, q1["id"], 1, "answered", "Q01-O01")
    qd = issue_next(api, cid, rev)
    rev = save(api, cid, qd["id"], rev, "answered", {"amount": 2, "unit": "days"})
    for status, value in (("answered", "Q01-O03"), ("unknown", None), ("answered", "Q01-O02")):
        rev = save(api, cid, q1["id"], rev, status, value)
    rev = save(api, cid, qd["id"], rev, "answered", {"amount": 1.5, "unit": "months"})
    assert stored_answer(application, q1["id"])[:2] == ("answered", "Q01-O02")
    assert stored_answer(application, qd["id"])[:2] == ("answered", {"amount": 1.5, "unit": "months"})
    kinds = [f["kind"] for f in api.case(cid)["case"]["confirmed_context"]]
    assert kinds.count("answer:Q01") == 1 and kinds.count("answer:QT-DUR") == 1


INVALID = {
    "Q01": ["Q04-O01", ["Q01-O01"], 2, ""],
    "QT-DUR": [{"amount": -1, "unit": "days"}, {"amount": 2, "unit": "fortnights"}, {"amount": 2, "unit": "hours"},
               {"amount": 2}, "3 days", 3],
    "Q03": [11, -1, True, "4", 4.5],
    "Q04": [[], ["Q04-O01", "Q04-O01"], ["Q04-O04", "Q04-O01"], ["Q99-O01"], "Q04-O01"],
    "Q05": ["   ", "x" * 2001, 5, ["a"]],
}


@pytest.mark.parametrize("template", list(INVALID))
def test_invalid_values_name_the_field_and_keep_the_last_valid_answer(typed, template):
    """T-R13-S02: each invalid value is refused with a field error; the earlier valid answer stays current."""
    application, api = typed
    cid = api.new_case()["id"]
    rev = 1
    while True:
        q = issue_next(api, cid, rev)
        if q["template_id"] == template:
            break
        rev = save(api, cid, q["id"], rev, "skipped", None)
    rev = save(api, cid, q["id"], rev, "answered", VALID[template][0])
    before = stored_answer(application, q["id"])
    for value in INVALID[template]:
        r = api.req("PUT", f"/cases/{cid}/answers/{q['id']}",
                    json={"expected_revision": rev, "status": "answered", "value": value})
        body = r.json()
        assert r.status_code == 422 and body["code"] in {"ANSWER_INVALID", "VALIDATION_FAILED"}, (value, body)
        assert body["field_errors"] and all(e["field"].startswith("value") for e in body["field_errors"]), body
        assert "case_revision" not in body and "value" not in body
        assert stored_answer(application, q["id"]) == before
    assert api.case(cid)["case"]["revision"] == rev


# --- #215: a scale answer carries its range for every reader ---------------------------------------------------------
def test_a_scale_answer_is_stored_with_its_range_for_review_summary_and_pdf(api):
    """#215: "4" alone means nothing on A06, A12 or the PDF; the fact's units say "on a 0–10 scale"."""
    api.start()
    case = api.new_case()
    api.answer_all(case["id"])  # answers every scale question with 4
    context = api.case(case["id"])["case"]["confirmed_context"]
    scale = [c for c in context if c["value"] == 4]
    assert scale and all(c["units"] == "on a 0–10 scale" for c in scale)
    assert all(c["units"] is None for c in context if c["value"] != 4 and str(c["kind"]).startswith("answer:"))


def test_the_local_model_reads_the_scale_value_not_its_display_range(local):
    """#215: the guidance input and the red-flag screen carry the answer value only, so the qualified input is unchanged."""
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    case = api.new_case(concern="A mild headache since Monday.", context=[NO_RED_FLAGS])
    api.to_guided(case["id"])
    guidance = next(c for c in model.calls if c["task"] == "guidance")["snapshot"]
    facts = guidance["case"]["confirmed_facts"]
    assert all(set(f) == {"id", "question", "answer"} for f in facts)
    assert "scale" not in str(facts)
    screen = next(c for c in reversed(model.calls) if c["task"] == "red_flag_screen")["snapshot"]
    assert "scale" not in str(screen["person_words"])
