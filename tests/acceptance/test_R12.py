"""R12 relevant questions without duplication, from the reviewed pathway (local mode, ADR-003). M04.

The enabled package conforms to the Pathway contract, and local intake issues its approved templates verbatim in
R12 order (urgency priority, then stable template ID), never more than ten. Uses a scripted model; never contacts ZRT.
"""
import json

REQUIREMENT = "R12"


def _package(name: str) -> dict:
    from conftest import ROOT
    registry = json.loads((ROOT / "content/pathways/registry.json").read_text())
    [version] = registry["enabled_pathways"]
    return json.loads((ROOT / "content/pathways" / version / name).read_text())


def test_the_enabled_package_conforms_to_the_pathway_contract():
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from conftest import ROOT, format_checker
    contracts = ROOT / "spec/contracts"
    registry = Registry().with_resources(
        [(p.name, Resource.from_contents(json.loads(p.read_text()))) for p in contracts.glob("*.schema.json")])
    schema = json.loads((contracts / "Pathway.schema.json").read_text())
    pathway = _package("pathway.json")
    errors = list(Draft202012Validator(schema, registry=registry, format_checker=format_checker()).iter_errors(pathway))
    assert not errors, [e.message for e in errors]
    assert pathway["enabled"] is True and pathway["version"] == "general-adult-4"
    assert [(r["decision"], r["record_id"]) for r in pathway["reviewers"]] == [
        ("approved", "ADR-003-amendment-2026-10-16"), ("approved", "ADR-003-amendment-2026-10-19")]
    assert (pathway["review_date"], pathway["expires_at"]) == ("2026-10-19T00:00:00Z", "2027-10-15T00:00:00Z")


def test_the_package_holds_exactly_what_the_reviewer_approved():
    """Q01-Q10 verbatim from the reviewed templates; RF01-RF16 from the exported review record, RF17-RF19 and RF20 from
    the amendments, verbatim."""
    from conftest import ROOT
    fixtures = {q["template_id"]: q for q in json.loads((ROOT / "fixtures/questions.json").read_text())["questions"]}
    for q in _package("questions.json")["questions"]:
        assert all(q[k] == fixtures[q["template_id"]][k] for k in q), q["template_id"]
    review = json.loads((ROOT / "evidence/clinical-review/2026-10-15/review.json").read_text())
    amendment = json.loads((ROOT / "evidence/clinical-review/2026-10-15-amendment/decision.json").read_text())
    flags = _package("red-flags.json")
    amendment_4 = json.loads((ROOT / "evidence/clinical-review/2026-10-19-amendment-4/decision.json").read_text())
    rf20 = {"id": "RF20", "level": amendment_4["decision"]["level"],
            "text": "Took too much of a medicine, or swallowed something poisonous"}
    assert rf20["text"] in amendment_4["decision"]["what"]
    approved = ([{k: f[k] for k in ("id", "level", "text")} for f in review["red_flags"]] + amendment["added_red_flags"]
                + [rf20])
    # RF01-RF16 from the review, RF17-RF19 from the amendment, RF20 from amendment 4 (#194), verbatim
    assert flags["red_flags"] == approved
    assert _package("policy.json")["undetermined_floor"] == amendment["clinician_floor"]["published_level"]
    # Amendment 2 (#79) added only the red-flag screen (general-adult-3); amendment 4 (#194) adds only RF20.
    amendment_2 = json.loads((ROOT / "evidence/clinical-review/2026-10-16-amendment-2/decision.json").read_text())
    assert (amendment_2["pathway_from"], amendment_2["pathway_to"]) == ("general-adult-2", "general-adult-3")
    assert amendment_2["reviewer"] == {"role": "MD", "decision": "approved"}
    assert (amendment_4["pathway_from"], amendment_4["pathway_to"]) == ("general-adult-3", _package("pathway.json")["version"])
    assert amendment_4["reviewer"] == {"role": "MD", "decision": "approved"}
    assert _package("policy.json")["red_flag_screen"] is True
    same = lambda d: {k: v for k, v in d.items() if k not in ("package", "note", "review_record_id")}  # noqa: E731
    previous = json.loads((ROOT / "content/pathways/general-adult-3/questions.json").read_text())
    assert same(_package("questions.json")) == same(previous)
    previous_flags = json.loads((ROOT / "content/pathways/general-adult-3/red-flags.json").read_text())
    assert same({**flags, "red_flags": flags["red_flags"][:-1]}) == same(previous_flags)  # RF20 is the only addition
    assert flags["messages"] == review["red_flag_messages"]
    rules = {r["id"]: r["urgency_level"] for r in _package("pathway.json")["urgent_rules"]}
    assert rules == {f["id"]: f["level"] for f in flags["red_flags"]}


def test_local_intake_issues_the_approved_templates_in_order_and_stops_at_ten(local):
    from conftest import NO_RED_FLAGS
    api, _, _ = local
    case = api.new_case(context=[NO_RED_FLAGS])
    approved = {q["template_id"]: q for q in _package("questions.json")["questions"]}
    rev, issued = case["revision"], []
    while True:
        nq = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                    json={"expected_revision": rev})
        if nq["kind"] == "review_required":
            break
        q = nq["question"]
        assert q["pathway_version"] == "general-adult-4" and q["slot"] == len(issued) + 1
        assert q["text"] == approved[q["template_id"]]["text"]
        issued.append(q["template_id"])
        rev = api.ok("PUT", f"/cases/{case['id']}/answers/{q['id']}", 200, "SaveAnswerResponse",
                     json={"expected_revision": rev, "status": "unknown", "value": None})["case_revision"]
    assert issued == [f"Q{i:02d}" for i in range(1, 11)]
    assert api.case(case["id"])["case"]["issued_slots"] == 10


def test_question_wording_promises_no_adaptive_questioning():
    """#414: Q01-Q10 are issued in a fixed order that does not depend on answers (#357), so no reason may say an answer
    shapes the next question, and the person describes their own concern, not "this example". Checked in the enabled
    package and in every copy the mock path or the R12 comparison reads."""
    import re
    from conftest import ROOT
    adaptive = re.compile(r"next question|fictional question|this example", re.IGNORECASE)
    for path in ("content/pathways/general-adult-4/questions.json", "content/pathways/general-adult-3/questions.json",
                 "fixtures/questions.json"):
        questions = {q["template_id"]: q for q in json.loads((ROOT / path).read_text())["questions"]}
        for tid, q in questions.items():
            assert not adaptive.search(q["text"]) and not adaptive.search(q.get("why", "")), (path, tid)
        assert questions["Q01"]["why"] == "When it began helps a clinician understand the timeline.", path
        assert questions["Q04"]["why"] == "These details give a clinician context.", path
        assert questions["Q04"]["text"] == "Which details apply to your concern?", path
        assert questions["Q10"]["text"] == "Are the details you gave complete?", path
