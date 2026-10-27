"""R11/R12/R14 issued-slot accounting and typed answers (mock routine scenario). M04."""

REQUIREMENT = "R11"


def test_refetch_returns_same_question_without_new_slot(api):
    api.start()
    case = api.new_case()
    q1 = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                json={"expected_revision": 1})
    q2 = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                json={"expected_revision": 1})
    assert q1["question"]["id"] == q2["question"]["id"] and q1["question"]["slot"] == 1
    assert api.case(case["id"])["case"]["issued_slots"] == 1


def test_never_more_than_ten_slots_and_edits_do_not_allocate(api):
    api.start()
    case = api.new_case()
    result = api.answer_all(case["id"])
    assert result["kind"] == "review_required"
    read = api.case(case["id"])["case"]
    assert read["issued_slots"] == 10 and read["state"] == "review"
    answer_fact = next(f for f in read["confirmed_context"] if f["kind"] == "answer:Q01")
    r = api.ok("PUT", f"/cases/{case['id']}/answers/{answer_fact['source_id']}", 200, "SaveAnswerResponse",
               json={"expected_revision": read["revision"], "status": "unknown", "value": None})
    assert r["next_action"] == "review"
    again = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                   json={"expected_revision": r["case_revision"]})
    assert again["kind"] == "review_required"
    assert any("When did this concern begin" in g for g in again["unresolved_gaps"])
    assert api.case(case["id"])["case"]["issued_slots"] == 10


def test_answer_validated_against_issued_question(api):
    api.start()
    case = api.new_case()
    q = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
               json={"expected_revision": 1})["question"]
    assert q["response_type"] == "single_choice"
    bad = api.req("PUT", f"/cases/{case['id']}/answers/{q['id']}",
                  json={"expected_revision": 1, "status": "answered", "value": "Q99-O01"})
    assert bad.status_code == 422 and bad.json()["code"] == "ANSWER_INVALID"
    assert api.case(case["id"])["case"]["revision"] == 1
    mismatched = api.req("PUT", f"/cases/{case['id']}/answers/{q['id']}",
                         json={"expected_revision": 1, "status": "skipped", "value": "Q01-O01"})
    assert mismatched.status_code == 422


def test_exclusive_choice_cannot_combine(api):
    api.start()
    case = api.new_case()
    rev = 1
    for _ in range(3):
        q = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                   json={"expected_revision": rev})["question"]
        rev = api.ok("PUT", f"/cases/{case['id']}/answers/{q['id']}", 200, "SaveAnswerResponse",
                     json={"expected_revision": rev, "status": "skipped", "value": None})["case_revision"]
    q4 = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                json={"expected_revision": rev})["question"]
    assert q4["template_id"] == "Q04"
    r = api.req("PUT", f"/cases/{case['id']}/answers/{q4['id']}",
                json={"expected_revision": rev, "status": "answered", "value": ["Q04-O01", "Q04-O04"]})
    assert r.status_code == 422


def question_rows(app, case_id: str) -> list:
    with app[0].state.ctx.db.read() as conn:
        return conn.execute("SELECT slot, template_id, status FROM questions WHERE case_id=? ORDER BY slot",
                            (case_id,)).fetchall()


def test_ten_mixed_slots_allocate_exactly_ten_question_records(app, api):
    """T-R11-S01: answered, unknown and skipped prompts fill the cap; no 11th Question record ever exists."""
    api.start()
    cid = api.new_case()["id"]
    rev, how = 1, ["answered", "skipped", "unknown"]
    for i in range(10):
        q = api.ok("POST", f"/cases/{cid}/questions/next", 200, "NextQuestionResponse", key=True,
                   json={"expected_revision": rev})["question"]
        status = how[i % 3]
        value = q["choices"][0]["id"] if status == "answered" and q["response_type"] == "single_choice" else None
        if status == "answered" and value is None:
            status = "skipped"
        rev = api.ok("PUT", f"/cases/{cid}/answers/{q['id']}", 200, "SaveAnswerResponse",
                     json={"expected_revision": rev, "status": status, "value": value})["case_revision"]
    with app[0].state.ctx.db.read() as conn:
        answers = conn.execute("SELECT status FROM answers WHERE case_id=?", (cid,)).fetchall()
    assert {a["status"] for a in answers} == {"answered", "skipped", "unknown"} and len(answers) == 10
    for _ in range(2):
        nq = api.ok("POST", f"/cases/{cid}/questions/next", 200, "NextQuestionResponse", key=True,
                    json={"expected_revision": rev})
        assert nq["kind"] == "review_required" and nq["unresolved_gaps"]
    rows = question_rows(app, cid)
    assert [r["slot"] for r in rows] == list(range(1, 11)) and len({r["template_id"] for r in rows}) == 10
    first = next(f for f in api.case(cid)["case"]["confirmed_context"] if f["kind"] == "answer:Q01")
    rev = api.ok("PUT", f"/cases/{cid}/answers/{first['source_id']}", 200, "SaveAnswerResponse",
                 json={"expected_revision": rev, "status": "unknown", "value": None})["case_revision"]
    assert api.ok("POST", f"/cases/{cid}/questions/next", 200, "NextQuestionResponse", key=True,
                  json={"expected_revision": rev})["kind"] == "review_required"
    assert len(question_rows(app, cid)) == 10 and api.case(cid)["case"]["issued_slots"] == 10


