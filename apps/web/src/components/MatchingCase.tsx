// #394/#419: the doctor pages (A09 preferences, A10 matches, A11 details) read the case first, as A07, A08 and A12 do,
// so their access guards hold on direct navigation, Back/Forward and reload: a case that cannot be shown (deleted,
// ended with its session, another session's, unknown) says so, and a case without current reviewed non-urgent guidance
// says that doctor matching needs it and leads to where the consultation is. The server still checks every request;
// this only decides what the page shows. Nothing is stored.
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApiError, type S } from "../api/client";
import { useJourneyCase } from "./JourneySteps";
import { caseNextStep } from "./resume";
import { CaseUnavailable, EmptyState, ErrorBanner, LoadingState } from "./ui";
import { useCase } from "./useCase";

/** Doctor matching is open for a case the server allows searchProviders on (current routine guidance). */
export function matchingAllowed(read: S["CaseReadResponse"]): boolean {
  return read.allowed_actions.includes("search_providers");
}

/**
 * #394: a doctor search this tab remembers is shown only while it is still the case's current search: made at the
 * case's current revision, and the search the server names for the visit summary (it names one only when the search
 * found an eligible doctor). A deleted, changed or replaced case never shows an earlier search.
 */
export function searchIsCurrent(read: S["CaseReadResponse"], result: S["ProviderSearchResult"]): boolean {
  if (result.case_id !== read.case.id || result.input_revision !== read.case.revision) return false;
  const named = read.found_doctors?.search_id ?? null;
  return result.matches.some((m) => m.eligible) ? named === result.id : named === null;
}

/**
 * Reads the case for a doctor page. `read` is the case once doctor matching is open for it; otherwise `gate` is what
 * the page shows instead (loading, unavailable, no current guidance, a failed read with Try again).
 */
export function useMatchingCase(caseId: string, loadingLabel: string) {
  const { data, error, reload } = useCase(caseId);
  const notFound = error instanceof ApiError && error.status === 404;
  // #343: the Guidance and Summary step links follow what this read showed.
  useJourneyCase(caseId, data ? data.allowed_actions.includes("view_guidance") : notFound ? false : undefined);
  const open = data !== null && matchingAllowed(data);
  let gate: ReactNode = null;
  if (!open) {
    if (notFound) gate = <CaseUnavailable />;
    else if (error) gate = <ErrorBanner error={error} onRetry={() => void reload()} />;
    else if (!data) gate = <LoadingState label={loadingLabel} />;
    else gate = <MatchingClosed read={data} />;
  }
  return { read: open ? data : null, gate };
}

/** The case exists but doctor matching is not open for it: say why, and lead to where the consultation is. */
function MatchingClosed({ read }: { read: S["CaseReadResponse"] }) {
  const next = caseNextStep(read.case, read.allowed_actions);
  // An urgent case, or guidance that suggests urgent care: matching is never offered (urgent routing blocks it).
  const urgent = read.case.state === "urgent" || read.allowed_actions.includes("view_guidance");
  return urgent ? (
    <EmptyState page title="Doctor matching is not available"
      action={<Link className="btn" to={next.to}>{next.label}</Link>}>
      <p>Aware Care does not match doctors for a consultation that needs urgent care. In an emergency call 911.</p>
    </EmptyState>
  ) : (
    <EmptyState page title="No current guidance" action={<Link className="btn" to={next.to}>{next.label}</Link>}>
      <p>Doctor matching needs current, reviewed guidance for this consultation. Continue from its current step.</p>
    </EmptyState>
  );
}
