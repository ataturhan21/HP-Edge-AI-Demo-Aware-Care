// O03 Demo scenarios (M12; R37, R39, R40; ADR-005 option A). Presenter-only. A loaded scenario hands this browser a
// synthetic patient session for the patient site (separate cookie, so this presenter session stays). Reset runs as a
// job owned by the presenter. A failed or pending reset blocks a new demo (the O03 required exception) until a reset
// succeeds.
// ADR-016 (#113): in local mode a scenario only starts its synthetic case; the questions, the red-flag screen and the
// guidance then run live on the local AI. A scenario whose point is a scripted outcome stays mock-only.
// #315: loading opens (or reuses) one named patient tab at the case's screen; an "Open on patient site" link is always
// offered too.
// #358 (ADR-016 amendment 2, CHG-DEV-API-006): /presenter/scenarios shows only three one-click flows and one line of
// device status. One click opens the patient tab (inside the click, so no pop-up blocker stops it), then the server
// runs that one flow live with every input ready: the synthetic case, consent, the checklist and the synthetic answers
// (loadScenario reset=false, prepare=result, or urgency_input=written for the warning sign); the card shows progress
// with the device name and the elapsed time, then the patient tab moves to the finished screen. Nothing is prepared
// ahead and nothing is substituted on failure. The full journeys and the end-of-day reset are the secondary view
// /presenter/scenarios/more (same screen O03, no new screen ID). The page follows each run through the presenter's own
// load response and prepare job only, never the patient's content.
// QA 2026-10-22 (CHG-DEV-API-007): the runs live outside this page (components/presenterRuns.ts), so leaving or
// reloading it never strands the patient tab (#423); whether a demo is blocked by a reset and which demo cases the
// patient tab can still open come from the server (getRuntime `demo`) on every load, refresh and focus (#422, #425,
// #426); a flow and a full journey never run at once (#424); an ended presenter session shows the gate (#460).
// #548: a quick flow opens no tab while it runs: its progress shows in a dialog on this page (components/FlowDialog.tsx),
// step by step from the server's real job state, and the patient tab opens on the result from the dialog's "Open the
// result" click. Close keeps the run going (there is no cancel operation); the card shows it and can show the dialog
// again.
import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type MouseEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { ApiError, api, pollJob, type S } from "../api/client";
import { PresenterState, usePresenter } from "../components/PresenterGate";
import { DEVICE } from "../components/Brand";
import { Icon, type IconName } from "../components/Icon";
import { ErrorBanner, PageHead, StatusBanner, useFocusReturn } from "../components/ui";
import { typicalWait } from "../components/typicalWait";
import { FlowDialog, currentStep, failureText, stepsFor } from "../components/FlowDialog";
import { useAppState } from "../state/AppState";
import {
  FLOW_IDS, PATIENT_TAB, START_PATH, anyRunning, clearRuns, durationText, forgetPatientTabs, getRuns, heldPatientTabs, markShown,
  noteReset, openResult, patientTabHandle, setSessionEndedHandler, startFlow, stillOpen, subscribeRuns, type FlowId,
} from "../components/presenterRuns";

/** #358: the secondary presenter view with the full journeys and the end-of-day reset. */
export const MORE_PATH = "/presenter/scenarios/more";

// The six existing fixture IDs (fixtures/scenarios.json), in fixture order. ADR-006 (proposed) may set a story
// order for the final rehearsal; it does not change the IDs.
const SCENARIOS: [string, string, string][] = [
  ["routine", "Find the right clinician", "Full journey"],
  ["selfcare", "Explore self-care guidance", "Shorter intake"],
  ["urgent", "Urgent interruption", "Safety branch"],
  ["unsupported", "Outside the demo scope", "Scope branch"],
  ["nomatch", "No matching doctors", "Recovery path"],
  ["failure", "Guidance unavailable", "Retry path"],
];

