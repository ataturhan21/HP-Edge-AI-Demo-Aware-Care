// A08 Sources (M07; R21, R22). Claim-to-source links; an unsupported sourced claim is suppressed, and possible
// explanations from general medical knowledge are marked as such (ADR-015). #456: in mock mode the explanation is a
// scripted fixture sentence and is marked scripted (A08 rule 3), read from the guidance's own model manifest.
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, asNoCurrentGuidance, type S } from "../api/client";
import { CaseUnavailable, EmptyState, ErrorBanner, formatDate, LoadingState, PageHead, StatusBanner } from "../components/ui";

const STATUS: Record<S["Claim"]["validation_status"], string> = {
  supported: "Supported",
  suppressed: "Suppressed — no approved source",
  general_knowledge: "General medical knowledge — no reviewed source",
  pending: "Pending",
};
const SCRIPTED = "Scripted illustrative text — no AI model, no reviewed source";

export default function A08() {
  const { caseId = "" } = useParams();
  const [data, setData] = useState<(S["CaseSources"] & { mock: boolean }) | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => {
    setError(null);
    // #269: sources of guidance never generated are 404; if the case itself is readable, show "No current guidance".
    // A 404 for the case itself stays a 404 and shows the unavailable state (#288).
    Promise.all([api.getSources(caseId), api.getGuidance(caseId)]).then(
      ([sources, guidance]) => setData({ ...sources, mock: guidance.model_manifest_id.startsWith("mock-") }),
      (err: unknown) =>
        err instanceof ApiError && err.status === 404
          ? api.getCase(caseId).then(() => setError(asNoCurrentGuidance(err)), setError)
          : setError(err),
    );
  }, [caseId]);
  useEffect(load, [load]);

  if (error instanceof ApiError && error.status === 409)
    return (
      <EmptyState page title="No current guidance" action={<Link className="btn" to={`/app/cases/${caseId}/review`}>Go to review</Link>}>
        <p>Sources are shown for the current guidance only.</p>
      </EmptyState>
    );
  // #288: a case that cannot be shown says so; any other failure can be tried again.
  if (error instanceof ApiError && error.status === 404) return <CaseUnavailable />;
  if (error) return <ErrorBanner error={error} onRetry={load} />;
  if (!data) return <LoadingState label="Loading sources" />;
  return (
    <>
      <PageHead eyebrow="Sources" title="Where the guidance comes from" />
      {data.evidence.length === 0 && (
        <StatusBanner tone="warn" title="No approved evidence sources are loaded">
          <p>
            {data.mock
              ? "The possible explanation is scripted illustrative text for this synthetic demo, not from an AI model, and is marked that way below."
              : "Possible explanations come from general medical knowledge and are marked that way below."}{" "}
            No statement is presented as coming from a reviewed source.
          </p>
        </StatusBanner>
      )}
      <section className="card">
        <h2>Statements in your guidance</h2>
        {data.claims.map((claim) => (
          <div className="datum" key={claim.id}>
            <span>{claim.text}</span>
            <span className={`badge ${claim.validation_status === "supported" ? "green" : "gray"}`}>
              {claim.kind === "case_fact" ? "From your answers"
                : data.mock && claim.validation_status === "general_knowledge" ? SCRIPTED : STATUS[claim.validation_status]}
            </span>
          </div>
        ))}
      </section>
      {data.evidence.map((ev) => (
        <section className="card" key={ev.id}>
          <h3>{ev.title}</h3>
          <p className="small">
            {ev.publisher} · retrieved {formatDate(ev.retrieved_at, { utc: true })} · {ev.locator}
          </p>
          <a href={ev.source_url} target="_blank" rel="noopener noreferrer">
            Open cited source
          </a>
        </section>
      ))}
      <div className="actions">
        <Link className="btn secondary" to={`/app/cases/${caseId}/guidance`}>
          Back to guidance
        </Link>
      </div>
    </>
  );
}
