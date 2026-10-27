// A10 Doctor matches (M09; R29, R30). Ranked factual cards with knowns/unknowns; explicit relaxation only.
// #341: the page leads on to the visit summary (A12) and back to the guidance (A07), with or without matches.
// #394/#419: the case is read first (components/MatchingCase.tsx); a search held in this tab's memory is shown only
// while it is the case's current search, so a deleted or changed case never shows an earlier search. #421: without a
// search on this page the copy says truthfully where the latest search is kept. #420: after "Keep my requirements" or
// an accepted filter change, focus moves to the outcome and the new result is announced.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type S } from "../api/client";
import { searchIsCurrent, useMatchingCase } from "../components/MatchingCase";
import { Button, EmptyState, ErrorBanner, LoadingState, PageHead, StatusBanner, SyntheticBadge } from "../components/ui";
import { useAppState } from "../state/AppState";
import { runSearch, SEARCH_PRESETS } from "./A09";

function relax(criteria: S["ProviderCriteria"], field: S["FilterChangeSuggestion"]["field"]): S["ProviderCriteria"] {
  switch (field) {
    case "required_verified_plan":
      return { ...criteria, required_verified_plan: false, ranked_preferences: [...new Set([...criteria.ranked_preferences, "plan" as const])] };
    case "required_language":
      return { ...criteria, required_language: false, ranked_preferences: [...new Set([...criteria.ranked_preferences, "language" as const])] };
    case "radius_miles": {
      const steps = [5, 10, 25, 50, 100] as const;
      return { ...criteria, radius_miles: steps.find((s) => s > criteria.radius_miles) ?? 100 };
    }
    case "visit_type":
      return { ...criteria, visit_type: "either" };
  }
}

// #247: rank badges and card edges cycle through the accent hues (the rank number stays).
const RANK_ACCENTS = ["acc-blue", "acc-teal", "acc-violet", "acc-coral", "acc-sky", "acc-rose"];

export default function A10() {
  const { caseId = "" } = useParams();
  const { read, gate } = useMatchingCase(caseId, "Loading doctor matches");
  if (gate || !read) return gate;
  return <Matches caseId={caseId} read={read} />;
}

