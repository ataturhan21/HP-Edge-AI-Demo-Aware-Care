// A07 Your guidance (M08; R24-R27). Polls the real job; distinguishes failure, limits and staleness.
// Shows only validated, published fields; mock results are labeled as scripted synthetic outcomes and local results
// carry the AI-generated notice. A red flag found in the person's own words (general-adult-3) routes to A15 with its
// reviewed level.
// #415: while guidance is being prepared, or after it failed, the case cannot be reviewed (A06 would only say "This step
// is complete" and send the person back here), so these views offer no "Back to review"; Retry opens the review again.
// #453: the wait shows the time since the job started (its created_at, or the case's last change into generating), so a
// reload or a return to the page continues the count instead of starting at 0 s.
import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { abortableDelay, api, ApiError, currentSessionExpiry, pollDelay, pollJob, type S } from "../api/client";
import { Button, CaseUnavailable, EmptyState, ErrorBanner, LoadingState, PageHead, StatusBanner, SyntheticBadge } from "../components/ui";
import { ResetActions } from "../components/ResetActions";
import { useJourneyCase } from "../components/JourneySteps";
import { screenForState } from "../components/useCase";
import { useAppState } from "../state/AppState";
import { DEVICE, DEVICE_PLACE, RUNTIME } from "../components/Brand";
import { Icon, type IconName } from "../components/Icon";
import { typicalWait } from "../components/typicalWait";

// #356: A12 shows the level in these same words.
export const URGENCY: Record<S["UrgencyDecision"]["level"], string> = {
  emergency: "Emergency care",
  urgent_clinician: "See a clinician urgently",
  routine_clinician: "Routine clinician visit",
  self_care_candidate: "Self-care with monitoring (illustrative)",
  undetermined: "Not determined",
};

// Job outcomes from the red-flag screen (M05 via M08): the level of the red flag the person described.
const DESCRIBED: Record<string, string> = {
  RED_FLAG_DESCRIBED_EMERGENCY: "emergency",
  RED_FLAG_DESCRIBED_URGENT_CLINICIAN: "urgent_clinician",
};

// The level is shown as text with an icon; colour only reinforces it (#98).
export const LEVEL_ICON: Record<S["UrgencyDecision"]["level"], IconName> = {
  emergency: "urgent",
  urgent_clinician: "alert",
  routine_clinician: "user",
  self_care_candidate: "check",
  undetermined: "info",
};

type View =
  | { kind: "loading" }
  | { kind: "generating"; startedAt: number | null }
  | { kind: "complete"; guidance: S["Guidance"] }
  | { kind: "failed"; retry: boolean; revision: number }
  | { kind: "stale" }
  | { kind: "error"; error: unknown };

