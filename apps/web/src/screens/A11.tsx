// A11 Doctor details (M09; R30, R31). Provenance and unknowns; contact is a labeled simulation.
// No booking, message or network call is made; fictional cards have no contact URL.
// #341: the details lead on to the visit summary (A12) and back to the guidance (A07), as well as back to the matches.
// #419: the case is read first (components/MatchingCase.tsx): a missing case, or one without current routine guidance,
// shows that state instead of "not in your current results".
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, type S } from "../api/client";
import { useMatchingCase } from "../components/MatchingCase";
import { ConfirmDialog, EmptyState, ErrorBanner, LoadingState, PageHead, StatusBanner, SyntheticBadge } from "../components/ui";
import { useAppState } from "../state/AppState";
import { explanationNote, WaysOn } from "./A10";

const VISIT: Record<string, string> = { in_person: "In person", telehealth: "Telehealth" };

export default function A11() {
  const { caseId = "", providerId = "" } = useParams();
  const { gate } = useMatchingCase(caseId, "Loading doctor details");
  if (gate) return gate;
  return <DoctorDetails caseId={caseId} providerId={providerId} />;
}

function DoctorDetails({ caseId, providerId }: { caseId: string; providerId: string }) {
  // #267: the card belongs to the search it was opened from (in the link, or the search held in memory).
  const [params] = useSearchParams();
  const { searches } = useAppState();
  const searchId = params.get("search") ?? searches.get(caseId)?.result.id ?? null;
  const [card, setCard] = useState<S["ProviderCard"] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [contact, setContact] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (searchId) api.getProvider(caseId, providerId, searchId).then(setCard, setError);
  }, [caseId, providerId, searchId, attempt]);

  if (!searchId || (error instanceof ApiError && (error.status === 404 || error.status === 409)))
    return (
      <EmptyState page title="This doctor is not in your current results" action={<Link className="btn" to={`/app/cases/${caseId}/preferences`}>Search again</Link>}>
        <p>Results expire when your case changes. Search again to see the current matches.</p>
      </EmptyState>
    );
  // #288: a failed read can be tried again.
  if (error) return <ErrorBanner error={error} onRetry={() => {
    setError(null);
    setAttempt((n) => n + 1);
  }} />;
  if (!card) return <LoadingState label="Loading doctor details" />;
  const p = card.provider;
  const synthetic = p.data_mode === "synthetic";
  return (
    <>
      <PageHead eyebrow="Doctor details" title={p.name}>
        <p>
          {p.specialties.join(", ")} · {p.practice}
        </p>
      </PageHead>
      {synthetic && <SyntheticBadge>Fictional doctor</SyntheticBadge>}
      <div className="grid2" style={{ marginTop: 16 }}>
        <section className="card">
          <h2>Why this doctor appears</h2>
          <p className="small muted">{explanationNote(card.match.explanation, card.match.confirmed_matches)}</p>
          <ul className="facts-confirmed">
            {card.match.confirmed_matches.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </section>
        <section className="card">
          <h2>Facts and their status</h2>
          <div className="datum">
            <span>Languages</span>
            <b>{p.languages.join(", ") || "Unknown"}</b>
          </div>
          <div className="datum">
            <span>Visit types</span>
            <b>{p.visit_types.map((v) => VISIT[v]).join(", ")}</b>
          </div>
          <div className="datum">
            <span>Plans</span>
            <b>{p.plans.length ? p.plans.map((x) => `${x.plan_id} (${x.verification_status})`).join(", ") : "Unknown"}</b>
          </div>
          <div className="datum">
            <span>Appointment availability</span>
            <b>{p.availability_status === "confirmed" ? "Confirmed" : "Unknown"}</b>
          </div>
          <div className="datum">
            <span>Credentials</span>
            <b>{p.credential_status === "confirmed" ? "Confirmed" : "Not verified"}</b>
          </div>
          <p className="small muted">
            Where this comes from: {p.source_records[0]?.publisher}, directory version {p.snapshot_version}. The date these
            facts were checked is not recorded.
          </p>
        </section>
      </div>
      <p className="actions">
        <button type="button" className="btn secondary" onClick={() => setContact(true)}>
          Open contact or booking site
        </button>
      </p>
      <WaysOn caseId={caseId}>
        <Link className="btn secondary" to={`/app/cases/${caseId}/doctors`}>
          Back to matches
        </Link>
      </WaysOn>
      {contact &&
        (p.contact_url && !synthetic ? (
          <ConfirmDialog title="Leave Aware Care?" confirmLabel="Continue" onCancel={() => setContact(false)}
            onConfirm={() => {
              window.open(p.contact_url!, "_blank", "noopener,noreferrer");
              setContact(false);
            }}>
            <p>You are going to {new URL(p.contact_url).host}. No case details are sent. That site will see your network address.</p>
          </ConfirmDialog>
        ) : (
          <ConfirmDialog title="Simulated contact" confirmLabel="" cancelLabel="Close" onCancel={() => setContact(false)}>
            <StatusBanner tone="warn" title="Simulation only">
              <p>
                {p.name} is fictional. Nothing was sent, no appointment was booked, and no external site was opened.
              </p>
            </StatusBanner>
            <p>For a real provider, Aware Care would show the destination and open it only after you confirm.</p>
          </ConfirmDialog>
        ))}
    </>
  );
}
