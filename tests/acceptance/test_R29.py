"""R29/R30 strict eligibility and deterministic ranking against fixtures/provider-filter-cases.json. M09."""
import json

import pytest

from conftest import ROOT
from app.modules.providers.schemas import ProviderCriteria
from app.modules.providers.service import match_providers

REQUIREMENT = "R29"
CASES = json.loads((ROOT / "fixtures/provider-filter-cases.json").read_text())["cases"]
ALIASES = {p["record_seed_id"]: p["id"] for p in json.loads((ROOT / "fixtures/providers.json").read_text())["providers"]}


def criteria(seed: dict) -> ProviderCriteria:
    city, _, region = seed["city"].partition(", ")
    return ProviderCriteria(
        location={"location_id": None, "city": city, "region": seed.get("jurisdiction", region), "postal_code": None},
        radius_miles=seed["radius_miles"], specialty_ids=["primary_care"], exact_plan_id=seed["plan"],
        required_verified_plan=seed["required_verified_plan"], visit_type=seed["visit_type"],
        language=seed["language"], required_language=seed["required_language"],
        ranked_preferences=["plan"] if seed["plan"] else [])


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_fixture_expected_order(app, case):
    result = match_providers(app[0].state.ctx, criteria(case["criteria_seed"]))
    eligible = [m for m in result["matches"] if m["eligible"]]
    assert [ALIASES[m["provider_id"]] for m in eligible] == case["expected_provider_alias_order"]
    # Disclosed candidates (unverified required attribute) follow the ranked matches and are never ranked.
    disclosed = result["matches"][len(eligible):]
    assert all(not m["eligible"] and m["rank_key"] == [] and m["exclusions"] for m in disclosed)
    assert all(e.startswith("Required ") for m in disclosed for e in m["exclusions"])
    if not eligible:
        assert len(result["suggested_filter_changes"]) <= 1
        assert all(s["requires_explicit_user_action"] for s in result["suggested_filter_changes"])


