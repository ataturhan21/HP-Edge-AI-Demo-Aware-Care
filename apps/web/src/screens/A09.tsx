// A09 Doctor preferences (M09; R28, R29). Explicit criteria; required vs preferred is user-chosen.
// #419: the case is read first (components/MatchingCase.tsx): a missing case or one without current routine guidance
// shows that state instead of the form. #394: the form starts from this tab's last criteria for the case, which a
// deletion forgets. #454: the in-person distance is marked as not used when only telehealth is chosen.
import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError, type S } from "../api/client";
import { useMatchingCase } from "../components/MatchingCase";
import { Button, ErrorBanner, PageHead, StatusBanner } from "../components/ui";
import { useAppState } from "../state/AppState";

export const LOCATIONS = ["Dallas, TX", "Irving, TX"];
export const PLANS = ["Demo Health PPO", "Demo Exclusive Plan"];

export function defaultCriteria(): S["ProviderCriteria"] {
  return {
    location: { location_id: null, city: "Dallas", region: "TX", postal_code: null },
    radius_miles: 25,
    specialty_ids: ["primary_care"],
    exact_plan_id: null,
    required_verified_plan: false,
    visit_type: "in_person",
    language: null,
    required_language: false,
    ranked_preferences: [],
  };
}

// #316: the searches a prepared quick demo opens A10 with (`/doctors?preset=…`, named by loadScenario's next_path;
// the same criteria as the server's prepared search in apps/api/app/modules/operations/scenarios.py).
export const SEARCH_PRESETS: Record<string, () => S["ProviderCriteria"]> = {
  default: defaultCriteria,
  "strict-plan": () => ({ ...defaultCriteria(), exact_plan_id: "Demo Exclusive Plan", required_verified_plan: true }),
};

export async function runSearch(caseId: string, criteria: S["ProviderCriteria"]) {
  const read = await api.getCase(caseId);
  return api.searchProviders(caseId, { expected_revision: read.case.revision, criteria });
}

export default function A09() {
  const { caseId = "" } = useParams();
  const { gate } = useMatchingCase(caseId, "Loading doctor preferences");
  if (gate) return gate;
  return <PreferencesForm caseId={caseId} />;
}

