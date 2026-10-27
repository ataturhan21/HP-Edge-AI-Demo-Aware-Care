// Reset and restart controls (M01/M11; R35). "Start a new consultation" (#345) keeps the guest session;
// "End session and reset" calls deleteSession, which revokes the session and purges its cases
// on the server, then clears all in-memory browser state. Nothing is kept in browser storage.
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAppState } from "../state/AppState";
import { ConfirmDialog, ErrorBanner } from "./ui";
import { START_LABEL } from "./resume";

export function useEndSession() {
  const navigate = useNavigate();
  const { clearAll } = useAppState();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function end() {
    setPending(true);
    setError(null);
    try {
      await api.deleteSession();
      clearAll();
      navigate("/app/start", { replace: true, state: { reset: true } });
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }
  return { end, pending, error };
}

export function EndSessionButton({ className = "btn secondary" }: { className?: string }) {
  const [confirm, setConfirm] = useState(false);
  const { end, pending, error } = useEndSession();
  return (
    <>
      <button type="button" className={className} onClick={() => setConfirm(true)}>
        End session and reset
      </button>
      {confirm && (
        <ConfirmDialog title="End this demo session?" confirmLabel="End session and reset" destructive pending={pending}
          onCancel={() => setConfirm(false)} onConfirm={end}>
          <p>All synthetic cases, answers, results and summaries in this guest session are deleted on this device.</p>
          <p className="small">A summary you already downloaded is outside Aware Care’s deletion controls.</p>
          {error != null && <ErrorBanner error={error} onRetry={end} />}
        </ConfirmDialog>
      )}
    </>
  );
}

export function ResetActions() {
  return (
    <section className="card" aria-labelledby="reset-heading">
      <h2 id="reset-heading">Finished with this consultation?</h2>
      <p className="small">Start a new consultation in this session, or end the session to delete everything.</p>
      <div className="actions">
        <EndSessionButton />
        <Link className="btn" to="/app/new">
          {START_LABEL}
        </Link>
      </div>
    </section>
  );
}