function Matches({ caseId, read }: { caseId: string; read: S["CaseReadResponse"] }) {
  const { searches, rememberSearch } = useAppState();
  // Searches run on this page are current by construction; one remembered from earlier must match the case read.
  const ranHere = useRef(new Set<string>());
  const remembered = searches.get(caseId);
  const current = remembered && (ranHere.current.has(remembered.result.id) || searchIsCurrent(read, remembered.result))
    ? remembered : undefined;
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [names, setNames] = useState<Record<string, S["Provider"]>>({});
  const [declinedFor, setDeclinedFor] = useState<string | null>(null);
  // #420: what takes focus after an action that removes its own button, and the announced outcome.
  const [focusTarget, setFocusTarget] = useState<string | null>(null);
  const [announced, setAnnounced] = useState("");
  // #316: a quick demo opens this screen with a named search preset. The full results live only in this tab's memory
  // (there is no read operation for a stored search), so the preset's search runs here once, in milliseconds.
  const preset = useSearchParams()[0].get("preset");
  const presetCriteria = preset && Object.hasOwn(SEARCH_PRESETS, preset) ? SEARCH_PRESETS[preset] : null;
  const [presetError, setPresetError] = useState<unknown>(null);
  const [presetTry, setPresetTry] = useState(0);
  const [, setPresetDone] = useState(0); // rememberSearch keeps the context value, so this screen re-renders itself

  useEffect(() => {
    if (current || !presetCriteria) return;
    let live = true;
    const criteria = presetCriteria();
    setPresetError(null);
    runSearch(caseId, criteria).then(
      (result) => {
        if (!live) return;
        ranHere.current.add(result.id);
        rememberSearch(caseId, { result, criteria });
        setPresetDone((n) => n + 1);
      },
      (err) => live && setPresetError(err),
    );
    return () => {
      live = false;
    };
  }, [caseId, current, presetCriteria, presetTry, rememberSearch]);

  useEffect(() => {
    if (!current) return;
    let live = true;
    // Only eligible matches have a card; disclosed candidates are named in their explanation.
    // #267: each card is read with the search it belongs to.
    Promise.all(current.result.matches.filter((m) => m.eligible).map((m) => api.getProvider(caseId, m.provider_id, current.result.id))).then(
      (cards) => live && setNames(Object.fromEntries(cards.map((c) => [c.provider.id, c.provider]))),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [caseId, current]);

  useEffect(() => {
    if (!focusTarget) return;
    document.getElementById(focusTarget)?.focus();
    setFocusTarget(null);
  }, [focusTarget, current]);

  if (!current && presetCriteria)
    return presetError != null ? (
      <ErrorBanner error={presetError} onRetry={() => setPresetTry((n) => n + 1)} />
    ) : (
      <LoadingState label="Finding fictional doctors" />
    );
  if (!current)
    return (
      <>
        <PageHead eyebrow="Find care" title="Doctor matches" />
        <EmptyState title="No search results to show"
          action={<Link className="btn" to={`/app/cases/${caseId}/preferences`}>Set preferences</Link>}>
          {read.found_doctors ? (
            <p>
              Your latest search for this consultation is kept on this device, and the doctors it found are in your
              visit summary. This page lists the full results only right after a search, not after a reload or in
              another tab. Run the search again to see them here.
            </p>
          ) : (
            <p>Set your preferences and run a search. The fictional doctors it finds are listed here and in your visit summary.</p>
          )}
        </EmptyState>
        <WaysOn caseId={caseId} />
      </>
    );
  const { result, criteria } = current;
  const eligible = result.matches.filter((m) => m.eligible);
  const disclosed = result.matches.filter((m) => !m.eligible);
  const declined = declinedFor === result.id;

  async function apply(field: S["FilterChangeSuggestion"]["field"]) {
    setPending(true);
    setError(null);
    setAnnounced("");
    try {
      const next = relax(criteria, field);
      const found = await runSearch(caseId, next);
      ranHere.current.add(found.id);
      rememberSearch(caseId, { result: found, criteria: next });
      // #420: the new result is announced, and focus moves to it (the button that asked for it is gone).
      const count = found.matches.filter((m) => m.eligible).length;
      setAnnounced(count ? matchCount(count) : "Still no doctors meet every requirement.");
      setFocusTarget(count ? "results-count" : "no-match-heading");
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <PageHead eyebrow="Find care" title="Doctor matches">
        <p>Ordered by specialty fit, your preferences, how recent the directory data is, and distance.</p>
      </PageHead>
      {/* #221: the directory version stays visible as evidence, in plain words and small print. */}
      <p className="small muted directory-version">
        Directory version {result.dataset_version} (
        {result.freshness_status === "cached" ? "an offline copy on this device" : result.freshness_status}).
      </p>
      <p className="sr-only" role="status">{announced}</p>
      {error != null && <ErrorBanner error={error} />}
      {eligible.length === 0 ? (
        <EmptyState title="No doctors meet every requirement" headingId="no-match-heading">
          <p>{result.no_match_reason}</p>
          {declined && <p role="status" id="kept-status" tabIndex={-1}>You kept your requirements, so no doctors are shown.</p>}
          {result.suggested_filter_changes.map((s) => (
            <div key={s.field} className="actions center">
              <Button type="button" pending={pending} onClick={() => apply(s.field)}>
                {s.suggestion}
              </Button>
              {!declined && (
                <button type="button" className="btn secondary" disabled={pending} onClick={() => {
                  setDeclinedFor(result.id);
                  setFocusTarget("kept-status"); // #420: the button removes itself; focus goes to what it did
                }}>
                  Keep my requirements
                </button>
              )}
            </div>
          ))}
          <p>
            <Link to={`/app/cases/${caseId}/preferences`}>Change preferences yourself</Link>
          </p>
        </EmptyState>
      ) : (
        <div className="stack">
          {/* #235: how many match, and the way back to the criteria, before the list. */}
          <div className="results-head">
            <p id="results-count" tabIndex={-1}>
              <b>{eligible.length}</b> fictional {eligible.length === 1 ? "doctor matches" : "doctors match"} your requirements.
            </p>
            <Link className="btn secondary sm" to={`/app/cases/${caseId}/preferences`}>
              Change preferences
            </Link>
          </div>
          <StatusBanner tone="info" title="Fictional doctors only">
            <p>No ratings or match percentages are used. Availability and credentials are unknown.</p>
          </StatusBanner>
          {eligible.map((m, i) => (
            <article className={`card provider ${RANK_ACCENTS[i % RANK_ACCENTS.length]}`} key={m.provider_id}>
              <div className="row">
                <span className="avatar" aria-hidden="true">
                  {i + 1}
                </span>
                <div>
                  <h2>{names[m.provider_id]?.name ?? `Match ${i + 1}`}</h2>
                  {names[m.provider_id] && (
                    <p className="small">
                      {names[m.provider_id].specialties.join(", ")} · {names[m.provider_id].practice}
                      {m.distance_miles !== null && ` · ${m.distance_miles} mi (fictional)`}
                    </p>
                  )}
                  <SyntheticBadge>Fictional doctor</SyntheticBadge>
                </div>
              </div>
              {/* #217: the facts appear once, in the lists; only the rest of the explanation is shown. */}
              <p className="small muted">{explanationNote(m.explanation, m.confirmed_matches)}</p>
              <div className="grid2">
                <div>
                  <h3>Confirmed</h3>
                  <ul className="facts-confirmed">
                    {m.confirmed_matches.map((x) => (
                      <li key={x}>{x}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3>Unknown</h3>
                  <ul className="facts-unknown">
                    {m.unknowns.map((x) => (
                      <li key={x}>{x}</li>
                    ))}
                  </ul>
                </div>
              </div>
              {/* #444: each link names its doctor (the visible words stay first, WCAG 2.5.3). */}
              <Link className="btn secondary" to={`/app/cases/${caseId}/doctors/${m.provider_id}?search=${result.id}`}
                aria-label={`Inspect doctor: ${names[m.provider_id]?.name ?? `Match ${i + 1}`}`}>
                Inspect doctor
              </Link>
            </article>
          ))}
        </div>
      )}
      {disclosed.length > 0 && (
        <section className="card" aria-labelledby="excluded-heading">
          <h2 id="excluded-heading">Not shown: a required detail is not verified</h2>
          <p className="small">These fictional doctors fit your other filters, but a required detail is unknown or out of date. They are not ranked.</p>
          <ul className="bullets">
            {disclosed.map((m) => (
              <li key={m.provider_id}>{m.explanation}</li>
            ))}
          </ul>
        </section>
      )}
      <WaysOn caseId={caseId}>
        <Link className="btn secondary" to={`/app/cases/${caseId}/preferences`}>
          Change preferences
        </Link>
      </WaysOn>
    </>
  );
}

/** "3 fictional doctors match your requirements." (the results line, as announced) */
function matchCount(n: number): string {
  return `${n} fictional ${n === 1 ? "doctor matches" : "doctors match"} your requirements.`;
}

/** #341: the ways on from the doctor pages (A10, A11): the visit summary first, then back to the guidance and the
 * screen's own way back. The same order as A07's next steps: primary first in reading and focus order. */
export function WaysOn({ caseId, children }: { caseId: string; children?: ReactNode }) {
  return (
    <nav className="actions next-steps" aria-label="Next steps">
      <Link className="btn" to={`/app/cases/${caseId}/summary`}>
        Continue to visit summary
      </Link>
      <div className="row">
        {children}
        <Link className="btn secondary" to={`/app/cases/${caseId}/guidance`}>
          Back to guidance
        </Link>
      </div>
    </nav>
  );
}

/** #217: the server's explanation for an eligible doctor is its confirmed facts joined with " · ", then a note
 * ("Fictional doctor; ordering uses only the listed facts."). The facts are listed under Confirmed, so only the note is
 * repeated here. Any other wording is shown in full, so nothing is ever dropped. */
export function explanationNote(explanation: string, confirmed: string[]): string {
  const facts = confirmed.join(" · ");
  if (!facts || !explanation.startsWith(facts)) return explanation;
  const rest = explanation.slice(facts.length).replace(/^[.\s]+/, "").trim();
  return rest || explanation;
}
