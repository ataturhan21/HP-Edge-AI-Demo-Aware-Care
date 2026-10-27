// A14 Data settings (M11; R34-R36). Retention facts, delete-all with one-use token, end session.
// #394: once the server accepts "Delete all consultations", this tab forgets what it held for every case.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, pollJob, type S } from "../api/client";
import { useForgetJourneyCase } from "../components/JourneySteps";
import { useEndSession } from "../components/ResetActions";
import { Icon } from "../components/Icon";
import { ConfirmDialog, ErrorBanner, LoadingState, PageHead, StatusBanner } from "../components/ui";
import { useAppState } from "../state/AppState";

export default function A14() {
  const [data, setData] = useState<S["SettingsResponse"] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [confirm, setConfirm] = useState<"delete" | "end" | null>(null);
  // "not_started" (#303): the request never reached the server or was refused before deletion began, so nothing was
  // deleted; "failed": the server accepted the deletion but it did not finish.
  const [status, setStatus] = useState<"idle" | "pending" | "not_started" | "failed" | "deleted">("idle");
  const key = useRef(crypto.randomUUID());
  const { forgetCases } = useAppState();
  const forgetJourney = useForgetJourneyCase();

  const load = useCallback(() => {
    api.getSettings().then(setData, setError);
  }, []);
  useEffect(load, [load]);

  async function deleteAll() {
    if (!data) return;
    setStatus("pending");
    setConfirm(null);
    let accepted: S["DeletionAccepted"];
    try {
      accepted = await api.deleteAll(data.delete_confirmation_token, key.current);
    } catch {
      setStatus("not_started");
      key.current = crypto.randomUUID();
      load();
      return;
    }
    forgetCases();
    forgetJourney();
    try {
      const job = await pollJob(accepted.deletion_job_id, new AbortController().signal);
      setStatus(job.status === "succeeded" ? "deleted" : "failed");
    } catch {
      setStatus("failed");
    } finally {
      key.current = crypto.randomUUID();
      load();
    }
  }

  // Clears browser state only after the server accepted the deletion; failures stay visible.
  const { end: endSession, pending: ending, error: endError } = useEndSession();

  if (error && !data) return <ErrorBanner error={error} onRetry={load} />;
  if (!data) return <LoadingState label="Loading data settings" />;
  const s = data.settings;
  return (
    <div className="narrow">
      <PageHead eyebrow="Your data" title="Data settings" />
      {status === "pending" && <StatusBanner tone="info" title="Deleting your demo health information…" />}
      {status === "deleted" && <StatusBanner tone="success" title="All consultations were deleted from this device." />}
      {status === "not_started" && (
        <StatusBanner tone="error" title="Deletion did not start.">
          <p>The request did not reach the Aware Care service or was not accepted, so nothing was deleted. Your consultations are unchanged.</p>
          <button type="button" className="btn secondary sm" onClick={() => setConfirm("delete")}>
            Try again
          </button>
        </StatusBanner>
      )}
      {status === "failed" && (
        <StatusBanner tone="error" title="Deletion did not finish.">
          <p>Access stays blocked while the server retries. You can try again.</p>
        </StatusBanner>
      )}
      <section className="card accent-card acc-sky">
        <h2 className="card-title">
          <span className="card-icon" aria-hidden="true"><Icon name="clock" size={18} /></span>
          Retention
        </h2>
        <div className="datum"><span>Guest session</span><b>{s.guest_idle_minutes} min idle or {s.guest_absolute_hours} h maximum</b></div>
        <div className="datum"><span>Summary downloads</span><b>{s.export_retention_minutes} minutes</b></div>
        <div className="datum"><span>Service logs (no health details)</span><b>{s.operational_event_retention_days} days</b></div>
        <div className="datum"><span>Backups of your health information</span><b>{s.patient_backups_enabled ? "Enabled" : "Disabled"}</b></div>
        <p className="small muted">Saved-account retention (7 or 30 days) needs a saved account, which this build does not offer.</p>
      </section>
      <section className="card accent-card acc-rose">
        <h2 className="card-title">
          <span className="card-icon" aria-hidden="true"><Icon name="trash" size={18} /></span>
          Delete data
        </h2>
        <p>Downloaded PDFs on your computer are outside these controls.</p>
        {/* #218: each action says what it removes and what happens next. */}
        <div className="delete-options">
          <div className="delete-option">
            <p id="end-desc" className="small">
              <b>End session and delete:</b> removes everything from this session and signs you out. You start again from the
              beginning.
            </p>
            <button type="button" className="btn secondary" aria-describedby="end-desc" onClick={() => setConfirm("end")}>
              End session and delete
            </button>
          </div>
          <div className="delete-option">
            <p id="delete-desc" className="small">
              <b>Delete all consultations:</b> removes every consultation (answers, guidance, searches and summaries). You stay
              in this session and can start a new consultation.
            </p>
            <button type="button" className="btn danger" aria-describedby="delete-desc" onClick={() => setConfirm("delete")}
              disabled={status === "pending"}>
              Delete all consultations
            </button>
          </div>
        </div>
      </section>
      {confirm === "delete" && (
        <ConfirmDialog title="Delete all your consultations?" confirmLabel="Delete everything" destructive
          onCancel={() => setConfirm(null)} onConfirm={deleteAll}>
          <p>All answers, guidance, searches and summaries for this session are removed. This cannot be undone.</p>
        </ConfirmDialog>
      )}
      {confirm === "end" && (
        <ConfirmDialog title="End your guest session?" confirmLabel="End session" destructive pending={ending}
          onCancel={() => setConfirm(null)} onConfirm={endSession}>
          <p>Your session ends and its health information is deleted from this device.</p>
          {endError != null && <ErrorBanner error={endError} onRetry={endSession} />}
        </ConfirmDialog>
      )}
    </div>
  );
}