def test_invalidated_prompt_keeps_its_record_and_allocates_nothing_more(app, api):
    """T-R11-S01 (invalidated prompts): an interrupted prompt keeps its slot and Question record."""
    api.start()
    cid = api.new_case()["id"]
    q = api.ok("POST", f"/cases/{cid}/questions/next", 200, "NextQuestionResponse", key=True,
               json={"expected_revision": 1})["question"]
    api.ok("PUT", f"/cases/{cid}/answers/{q['id']}", 200, "SaveAnswerResponse",
           json={"expected_revision": 1, "status": "answered", "value": ["fixture:urgent-signal"]})
    rev = api.case(cid)["case"]["revision"]
    assert api.req("POST", f"/cases/{cid}/questions/next", key=True, json={"expected_revision": rev}).status_code == 409
    assert [tuple(r) for r in question_rows(app, cid)] == [(1, "Q01", "invalidated")]
    assert api.case(cid)["case"]["issued_slots"] == 1


def test_concurrent_next_question_requests_issue_one_question(app, api):
    """T-R11-S02: concurrent requests for the same case revision get the same question and one slot."""
    from concurrent.futures import ThreadPoolExecutor
    api.start()
    cid = api.new_case()["id"]

    def ask(_):
        return api.ok("POST", f"/cases/{cid}/questions/next", 200, "NextQuestionResponse", key=True,
                      json={"expected_revision": 1})

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(ask, range(16)))
    assert {r["question"]["id"] for r in results} == {results[0]["question"]["id"]}
    assert {r["question"]["slot"] for r in results} == {1}
    assert len(question_rows(app, cid)) == 1 and api.case(cid)["case"]["issued_slots"] == 1
    # Answering or skipping the active question is not a new issue; only the next call allocates slot 2.
    rev = api.ok("PUT", f"/cases/{cid}/answers/{results[0]['question']['id']}", 200, "SaveAnswerResponse",
                 json={"expected_revision": 1, "status": "skipped", "value": None})["case_revision"]
    assert len(question_rows(app, cid)) == 1 and api.case(cid)["case"]["issued_slots"] == 1

    def ask_again(_):
        return api.ok("POST", f"/cases/{cid}/questions/next", 200, "NextQuestionResponse", key=True,
                      json={"expected_revision": rev})

    with ThreadPoolExecutor(max_workers=8) as pool:
        second = list(pool.map(ask_again, range(16)))
    assert {r["question"]["slot"] for r in second} == {2} and len({r["question"]["id"] for r in second}) == 1
    assert [r["slot"] for r in question_rows(app, cid)] == [1, 2]


# #357 (CHG-DEV-API-005): a previous-question step on A05. A question response carries the earlier issued questions
# with their current answers; changing one during intake keeps every later question and answer, because the issue
# order does not depend on answers (R12). The 10-slot cap, revision checks and urgent screening still apply.
TRIGGER = ["fixture:urgent-signal"]


def _next(api, cid: str, rev: int, key: str | None = None) -> dict:
    headers = {"Idempotency-Key": key} if key else None
    return api.ok("POST", f"/cases/{cid}/questions/next", 200, "NextQuestionResponse", key=key is None,
                  headers=headers, json={"expected_revision": rev})


def _save(api, cid: str, qid: str, rev: int, status: str, value) -> dict:
    return api.ok("PUT", f"/cases/{cid}/answers/{qid}", 200, "SaveAnswerResponse",
                  json={"expected_revision": rev, "status": status, "value": value})


