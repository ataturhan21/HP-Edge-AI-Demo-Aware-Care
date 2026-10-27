// A13 Consultation history (M03; R03, R10, R35). Owned cases only; resume or delete with confirmation.
// #188: each row says which consultation it is (its concern, read from the owned case), its status in plain words,
// the time left in words, and an action named for the next step.
// #330: below 640 px each row is a stacked card (status, times, full-width actions); the table and its named scroll
// region stay at wider widths. The concern wraps at word boundaries; only an unbroken string may break anywhere.
// #394: once the server accepts a deletion, this tab forgets what it held for the case (its doctor search and criteria,
// its step links), so the case cannot come back through browser Back. #458: the confirmation names the consultation.
// #611: a deletion in flight belongs to its own consultation: its state, its error and its completion apply to that
// consultation's confirmation only. #629 (owner decision): while it is in flight its confirmation stays locked (Escape
// and Cancel do nothing; "Deleting…", aria-busy) until it finishes (the dialog closes) or fails (the error shows in the
// dialog, which Cancel or Escape then closes).
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, pollJob, type S } from "../api/client";
import { ConfirmDialog, EmptyState, ErrorBanner, formatDate, formatDateTime, formatTime, LoadingState, PageHead, ScrollTable, StatusBanner } from "../components/ui";
import { Icon, type IconName } from "../components/Icon";
import { useForgetJourneyCase } from "../components/JourneySteps";
import { caseNextStep, START_LABEL } from "../components/resume";
import { useAppState } from "../state/AppState";

// The action for a row is named for what happens next (caseNextStep, shared with the resume target, #340).
// #282: a limited case whose guidance failed recoverably opens A07, which offers Retry.
const RETRY_STATE = "Guidance failed, can retry";

// #305: the same output in every browser locale; the browser's time zone, so the time is the local one.
// #347: the shared date and time style ("Today, 08:21" or "16 Oct 2026, 08:21").
function started(iso: string): string {
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString() ? `Today, ${formatTime(d)}` : `${formatDate(d)}, ${formatTime(d)}`;
}