// #234: what the audience will see, verbatim from fixtures/scenarios.json (`desc`; tests/ui/intuitive2.spec.ts fails on
// any drift).
export const SCENARIO_DESC: Record<string, string> = {
  "routine": "Jordan explores recurring headaches and a suitable primary care visit.",
  "selfcare": "A fictional mild concern demonstrates a shorter path with escalation advice.",
  "urgent": "A preset urgent answer interrupts questions and removes routine recommendations.",
  "unsupported": "See how the experience explains a concern it cannot assess.",
  "nomatch": "Required insurance excludes every provider. Change filters explicitly.",
  "failure": "Simulate a generation failure, retain answers and recover with Retry.",
};

// #248: each scenario's tag coloured by kind (the words stay).
const SCENARIO_ACCENT: Record<string, string> = {
  routine: "acc-blue", selfcare: "acc-teal", urgent: "acc-red", unsupported: "acc-amber", nomatch: "acc-violet", failure: "acc-rose",
};

// Local mode: what each scenario does with the live AI, and why one is not offered.
const LOCAL: Record<string, { tag: string; unavailable?: string }> = {
  routine: { tag: "Live AI · full journey" },
  selfcare: { tag: "Live AI · mild concern" },
  urgent: { tag: "Safety branch · stops before the AI" },
  unsupported: { tag: "Scope branch · stops before the AI" },
  nomatch: { tag: "Live AI · recovery path" },
  failure: {
    tag: "Mock mode only",
    unavailable: "A forced failure would fake the local AI, so this scenario runs in mock mode only.",
  },
};

// #358: the three one-click flows (their requests: components/presenterRuns.ts). `live`/`mock` are the one line under
// the title, true to the mode.
type Flow = {
  id: FlowId;
  title: string;
  accent: string;
  icon: IconName;
  live: string;
  mock: string;
  guidance: boolean; // #529: the flow waits for a guidance job, so its usual time is known (typicalWait)
};
const FLOWS: Flow[] = [
  { id: "guidance", title: "Guidance from the local AI", accent: "acc-blue", icon: "chat",
    live: "A routine headache case, answered with synthetic answers: the AI writes the guidance.",
    mock: "A routine headache case, answered with synthetic answers: the scripted guidance (mock mode, no AI).",
    guidance: true },
  { id: "selfcare", title: "Self-care guidance", accent: "acc-teal", icon: "pulse",
    live: "A mild, improving complaint: the AI writes self-care guidance and when to get help.",
    mock: "A mild, improving complaint: the scripted self-care guidance (mock mode, no AI).",
    guidance: true },
  { id: "urgent", title: "Urgent warning sign", accent: "acc-red", icon: "urgent",
    live: "An emergency written in the concern, no box ticked: the AI's warning-sign screen sends it to urgent help.",
    mock: "An emergency in the concern: the scripted urgent-help screen (mock mode, no AI screen).",
    guidance: false },
];
const STATUS_REFRESH_MS = 15_000;

type ResetState = { kind: "idle" } | { kind: "running" } | { kind: "succeeded" } | { kind: "failed" };
const READINESS: Record<string, string> = { ready: "Ready", degraded: "Degraded", unavailable: "Unavailable" };

// Full journeys that stop before the AI (the safety and scope branches) stay available when the device is not ready.
const NO_AI_JOURNEYS = new Set(["urgent", "unsupported"]);

const seconds = (since: number, now = Date.now()) => Math.max(0, Math.round((now - since) / 1000));

/** #460: the presenter session ended (or this is not a presenter session): the gate offers a new one. */
const sessionEnded = (err: unknown) =>
  err instanceof ApiError && (err.status === 401 || (err.status === 403 && err.code === "PRESENTER_REQUIRED"));