def _three_answered(api) -> tuple[str, int, dict]:
    """Q01 answered, Q02 skipped, Q03 answered 7; returns (case ID, revision, the response issuing Q04)."""
    api.start()
    cid = api.new_case()["id"]
    rev = 1
    for status, value in (("answered", "Q01-O02"), ("skipped", None), ("answered", 7)):
        q = _next(api, cid, rev)["question"]
        rev = _save(api, cid, q["id"], rev, status, value)["case_revision"]
    return cid, rev, _next(api, cid, rev)


def test_357_a_question_carries_the_earlier_questions_with_their_current_answers(api):
    cid, rev, nq = _three_answered(api)
    assert nq["question"]["slot"] == 4
    earlier = nq["earlier_questions"]
    assert [e["question"]["slot"] for e in earlier] == [1, 2, 3]
    assert [e["question"]["template_id"] for e in earlier] == ["Q01", "Q02", "Q03"]
    assert [(e["answer"]["status"], e["answer"]["value"]) for e in earlier] == [
        ("answered", "Q01-O02"), ("skipped", None), ("answered", 7)]
    assert all(e["answer"]["question_id"] == e["question"]["id"] for e in earlier)
    # The first question has no earlier one.
    api.start()
    first = _next(api, api.new_case()["id"], 1)
    assert first["question"]["slot"] == 1 and first["earlier_questions"] == []


def test_357_a_replayed_question_reads_the_earlier_answers_fresh_and_stores_none(app, api):
    cid, rev, _ = _three_answered(api)
    key = "6f0b5c1e-0000-4000-8000-000000000357"
    before = _next(api, cid, rev, key)
    q1 = before["earlier_questions"][0]["question"]
    rev2 = _save(api, cid, q1["id"], rev, "answered", "Q01-O03")["case_revision"]
    replay = _next(api, cid, rev, key)  # same key and request: the same question, the answers as they are now
    assert replay["question"]["id"] == before["question"]["id"]
    assert replay["earlier_questions"][0]["answer"]["value"] == "Q01-O03"
    assert _next(api, cid, rev2)["question"]["id"] == before["question"]["id"]
    with app[0].state.ctx.db.read() as conn:
        stored = [r["response_json"] for r in conn.execute("SELECT response_json FROM idempotency WHERE case_id=?",
                                                           (cid,))]
    assert stored and not any("earlier_questions" in s for s in stored)


def test_357_changing_an_earlier_answer_keeps_the_later_questions_and_answers(app, api):
    cid, rev, nq = _three_answered(api)
    current = nq["question"]
    q2 = nq["earlier_questions"][1]["question"]
    changed = _save(api, cid, q2["id"], rev, "answered", "Q02-O03")
    assert changed["next_action"] == "next_question" and changed["case_revision"] == rev + 1
    again = _next(api, cid, changed["case_revision"])
    # The same current question, no new slot; the later answer (Q03) is kept; the change is the current answer.
    assert (again["question"]["id"], again["question"]["slot"]) == (current["id"], 4)
    assert [(e["answer"]["status"], e["answer"]["value"]) for e in again["earlier_questions"]] == [
        ("answered", "Q01-O02"), ("answered", "Q02-O03"), ("answered", 7)]
    assert api.case(cid)["case"]["issued_slots"] == 4
    assert [tuple(r) for r in question_rows(app, cid)] == [
        (1, "Q01", "answered"), (2, "Q02", "answered"), (3, "Q03", "answered"), (4, "Q04", "active")]
    facts = [f for f in api.case(cid)["case"]["confirmed_context"] if f["kind"].startswith("answer:")]
    assert sorted(f["kind"] for f in facts) == ["answer:Q01", "answer:Q02", "answer:Q03"]  # one current answer each
    assert next(f["value"] for f in facts if f["kind"] == "answer:Q02") == "Worsening"


def test_357_the_cap_holds_when_earlier_answers_change_at_every_step(app, api):
    api.start()
    cid = api.new_case()["id"]
    rev, issued = 1, []
    while True:
        nq = _next(api, cid, rev)
        if nq["kind"] == "review_required":
            break
        issued.append(nq["question"]["template_id"])
        if nq["earlier_questions"]:  # change the previous answer first, as A05's "Previous question" does
            prev = nq["earlier_questions"][-1]
            rev = _save(api, cid, prev["question"]["id"], rev, "unknown", None)["case_revision"]
            assert _next(api, cid, rev)["question"]["id"] == nq["question"]["id"]
        rev = _save(api, cid, nq["question"]["id"], rev, "skipped", None)["case_revision"]
    assert issued == [f"Q{i:02d}" for i in range(1, 11)]
    assert len(question_rows(app, cid)) == 10 and api.case(cid)["case"]["issued_slots"] == 10
    assert api.case(cid)["case"]["state"] == "review"


