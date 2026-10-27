"""M09 factual provider eligibility and deterministic ranking (R28-R31).

Eligibility runs before ranking; unknown required attributes fail eligibility;
optional preferences only order results. A candidate that fits every factual
filter but whose required plan or language is unknown or stale is disclosed as
ineligible (eligible=false, with the exclusion stated), after the ranked
matches; it is never ranked and cannot be inspected or contacted (R29). Rank key: specialty tier, preferences
in the user's order (selected-but-unranked plan/language follow), freshness
tier, in-person distance (not for a telehealth-only search, #454), then the stable directory order. No quality scores.
The directory is the synthetic fixture snapshot; every card is fictional and
has no contact URL. Locations/distances are fictional lookup values.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.core.db import dumps, iso, utcnow
from app.core.errors import ApiError, not_found, state_conflict
from app.core.security import SessionInfo
from app.modules.cases import repository as cases_repo
from app.modules.guidance.service import current_guidance
from app.modules.operations.service import record_event
from app.modules.providers.schemas import ProviderCriteria

SPECIALTY_GROUPS = {
    "primary_care": {"Family medicine", "Internal medicine"},
    "family_medicine": {"Family medicine"},
    "internal_medicine": {"Internal medicine"},
}
DEFAULT_SPECIALTIES = ["primary_care"]
FAR = 1_000_000.0


def _seed_uuid(ctx, kind: str, alias: str) -> str:
    namespace = uuid.UUID("17890bd0-4ee8-53eb-a778-46d087d933bd")
    return ctx.fixtures.id_map.get(f"{kind}:{alias}") or str(uuid.uuid5(namespace, f"{kind}:{alias}"))


# Fixture plan status -> (participation, verification_status) of the provider's single synthetic plan record.
PLAN_STATUS = {"confirmed_in_fixture": ("in_network", "confirmed"),
               "out_of_network_in_fixture": ("out_of_network", "confirmed"),
               "stale_in_fixture": ("in_network", "stale")}


def provider_record(ctx, p: dict[str, Any]) -> dict[str, Any]:
    source_id = _seed_uuid(ctx, "source", ctx.fixtures.provider_source["id"])
    plan = PLAN_STATUS.get(p["synthetic_plan_status"]) if p["plan"] else None
    visit_types = ["in_person", "telehealth"] if p["tele"] else ["in_person"]

    def prov(attribute: str, status: str = "confirmed") -> dict[str, Any]:
        return {"attribute": attribute, "source_id": source_id, "checked_at": None, "verification_status": status}

    attributes = [prov("name"), prov("specialties"), prov("practice"), prov("languages"), prov("visit_types"),
                  prov("telehealth_jurisdictions"), prov("plans", plan[1] if plan else "unknown"),
                  prov("credential_status", "unknown"), prov("availability_status", "unknown"),
                  prov("locations")]
    return {
        "id": p["record_seed_id"], "name": p["name"], "specialties": [p["specialty"]], "practice": p["practice"],
        "locations": [{"id": _seed_uuid(ctx, "location", p["id"]), "display_address": None, "city": None,
                       "region": "TX", "postal_code": None, "latitude": None, "longitude": None}],
        "contact_url": None, "data_mode": "synthetic",
        "source_records": [{"id": source_id, "source_url": None, "publisher": "Synthetic fixture directory (fictional)",
                            "checked_at": None, "permitted_use": "Synthetic demonstration only; not a real directory.",
                            "attributes": attributes}],
        "snapshot_version": ctx.fixtures.directory_version, "languages": p["languages"], "visit_types": visit_types,
        "telehealth_jurisdictions": p["synthetic_telehealth_jurisdictions"],
        "plans": ([{"plan_id": p["plan"], "participation": plan[0], "verification_status": plan[1],
                    "source_id": source_id, "checked_at": None}] if plan else []),
        "credential_status": "unknown", "availability_status": "unknown", "attribute_provenance": attributes,
    }


def _location_key(criteria: ProviderCriteria, known_keys: set[str]) -> tuple[str | None, str | None]:
    """(directory location key, region). #270: the city matches case-insensitively ("dallas" is Dallas, TX)."""
    city = " ".join((criteria.location.city or "").split())
    region = (criteria.location.region or "").strip().upper()
    if not (city and region):
        return None, (region or None)
    wanted = f"{city}, {region}".casefold()
    return next((k for k in sorted(known_keys) if k.casefold() == wanted), f"{city}, {region}"), region