export default function O03() {
  const more = useLocation().pathname.replace(/\/+$/, "") === MORE_PATH;
  // Authorization is checked with the runtime endpoint before any control is offered.
  const load = useCallback(() => api.getRuntime(), []);
  const { data, error, reload } = usePresenter(load);
  const [live, setLive] = useState<S["RuntimeSnapshot"] | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [reset, setReset] = useState<ResetState>({ kind: "idle" });
  const [busy, setBusy] = useState<string | null>(null);
  useFocusReturn(busy !== null); // #402: Load scenario and Reset demo are disabled while they run; focus comes back
  const [loaded, setLoaded] = useState<{ id: string; title: string; result: S["ScenarioLoaded"]; opened: boolean } | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const [popupBlocked, setPopupBlocked] = useState<string | null>(null);
  const runs = useSyncExternalStore(subscribeRuns, getRuns);
  // #548: the flow whose progress dialog is open, and each flow's Run button (focus goes back there on close).
  const [dialog, setDialog] = useState<FlowId | null>(null);
  const runButtons = useRef<Partial<Record<FlowId, HTMLButtonElement | null>>>({});
  const { guidanceTypicalMs } = useAppState();
  const [now, setNow] = useState(() => Date.now());
  // #426: when (this browser's clock) the snapshot in use was asked for; the first one at the latest when the page
  // mounted. A run that finished after it is not judged by it.
  const mountedAt = useRef(Date.now());
  const [askedAt, setAskedAt] = useState(mountedAt.current);
  const runtime = live ?? data;
  const local = runtime?.mode === "local";
  const aiReady = runtime?.readiness === "ready" && !statusFailed;
  const readiness = statusFailed ? "Not reachable" : READINESS[runtime?.readiness ?? "unavailable"];
  const notReady = statusFailed ? "the device did not answer the last status check" : `the device is ${readiness}`;
  // #425: the server says whether the last reset blocks a new demo, on every presenter view and after a reload.
  const serverReset = runtime?.demo.reset_status ?? "none";
  const blocked = busy !== "reset" && (serverReset === "failed" || serverReset === "running");

  // #460: a run that finds the presenter session ended shows the gate at once.
  useEffect(() => {
    setSessionEndedHandler(reload);
    return () => setSessionEndedHandler(null);
  }, [reload]);

  const running = anyRunning(runs);
  const closeDialog = useCallback(() => {
    setDialog((open) => {
      if (open) window.setTimeout(() => runButtons.current[open]?.focus(), 0);
      return null;
    });
  }, []);
  // A run that ends without an outcome (a reset, an ended presenter session) closes its dialog.
  const dialogRun = dialog ? runs[dialog] : null;
  useEffect(() => {
    if (dialogRun?.kind === "idle") closeDialog();
  }, [dialogRun?.kind, closeDialog]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  /** A fresh runtime snapshot: device status, the reset that blocks, and the demo cases still open (#426). */
  const applySnapshot = useCallback((next: S["RuntimeSnapshot"], asked: number) => {
    setLive(next);
    setAskedAt(asked);
    setStatusFailed(false);
    if (noteReset(next.demo)) {
      // Another presenter tab or browser reset the demo: every case is gone, so this page's patient tab leaves it.
      for (const tab of heldPatientTabs()) tab.location.href = START_PATH;
      forgetPatientTabs();
      clearRuns();
    }
  }, []);

  const refresh = useCallback(() => {
    const asked = Date.now();
    return api.getRuntime().then((next) => applySnapshot(next, asked), (err) => {
      if (sessionEnded(err)) reload();
      else setStatusFailed(true);
    });
  }, [applySnapshot, reload]);

  // #328: the device status, from the runtime snapshot this page already reads, refreshed every 15 s; #426: and when
  // the presenter comes back to this tab (a reset in another tab shows at once).
  useEffect(() => {
    if (!data) return;
    applySnapshot(data, mountedAt.current);
    const timer = window.setInterval(() => void refresh(), STATUS_REFRESH_MS);
    const onFocus = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [data, applySnapshot, refresh]);

  // #426: a run that just finished is checked against a fresh snapshot (so a later Show again is judged correctly).
  const finished = FLOW_IDS.map((id) => (runs[id].kind === "done" ? id : "")).join("");
  useEffect(() => {
    if (data && finished) void refresh();
  }, [finished]); // only when a run finishes, not on every snapshot

  /** A load refused because of the last reset: show the server's state (banner, disabled controls). */
  const blockFor = (err: unknown) => {
    if (err instanceof ApiError && (err.code === "RESET_FAILED" || err.code === "RESET_PENDING")) {
      const status = err.code === "RESET_FAILED" ? "failed" : "running";
      setLive((l) => (l ? { ...l, demo: { ...l.demo, reset_status: status } } : l));
      void refresh();
      return true;
    }
    return false;
  };

  /** #358: one click runs one flow live. #548: no tab opens; the progress dialog follows the run on this page. */
  const runFlow = (flow: Flow) => {
    if (running || busy !== null || !aiReady || blocked) return;
    setReset({ kind: "idle" });
    startFlow(flow.id, local);
    setDialog(flow.id);
  };

  /** Reset every demo of this browser's presenter tools (#396). `handle` is the patient tab, taken inside the click
   *  before any await (#329). */
  const runReset = async (handle: { tab: Window | null; fresh: boolean }) => {
    setBusy("reset");
    setFailure(null);
    setLoaded(null);
    setPopupBlocked(null);
    setReset({ kind: "running" });
    let done = false;
    try {
      const accepted = await api.resetDemo(crypto.randomUUID());
      const job = await pollJob(accepted.deletion_job_id, new AbortController().signal, { quiet: true, role: "presenter" });
      setReset({ kind: job.status === "succeeded" ? "succeeded" : "failed" });
      done = true;
    } catch (err) {
      if (sessionEnded(err)) {
        // #422: no reset ran; the presenter session ended. The gate offers a new one; nothing is claimed.
        setReset({ kind: "idle" });
        if (handle.tab && handle.fresh) handle.tab.close();
        reload();
        return;
      }
      setReset({ kind: "failed" });
      done = true;
    } finally {
      setBusy(null);
    }
    if (done) {
      // #329: the patient tab leaves the previous audience's case for the start page (a fresh blank tab just closes).
      const { tab, fresh } = handle;
      for (const other of heldPatientTabs()) if (other !== tab) other.location.href = START_PATH;
      if (tab && fresh) tab.close();
      else if (tab) tab.location.href = START_PATH;
      if (tab) window.focus();
      forgetPatientTabs();
      clearRuns();
      try {
        const asked = Date.now();
        const next = await api.getRuntime();
        noteReset(next.demo); // this page's own reset: nothing more to do for it
        applySnapshot(next, asked);
      } catch (err) {
        if (sessionEnded(err)) reload();
        else setStatusFailed(true);
      }
    }
  };

  const loadScenario = async (id: string, title: string) => {
    // #315: the named patient tab is opened inside the click (popup blockers allow that), then pointed at the case.
    const { tab, fresh } = patientTabHandle();
    setBusy(id);
    setFailure(null);
    setLoaded(null);
    setPopupBlocked(null);
    setReset({ kind: "idle" });
    try {
      // #316: a full journey joins the live demo (reset=false), so earlier runs stay; Reset removes all.
      const result = await api.loadScenario(id, crypto.randomUUID(), { reset: false, prepare: "start" });
      setLoaded({ id, title, result, opened: tab !== null });
      if (tab) {
        tab.location.href = result.next_path;
        tab.focus();
      } else setPopupBlocked(result.next_path);
      void refresh();
    } catch (err) {
      if (tab && fresh) tab.close();
      if (sessionEnded(err)) reload(); // #460: the gate, not "Your session has ended" with nothing to start
      else if (!blockFor(err)) setFailure(err);
    } finally {
      setBusy(null);
    }
  };

  /** #426: Show again checks with the server first; a demo that ended or was reset says so here, not on the patient
   *  site's consent page in front of the audience. The patient tab is taken inside the click. */
  const showAgain = (event: MouseEvent<HTMLAnchorElement>, caseId: string, url: string, flow?: FlowId) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const { tab, fresh } = patientTabHandle();
    const asked = Date.now();
    api.getRuntime().then((next) => {
      applySnapshot(next, asked);
      if (next.demo.live_case_ids.includes(caseId)) {
        if (tab) {
          tab.location.href = url;
          tab.focus();
        } else window.open(url, PATIENT_TAB);
        if (flow) markShown(flow);
      } else if (tab && fresh) {
        tab.close();
        window.focus();
      }
    }, (err) => {
      if (tab && fresh) tab.close();
      if (sessionEnded(err)) reload();
      else setStatusFailed(true);
    });
  };

  const deviceLine = runtime && (
    <p className={`o03-line small ${aiReady ? "ready" : "failed"}`}>
      <Icon name={aiReady ? "check" : "alert"} size={16} />
      <span>
        <b>{DEVICE}</b>
        {" · "}
        {local
          ? aiReady ? "AI ready" : `AI ${readiness.toLowerCase()}`
          : aiReady ? "mock mode: scripted outcomes, no AI model" : `service ${readiness.toLowerCase()} (mock mode)`}
        {!aiReady && <span className="muted"> · the flows wait until it is ready</span>}
      </span>
    </p>
  );

  // #425: shown on both views from the server's state, so a reload or another tab never looks ready by mistake.
  const resetBanner = blocked && (serverReset === "failed" ? (
    <StatusBanner tone="error" title="New demo blocked: the last reset did not complete">
      <p>
        No scenario can be loaded and no flow can run until a reset succeeds. Earlier demo data stays inaccessible
        meanwhile.
      </p>
      <button type="button" className="btn" onClick={() => runReset(patientTabHandle())} disabled={busy !== null}>
        Retry reset
      </button>
    </StatusBanner>
  ) : (
    <StatusBanner tone="info" title="A reset is running">
      <p>New demos wait until it completes.</p>
    </StatusBanner>
  ));

  /** #529: how long a flow usually takes here. #548: the warning-sign screen has no measured time; it is one short
   *  model call (about half a second on the Nano), so the dialog says so without a figure. */
  const typicalFor = (flow: Flow, isLocal: boolean) =>
    flow.guidance ? typicalWait(guidanceTypicalMs, isLocal ? "local" : "mock", DEVICE).text
      : isLocal ? "Usually a second or two on this device" : "Usually a moment in this scripted demo";

  const flowStatus = (flow: Flow) => {
    const run = runs[flow.id];
    if (run.kind === "running") {
      // #548: the step the dialog shows, from the server's real job state.
      const doing = run.local ? `${stepsFor(flow, true)[currentStep(flow, run).index].label} on the ${DEVICE}…`
        : `Running the scripted outcome on the ${DEVICE}…`;
      return { tone: "busy", icon: "clock" as IconName, text: doing, secs: seconds(run.since, now),
        typical: typicalFor(flow, run.local) };
    }
    if (run.kind === "done" && !stillOpen(run, runtime?.demo, askedAt))
      return { tone: "none", icon: "info" as IconName, text: "Expired: run it again",
        detail: "the demo patient's session ended or the demo was reset, so the patient tab cannot show it any more" };
    if (run.kind === "done")
      return { tone: "ready", icon: "check" as IconName,
        text: run.shown ? "Shown in the patient tab" : "Ready: not shown yet",
        detail: `${run.detail}, ${durationText(run.ms)}` };
    if (run.kind === "failed")
      return { tone: "failed", icon: "alert" as IconName, text: "Not shown",
        // #569: the server's plain-words reason when it has one, as the dialog says it (Job.error_reason)
        detail: run.explain ? failureText(run) : `${run.reason}. Nothing was substituted.` };
    if (blocked) return { tone: "none", icon: "info" as IconName, text: "Waits until a reset succeeds" };
    if (!aiReady) return { tone: "none", icon: "info" as IconName, text: `Waits until the device is ready (${notReady})` };
    return null;
  };

  const flowsView = runtime && (
    <>
      {deviceLine}
      {resetBanner}
      <div className="flow-grid">
        {FLOWS.map((flow) => {
          const run = runs[flow.id];
          const status = flowStatus(flow);
          const off = running || busy !== null || !aiReady || blocked;
          const open = run.kind === "done" && stillOpen(run, runtime?.demo, askedAt);
          return (
            <section className={`flow-card ${flow.accent}`} key={flow.id} aria-labelledby={`flow-${flow.id}`}>
              <span className="flow-icon" aria-hidden="true"><Icon name={flow.icon} size={24} /></span>
              <h2 id={`flow-${flow.id}`}>{flow.title}</h2>
              <p className="flow-line">{local ? flow.live : flow.mock}</p>
              {/* aria-disabled (not disabled) while a flow runs, so keyboard focus stays on the button. #443: the
                  accessible name starts with the visible label in every state (WCAG 2.5.3). */}
              <button type="button" className="btn flow-run" onClick={() => runFlow(flow)}
                ref={(node) => { runButtons.current[flow.id] = node; }}
                aria-disabled={off || undefined} aria-busy={run.kind === "running" || undefined}
                aria-describedby={`flow-${flow.id}-status`}
                aria-label={run.kind === "running" ? `Running… ${flow.title}` : `Run on ${DEVICE}: ${flow.title}`}>
                {run.kind === "running" ? "Running…" : `Run on ${DEVICE}`}
              </button>
              <div id={`flow-${flow.id}-status`} className={`flow-status ${status?.tone ?? "none"}`} aria-live="polite">
                {status && (
                  <p>
                    {/* #529: a running flow shows a spinner (static under reduced motion), not a still clock. */}
                    {status.tone === "busy"
                      ? <span className="spinner sm" aria-hidden="true" data-testid="flow-spinner" />
                      : <Icon name={status.icon} size={16} />}
                    <span>
                      <b>{status.text}</b>
                      {"secs" in status && <span className="flow-secs" aria-hidden="true"> {status.secs} s</span>}
                      {"detail" in status && status.detail && <span className="flow-detail"> ({status.detail})</span>}
                      {"typical" in status && status.typical && <span className="flow-typical">{status.typical}.</span>}
                    </span>
                  </p>
                )}
                {run.kind === "running" && dialog !== flow.id && (
                  <button type="button" className="btn secondary sm flow-progress" onClick={() => setDialog(flow.id)}>
                    Show progress
                  </button>
                )}
                {open && (
                  <a href={run.path} target={PATIENT_TAB}
                    onClick={(e) => showAgain(e, run.caseId, run.path, flow.id)}>
                    {run.shown ? "Show again" : "Open in the patient tab"}
                  </a>
                )}
                {run.kind === "failed" && run.path && (
                  <a href={run.path} target={PATIENT_TAB}>Open the case at its questions</a>
                )}
                {run.kind === "failed" && run.reset && <Link to={MORE_PATH}>Repair the reset in More scenarios</Link>}
              </div>
            </section>
          );
        })}
      </div>
      {dialog && runs[dialog].kind !== "idle" && (() => {
        const flow = FLOWS.find((f) => f.id === dialog)!;
        return (
          <FlowDialog flow={flow} run={runs[dialog]} local={local} typical={typicalFor(flow, local)} now={now}
            onClose={closeDialog} onRetry={() => runFlow(flow)}
            retryBlocked={blocked ? "Waits until a reset succeeds" : !aiReady ? `Waits until the device is ready (${notReady})`
              : busy !== null ? "Waits until the current action ends" : null}
            onOpen={() => {
              const opened = openResult(flow.id);
              if (opened) closeDialog();
              return opened;
            }} />
        );
      })()}
    </>
  );

  const moreView = runtime && (
    <>
      {deviceLine}
      {resetBanner}
      {!blocked && reset.kind === "succeeded" && (
        <StatusBanner tone="success" title="Reset completed">
          <p>Every earlier demo session and synthetic case from this browser's presenter tools was removed.</p>
        </StatusBanner>
      )}
      {popupBlocked && (
        <StatusBanner tone="warn" title="The browser did not open the patient tab">
          <p>
            <a href={popupBlocked} target={PATIENT_TAB}>
              Open on patient site
            </a>{" "}
            (allow pop-ups for this site to open it directly next time).
          </p>
        </StatusBanner>
      )}
      {failure !== null && <ErrorBanner error={failure} />}

      <h2>Full journeys</h2>
      <p>
        {local
          ? `The whole consultation runs as you present: the questions, the red-flag screen and the guidance run on the local AI of the ${DEVICE} as you go.`
          : "The whole consultation runs as you present, with the scripted synthetic outcomes of mock mode (no AI model)."}
      </p>
      {!aiReady && (
        <p className="small quick-reason">
          <Icon name="alert" size={16} />
          <span>Live journeys wait until the device is Ready ({notReady}); Urgent interruption and Outside the demo scope stop before the AI and stay available.</span>
        </p>
      )}
      {running && (
        <p className="small quick-reason">
          <Icon name="clock" size={16} />
          <span>
            A quick flow is running on <Link to="/presenter/scenarios">Scenarios</Link>; full journeys wait until it
            has shown its result, so the patient tab keeps one demo at a time.
          </span>
        </p>
      )}
      {loaded && (
        <StatusBanner tone="success" title={`Loaded: ${loaded.title}`}>
          {/* #430: says only what happened: opened, or ready behind the link above when the browser blocked the tab;
              and "answers live" only for a journey that reaches the AI. */}
          <p>
            Synthetic scenario <b>{loaded.result.scenario_id}</b>{" "}
            {loaded.opened ? "opened in the patient tab" : "is ready on the patient site (use the link above)"}; this
            presenter session stays open.
            {loaded.opened && (
              <>
                {" "}
                <a href={loaded.result.next_path} target={PATIENT_TAB}>
                  Open on patient site
                </a>
              </>
            )}
            {local && (NO_AI_JOURNEYS.has(loaded.id)
              ? " This branch stops before the AI."
              : ` The local AI on the ${DEVICE} answers live.`)}
          </p>
        </StatusBanner>
      )}
      <div className="grid3">
        {SCENARIOS.map(([id, title, mockTag]) => {
          const tag = local ? LOCAL[id] : undefined;
          return (
            <section className={`card scenario-card ${SCENARIO_ACCENT[id] ?? "acc-slate"}`} key={id}>
              <span className="badge">{tag ? tag.tag : mockTag}</span>
              <h3>{title}</h3>
              <p>{SCENARIO_DESC[id]}</p>
              <p className="small muted">Scenario {id} · synthetic</p>
              {tag?.unavailable && <p className="small">{tag.unavailable}</p>}
              <button type="button" className="btn secondary"
                disabled={blocked || busy !== null || running || Boolean(tag?.unavailable) || (!aiReady && !NO_AI_JOURNEYS.has(id))}
                onClick={() => loadScenario(id, title)} aria-busy={busy === id || undefined}
                aria-label={busy === id ? `Loading scenario: ${title}…` : `Load scenario: ${title}`}>
                {busy === id ? "Loading…" : "Load scenario"}
              </button>
            </section>
          );
        })}
      </div>
      <section className="card">
        <h2>Reset</h2>
        <p>
          Between audiences or at the end of the day: removes every demo session and synthetic case this browser's
          presenter tools created, including the quick flows' cases and those of earlier presenter sessions, and
          returns the patient tab to the start page. Patient guest sessions are not touched. The presenter session
          stays.
        </p>
        <button type="button" className="btn danger" onClick={() => runReset(patientTabHandle())} disabled={busy !== null}>
          {busy === "reset" ? "Resetting…" : "Reset demo"}
        </button>
      </section>
    </>
  );

  return (
    <>
      {more ? (
        <PageHead eyebrow="Presenter" title="More scenarios">
          <p>Synthetic fixtures. Full journeys open the patient tab at the first question; Reset clears the demo.</p>
        </PageHead>
      ) : (
        <PageHead eyebrow="Presenter" title="Demo scenarios" />
      )}
      <PresenterState error={error} loading={!data} reload={reload}>
        {data && (more ? moreView : flowsView)}
      </PresenterState>
    </>
  );
}