def test_357_a_changed_earlier_answer_with_the_urgent_signal_routes_to_urgent(app, api):
    cid, rev, nq = _three_answered(api)
    q2 = nq["earlier_questions"][1]["question"]
    urgent = _save(api, cid, q2["id"], rev, "answered", TRIGGER)
    assert urgent == {"case_revision": rev + 1, "next_action": "urgent"}
    read = api.case(cid)
    assert read["case"]["state"] == "urgent" and "next_question" not in read["allowed_actions"]
    assert api.req("POST", f"/cases/{cid}/questions/next", key=True,
                   json={"expected_revision": read["case"]["revision"]}).status_code == 409
    assert read["case"]["issued_slots"] == 4  # nothing more is issued; the changed prompt keeps its slot
    assert ("Q02", "invalidated") in [(r["template_id"], r["status"]) for r in question_rows(app, cid)]


def test_357_a_stale_revision_on_an_earlier_answer_is_a_conflict_and_changes_nothing(api):
    cid, rev, nq = _three_answered(api)
    q1 = nq["earlier_questions"][0]["question"]
    rev2 = _save(api, cid, q1["id"], rev, "answered", "Q01-O01")["case_revision"]
    stale = api.req("PUT", f"/cases/{cid}/answers/{q1['id']}",
                    json={"expected_revision": rev, "status": "answered", "value": "Q01-O03"})
    assert stale.status_code == 409 and stale.json()["code"] == "REVISION_CONFLICT"
    again = _next(api, cid, rev2)
    assert again["earlier_questions"][0]["answer"]["value"] == "Q01-O01"
    assert api.case(cid)["case"]["revision"] == rev2


def test_357_local_a_changed_earlier_answer_is_screened_before_guidance(local):
    """Local mode: the reviewed screen reads the changed answer (not the old one) before guidance; a red flag there
    routes to urgent help with no guidance generated."""
    from conftest import NO_RED_FLAGS
    api, model, _ = local
    case = api.new_case(concern="A chest cold for a week.", context=[NO_RED_FLAGS])
    rev, changed = case["revision"], False
    while True:
        nq = api.ok("POST", f"/cases/{case['id']}/questions/next", 200, "NextQuestionResponse", key=True,
                    json={"expected_revision": rev})
        if nq["kind"] == "review_required":
            break
        q = nq["question"]
        if q["template_id"] == "Q06" and not changed:
            prev = nq["earlier_questions"][-1]
            assert (prev["question"]["template_id"], prev["answer"]["value"]) == ("Q05", "Rest and water.")
            rev = api.ok("PUT", f"/cases/{case['id']}/answers/{prev['question']['id']}", 200, "SaveAnswerResponse",
                         json={"expected_revision": rev, "status": "answered",
                               "value": "I have been coughing up blood since yesterday."})["case_revision"]
            changed = True
            model.screen = {"present": ["RF17"]}
            continue
        value = {"single_choice": lambda: q["choices"][0]["id"], "multiple_choice": lambda: [q["choices"][0]["id"]],
                 "text": lambda: "Rest and water.", "scale": lambda: 4}[q["response_type"]]()
        rev = api.ok("PUT", f"/cases/{case['id']}/answers/{q['id']}", 200, "SaveAnswerResponse",
                     json={"expected_revision": rev, "status": "answered", "value": value})["case_revision"]
    assert changed and api.case(case["id"])["case"]["issued_slots"] == 10
    rev = api.case(case["id"])["case"]["revision"]
    api.ok("POST", f"/cases/{case['id']}/review", 200, "Case", json={"expected_revision": rev, "facts_confirmed": True})
    job = api.wait_job(api.ok("POST", f"/cases/{case['id']}/guidance", 202, "Job", key=True,
                              json={"expected_revision": rev})["id"])
    assert (job["status"], job["error_code"]) == ("failed", "RED_FLAG_DESCRIBED_URGENT_CLINICIAN")
    words = [w["text"] for w in [c for c in model.calls if c["task"] == "red_flag_screen"][-1]["snapshot"]["person_words"]]
    assert "I have been coughing up blood since yesterday." in words
    assert words.count("Rest and water.") == 1  # Q07's answer; Q05's old answer is no longer read
    assert not [c for c in model.calls if c["task"] == "guidance"]
    assert api.case(case["id"])["case"]["state"] == "urgent"