def _listed_language(language: str, languages: list[str]) -> str | None:
    """#270: the provider's listed language matching the requested one case-insensitively ("spanish" is Spanish)."""
    wanted = language.strip().casefold()
    return next((lang for lang in languages if lang.casefold() == wanted), None)


def match_providers(ctx, criteria: ProviderCriteria) -> dict[str, Any]:
    """Pure deterministic matcher over the synthetic snapshot."""
    unknown = [sid for sid in criteria.specialty_ids if sid not in SPECIALTY_GROUPS]
    if unknown:
        # #270: an unknown specialty is an error, not a silently ignored filter (which suggested a wider radius).
        raise ApiError(422, "VALIDATION_FAILED", "Choose a specialty from the list.",
                       field_errors=[{"field": "criteria.specialty_ids", "code": "unknown_specialty",
                                      "message": "Unknown specialty."}])
    known_keys = {k for p in ctx.fixtures.providers for k in p["distances_miles"]}
    key, region = _location_key(criteria, known_keys)
    needs_distance = criteria.visit_type in {"in_person", "either"}
    if (needs_distance and key not in known_keys) or (criteria.visit_type == "telehealth" and not region):
        raise ApiError(422, "INVALID_LOCATION", "Choose a supported demo location (Dallas, TX or Irving, TX).",
                       field_errors=[{"field": "criteria.location", "code": "unresolved",
                                      "message": "Location not found in the synthetic directory."}])
    wanted = set()
    for sid in criteria.specialty_ids or DEFAULT_SPECIALTIES:
        wanted |= SPECIALTY_GROUPS.get(sid, set())
    prefs = list(criteria.ranked_preferences)
    if criteria.exact_plan_id and "plan" not in prefs:
        prefs.append("plan")
    if criteria.language and "language" not in prefs:
        prefs.append("language")

    matches, disclosed = [], []
    for order, p in enumerate(ctx.fixtures.providers):
        record = provider_record(ctx, p)
        confirmed, unknowns, exclusions = [], [], []
        unverified: list[str] = []  # required attributes that are unknown or stale (disclosed, never matched)
        if p["specialty"] in wanted:
            confirmed.append(f"Specialty: {p['specialty']}")
        else:
            exclusions.append("Specialty not relevant to this search")
        # #454: the in-person distance and radius apply only when an in-person visit is possible in this search; a
        # telehealth-only search neither filters, orders nor reports by distance (no distance, whatever the radius).
        distance = p["distances_miles"].get(key) if key and criteria.visit_type != "telehealth" else None
        in_person_ok = distance is not None and distance <= criteria.radius_miles
        tele_ok = p["tele"] and region in p["synthetic_telehealth_jurisdictions"]
        visit_ok = {"in_person": in_person_ok, "telehealth": tele_ok, "either": in_person_ok or tele_ok}[
            criteria.visit_type]
        if criteria.visit_type in {"in_person", "either"} and in_person_ok:
            confirmed.append(f"In person within {criteria.radius_miles} miles (fictional distance {distance} mi)")
        if criteria.visit_type in {"telehealth", "either"} and tele_ok:
            confirmed.append(f"Telehealth in {region} (synthetic jurisdiction)")
        if not visit_ok:
            exclusions.append("Visit type or distance does not fit")
        plan_state = None
        if criteria.exact_plan_id:
            plan_id = criteria.exact_plan_id
            plan = next((x for x in record["plans"] if x["plan_id"] == plan_id), None)
            if plan is None or plan["participation"] == "unknown" or plan["verification_status"] == "unknown":
                plan_state = "unknown"
            elif plan["verification_status"] == "stale":
                plan_state = "stale"
            else:
                plan_state = "confirmed" if plan["participation"] == "in_network" else "out_of_network"
            if plan_state == "confirmed":
                confirmed.append(f"Plan {plan_id} confirmed in synthetic fixture")
            elif plan_state == "out_of_network":
                if criteria.required_verified_plan:
                    exclusions.append(f"Out of network for required plan {plan_id}")
            else:
                status = "unknown" if plan_state == "unknown" else "record is out of date"
                unknowns.append(f"Plan {plan_id} participation {status}")
                if criteria.required_verified_plan:
                    unverified.append(f"Required plan {plan_id} not verified: participation {status}")
        lang_state = None
        if criteria.language:
            listed = _listed_language(criteria.language, p["languages"])
            lang_state = "confirmed" if listed else "unknown"
            if lang_state == "confirmed":
                confirmed.append(f"Language: {listed}")
            else:
                unknowns.append(f"{criteria.language} not listed")
                if criteria.required_language:
                    unverified.append(f"Required language {criteria.language} not verified: not listed")
        unknowns += ["Appointment availability unknown", "Credentials not verified (synthetic record)"]
        if exclusions:
            continue  # a confirmed mismatch of a factual filter
        if unverified:
            disclosed.append({"provider_id": record["id"], "eligible": False, "confirmed_matches": confirmed,
                              "unknowns": unknowns, "exclusions": unverified, "rank_key": [],
                              "explanation": f"{p['name']} is not shown as a match: " + "; ".join(unverified)
                              + ". Fictional doctor; not ranked.",
                              "distance_miles": distance if in_person_ok else None,
                              "source_ids": [record["source_records"][0]["id"]]})
            continue
        pref_scores: list[float] = []
        for pref in prefs:
            if pref == "plan":
                pref_scores.append(0 if plan_state == "confirmed" else 1)
            elif pref == "language":
                pref_scores.append(0 if lang_state == "confirmed" else 1)
            else:
                pref_scores.append(0)
        rank_key: list[float | str] = [p["specialty_relevance_tier_for_routine_fixture"], *pref_scores, 0,
                                       distance if in_person_ok else FAR, f"{order:04d}"]
        matches.append({"provider_id": record["id"], "eligible": True, "confirmed_matches": confirmed,
                        "unknowns": unknowns, "exclusions": [], "rank_key": rank_key,
                        "explanation": " · ".join(confirmed) + ". Fictional doctor; ordering uses only the listed facts.",
                        "distance_miles": distance if in_person_ok else None, "source_ids": [
                            record["source_records"][0]["id"]]})
    matches.sort(key=lambda m: m["rank_key"])
    suggestions = []
    no_match_reason = None
    if not matches:
        no_match_reason = "No fictional doctors meet every required filter."
        if criteria.required_verified_plan:
            suggestions.append(("required_verified_plan", "Make the plan a preference instead of a requirement."))
        elif criteria.required_language:
            suggestions.append(("required_language", "Make the language a preference instead of a requirement."))
        elif criteria.radius_miles < 100 and criteria.visit_type != "telehealth":
            suggestions.append(("radius_miles", "Increase the search radius."))
        elif criteria.visit_type != "either":
            suggestions.append(("visit_type", "Allow either in-person or telehealth visits."))
    ranked = matches[:10]
    return {"matches": ranked + disclosed[:10 - len(ranked)], "no_match_reason": no_match_reason,
            "suggested_filter_changes": [{"field": f, "suggestion": s, "requires_explicit_user_action": True}
                                         for f, s in suggestions[:1]]}