export default function A07() {
  const { caseId = "" } = useParams();
  const navigate = useNavigate();
  const jobId = (useLocation().state as { jobId?: string } | null)?.jobId;
  const [view, setView] = useState<View>({ kind: "loading" });
  // The published result proves which runtime produced it (#98: the local-AI signature only says what is observed).
  const { noteRuntimeMode } = useAppState();
  useEffect(() => {
    if (view.kind === "complete") noteRuntimeMode(view.guidance.model_manifest_id.startsWith("mock-") ? "mock" : "local");
  }, [view, noteRuntimeMode]);
  // #343: shown guidance opens the Guidance, Find care and Summary step links; a failed or stale run closes them.
  useJourneyCase(caseId, view.kind === "complete" ? true : view.kind === "failed" || view.kind === "stale" ? false : undefined);
  const [pending, setPending] = useState(false);
  // #277: "Try again" after an error starts a new run (the effect below aborts the previous one).
  const [attempt, setAttempt] = useState(0);

  const resolve = useCallback(
    async (signal: AbortSignal) => {
      // #278: a run that was aborted (the person left this page, or tried again) never changes the view or navigates.
      const live = () => !signal.aborted;
      try {
        let described: string | undefined;
        if (jobId) {
          setView({ kind: "generating", startedAt: null });
          let startedAt: number | null = null;
          const job = await pollJob(jobId, signal, { onRead: (running) => {
            const at = Date.parse(running.created_at);
            if (startedAt === null && Number.isFinite(at) && live()) setView({ kind: "generating", startedAt: (startedAt = at) });
          } });
          if (!live()) return;
          if (job.status === "stale" || job.status === "cancelled") return setView({ kind: "stale" });
          described = DESCRIBED[job.error_code ?? ""];
          if (job.status === "succeeded" && job.result_type === "guidance") {
            // #203: read the case and the result together. The result is shown only if the case is still guided at
            // the revision it was made for; otherwise the case state decides below, as before.
            const [read, guidance] = await Promise.all([api.getCase(caseId), api.getGuidance(caseId).catch(() => null)]);
            if (!live()) return;
            if (read.case.state === "guided" && guidance && guidance.id === read.case.latest_guidance_id)
              return setView({ kind: "complete", guidance });
          }
        }
        const waiting = Date.now();
        for (;;) {
          const read = await api.getCase(caseId);
          if (!live()) return;
          const state = read.case.state;
          if (state === "generating") {
            // The case changed into generating when the job was created (same transaction).
            const at = Date.parse(read.case.updated_at);
            setView({ kind: "generating", startedAt: Number.isFinite(at) ? at : null });
            await abortableDelay(pollDelay(Date.now() - waiting), signal);
            continue;
          }
          if (state === "guided") {
            const guidance = await api.getGuidance(caseId);
            return live() ? setView({ kind: "complete", guidance }) : undefined;
          }
          if (state === "limited")
            return setView({ kind: "failed", retry: read.allowed_actions.includes("retry"), revision: read.case.revision });
          if (state === "urgent")
            return navigate(`/app/cases/${caseId}/urgent`, {
              replace: true,
              state: (described ?? read.case.urgent_level) ? { level: described ?? read.case.urgent_level } : null,
            });
          return navigate(screenForState(caseId, state, read.allowed_actions), { replace: true });
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError" && live()) setView({ kind: "error", error: err });
      }
    },
    [caseId, jobId, navigate],
  );

  useEffect(() => {
    const controller = new AbortController();
    void resolve(controller.signal);
    return () => controller.abort();
  }, [resolve, attempt]);

  async function retry(revision: number) {
    setPending(true);
    try {
      await api.nextQuestion(caseId, revision, crypto.randomUUID());
      navigate(`/app/cases/${caseId}/review`);
    } catch (err) {
      setView({ kind: "error", error: err });
    } finally {
      setPending(false);
    }
  }

  if (view.kind === "loading") return <LoadingState label="Loading guidance" />;
  if (view.kind === "generating")
    return (
      <div className="narrow">
        <PageHead eyebrow="Guidance" title="Preparing your guidance" />
        <LoadingState label="The local service is working on your request. This page updates when the job finishes." />
        <GeneratingProgress startedAt={view.startedAt} />
      </div>
    );
  if (view.kind === "error") {
    if (view.error instanceof ApiError && view.error.status === 404)
      return <CaseUnavailable />;
    return (
      <ErrorBanner error={view.error} onRetry={() => {
        setView({ kind: "loading" });
        setAttempt((n) => n + 1);
      }} />
    );
  }
  if (view.kind === "stale")
    return (
      <EmptyState page title="This result is out of date" action={<Link className="btn" to={`/app/cases/${caseId}/review`}>Review again</Link>}>
        <p>Your case changed while guidance was being prepared, so that result was discarded.</p>
      </EmptyState>
    );
  if (view.kind === "failed")
    return (
      <div className="narrow">
        <PageHead eyebrow="Guidance" title="Guidance is unavailable right now" />
        <StatusBanner tone="error" title="The service could not produce a validated result.">
          <p>This is a service problem, not a finding about your health. Your answers are kept.</p>
        </StatusBanner>
        {view.retry && (
          <div className="actions">
            <p className="small muted" id="retry-hint">Retry shows your answers for review again; then generate guidance.</p>
            <Button type="button" pending={pending} onClick={() => retry(view.revision)} aria-describedby="retry-hint">
              Retry
            </Button>
          </div>
        )}
        <p className="small">If you are worried, contact a clinician. In an emergency call 911.</p>
      </div>
    );

  const g = view.guidance;
  const mock = g.model_manifest_id.startsWith("mock-");
  const limited = g.urgency.reason_codes.includes("LIMITED_INFORMATION");
  return (
    <>
      <PageHead eyebrow="Guidance" title="Your guidance">
        <p className="user-text">{g.case_summary}</p>
      </PageHead>
      {mock && (
        <StatusBanner tone="warn" title="Mock mode: scripted synthetic outcome">
          <p>No model analysed your answers. This result was selected by a demo scenario and is not medical advice.</p>
        </StatusBanner>
      )}
      {!mock && (
        <StatusBanner tone="info" title="AI-generated on this device">
          <p>
            An AI model wrote this guidance from your answers, within limits a clinician reviewed. Like a person, it can
            make mistakes, and it is not a diagnosis. If you are worried, or anything changes or gets worse, contact a
            clinician. In an emergency call 911.
          </p>
          <p className="small">
            Generated on the {DEVICE} through {RUNTIME}. Your answers stayed on {DEVICE_PLACE}.
          </p>
        </StatusBanner>
      )}
      {limited && (
        <StatusBanner tone="warn" title="Limited information">
          <p>
            Some questions were answered “Not sure” or skipped, so this result is less specific and does not offer
            self-care reassurance. You can go back to review and add answers, or discuss the open points with a
            clinician.
          </p>
        </StatusBanner>
      )}
      <section className={`card level-card level-${g.urgency.level}`}>
        <p className="eyebrow">Suggested level of care</p>
        <h2 className="level-badge">
          <Icon name={LEVEL_ICON[g.urgency.level]} size={20} />
          {URGENCY[g.urgency.level]}
        </h2>
        {mock && (
          <p>
            <SyntheticBadge />
          </p>
        )}
        <ul className="action-list">
          {g.actions.map((a) => (
            <li key={a.id}>
              <p>
                <strong>{a.text}</strong>
              </p>
              <p className="small muted">{a.rationale}</p>
            </li>
          ))}
        </ul>
      </section>
      {/* #187: the next steps come right after the result, not after every card (≈2,500 px down on a phone). */}
      <nav className="actions next-steps" aria-label="Next steps">
        <Link className="btn" to={`/app/cases/${caseId}/preferences`}>
          Find appropriate care
        </Link>
        <div className="row">
          <Link className="btn secondary" to={`/app/cases/${caseId}/summary`}>
            Appointment summary
          </Link>
          <Link className="btn secondary" to={`/app/cases/${caseId}/sources`}>
            Sources
          </Link>
        </div>
      </nav>
      <div className="grid2 result-grid">
        <section className="card accent-card acc-violet">
          <h2 className="card-title">
            <span className="card-icon" aria-hidden="true"><Icon name="info" size={18} /></span>
            Possible explanations
          </h2>
          {g.possible_explanations.some((p) => p.validation_status === "general_knowledge") && (
            // ADR-015 (#105): the origin is stated where the explanations are read, not only under the limits.
            <p className="small muted" data-testid="explanations-origin">
              {mock
                ? "Scripted illustrative explanation for this synthetic demo, not from an AI model or reviewed sources."
                : "From the AI's general medical knowledge, not checked against reviewed sources. It can be wrong and is not a diagnosis."}
            </p>
          )}
          {g.possible_explanations.length === 0 && (
            // #103 fallback: since ADR-015 every result carries explanations, so this should not occur; if it does,
            // the card says so honestly and never implies there is nothing to explain.
            <p className="muted">No possible explanations are shown for this result. Ask a clinician what could be causing it.</p>
          )}
          {g.possible_explanations.map((p) =>
            p.validation_status === "suppressed" ? (
              <StatusBanner key={p.id} tone="info" title="Not shown without approved sources">
                <p>{p.text}</p>
              </StatusBanner>
            ) : (
              <p key={p.id}>{p.text}</p>
            ),
          )}
        </section>
        <section className="card accent-card acc-teal">
          <h2 className="card-title">
            <span className="card-icon" aria-hidden="true"><Icon name="chat" size={18} /></span>
            Questions to ask a clinician
          </h2>
          <ul className="bullets">
            {g.clinician_questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </section>
        <section className="card accent-card acc-amber">
          <h2 className="card-title">
            <span className="card-icon" aria-hidden="true"><Icon name="alert" size={18} /></span>
            When to seek help sooner
          </h2>
          <ul className="bullets">
            {g.escalation_advice.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </section>
        <section className="card accent-card acc-slate">
          <h2 className="card-title">
            <span className="card-icon" aria-hidden="true"><Icon name="shield" size={18} /></span>
            Limits of this result
          </h2>
          <ul className="bullets">
            {g.uncertainties.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        </section>
      </div>
      <ResetActions />
    </>
  );
}


// #323: the parts of the result, named as the result page names them (no stages: the job reports none).
const GUIDANCE_PARTS = [
  "Suggested level of care",
  "Possible explanations",
  "Questions to ask a clinician",
  "When to seek help sooner",
  "Limits of this result",
];

/** #186/#323: what is happening while guidance is prepared, and for how long. From 0 s the page says how long it usually
 * takes on this device; a bar fills over that time and then turns indeterminate. Visible every second; announced to
 * screen readers at most every 10 s. The keep-open note appears after 1.5 times the usual time (at least 30 s). */
function GeneratingProgress({ startedAt }: { startedAt: number | null }) {
  const { guidanceTypicalMs, runtimeMode } = useAppState();
  const typical = typicalWait(guidanceTypicalMs, runtimeMode, DEVICE);
  const [mountedAt] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);
  // #453: once the job's start is known, how long it had already run then (on the server's clock, with the offset from
  // the last response) and this page's time at that moment; from there this page's clock moves the count on. Until the
  // start is known, the count runs from when this view appeared.
  const [base, setBase] = useState<{ startedAt: number; elapsedMs: number; at: number } | null>(null);
  useEffect(() => {
    if (startedAt === null) return;
    const at = Date.now();
    const skewMs = currentSessionExpiry()?.skewMs ?? 0;
    setBase({ startedAt, elapsedMs: Math.max(0, at + skewMs - startedAt), at });
  }, [startedAt]);
  const elapsedMs = Math.max(0, base && base.startedAt === startedAt ? base.elapsedMs + (now - base.at) : now - mountedAt);
  const seconds = Math.floor(elapsedMs / 1000);
  const announced = Math.floor(seconds / 10) * 10;
  const longer = elapsedMs >= typical.ms;
  const keepOpenAfter = Math.max(30_000, 1.5 * typical.ms);
  return (
    <div className="generating-progress">
      <p className="generating-typical" data-testid="generating-typical">
        <Icon name="clock" size={18} />
        <span>
          <strong>{typical.text}.</strong>
          {typical.measured && <span className="small muted"> Measured on this device over recent days.</span>}
        </span>
      </p>
      <div className={`generating-bar${longer ? " indeterminate" : ""}`} aria-hidden="true" data-testid="generating-bar">
        <i style={longer ? undefined : { width: `${Math.min(100, (elapsedMs / typical.ms) * 100)}%` }} />
      </div>
      <p className="generating-elapsed" aria-hidden="true">{seconds} s</p>
      {longer && <p className="small">Taking a little longer than usual. It is still working.</p>}
      <p>
        {runtimeMode === "mock"
          ? "The demo scenario prepares a scripted result; no AI model reads your answers."
          : "The AI on this device first checks your words for urgent warning signs, then writes your guidance and checks it before it is shown."}
      </p>
      <div>
        <p className="small muted">Your guidance will include:</p>
        <ul className="bullets small">
          {GUIDANCE_PARTS.map((part) => <li key={part}>{part}</li>)}
        </ul>
      </div>
      {elapsedMs >= keepOpenAfter && (
        <p className="small muted">Please keep this page open. It updates as soon as your guidance is ready.</p>
      )}
      <p className="sr-only" role="status">{announced > 0 ? `Still working, ${announced} seconds so far.` : ""}</p>
    </div>
  );
}
