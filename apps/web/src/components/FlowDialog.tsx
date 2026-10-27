// #548: a presenter quick flow's progress, in a dialog on the presenter screen (O03) instead of a waiting page in a new
// tab. While the flow runs it names the flow and the device, lists the steps with the current one marked (from the
// prepare job's real `stage`, never a percentage), counts the elapsed seconds and says how long it usually takes here.
// There is no cancel operation, so Close only closes the dialog: the run goes on and its card shows the outcome. Done:
// the outcome and "Open the result", which opens the patient tab inside that click (so no pop-up blocker stops it).
// Failed: the honest reason, "Nothing was substituted.", Try again and Close. Focus stays inside the dialog (Tab wraps),
// Escape closes it, focus goes back to the flow's Run button, and the step and outcome are announced politely.
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { DEVICE } from "./Brand";
import { Icon } from "./Icon";
import { PATIENT_TAB, durationText, type FlowId, type Run, type Stage } from "./presenterRuns";

export type DialogFlow = { id: FlowId; title: string; guidance: boolean };
type Step = { label: string };

/** The steps a flow goes through on the device, in order. The Urgent flow's load runs the warning-sign screen of the
 *  written concern inside one request, so it is one step. */
export function stepsFor(flow: DialogFlow, local: boolean): Step[] {
  if (!flow.guidance)
    return [{ label: local ? "Loading the scenario: the on-device AI checks the written concern for warning signs"
      : "Loading the scenario (scripted urgent outcome, no AI model)" }];
  const what = flow.id === "selfcare" ? "self-care guidance" : "guidance";
  return local
    ? [{ label: "Loading the scenario" }, { label: "The on-device AI is checking for warning signs" },
      { label: `The on-device AI is writing the ${what}` }, { label: `Checking the ${what}` }]
    : [{ label: "Loading the scenario" }, { label: "Checking for warning signs (scripted)" },
      { label: `Writing the scripted ${what} (mock mode, no AI model)` }, { label: `Checking the ${what}` }];
}

const STEP_OF_STAGE: Record<Stage, number> = {
  preparing: 0, queued: 0, screening: 1, writing: 2, rewriting: 2, checking: 3, finishing: 3,
};
const STAGE_NOTE: Partial<Record<Stage, string>> = {
  queued: "waiting for the device's AI to be free",
  rewriting: "a second draft, after the first did not pass a check",
};

/** The step a running flow is on (index into stepsFor) and a note on it, from the run's real state only. */
export function currentStep(flow: DialogFlow, run: Extract<Run, { kind: "running" }>): { index: number; note?: string } {
  if (!flow.guidance || !run.caseId || !run.stage) return { index: 0 };
  return { index: STEP_OF_STAGE[run.stage], note: STAGE_NOTE[run.stage] };
}

/** What a finished flow says it has ready. */
export function outcomeTitle(flow: DialogFlow, run: Extract<Run, { kind: "done" }>): string {
  if (!flow.guidance || run.path.endsWith("/urgent")) return "The case was routed to urgent help";
  return flow.id === "selfcare" ? "Self-care guidance is ready" : "Guidance is ready";
}

const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const lowerFirst = (text: string) => text.charAt(0).toLowerCase() + text.slice(1);

/** #550/#548: what a failed run says: the server's plain-words reason when it has one (Job.error_reason), else the
 *  short reason; always that nothing was put in its place. */
export function failureText(run: Extract<Run, { kind: "failed" }>): string {
  if (run.explain) return /Nothing was (published|substituted)\.$/.test(run.explain) ? run.explain
    : `${run.explain} Nothing was substituted.`;
  return `${capitalized(run.reason)}. Nothing was substituted.`;
}

