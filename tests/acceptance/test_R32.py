"""R32/R33 reviewed export: owned, expiring, revoked on clinical edit. M10."""

REQUIREMENT = "R32"


def export(api, case_id: str) -> dict:
    rev = api.case(case_id)["case"]["revision"]
    job = api.ok("POST", f"/cases/{case_id}/exports", 202, "Job", key=True,
                 json={"expected_revision": rev, "user_reviewed": True})
    return api.wait_job(job["id"])


def test_export_requires_explicit_review_flag(api):
    api.start()
    case = api.new_case()
    api.to_guided(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    r = api.req("POST", f"/cases/{case['id']}/exports", key=True, json={"expected_revision": rev, "user_reviewed": False})
    assert r.status_code == 422


def test_download_is_pdf_attachment_and_owner_only(api, other):
    api.start()
    case = api.new_case()
    api.to_guided(case["id"])
    job = export(api, case["id"])
    assert job["status"] == "succeeded" and job["result_type"] == "export"
    r = api.req("GET", f"/exports/{job['result_id']}/download")
    assert r.status_code == 200 and r.content.startswith(b"%PDF-1.4") and b"%%EOF" in r.content[-10:]
    assert r.headers["content-disposition"].startswith("attachment")
    other.start()
    assert other.req("GET", f"/exports/{job['result_id']}/download").status_code == 404


def test_clinical_edit_revokes_export(api):
    api.start()
    case = api.new_case()
    api.to_guided(case["id"])
    job = export(api, case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    api.ok("PATCH", f"/cases/{case['id']}", 200, "Case", json={"expected_revision": rev, "concern": "Edited"})
    r = api.req("GET", f"/exports/{job['result_id']}/download")
    assert r.status_code == 409


def test_expired_export_is_refused(app, api):
    api.start()
    case = api.new_case()
    api.to_guided(case["id"])
    job = export(api, case["id"])
    with app[0].state.ctx.db.tx() as conn:
        conn.execute("UPDATE exports SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (job["result_id"],))
    r = api.req("GET", f"/exports/{job['result_id']}/download")
    assert r.status_code == 409 and r.json()["code"] == "EXPORT_EXPIRED"


def pdf_lines(data: bytes) -> list[str]:
    """The text lines drawn in the PDF, unescaped (the summary uses uncompressed `(text) Tj` operators)."""
    import re
    raw = re.findall(rb"\((?:\\.|[^\\)])*\) Tj", data)
    return [re.sub(r"\\(.)", r"\1", r[1:-4].decode("latin-1")) for r in raw]


def test_pdf_contains_facts_gaps_sources_timestamp_and_ai_labels_only(api):
    """T-R32-S01: the PDF carries the reviewed content and labels, and nothing the guidance suppressed."""
    import re
    api.start()
    cid = api.new_case("Recurring headaches after long workdays (synthetic).")["id"]
    api.answer_all(cid)
    q01 = next(f for f in api.case(cid)["case"]["confirmed_context"] if f["kind"] == "answer:Q01")
    rev = api.case(cid)["case"]["revision"]
    api.ok("PUT", f"/cases/{cid}/answers/{q01['source_id']}", 200, "SaveAnswerResponse",
           json={"expected_revision": rev, "status": "unknown", "value": None})
    assert api.to_guided(cid)["status"] == "succeeded"
    guidance = api.ok("GET", f"/cases/{cid}/guidance", 200, "Guidance")
    case = api.case(cid)["case"]
    job = export(api, cid)
    pdf = api.req("GET", f"/exports/{job['result_id']}/download").content
    text = " ".join(pdf_lines(pdf))
    # Reported and confirmed facts, including the unresolved gap.
    assert "Recurring headaches after long workdays (synthetic)." in text
    assert "4 on a 0-10 scale" in text  # #215: a scale answer carries its range (the PDF prints the dash plainly)
    from app.modules.exports.service import CONTEXT_LABELS
    for fact in case["confirmed_context"]:
        assert f"- {fact['original_text'] or CONTEXT_LABELS[fact['kind']]}: " in text, fact["kind"]
    assert f"{q01['original_text']}: Not answered / unknown" in text
    assert "Unresolved or unknown details" in text and f"Not answered: {q01['original_text']}" in text
    # Generation timestamp (#459: the product's date style, labelled UTC), case version, AI and synthetic labels, and
    # the source statement.
    assert re.search(r"Generated \d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}, \d{2}:\d{2} UTC\. "
                     r"Case version " + str(case["revision"]) + r"\.", text)
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}", text)  # no raw ISO timestamp
    assert "AI-assisted content is labeled; mock mode used scripted synthetic fixtures." in text
    assert "SYNTHETIC DEMO DOCUMENT. Not a diagnosis, referral, prescription or appointment." in text
    # #456: mock mode's explanation is a scripted fixture sentence, labelled so; never "general medical knowledge".
    assert ("Sources No approved evidence sources are loaded; the possible explanation is scripted illustrative text "
            "for this synthetic demo, not from an AI model.") in text
    assert "general medical knowledge" not in text
    # Possible explanations appear under their label (ADR-015); a suppressed claim never would.
    assert guidance["possible_explanations"]
    assert ("Possible explanations (scripted illustrative text, not from an AI model or reviewed sources; not a "
            "diagnosis)") in text
    for claim in guidance["possible_explanations"]:
        assert claim["validation_status"] == "general_knowledge" and f"- {claim['text']}" in text
    for action in guidance["actions"]:
        assert f"- {action['text']}" in text
    # No transmission: the summary names no recipient address, and only the download stores it.
    assert not re.search(r"https?://|@[A-Za-z0-9-]+\.|\bmailto:", text)


def test_create_export_is_refused_without_current_reviewed_guidance(api):
    """T-R32-S02: createExport called directly before guidance exists, or after a clinical edit, is refused."""
    api.start()
    cid = api.new_case()["id"]
    api.answer_all(cid)
    rev = api.case(cid)["case"]["revision"]
    r = api.req("POST", f"/cases/{cid}/exports", key=True, json={"expected_revision": rev, "user_reviewed": True})
    assert r.status_code == 409 and r.json()["code"] == "STATE_CONFLICT"
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    api.ok("PATCH", f"/cases/{cid}", 200, "Case", json={"expected_revision": rev, "concern": "Edited concern."})
    for revision, code in ((rev, "REVISION_CONFLICT"), (rev + 1, "STATE_CONFLICT")):
        r = api.req("POST", f"/cases/{cid}/exports", key=True,
                    json={"expected_revision": revision, "user_reviewed": True})
        assert r.status_code == 409 and r.json()["code"] == code, r.text
    with api.c.app.state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0


def test_local_pdf_labels_ai_generated_guidance_and_never_claims_a_script(local):
    """Local mode (ADR-003): the summary says the guidance was AI-generated, and shows the checklist answer."""
    from conftest import NO_RED_FLAGS
    api, _, _ = local
    cid = api.new_case(context=[NO_RED_FLAGS])["id"]
    assert api.to_guided(cid)["status"] == "succeeded"
    job = export(api, cid)
    text = " ".join(pdf_lines(api.req("GET", f"/exports/{job['result_id']}/download").content))
    assert "Guidance was generated on this device by an AI model and can contain mistakes." in text
    assert "Suggested next steps (AI-generated, check with a clinician)" in text
    assert "- Urgent warning signs checklist: None of these apply" in text
    assert "scripted" not in text


def test_pdf_lists_labeled_explanations_and_never_a_suppressed_claim():
    """ADR-015: general-knowledge and supported explanations are listed under their label; a suppressed one is not."""
    from app.modules.exports.service import _lines

    def claim(text, status):
        return {"id": "x", "text": text, "kind": "clinical", "fact_ids": [], "evidence_ids": [],
                "validation_status": status}
    guidance = {"model_manifest_id": "test-model@local-test", "input_revision": 4, "uncertainties": [], "actions": [],
                "clinician_questions": [], "escalation_advice": [], "possible_explanations": [
                    claim("Often linked to eye strain.", "general_knowledge"), claim("A withheld statement.", "suppressed")]}
    text = " ".join(t for _, t in _lines("Synthetic concern.", [], guidance, "2026-10-16T12:00:00Z"))
    assert "Possible explanations (general medical knowledge, not from reviewed sources; not a diagnosis)" in text
    assert "- Often linked to eye strain." in text and "A withheld statement." not in text


def test_the_pdf_prints_typographic_punctuation_plainly_not_as_question_marks():
    """#215: dashes, curly quotes and ellipses (written by the app and the model) are not Latin-1; they used to print
    as "?"."""
    from app.modules.exports.pdf import _escape
    assert _escape("4 on a 0–10 scale — it’s “mild”…") == "4 on a 0-10 scale - it's \"mild\"..."
    assert _escape("日本") == "??"  # anything else still stays well-formed


# #265 (QA 2026-10-19): accented Latin text prints as written; what cannot be shown is marked and disclosed.

def _pdftotext(data: bytes, tmp_path) -> str:
    """The PDF's text as a viewer reads it. With poppler's pdftotext installed (developer machines), the real extractor
    is used. Otherwise (the CI runner has no poppler) the text strings of the uncompressed content streams are decoded
    as WinAnsi (cp1252), which is exactly what the fonts now declare, so the check stays meaningful there too."""
    import re
    import shutil
    import subprocess
    if shutil.which("pdftotext"):
        path = tmp_path / "summary.pdf"
        path.write_bytes(data)
        return subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"], check=True, capture_output=True,
                              text=True).stdout
    assert b"/Filter" not in data  # the writer emits plain content streams, so their strings can be read directly
    strings = re.findall(rb"\((.*?)(?<!\\)\) Tj", data, flags=re.S)
    unescape = lambda raw: re.sub(rb"\\([\\()])", rb"\1", raw)
    return "\n".join(unescape(raw).decode("cp1252") for raw in strings)


def test_the_pdf_declares_winansi_and_prints_accents_degree_and_plus_minus(api, tmp_path):
    api.start()
    concern = "Douleur à la tête après café, 38°C, naïve ± Ünïcode"
    cid = api.new_case(concern)["id"]
    api.to_guided(cid)
    job = export(api, cid)
    data = api.req("GET", f"/exports/{job['result_id']}/download").content
    assert data.count(b"/Encoding /WinAnsiEncoding") == 2  # both fonts
    assert concern.encode("cp1252") in data  # the text is encoded to cp1252, not left to StandardEncoding
    text = _pdftotext(data, tmp_path)
    assert concern in text
    assert "could not be shown" not in text  # nothing was replaced


def test_characters_that_cannot_be_shown_are_replaced_visibly_and_the_pdf_says_so(api, tmp_path):
    from app.modules.exports.pdf import UNSHOWN_NOTE, render
    data = render([("h1", "Summary"), ("p", "Headache 头痛 since Monday, café")])
    text = _pdftotext(data, tmp_path)
    assert "Headache ?? since Monday, café" in text
    assert " ".join(UNSHOWN_NOTE.split()) in " ".join(text.split())
    api.start()
    cid = api.new_case("Головная боль after work")["id"]
    api.to_guided(cid)
    text = _pdftotext(api.req("GET", f"/exports/{export(api, cid)['result_id']}/download").content, tmp_path)
    assert "??????? ???? after work" in text and "could not be shown" in text


# #356 (maintainer decision 2026-10-21): the summary carries the published level of care and the doctors found.

# The level in A07's words (apps/web/src/screens/A07.tsx, URGENCY).
A07_LEVELS = {"emergency": "Emergency care", "urgent_clinician": "See a clinician urgently",
              "routine_clinician": "Routine clinician visit",
              "self_care_candidate": "Self-care with monitoring (illustrative)", "undetermined": "Not determined"}


def _search(api, cid: str, **change) -> dict:
    from test_R03 import SEARCH
    rev = api.case(cid)["case"]["revision"]
    return api.ok("POST", f"/cases/{cid}/provider-search", 200, "ProviderSearchResult",
                  json={"expected_revision": rev, "criteria": {**SEARCH, **change}})


def test_summary_shows_the_level_of_care_and_the_first_three_doctors_found(app, api, tmp_path):
    """#356: getCase (the A12 preview) and the PDF carry the guidance's level and the latest search's doctors."""
    import uuid
    providers = app[0].state.ctx.fixtures.providers  # this test's own app: three more fictional doctors, ranked last
    providers += [{**p, "id": f"{p['id']}-clone", "record_seed_id": str(uuid.uuid4()), "name": f"Dr. Clone {i}"}
                  for i, p in enumerate(list(providers))]
    api.start()
    cid = api.new_case()["id"]
    assert api.to_guided(cid)["status"] == "succeeded"
    level = api.ok("GET", f"/cases/{cid}/guidance", 200, "Guidance")["urgency"]["level"]
    _search(api, cid, radius_miles=5)
    search = _search(api, cid, radius_miles=100, visit_type="either")  # the latest search counts
    eligible = [m for m in search["matches"] if m["eligible"]]
    assert len(eligible) > 3
    found = api.case(cid)["found_doctors"]  # validated against CaseReadResponse by api.case
    assert found["search_id"] == search["id"] and found["data_mode"] == "synthetic"
    assert [d["provider_id"] for d in found["doctors"]] == [m["provider_id"] for m in eligible[:3]]
    for d, m in zip(found["doctors"], eligible):
        card = api.ok("GET", f"/cases/{cid}/providers/{m['provider_id']}?search_id={search['id']}", 200,
                      "ProviderCard")["provider"]
        assert (d["name"], d["specialties"], d["practice"]) == (card["name"], card["specialties"], card["practice"])
        assert d["confirmed_matches"] == m["confirmed_matches"] and d["distance_miles"] == m["distance_miles"]
    data = api.req("GET", f"/exports/{export(api, cid)['result_id']}/download").content
    assert data.count(b"/Encoding /WinAnsiEncoding") == 2
    lines = pdf_lines(data)
    text = " ".join(lines)
    heading = lines.index("Suggested level of care (synthetic scripted outcome)")
    assert lines[heading + 1] == A07_LEVELS[level]
    assert "Doctors you found (fictional doctors from a synthetic directory)" in lines
    assert "Fictional doctors only." in text
    for d in found["doctors"]:
        where = f" \xb7 {d['distance_miles']} mi (fictional)" if d["distance_miles"] is not None else ""
        assert f"- {d['name']} \xb7 {', '.join(d['specialties'])} \xb7 {d['practice']}{where}" in text
        for fact in d["confirmed_matches"]:
            assert f"Confirmed: {fact}" in text
    others = [m for m in eligible[3:]]
    assert others and all(api.ok("GET", f"/cases/{cid}/providers/{m['provider_id']}?search_id={search['id']}", 200,
                                 "ProviderCard")["provider"]["name"] not in text for m in others)
    assert "could not be shown" not in _pdftotext(data, tmp_path)


def test_summary_omits_the_doctors_without_a_search_or_after_a_clinical_edit(api):
    """#356: no search (or a retired one) means no doctors section; the level still comes from the guidance."""
    api.start()
    cid = api.new_case()["id"]
    api.to_guided(cid)
    assert "found_doctors" not in api.case(cid)
    lines = pdf_lines(api.req("GET", f"/exports/{export(api, cid)['result_id']}/download").content)
    assert "Suggested level of care (synthetic scripted outcome)" in lines
    assert not any(line.startswith("Doctors you found") for line in lines)
    _search(api, cid)
    assert "found_doctors" in api.case(cid)
    rev = api.case(cid)["case"]["revision"]
    api.ok("PATCH", f"/cases/{cid}", 200, "Case", json={"expected_revision": rev, "concern": "Edited concern."})
    assert "found_doctors" not in api.case(cid)
    api.to_guided(cid)
    assert "found_doctors" not in api.case(cid)  # the earlier search is not brought back
    lines = pdf_lines(api.req("GET", f"/exports/{export(api, cid)['result_id']}/download").content)
    assert not any(line.startswith("Doctors you found") for line in lines)


def test_summary_omits_the_doctors_when_the_search_found_none(api):
    api.start()
    cid = api.new_case()["id"]
    api.to_guided(cid)
    search = _search(api, cid, exact_plan_id="NO-SUCH-PLAN", required_verified_plan=True)
    assert not [m for m in search["matches"] if m["eligible"]]
    assert "found_doctors" not in api.case(cid)


def test_local_summary_labels_the_level_ai_generated(local):
    """#356: in local mode the level carries the AI-generated label, never the scripted one."""
    from conftest import NO_RED_FLAGS
    api, _, _ = local
    cid = api.new_case(context=[NO_RED_FLAGS])["id"]
    assert api.to_guided(cid)["status"] == "succeeded"
    level = api.ok("GET", f"/cases/{cid}/guidance", 200, "Guidance")["urgency"]["level"]
    lines = pdf_lines(api.req("GET", f"/exports/{export(api, cid)['result_id']}/download").content)
    heading = lines.index("Suggested level of care (AI-generated, check with a clinician)")
    assert lines[heading + 1] == A07_LEVELS[level]


def test_the_level_is_never_invented_without_published_guidance_urgency():
    """#356: no urgency in the guidance means no level section (the summary never makes one up)."""
    from app.modules.exports.service import LEVEL_LABELS, _lines
    assert LEVEL_LABELS == A07_LEVELS
    guidance = {"model_manifest_id": "test-model@local-test", "input_revision": 1, "uncertainties": [], "actions": [],
                "clinician_questions": [], "escalation_advice": [], "possible_explanations": []}
    text = " ".join(t for _, t in _lines("Synthetic concern.", [], guidance, "2026-10-21T12:00:00Z"))
    assert "Suggested level of care" not in text and "Doctors you found" not in text


# QA 2026-10-22 (v0.14.0-demo.1): #395 (P-02), #416 (P-03), #417 (P-04), #455 (P-11), #456 (P-12), #459 (P-16).

def _guided_with_sample_record(api, correction: str | None = None) -> str:
    """A guided mock case whose bundled sample-record fact was confirmed, or corrected to `correction` (as A04 does)."""
    from records_helpers import records, upload_ok
    api.start()
    cid = api.new_case()["id"]
    assert upload_ok(api, cid)["status"] == "succeeded"
    fact = records(api, cid)["facts"][0]
    assert fact["original_text"] == "No medications listed in sample record"
    review = ({"action": "correct", "corrected_value": {"value": correction, "units": None}} if correction
              else {"action": "confirm"})
    api.ok("PATCH", f"/cases/{cid}/facts/{fact['id']}", 200, "FactReviewResponse",
           json={"expected_revision": api.case(cid)["case"]["revision"], **review})
    api.answer_all(cid)
    assert api.to_guided(cid)["status"] == "succeeded"
    return cid


def test_a_corrected_record_fact_is_printed_under_its_kind_never_under_its_old_source_text(api):
    """#395 (P-02): the record's extracted text is not a label; the corrected value stands under the kind label A06
    shows, so the summary never says "No medications listed in sample record: Ibuprofen 200 mg as needed"."""
    cid = _guided_with_sample_record(api, "Ibuprofen 200 mg as needed")
    text = " ".join(pdf_lines(api.req("GET", f"/exports/{export(api, cid)['result_id']}/download").content))
    assert "- Medications (from a record you confirmed): Ibuprofen 200 mg as needed" in text
    assert "No medications listed in sample record" not in text


def test_a_confirmed_record_fact_is_printed_once_under_its_kind_label(api):
    """#395 (P-02): an unchanged confirmed record fact is not printed as "<text>: <text>"."""
    cid = _guided_with_sample_record(api)
    text = " ".join(pdf_lines(api.req("GET", f"/exports/{export(api, cid)['result_id']}/download").content))
    assert "- Medications (from a record you confirmed): No medications listed in sample record" in text
    assert "No medications listed in sample record: " not in text


def test_a_test_result_keeps_its_printed_unit_and_reference_range_in_the_pdf():
    """#395: a confirmed test result reads as on A06 (R19): value, unit and range, or that they were not readable."""
    from app.modules.exports.service import _lines

    def lab(value, units, reference=None):
        fact = {"kind": "record:lab_result", "value": value, "units": units, "provenance": "document",
                "original_text": "Fasting glucose 5.4 mmol/L (reference 3.9-5.5 mmol/L)"}
        return {**fact, "reference_range": reference} if reference else fact
    guidance = {"model_manifest_id": "test-model@local-test", "input_revision": 3, "uncertainties": [], "actions": [],
                "clinician_questions": [], "escalation_advice": [], "possible_explanations": []}
    text = " ".join(t for _, t in _lines("Synthetic concern.", [lab(5.4, "mmol/L", "3.9-5.5 mmol/L"), lab(13.1, None)],
                                         guidance, "2026-10-22T03:13:59.744837Z"))
    assert "- Test result (from a record you confirmed): 5.4 mmol/L; reference range 3.9-5.5 mmol/L" in text
    assert "- Test result (from a record you confirmed): 13.1 (unit not readable); reference range not readable" in text
    assert "Fasting glucose" not in text


CAPS = ("QAMARK-CAPS2 HEADACHES FOR TWO WEEKS, MOSTLY BEHIND MY EYES AFTER WORKING ON THE LAPTOP ALL DAY WITHOUT "
        "BREAKS")
RIGHT_EDGE = 556  # a 612 pt page with 56 pt margins


def _right_edges(data: bytes, tmp_path) -> list[tuple[float, str]]:
    """(right edge in pt, text) of every word as poppler's pdftotext lays it out (developer machines), or, without
    poppler (the CI runner), of every drawn line from its position and the standard Helvetica widths."""
    import html
    import re
    import shutil
    import subprocess
    if shutil.which("pdftotext"):
        path = tmp_path / "edges.pdf"
        path.write_bytes(data)
        out = subprocess.run(["pdftotext", "-bbox", str(path), "-"], check=True, capture_output=True, text=True).stdout
        return [(float(m[1]), html.unescape(m[2])) for m in
                re.finditer(r'<word xMin="[\d.]+" yMin="[\d.]+" xMax="([\d.]+)" yMax="[\d.]+">(.*?)</word>', out)]
    from app.modules.exports.pdf import text_width
    edges = []
    for face, size, x, raw in re.findall(rb"/F(\d) ([\d.]+) Tf 1 0 0 1 ([\d.]+) [\d.]+ Tm \(((?:\\.|[^\\)])*)\) Tj",
                                         data):
        text = re.sub(rb"\\(.)", rb"\1", raw).decode("cp1252")
        edges.append((float(x) + text_width(text, float(size), face == b"2"), text))
    return edges


def test_every_line_of_the_pdf_stays_inside_the_margins_and_no_word_is_cut_off(api, tmp_path):
    """#416 (P-03): text is wrapped by its drawn width, not a character count. A concern in capitals used to run past
    the page edge ("LAPTO", "ALL" lost) and the long explanations heading ended 8 pt from it."""
    api.start()
    cid = api.new_case(CAPS)["id"]
    api.answer_all(cid)
    assert api.to_guided(cid)["status"] == "succeeded"
    data = api.req("GET", f"/exports/{export(api, cid)['result_id']}/download").content
    edges = _right_edges(data, tmp_path)
    assert edges
    assert [(round(e, 1), w) for e, w in edges if e > RIGHT_EDGE + 0.01] == []
    assert CAPS in " ".join(pdf_lines(data))  # every word is drawn, in order


def test_long_headings_and_unbroken_words_wrap_inside_the_margins(tmp_path):
    """#416: headings wrap too, and a word wider than a line is split at the margin, never drawn past it."""
    from app.modules.exports.pdf import render
    heading = "Possible explanations (general medical knowledge, not from reviewed sources; not a diagnosis)"
    word = "W" * 120
    data = render([("h1", "Aware Care - appointment preparation summary " * 2), ("h2", heading),
                   ("p", f"- {word} after {'M' * 300}"), ("p", "  Confirmed: " + "WIDE CAPITAL WORDS " * 12)])
    edges = _right_edges(data, tmp_path)
    assert [(round(e, 1), w) for e, w in edges if e > RIGHT_EDGE + 0.01] == []
    lines = pdf_lines(data)
    assert heading in " ".join(lines) and len([line for line in lines if "W" * 10 in line]) > 1
    assert "".join(lines).replace(" ", "").count("W" * 120) == 1  # split, not shortened


def test_the_helvetica_widths_are_the_standard_font_metrics():
    """#416: spot checks against the Adobe Core 14 AFM advance widths (Helvetica, Helvetica-Bold)."""
    from app.modules.exports.pdf import text_width
    assert [text_width(c, 1000) for c in "W i m A é ÿ".split()] == [944, 222, 833, 667, 556, 500]
    assert [text_width(c, 1000, bold=True) for c in "W i m A é".split()] == [944, 278, 889, 722, 556]
    assert text_width("LAPTOP", 10.5) == (556 + 667 + 667 + 611 + 778 + 667) * 10.5 / 1000


def test_decomposed_accents_and_comparison_signs_print_as_written_not_as_question_marks(api, tmp_path):
    """#455 (P-11): NFC normalisation first ("cafe" + U+0301 is "café", which WinAnsi has), and signs WinAnsi lacks
    are written out (">=", "<="), so "fever ≥ 38°C" keeps its meaning instead of printing "fever ? 38°C"."""
    from app.modules.exports.pdf import render
    api.start()
    concern = "headache at the café after work, fever ≥ 38°C"
    cid = api.new_case(concern)["id"]
    api.to_guided(cid)
    data = api.req("GET", f"/exports/{export(api, cid)['result_id']}/download").content
    text = " ".join(_pdftotext(data, tmp_path).split())
    assert "headache at the café after work, fever >= 38°C" in text
    assert "could not be shown" not in text and "cafe?" not in text and "fever ? 38" not in text
    text = " ".join(_pdftotext(render([("h1", "Summary"), ("p", "Rámon ≤ 2 h, ≠ 0, 5 μg, "
                                                                "37 ℃")]), tmp_path).split())
    assert "Rámon <= 2 h, != 0, 5 µg, 37 °C" in text and "could not be shown" not in text


def test_the_generation_time_is_in_the_product_date_style_labelled_utc():
    """#459 (P-16): "22 Oct 2026, 03:13 UTC" (#347), not "2026-10-22T03:13:59.744837Z (UTC)"."""
    from app.modules.exports.service import _lines, generated_at
    assert generated_at("2026-10-22T03:13:59.744837Z") == "22 Oct 2026, 03:13 UTC"
    assert generated_at("2026-01-05T23:59:00+00:00") == "5 Jan 2026, 23:59 UTC"
    guidance = {"model_manifest_id": "test-model@local-test", "input_revision": 11, "uncertainties": [],
                "actions": [], "clinician_questions": [], "escalation_advice": [], "possible_explanations": []}
    text = " ".join(t for _, t in _lines("Synthetic concern.", [], guidance, "2026-10-22T03:13:59.744837Z"))
    assert "Generated 22 Oct 2026, 03:13 UTC. Case version 11." in text


# The A12 preview's section titles (apps/web/src/screens/A12.tsx) in mock mode, in order, without the doctors (no
# search here). #417: every PDF heading is one of them (the text before its parenthesis), so the person reviews on A12
# every section the PDF prints; tests/ui/improve-summary.spec.ts checks the preview against a downloaded PDF.
A12_TITLES = ["Main concern", "What you reported", "Unresolved or unknown details", "Suggested level of care",
              "Suggested next step", "Possible explanations", "Questions for a clinician", "When to seek help sooner",
              "Sources"]


def test_the_pdf_prints_exactly_the_sections_the_a12_preview_shows(api):
    """#417 (P-04): the PDF's section headings are the preview's titles (with the PDF's own labels in parentheses)."""
    import re
    api.start()
    cid = api.new_case()["id"]
    assert api.to_guided(cid)["status"] == "succeeded"
    data = api.req("GET", f"/exports/{export(api, cid)['result_id']}/download").content
    # Headings are drawn in Helvetica-Bold at 12 pt (F2 12); a wrapped heading continues on the next F2 12 line.
    drawn = re.findall(rb"/(F\d) ([\d.]+) Tf 1 0 0 1 ([\d.]+) [\d.]+ Tm \(((?:\\.|[^\\)])*)\) Tj", data)
    headings: list[str] = []
    previous = None
    for face, size, _, raw in drawn:
        text = re.sub(rb"\\(.)", rb"\1", raw).decode("cp1252")
        if (face, size) == (b"F2", b"12"):
            if previous == (face, size):
                headings[-1] += f" {text}"
            else:
                headings.append(text)
        previous = (face, size)
    assert [h.split(" (")[0] for h in headings] == A12_TITLES