function timeLeft(iso: string, now: number): string {
  const minutes = Math.round((new Date(iso).getTime() - now) / 60000);
  if (minutes <= 0) return "Ending now";
  if (minutes < 60) return `Ends in ${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
  const hours = Math.floor(minutes / 60);
  return `Ends in ${hours} h ${minutes % 60} min`;
}

/** #330: a run this long has no word boundary to wrap at, so it may break anywhere instead of widening the row. */
const UNBROKEN = /\S{24,}/;

function shorten(text: string, max = 60): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

const STATE_LABEL: Record<string, string> = {
  draft: "Started",
  intake: "Answering questions",
  review: "Ready for review",
  reviewed: "Reviewed",
  generating: "Preparing guidance",
  guided: "Guidance ready",
  urgent: "Urgent action",
  limited: "Outside demo limits",
};

// #246: each status as a coloured chip with an icon; the words carry the meaning.
const STATE_CHIP: Record<string, [string, IconName]> = {
  draft: ["acc-sky", "list"],
  intake: ["acc-sky", "list"],
  review: ["acc-violet", "check"],
  reviewed: ["acc-violet", "check"],
  generating: ["acc-blue", "clock"],
  guided: ["acc-green", "check"],
  urgent: ["acc-rose", "urgent"],
  limited: ["acc-amber", "info"],
};

export default function A13() {
  const navigate = useNavigate();
  const { forgetCases } = useAppState();
  const forgetJourney = useForgetJourneyCase();
  const [list, setList] = useState<S["CaseList"] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [target, setTarget] = useState<S["CaseMetadata"] | null>(null);
  // #611: the consultations whose deletion is in flight, by case ID.
  const [deleting, setDeleting] = useState<ReadonlySet<string>>(() => new Set());
  // R35: report deletion only after the server's deletion job succeeded; a failed purge stays visible.
  const [outcome, setOutcome] = useState<"deleted" | "failed" | null>(null);
  const [concerns, setConcerns] = useState<Record<string, string>>({});
  // #282: which limited cases allow a retry (from the same owned case read as the concern).
  const [retryable, setRetryable] = useState<Record<string, boolean>>({});
  // #283: a delete error is shown inside the dialog, where the person is. #611: it belongs to its consultation; when
  // that consultation's dialog was closed meanwhile, the page shows it.
  const [deleteError, setDeleteError] = useState<{ id: string; error: unknown } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!list) return;
    let live = true;
    // The concern is shown on screen elsewhere in the same session (A06); it is read from the owned case only.
    Promise.all(list.items.map((c) => api.getCaseQuietly(c.id).then((r) => [c.id, r] as const, () => null)))
      .then((pairs) => {
        if (!live) return;
        const reads = pairs.filter((p): p is readonly [string, S["CaseReadResponse"]] => p !== null);
        setConcerns(Object.fromEntries(reads.map(([id, r]) => [id, r.case.concern])));
        setRetryable(Object.fromEntries(reads.map(([id, r]) => [id, r.allowed_actions.includes("retry")])));
      });
    return () => {
      live = false;
    };
  }, [list]);

  const load = useCallback(() => {
    setError(null);
    api.listCases().then(setList, setError);
  }, []);
  useEffect(load, [load]);

  // #283: the deleted row (and its Delete button) is gone after the list reloads; focus goes to the page heading
  // instead of falling back to the page body.
  useEffect(() => {
    if (outcome && (document.activeElement === document.body || !document.activeElement))
      document.querySelector<HTMLElement>("main h1, h1")?.focus();
  }, [outcome, list]);
  // #266: the list is paged (20 at a time, newest first); older consultations load on request.
  const [loadingOlder, setLoadingOlder] = useState(false);
  async function loadOlder() {
    if (!list?.next_cursor) return;
    setLoadingOlder(true);
    setError(null);
    try {
      const page = await api.listCases(list.next_cursor);
      setList((prev) => (prev ? { items: [...prev.items, ...page.items.filter((c) => !prev.items.some((p) => p.id === c.id))], next_cursor: page.next_cursor } : page));
    } catch (err) {
      setError(err);
    } finally {
      setLoadingOlder(false);
    }
  }

  async function confirmDelete() {
    if (!target || deleting.has(target.id)) return;
    const doomed = target; // #611: this operation's consultation, whatever is selected when it finishes
    setDeleting((ids) => new Set(ids).add(doomed.id));
    setOutcome(null);
    setDeleteError(null);
    try {
      const accepted = await api.deleteCase(doomed.id, doomed.revision);
      // #394: the server revoked access when it accepted; nothing of the case stays in this tab.
      forgetCases(doomed.id);
      forgetJourney(doomed.id);
      const job = await pollJob(accepted.deletion_job_id, new AbortController().signal);
      setOutcome(job.status === "succeeded" ? "deleted" : "failed");
      setTarget((current) => (current?.id === doomed.id ? null : current));
      load();
    } catch (err) {
      setDeleteError({ id: doomed.id, error: err });
      if (err instanceof ApiError && err.status === 409) load();
    } finally {
      setDeleting((ids) => {
        const rest = new Set(ids);
        rest.delete(doomed.id);
        return rest;
      });
    }
  }

  if (error && !list) return <ErrorBanner error={error} onRetry={load} />;
  if (!list) return <LoadingState label="Loading your consultations" />;
  return (
    <>
      <PageHead eyebrow="History" title="Consultation history">
        <p>Guest consultations end with your session.</p>
      </PageHead>
      {outcome === "deleted" && <StatusBanner tone="success" title="The consultation was deleted." />}
      {outcome === "failed" && (
        <StatusBanner tone="error" title="Deletion did not finish.">
          <p>The consultation stays unavailable while the server retries the removal.</p>
        </StatusBanner>
      )}
      {error != null && <ErrorBanner error={error} />}
      {deleteError && deleteError.id !== target?.id && <ErrorBanner error={deleteError.error} />}
      {list.items.length === 0 ? (
        <EmptyState title="No consultations yet" action={<Link className="btn" to="/app/new">{START_LABEL}</Link>} />
      ) : (
        <ScrollTable className="card history-wrap" label="Consultation history">
          <table className="stack-table history-table">
            <thead>
              <tr>
                <th scope="col">Concern</th>
                <th scope="col">Status</th>
                <th scope="col">Started</th>
                <th scope="col">Time left</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((c) => (
                <tr key={c.id}>
                  <td id={`concern-${c.id}`}
                    className={`history-concern${concerns[c.id] && UNBROKEN.test(concerns[c.id]) ? " unbroken" : ""}`}>
                    {/* #392: a case sent to urgent help from a ticked sign may have no concern written. */}
                    {concerns[c.id] ? shorten(concerns[c.id]) : concerns[c.id] === ""
                      ? <span className="muted">No concern written (warning sign ticked)</span>
                      : <span className="muted">…</span>}
                  </td>
                  <td>
                    <span className={`chip ${(STATE_CHIP[c.state] ?? ["acc-slate"])[0]}`}>
                      <Icon name={(STATE_CHIP[c.state] ?? ["", "info"])[1] as IconName} size={14} />
                      {c.state === "limited" && retryable[c.id] ? RETRY_STATE : STATE_LABEL[c.state] ?? c.state}
                    </span>
                  </td>
                  <td data-label="Started">{started(c.created_at)}</td>
                  <td data-label="Time left">
                    <time dateTime={c.expires_at} title={formatDateTime(c.expires_at)}>
                      {timeLeft(c.expires_at, now)}
                    </time>
                  </td>
                  <td className="row history-actions">
                    <button type="button" className="btn sm" aria-describedby={`concern-${c.id}`}
                      onClick={() => navigate(caseNextStep(c, retryable[c.id] ? ["retry"] : undefined).to)}>
                      {caseNextStep(c, retryable[c.id] ? ["retry"] : undefined).label}
                    </button>
                    <button type="button" className="btn secondary sm" aria-describedby={`concern-${c.id}`}
                      onClick={() => {
                        setDeleteError(null);
                        setTarget(c);
                      }}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      )}
      {list.next_cursor && (
        <p className="row">
          <button type="button" className="btn secondary" onClick={loadOlder} disabled={loadingOlder} aria-busy={loadingOlder}>
            {loadingOlder ? "Loading older consultations…" : "Show older consultations"}
          </button>
        </p>
      )}
      {target && (
        <ConfirmDialog title="Delete this consultation?" confirmLabel="Delete" destructive pending={deleting.has(target.id)}
          pendingLabel="Deleting…"
          onCancel={() => {
            if (deleting.has(target.id)) return; // #629: locked while its deletion is in flight
            // An error the person saw in this dialog closes with it.
            setDeleteError((e) => (e?.id === target.id ? null : e));
            setTarget(null);
          }} onConfirm={confirmDelete}>
          {/* #458: which consultation: its concern (as in its row) and when it started. */}
          {concerns[target.id] && <p className="user-text"><b>“{shorten(concerns[target.id])}”</b></p>}
          <p className="small">
            Started {started(target.created_at)} ·{" "}
            {target.state === "limited" && retryable[target.id] ? RETRY_STATE : STATE_LABEL[target.state] ?? target.state}
          </p>
          <p>Its answers, guidance, searches and summaries are removed from this device. This cannot be undone.</p>
          {deleteError?.id === target.id && <ErrorBanner error={deleteError.error} />}
        </ConfirmDialog>
      )}
    </>
  );
}