export function FlowDialog({ flow, run, local, typical, now, onClose, onRetry, onOpen, retryBlocked = null }: {
  flow: DialogFlow;
  run: Run;
  local: boolean;
  typical?: string;
  now: number;
  onClose: () => void;
  onRetry: () => void;
  /** #568: why Try again cannot run now (the device is not ready, a reset blocks it), else null. */
  retryBlocked?: string | null;
  /** Opens the result in the patient tab; called inside the click. False when the browser blocked the tab. */
  onOpen: () => boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [blocked, setBlocked] = useState(false);
  const close = useRef(onClose);
  close.current = onClose;
  const steps = stepsFor(flow, run.kind === "running" ? run.local : local);
  const step = run.kind === "running" ? currentStep(flow, run) : null;
  const secs = run.kind === "running" ? Math.max(0, Math.floor((now - run.since) / 1000)) : 0;

  // Focus moves into the dialog when it opens and to the outcome's main action when the run ends.
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const target = run.kind === "done" ? node.querySelector<HTMLElement>("[data-primary]")
      : run.kind === "failed" ? node.querySelector<HTMLElement>("[data-primary]")
        : node.querySelector<HTMLElement>("h2");
    target?.focus();
  }, [run.kind]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close.current();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const trap = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab" || !ref.current) return;
    const items = Array.from(ref.current.querySelectorAll<HTMLElement>("button:not([disabled]), [href]"));
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || !ref.current.contains(active) || active?.tagName === "H2")) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const open = () => {
    if (!onOpen()) setBlocked(true);
  };

  // What the screen reader hears: the step when it changes, then the outcome (never the seconds, which change often).
  const spoken = run.kind === "running" && step
    ? `Step ${step.index + 1} of ${steps.length}: ${steps[step.index].label}${step.note ? `, ${step.note}` : ""}.`
    : run.kind === "done" ? `${outcomeTitle(flow, run)}.`
      : run.kind === "failed" ? `Not shown: ${failureText(run)}` : "";

  return (
    <div className="modalshade">
      <div className={`modal flow-dialog ${run.kind}`} role="dialog" aria-modal="true" ref={ref} onKeyDown={trap}
        aria-labelledby="flow-dialog-title" aria-describedby="flow-dialog-device" data-testid="flow-dialog">
        <p className="eyebrow">Demo · synthetic patient</p>
        <h2 id="flow-dialog-title" tabIndex={-1}>{flow.title}</h2>
        <p id="flow-dialog-device" className="small muted">
          {local ? `Running on the ${DEVICE}` : `On the ${DEVICE} · mock mode: scripted outcome, no AI model`}
        </p>
        <p className="sr-only" role="status" aria-live="polite" data-testid="flow-dialog-live">{spoken}</p>

        {run.kind === "running" && step && (
          <>
            <ol className="flow-steps" aria-label="Steps">
              {steps.map((s, i) => {
                const state = i < step.index ? "done" : i === step.index ? "current" : "next";
                return (
                  <li key={s.label} className={`flow-step ${state}`} aria-current={state === "current" ? "step" : undefined}>
                    <span className="flow-step-mark" aria-hidden="true">
                      {state === "done" ? <Icon name="check" size={16} />
                        : state === "current" ? <span className="spinner sm" data-testid="flow-dialog-spinner" /> : null}
                    </span>
                    <span>
                      {s.label}
                      {state === "current" && step.note && <span className="flow-step-note"> ({step.note})</span>}
                      <span className="sr-only">{state === "done" ? " (done)" : state === "current" ? " (now)" : " (next)"}</span>
                    </span>
                  </li>
                );
              })}
            </ol>
            <p className="flow-dialog-time small">
              <span aria-hidden="true" data-testid="flow-dialog-elapsed">{secs} s elapsed</span>
              {typical && <span className="muted">{typical}.</span>}
            </p>
            <p className="small muted">There is no way to stop a run on the device. Closing this keeps it running; its
              card shows the outcome.</p>
            <div className="actions">
              <button type="button" className="btn secondary" onClick={onClose}>Close</button>
            </div>
          </>
        )}

        {run.kind === "done" && (
          <>
            <div className="flow-outcome ready">
              <Icon name="check" size={20} />
              <div>
                <p className="flow-outcome-title">{outcomeTitle(flow, run)}</p>
                <p className="small">{capitalized(run.detail)}, {durationText(run.ms)}.</p>
              </div>
            </div>
            {blocked && (
              <p className="small" role="alert">
                The browser blocked the patient tab.{" "}
                <a href={run.path} target={PATIENT_TAB}>Open the result in the patient tab</a>
              </p>
            )}
            <div className="actions">
              <button type="button" className="btn secondary" onClick={onClose}>Close</button>
              <button type="button" className="btn" data-primary onClick={open}>Open the result</button>
            </div>
          </>
        )}

        {run.kind === "failed" && (
          <>
            <div className="flow-outcome failed">
              <Icon name="alert" size={20} />
              <div>
                <p className="flow-outcome-title">Not shown</p>
                <p className="small">{failureText(run)}</p>
              </div>
            </div>
            {(run.path || run.reset) && (
              <p className="small">
                {run.path && <a href={run.path} target={PATIENT_TAB}>Open the case at its questions</a>}
                {run.reset && <Link to="/presenter/scenarios/more" onClick={onClose}>Repair the reset in More scenarios</Link>}
              </p>
            )}
            {retryBlocked && <p className="small muted" id="flow-retry-why">Try again {lowerFirst(retryBlocked)}.</p>}
            <div className="actions">
              <button type="button" className="btn secondary" data-primary={retryBlocked ? true : undefined} onClick={onClose}>Close</button>
              <button type="button" className="btn" data-primary={retryBlocked ? undefined : true} onClick={onRetry}
                disabled={retryBlocked != null} aria-describedby={retryBlocked ? "flow-retry-why" : undefined}>Try again</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