def test_search_over_api_is_versioned_and_deterministic(api):
    api.start()
    case = api.new_case()
    api.to_guided(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    body = {"expected_revision": rev, "criteria": {
        "location": {"location_id": None, "city": "Dallas", "region": "TX", "postal_code": None},
        "radius_miles": 25, "specialty_ids": ["primary_care"], "exact_plan_id": "Demo Health PPO",
        "required_verified_plan": False, "visit_type": "in_person", "language": None, "required_language": False,
        "ranked_preferences": ["plan"]}}
    s1 = api.ok("POST", f"/cases/{case['id']}/provider-search", 200, "ProviderSearchResult", json=body)
    s2 = api.ok("POST", f"/cases/{case['id']}/provider-search", 200, "ProviderSearchResult", json=body)
    assert [m["provider_id"] for m in s1["matches"]] == [m["provider_id"] for m in s2["matches"]]
    assert s2["criteria_version"] == s1["criteria_version"] + 1 and s1["data_mode"] == "synthetic"
    card = api.ok("GET", f"/cases/{case['id']}/providers/{s2['matches'][0]['provider_id']}?search_id={s2['id']}",
                  200, "ProviderCard")
    assert card["provider"]["contact_url"] is None and card["provider"]["data_mode"] == "synthetic"
    assert card["search_id"] == s2["id"]
    unknown = api.req("GET", f"/cases/{case['id']}/providers/00000000-0000-4000-8000-000000000000"
                             f"?search_id={s2['id']}")
    assert unknown.status_code == 404


def test_unknown_location_is_rejected_not_guessed(api):
    api.start()
    case = api.new_case()
    api.to_guided(case["id"])
    rev = api.case(case["id"])["case"]["revision"]
    r = api.req("POST", f"/cases/{case['id']}/provider-search", json={"expected_revision": rev, "criteria": {
        "location": {"location_id": None, "city": "Austin", "region": "TX", "postal_code": None},
        "radius_miles": 25, "specialty_ids": [], "exact_plan_id": None, "required_verified_plan": False,
        "visit_type": "in_person", "language": None, "required_language": False, "ranked_preferences": []}})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_LOCATION"


def _plan_criteria(plan: str = "Demo Health PPO", required: bool = True, **over) -> dict:
    base = {"location": {"location_id": None, "city": "Dallas", "region": "TX", "postal_code": None},
            "radius_miles": 25, "specialty_ids": ["primary_care"], "exact_plan_id": plan,
            "required_verified_plan": required, "visit_type": "in_person", "language": None,
            "required_language": False, "ranked_preferences": ["plan"]}
    return {**base, **over}


@pytest.fixture
def directory(tmp_path):
    """The synthetic directory plus test-only doctors whose plan record is out of network or stale."""
    import shutil
    import uuid as uuidlib
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from conftest import Api
    from app.config import load_settings
    from app.main import create_app
    pack = tmp_path / "fixtures"
    shutil.copytree(ROOT / "fixtures", pack)
    doc = json.loads((pack / "providers.json").read_text())
    template = next(p for p in doc["providers"] if p["id"] == "p01")
    for alias, name, status in (("p04", "Dr. Out Network (fictional)", "out_of_network_in_fixture"),
                                ("p05", "Dr. Stale Record (fictional)", "stale_in_fixture")):
        doc["providers"].append({**template, "id": alias, "legacy_alias": alias, "name": name,
                                 "record_seed_id": str(uuidlib.uuid5(uuidlib.NAMESPACE_URL, f"test:{alias}")),
                                 "synthetic_plan_status": status})
    (pack / "providers.json").write_text(json.dumps(doc))
    application = create_app(replace(load_settings(), data_dir=tmp_path / "data", fixtures_dir=pack))
    with TestClient(application) as client:
        api = Api(client)
        api.start()
        cid = api.new_case()["id"]
        api.to_guided(cid)
        aliases = {p["record_seed_id"]: p["id"] for p in doc["providers"]}
        yield api, cid, aliases


def search(api, cid: str, criteria: dict) -> dict:
    rev = api.case(cid)["case"]["revision"]
    return api.ok("POST", f"/cases/{cid}/provider-search", 200, "ProviderSearchResult",
                  json={"expected_revision": rev, "criteria": criteria})


def test_only_current_verified_participation_is_eligible_and_the_rest_is_disclosed(directory):
    """T-R29-S01: in-network confirmed are ranked; unknown and stale are disclosed exclusions; out-of-network is out."""
    api, cid, aliases = directory
    result = search(api, cid, _plan_criteria())
    eligible = [aliases[m["provider_id"]] for m in result["matches"] if m["eligible"]]
    disclosed = {aliases[m["provider_id"]]: m for m in result["matches"] if not m["eligible"]}
    assert eligible == ["p01", "p02"]
    assert set(disclosed) == {"p03", "p05"} and "p04" not in eligible + list(disclosed)
    assert disclosed["p03"]["exclusions"] == ["Required plan Demo Health PPO not verified: participation unknown"]
    assert disclosed["p05"]["exclusions"] == [
        "Required plan Demo Health PPO not verified: participation record is out of date"]
    for m in disclosed.values():
        assert m["rank_key"] == [] and "not shown as a match" in m["explanation"]
        # A disclosed candidate cannot be inspected or contacted as a match.
        assert api.req("GET", f"/cases/{cid}/providers/{m['provider_id']}?search_id={result['id']}").status_code == 404
    # As an optional preference the same records are ranked, verified plan first, and nothing is excluded.
    optional = search(api, cid, _plan_criteria(required=False))
    assert all(m["eligible"] for m in optional["matches"])
    order = [aliases[m["provider_id"]] for m in optional["matches"]]
    assert set(order) == {"p01", "p02", "p03", "p04", "p05"} and set(order[:2]) == {"p01", "p02"}


def test_specialty_is_a_hard_filter_before_ranking(directory):
    """T-R29-S02 (specialty): candidates outside the requested specialty never reach ranking or disclosure."""
    api, cid, aliases = directory
    family = search(api, cid, _plan_criteria(plan=None, required=False, specialty_ids=["family_medicine"],
                                              ranked_preferences=[]))
    internal = search(api, cid, _plan_criteria(plan=None, required=False, specialty_ids=["internal_medicine"],
                                                ranked_preferences=[]))
    assert "p02" not in [aliases[m["provider_id"]] for m in family["matches"]]
    assert [aliases[m["provider_id"]] for m in internal["matches"]] == ["p02"]


@pytest.mark.parametrize("field,over", [
    ("required_verified_plan", {"exact_plan_id": "Demo Exclusive Plan"}),
    ("required_language", {"exact_plan_id": None, "required_verified_plan": False, "ranked_preferences": [],
                           "language": "French", "required_language": True}),
])
def test_no_match_keeps_the_filter_until_a_change_is_explicitly_accepted(app, api, field, over):
    """T-R29-S02: a no-match offers one change; nothing is relaxed or re-searched until the user accepts it."""
    api.start()
    cid = api.new_case()["id"]
    api.to_guided(cid)
    strict = _plan_criteria(**over)
    first = search(api, cid, strict)
    assert [m for m in first["matches"] if m["eligible"]] == [] and first["no_match_reason"]
    assert [s["field"] for s in first["suggested_filter_changes"]] == [field]
    assert first["suggested_filter_changes"][0]["requires_explicit_user_action"] is True
    with app[0].state.ctx.db.read() as conn:
        rows = conn.execute("SELECT criteria_version, current FROM provider_searches WHERE case_id=?",
                            (cid,)).fetchall()
    assert [tuple(r) for r in rows] == [(first["criteria_version"], 1)]
    # The server never relaxes a filter by itself: the same strict filter searched again still has no match.
    again = search(api, cid, strict)
    assert [m for m in again["matches"] if m["eligible"]] == [] and again["criteria_version"] == 2
    # Only the accepted change (a new criteria version) produces matches.
    relaxed = {**strict, field: False}
    relaxed["ranked_preferences"] = ["plan"] if field == "required_verified_plan" else ["language"]
    accepted = search(api, cid, relaxed)
    assert accepted["criteria_version"] == 3 and [m for m in accepted["matches"] if m["eligible"]]


# QA 2026-10-19: #267 getProvider requires the search the card is opened from; #270 case-insensitive city and
# language, unknown specialties refused; #269 doctor matching is not offered for an urgent-level result.

def _guided_search(api, criteria=None):
    from test_R03 import SEARCH
    api.start()
    cid = api.new_case()["id"]
    api.to_guided(cid)
    rev = api.case(cid)["case"]["revision"]
    result = api.ok("POST", f"/cases/{cid}/provider-search", 200, "ProviderSearchResult",
                    json={"expected_revision": rev, "criteria": criteria or SEARCH})
    return cid, rev, result


def test_get_provider_requires_the_current_search_and_its_membership(api):
    from test_R03 import SEARCH
    cid, rev, first = _guided_search(api)
    pid = first["matches"][0]["provider_id"]
    card = api.ok("GET", f"/cases/{cid}/providers/{pid}?search_id={first['id']}", 200, "ProviderCard")
    assert card["search_id"] == first["id"] and card["match"]["provider_id"] == pid
    # Missing or malformed search_id: a field error.
    for query in ("", "?search_id=not-a-uuid"):
        r = api.req("GET", f"/cases/{cid}/providers/{pid}{query}")
        assert r.status_code == 422 and r.json()["field_errors"][0]["field"] == "search_id"
    # A search that is not the current one (replaced, or never existed): 409, never another search's match.
    second = api.ok("POST", f"/cases/{cid}/provider-search", 200, "ProviderSearchResult",
                    json={"expected_revision": rev, "criteria": {**SEARCH, "visit_type": "either"}})
    for stale in (first["id"], "00000000-0000-4000-8000-000000000000"):
        r = api.req("GET", f"/cases/{cid}/providers/{pid}?search_id={stale}")
        assert r.status_code == 409 and r.json()["code"] == "STATE_CONFLICT"
    assert api.ok("GET", f"/cases/{cid}/providers/{pid}?search_id={second['id']}", 200, "ProviderCard")[
        "search_id"] == second["id"]
    # A provider that is not an eligible match in the current search: 404.
    r = api.req("GET", f"/cases/{cid}/providers/00000000-0000-4000-8000-000000000000?search_id={second['id']}")
    assert r.status_code == 404


def test_city_and_language_match_case_insensitively(api):
    from test_R03 import SEARCH
    cid, rev, exact = _guided_search(api)
    lower = api.ok("POST", f"/cases/{cid}/provider-search", 200, "ProviderSearchResult",
                   json={"expected_revision": rev, "criteria": {**SEARCH, "location": {
                       **SEARCH["location"], "city": "  dallas ", "region": "tx"}}})
    assert [m["provider_id"] for m in lower["matches"]] == [m["provider_id"] for m in exact["matches"]]
    spanish = api.ok("POST", f"/cases/{cid}/provider-search", 200, "ProviderSearchResult",
                     json={"expected_revision": rev, "criteria": {**SEARCH, "language": "spanish",
                                                                  "required_language": True}})
    eligible = [m for m in spanish["matches"] if m["eligible"]]
    assert [ALIASES[m["provider_id"]] for m in eligible] == ["p02"]  # Dr. Rivera lists Spanish
    assert "Language: Spanish" in eligible[0]["confirmed_matches"]


def test_unknown_specialty_ids_are_refused_naming_the_field(api):
    from test_R03 import SEARCH
    cid, rev, _ = _guided_search(api)
    r = api.req("POST", f"/cases/{cid}/provider-search",
                json={"expected_revision": rev,
                      "criteria": {**SEARCH, "specialty_ids": ["primary_care", "cardiology"]}})
    assert r.status_code == 422 and r.json()["field_errors"][0]["field"] == "criteria.specialty_ids"
    with api.c.app.state.ctx.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM provider_searches WHERE case_id=?", (cid,)).fetchone()[0] == 1


def test_urgent_level_guidance_does_not_offer_doctor_matching(local):
    """#269: allowed_actions offered search_providers although the search returns 409 for an urgent level."""
    from conftest import NO_RED_FLAGS
    from test_R03 import SEARCH
    api, model, _ = local
    model.level = "urgent_clinician"
    case = api.new_case(context=[NO_RED_FLAGS])
    assert api.to_guided(case["id"])["status"] == "succeeded"
    read = api.case(case["id"])
    assert read["case"]["state"] == "guided" and "view_guidance" in read["allowed_actions"]
    assert "search_providers" not in read["allowed_actions"]
    r = api.req("POST", f"/cases/{case['id']}/provider-search",
                json={"expected_revision": read["case"]["revision"], "criteria": SEARCH})
    assert r.status_code == 409
    model.level = None
    routine = api.new_case(context=[NO_RED_FLAGS])
    api.to_guided(routine["id"])
    assert "search_providers" in api.case(routine["id"])["allowed_actions"]


@pytest.mark.parametrize("city", ["Irving", "Dallas"])
def test_telehealth_only_search_does_not_depend_on_the_in_person_radius(app, city):
    """#454: a telehealth-only search neither filters, orders nor reports by the in-person distance: every radius gives
    the same matches, rank keys and explanations, and no match carries a fictional distance (A10, A12 and the PDF show
    none)."""
    ctx = app[0].state.ctx

    def run(radius: int) -> dict:
        return match_providers(ctx, ProviderCriteria(
            location={"location_id": None, "city": city, "region": "TX", "postal_code": None}, radius_miles=radius,
            specialty_ids=["primary_care"], exact_plan_id=None, required_verified_plan=False, visit_type="telehealth",
            language=None, required_language=False, ranked_preferences=[]))

    results = [run(radius) for radius in (5, 10, 25, 50, 100)]
    shown = [[(m["provider_id"], m["rank_key"], m["explanation"], m["distance_miles"]) for m in r["matches"]]
             for r in results]
    assert shown[0] and all(s == shown[0] for s in shown)
    assert all(m["eligible"] and m["distance_miles"] is None for r in results for m in r["matches"])
    assert not any("In person" in fact or " mi" in fact for r in results for m in r["matches"]
                   for fact in m["confirmed_matches"])