def _require_routine_guidance(conn, session: SessionInfo, case_id: str):
    row, guidance = current_guidance(conn, session, case_id)
    if guidance["urgency"]["level"] in {"emergency", "urgent_clinician"}:
        raise state_conflict("Doctor matching is not available for urgent results.", current_revision=row["revision"])
    return row


def search(ctx, session: SessionInfo, case_id: str, expected_revision: int, criteria: ProviderCriteria
           ) -> dict[str, Any]:
    with ctx.db.tx() as conn:
        row = cases_repo.get_owned(conn, session.actor_id, case_id)
        cases_repo.check_revision(row, expected_revision)
        row = _require_routine_guidance(conn, session, case_id)
        result = match_providers(ctx, criteria)
        version = conn.execute("SELECT COUNT(*) FROM provider_searches WHERE case_id=? AND input_revision=?",
                               (case_id, row["revision"])).fetchone()[0] + 1
        payload = {"id": str(uuid.uuid4()), "case_id": case_id, "input_revision": row["revision"],
                   "criteria_version": version, "dataset_version": ctx.fixtures.directory_version,
                   "data_mode": "synthetic", "freshness_status": "cached", **result}
        conn.execute("UPDATE provider_searches SET current=0 WHERE case_id=?", (case_id,))
        conn.execute("INSERT INTO provider_searches (id, case_id, input_revision, criteria_version, result_json, "
                     "created_at, current) VALUES (?,?,?,?,?,?,1)",
                     (payload["id"], case_id, row["revision"], version, dumps(payload), iso(utcnow())))
        record_event(conn, "provider_search", "succeeded", operation_id="searchProviders")
    return payload


