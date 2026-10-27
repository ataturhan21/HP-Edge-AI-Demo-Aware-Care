// Presenter data loader (ADR-005 option A). The server decides the role: a presenter session exists only
// when the request came through the gateway's presenter path (#487: /presenter-api/ of the one address), which signs
// every request. This component only offers to start one when that path identifies itself (X-AwareCare-Gateway:
// presenter); a hidden link, route or header seen by the browser is never treated as authorization.
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApiError, PRESENTER_API, api } from "../api/client";
import { CONSENT_VERSION } from "../screens/A01";
import { ErrorBanner, LoadingState, OriginHelp, StatusBanner, useFocusReturn } from "./ui";

type PresenterContext = { reload: () => void };

/** #327: O03 kept its prepared quick demos in sessionStorage under this prefix (ids, times and states only). Since
 *  #358 nothing is prepared ahead; a new presenter session still clears what an earlier build left there. */
export const PREPARED_DEMOS_PREFIX = "aware-care:o03-prepared:";

/** #423: O03's one-click flow runs of this browser tab (components/presenterRuns.ts; IDs and states only). */
export const FLOW_RUNS_KEY = "aware-care:o03-runs";

/** A new presenter session owns no demo of an earlier one: forget them (storage may be unavailable). */
function forgetPreparedDemos() {
  try {
    for (const key of Object.keys(sessionStorage))
      if (key.startsWith(PREPARED_DEMOS_PREFIX) || key === FLOW_RUNS_KEY) sessionStorage.removeItem(key);
  } catch {
    // storage blocked: nothing was kept
  }
}

const sessionStartListeners = new Set<() => void>();
/** #423: a new presenter session starts with no flow runs of an earlier one (presenterRuns.ts listens). */
export function onPresenterSessionStarted(listener: () => void): () => void {
  sessionStartListeners.add(listener);
  return () => sessionStartListeners.delete(listener);
}

/** #423: whether this tab has a flow run kept from before a reload (then the presenter shell resumes it). */
export function hasFlowRuns(): boolean {
  try {
    return sessionStorage.getItem(FLOW_RUNS_KEY) !== null;
  } catch {
    return false;
  }
}

export function usePresenter<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setError(null);
    load().then(setData, setError);
  }, [load, attempt]);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { data, error, reload };
}

/** #487: true when this device offers presenter access, that is when its presenter path answers as the presenter
 *  gateway (a UI hint only; the API authorizes). Called from presenter pages only: a patient page never calls the
 *  presenter API. */
export async function presenterAccessOffered(): Promise<boolean> {
  const response = await fetch(`${PRESENTER_API}/health/ready`, { credentials: "same-origin", cache: "no-store" });
  // #331: read the small body, so the request completes (an unread body stayed in flight on W03).
  await response.text().catch(() => "");
  return response.headers.get("X-AwareCare-Gateway") === "presenter";
}

function PresenterSignIn({ reload }: PresenterContext) {
  const [gateway, setGateway] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  useFocusReturn(busy); // #402: a refused start leaves focus on the button
  useEffect(() => {
    presenterAccessOffered().then(setGateway, () => setGateway(false));
  }, []);
  const start = async () => {
    forgetPreparedDemos();
    setBusy(true);
    setFailure(null);
    try {
      await api.createSession({ mode: "guest", consent_version: CONSENT_VERSION, adult_eligible: true },
        crypto.randomUUID(), "presenter");
      for (const listener of sessionStartListeners) listener();
      reload();
      // #402: the sign-in banner gives way to the presenter page; its heading (outside this banner) takes focus.
      document.querySelector<HTMLElement>("main h1")?.focus();
    } catch (err) {
      setFailure(err);
    } finally {
      setBusy(false);
    }
  };
  const originRefused = failure instanceof ApiError && failure.code === "ORIGIN_REJECTED"; // #461
  if (gateway === null) return <LoadingState label="Checking presenter access" />;
  if (!gateway) {
    // #487: the same address serves the presenter tools; only the device's configuration can turn them on.
    return (
      <StatusBanner tone="warn" title="Presenter authorization required">
        <p>
          Presenter access is not enabled on this device, so the presenter tools are unavailable. It is turned on by the
          device's presenter key (see the delivery runbook), and only for the address reached through the SSH tunnel.
        </p>
        <p>
          <Link to="/">Back to the home page</Link> to start a consultation as a patient.
        </p>
      </StatusBanner>
    );
  }
  return (
    <>
      {/* #461: the refused address explained (the error banner's help), or up front at "localhost". */}
      {originRefused ? <OriginHelp /> : window.location.hostname === "localhost" && <OriginHelp refused={false} />}
      <StatusBanner tone="info" title="Start a presenter session">
        <p>
          These are the presenter tools of this device. A presenter session shows runtime and demo controls without
          patient health content. It follows the demo terms (synthetic data only) and expires like a guest session.
        </p>
        {failure !== null && !originRefused && <ErrorBanner error={failure} />}
        <button type="button" className="btn" onClick={start} disabled={busy}>
          {busy ? "Starting…" : "Start presenter session"}
        </button>
      </StatusBanner>
    </>
  );
}

export function PresenterState({ error, children, loading, reload }:
  { error: unknown; loading: boolean; children: ReactNode; reload: () => void }) {
  if (error instanceof ApiError && (error.status === 401 || error.status === 403))
    return <PresenterSignIn reload={reload} />;
  if (error) return <ErrorBanner error={error} onRetry={reload} />;
  if (loading) return <LoadingState label="Loading presenter data" />;
  return <>{children}</>;
}