function PreferencesForm({ caseId }: { caseId: string }) {
  const navigate = useNavigate();
  const { searches, rememberSearch } = useAppState();
  const [c, setC] = useState<S["ProviderCriteria"]>(searches.get(caseId)?.criteria ?? defaultCriteria());
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const locationLabel = `${c.location.city}, ${c.location.region}`;

  function update(patch: Partial<S["ProviderCriteria"]>) {
    setC((prev) => {
      const next = { ...prev, ...patch };
      const prefs = new Set(next.ranked_preferences);
      if (next.exact_plan_id && !next.required_verified_plan) prefs.add("plan");
      else prefs.delete("plan");
      if (next.language && !next.required_language) prefs.add("language");
      else prefs.delete("language");
      return { ...next, ranked_preferences: Array.from(prefs) };
    });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setFieldError(null);
    try {
      const result = await runSearch(caseId, c);
      rememberSearch(caseId, { result, criteria: c });
      navigate(`/app/cases/${caseId}/doctors`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "INVALID_LOCATION") setFieldError(err.message);
      else setError(err);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="narrow">
      <PageHead eyebrow="Find care" title="Doctor preferences">
        <p>
          Each choice is marked: a <b>filter</b> leaves out doctors who do not match; an <b>ordering</b> choice only
          changes the order.
        </p>
      </PageHead>
      <StatusBanner tone="info" title="Fictional directory">
        <p>All doctors are fictional. Locations and distances are made-up demo values.</p>
      </StatusBanner>
      {error != null && <ErrorBanner error={error} />}
      <form className="card" onSubmit={submit} noValidate>
        <div className="field">
          <div className="field-head">
            <label htmlFor="loc">Location</label>
            <CriterionTag id="loc-kind" kind="filter" />
          </div>
          <select id="loc" value={locationLabel} aria-invalid={fieldError ? true : undefined}
            aria-describedby={fieldError ? "loc-kind loc-error" : "loc-kind"}
            onChange={(e) => {
              const [city, region] = e.target.value.split(", ");
              update({ location: { location_id: null, city, region, postal_code: null } });
            }}>
            {LOCATIONS.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
          {fieldError && (
            <span id="loc-error" className="field-error" role="alert">
              {fieldError}
            </span>
          )}
        </div>
        <div className="field">
          <div className="field-head">
            <label htmlFor="radius">Distance for in-person visits</label>
            <CriterionTag id="radius-kind" kind={c.visit_type === "telehealth" ? "unused" : "filter"} />
          </div>
          <select id="radius" value={c.radius_miles} aria-describedby="radius-kind"
            onChange={(e) => update({ radius_miles: Number(e.target.value) as S["ProviderCriteria"]["radius_miles"] })}>
            {[5, 10, 25, 50, 100].map((r) => (
              <option key={r} value={r}>
                Within {r} miles
              </option>
            ))}
          </select>
        </div>
        <fieldset aria-describedby="visit-kind">
          <legend>
            Visit type <CriterionTag id="visit-kind-tag" kind="filter" decorative />
          </legend>
          <span id="visit-kind" className="sr-only">Filter: leaves out doctors who do not match</span>
          {(
            [
              ["in_person", "In person"],
              ["telehealth", "Telehealth (Texas)"],
              ["either", "Either"],
            ] as const
          ).map(([v, label]) => (
            <label className="choice" key={v}>
              <input type="radio" name="visit" checked={c.visit_type === v} onChange={() => update({ visit_type: v })} />
              {label}
            </label>
          ))}
        </fieldset>
        <div className="field">
          <div className="field-head">
            <label htmlFor="plan">Insurance plan</label>
            <CriterionTag id="plan-kind" kind={!c.exact_plan_id ? "optional" : c.required_verified_plan ? "filter" : "ordering"} />
          </div>
          <select id="plan" value={c.exact_plan_id ?? ""} aria-describedby="plan-kind"
            onChange={(e) => update({ exact_plan_id: e.target.value || null, required_verified_plan: e.target.value ? c.required_verified_plan : false })}>
            <option value="">No plan preference</option>
            {PLANS.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
          {c.exact_plan_id && (
            <label className="check">
              <input type="checkbox" checked={c.required_verified_plan}
                onChange={(e) => update({ required_verified_plan: e.target.checked })} />
              Require a verified match for this plan
            </label>
          )}
        </div>
        <div className="field">
          <div className="field-head">
            <label htmlFor="lang">Language</label>
            <CriterionTag id="lang-kind" kind={!c.language ? "optional" : c.required_language ? "filter" : "ordering"} />
          </div>
          <select id="lang" value={c.language ?? ""} aria-describedby="lang-kind"
            onChange={(e) => update({ language: e.target.value || null, required_language: e.target.value ? c.required_language : false })}>
            <option value="">No language preference</option>
            <option>English</option>
            <option>Spanish</option>
          </select>
          {c.language && (
            <label className="check">
              <input type="checkbox" checked={c.required_language} onChange={(e) => update({ required_language: e.target.checked })} />
              Require this language
            </label>
          )}
        </div>
        <div className="actions">
          <span />
          <Button type="submit" pending={pending}>
            Find matches
          </Button>
        </div>
      </form>
    </div>
  );
}

/** #216: whether a criterion leaves doctors out (filter) or only changes the order, matching the provider search (M09):
 * location, distance and visit type always filter; a plan or language orders unless it is required. #454: the
 * distance is not used for a telehealth-only search (the server neither filters nor orders by it then). */
function CriterionTag({ id, kind, decorative }: { id: string; kind: "filter" | "ordering" | "optional" | "unused"; decorative?: boolean }) {
  const text = { filter: "Filter", ordering: "Ordering", optional: "Optional", unused: "Not used" }[kind];
  const detail = { filter: "leaves out doctors who do not match", ordering: "only changes the order",
    optional: "not used unless you choose one", unused: "not used for telehealth visits" }[kind];
  // The tag sits beside the label, so the field keeps its plain name; the control is described by it. In a legend
  // (visit type) it is decorative and the fieldset carries the description.
  return (
    <span id={id} className={`crit-tag crit-${kind}`} aria-hidden={decorative || undefined}>
      {text}
      <span className="sr-only">: {detail}</span>
    </span>
  );
}