SUMMARY_DOCTORS_MAX = 3


def found_doctors(ctx, conn, case_row) -> dict[str, Any] | None:
    """#356: the first eligible matches of the case's current doctor search, for the visit summary (A12 and its PDF).

    Only what A10 showed: name, specialty, practice, the fictional distance and the confirmed facts of at most the
    first three eligible (ranked) matches. None when the case has no current routine guidance, no current search at
    this revision, or the search found no eligible doctor; a clinical edit retires the search (cases.repository)."""
    if case_row["state"] != "guided" or not case_row["latest_guidance_id"]:
        return None
    g = conn.execute("SELECT body_json FROM guidance WHERE id=?", (case_row["latest_guidance_id"],)).fetchone()
    if g is None or json.loads(g["body_json"])["urgency"]["level"] in {"emergency", "urgent_clinician"}:
        return None
    s = conn.execute("SELECT result_json FROM provider_searches WHERE case_id=? AND input_revision=? AND current=1",
                     (case_row["id"], case_row["revision"])).fetchone()
    if s is None:
        return None
    result = json.loads(s["result_json"])
    fixtures = {p["record_seed_id"]: p for p in ctx.fixtures.providers}
    doctors = []
    for m in result["matches"]:
        fixture = fixtures.get(m["provider_id"])
        if not m["eligible"] or fixture is None:
            continue
        doctors.append({"provider_id": m["provider_id"], "name": fixture["name"],
                        "specialties": [fixture["specialty"]], "practice": fixture["practice"],
                        "distance_miles": m["distance_miles"], "confirmed_matches": list(m["confirmed_matches"])})
        if len(doctors) == SUMMARY_DOCTORS_MAX:
            break
    if not doctors:
        return None
    return {"search_id": result["id"], "data_mode": "synthetic", "doctors": doctors}


def provider_card(ctx, session: SessionInfo, case_id: str, provider_id: str, search_id: str) -> dict[str, Any]:
    """#267: the card is read from the search the person is looking at. A search that is not the case's current one
    (replaced, or from an earlier case version) is refused with 409, so a card never shows another search's match;
    a provider that is not an eligible match in that search is 404."""
    with ctx.db.read() as conn:
        row = _require_routine_guidance(conn, session, case_id)
        s = conn.execute("SELECT * FROM provider_searches WHERE case_id=? AND input_revision=? AND current=1",
                         (case_id, row["revision"])).fetchone()
    if s is None or s["id"] != search_id:
        raise state_conflict("These search results are out of date. Search again.", current_revision=row["revision"])
    result = json.loads(s["result_json"])
    match = next((m for m in result["matches"] if m["provider_id"] == provider_id and m["eligible"]), None)
    fixture = next((p for p in ctx.fixtures.providers if p["record_seed_id"] == provider_id), None)
    if match is None or fixture is None:
        raise not_found()
    return {"provider": provider_record(ctx, fixture), "match": match, "search_id": result["id"],
            "input_revision": row["revision"]}
