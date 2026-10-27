// O01 Runtime overview (M12; R03, R37, R38). Observed values only; unmeasured stays "Not measured".
// QA 2026-10-22 (CHG-DEV-API-007): every value says where it comes from and when (#429): the time this page observed
// readiness and the queue, the date the device inventory was recorded, the serving runtime's versions from the model
// manifest with its last passed qualification, and the newest timing sample. Mock mode's timings are labelled
// scripted, with no inference time, as no model runs (#428).
// #548: a second view, Logs (/presenter/runtime?view=logs, components/LogsPanel.tsx): the presenter's debug log, inside
// this page so the app keeps its 25 routes.
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { PresenterState, usePresenter } from "../components/PresenterGate";
import { PageHead, StatusBanner, formatDate, formatDateTime, formatTime } from "../components/ui";
import { useAppState } from "../state/AppState";
import { DEVICE, RUNTIME } from "../components/Brand";
import { Icon } from "../components/Icon";
import { LogsPanel } from "../components/LogsPanel";

const ms = (v: number | null) => (v === null ? "Not measured" : `${Math.round(v)} ms`);

// #259: each timing has a bar proportional to the total, beside its value in words.
function Timing({ label, value, total, tone }: { label: string; value: number | null; total: number | null; tone: string }) {
  const pct = value !== null && total ? Math.min(100, Math.max(2, (value / total) * 100)) : 0;
  return (
    <div className={`datum timing ${tone}`}>
      <span>{label}</span>
      <span className="timing-bar" aria-hidden="true">{value !== null && <i style={{ width: `${pct}%` }} />}</span>
      <b>{ms(value)}</b>
    </div>
  );
}

export default function O01() {
  const { data, error, reload } = usePresenter(api.getRuntime);
  const { noteRuntimeMode } = useAppState();
  const logs = useSearchParams()[0].get("view") === "logs";
  useEffect(() => {
    if (data) noteRuntimeMode(data.mode);
  }, [data, noteRuntimeMode]);
  return (
    <>
      <PageHead eyebrow="Presenter" title="Runtime overview" />
      <PresenterState error={error} loading={!data} reload={reload}>
        {data && (
          <nav className="viewswitch" aria-label="Runtime views">
            <Link to="/presenter/runtime" aria-current={logs ? undefined : "page"}>
              <Icon name="chip" size={16} />Overview
            </Link>
            <Link to="/presenter/runtime?view=logs" aria-current={logs ? "page" : undefined}>
              <Icon name="list" size={16} />Logs
            </Link>
          </nav>
        )}
        {data && logs && <LogsPanel onSessionEnded={reload} />}
        {data && !logs && (
          <>
            {data.mode === "mock" && (
              <StatusBanner tone="warn" title="Mock mode: synthetic flow simulation">
                <p>No model is used. Readiness means synthetic flow simulation, not clinical or model readiness.</p>
              </StatusBanner>
            )}
            <div className="tiles" role="group" aria-label="Runtime at a glance">
              <div className="tile acc-blue">
                <span className="tile-label">Device</span>
                <span className="tile-value"><Icon name="chip" />{DEVICE}</span>
              </div>
              <div className="tile acc-violet">
                <span className="tile-label">Serving runtime</span>
                <span className="tile-value">
                  <Icon name={data.mode === "local" ? "pulse" : "info"} />
                  {data.mode === "local" ? `${RUNTIME} · on-device model` : "Mock · no model"}
                </span>
              </div>
              <div className={`tile ${data.readiness === "ready" ? "acc-green" : data.readiness === "degraded" ? "acc-amber" : "acc-red"}`}>
                <span className="tile-label">Service status</span>
                <span className="tile-value">
                  <Icon name={data.readiness === "ready" ? "check" : "alert"} />
                  {data.readiness === "ready" ? "Ready" : data.readiness === "degraded" ? "Degraded" : "Unavailable"}
                </span>
              </div>
            </div>
            <p className="small muted">
              Readiness{data.mode === "local" ? " (including whether ZRT serves the configured model)" : ""} and the
              queue observed at {formatTime(data.observed_at, { seconds: true })}; reload the page to observe them again.
            </p>
            <section className="card">
              <div className="datum"><span>Mode</span><b>{data.mode}</b></div>
              <div className="datum"><span>Readiness</span><b>{data.readiness}</b></div>
              <div className="datum"><span>Device inventory</span><b>{data.device_inventory_id}</b></div>
              <div className="datum"><span>Inventory recorded</span>
                <b>{data.device_inventory_observed_on ? formatDate(data.device_inventory_observed_on) : "Unknown"}</b></div>
              <div className="datum"><span>Model manifest</span><b>{data.model_manifest_id ?? "Not configured"}</b></div>
              <div className="datum"><span>Serving runtime</span>
                <b>{data.runtime_version ?? (data.mode === "mock" ? "None: mock mode runs no model" : "Not recorded")}</b></div>
              {data.mode === "local" && (
                <div className="datum"><span>Runtime qualified</span>
                  <b>{data.runtime_qualified_on ? `${formatDate(data.runtime_qualified_on)} (model manifest)` : "Not recorded"}</b></div>
              )}
              <div className="datum"><span>Corpus</span><b>{data.corpus_version ?? "None approved"}</b></div>
              <div className="datum"><span>Directory</span><b>{data.directory_version ?? "Unavailable"}</b></div>
              <div className="datum"><span>Queue / active</span><b>{data.queue_depth} / {data.active_jobs}</b></div>
              <div className="datum"><span>App build</span><b>{data.app_commit ?? "Not recorded"}</b></div>
            </section>
            <section className="card">
              {data.mode === "mock" ? (
                <>
                  <h2>Scripted timings (mock mode, median, {data.timing_summary.sample_count} samples)</h2>
                  <p className="small">
                    No AI model runs in mock mode, so there is no inference time. These are the scripted pipeline's own
                    durations, not model measurements.
                  </p>
                </>
              ) : (
                <h2>Measured timings (median, {data.timing_summary.sample_count} samples)</h2>
              )}
              <Timing label="Queue" value={data.timing_summary.queue_ms} total={data.timing_summary.total_ms} tone="acc-sky" />
              {data.mode !== "mock" && (
                <Timing label="Inference" value={data.timing_summary.inference_ms} total={data.timing_summary.total_ms} tone="acc-violet" />
              )}
              <Timing label="Validation" value={data.timing_summary.validation_ms} total={data.timing_summary.total_ms} tone="acc-teal" />
              <Timing label="Total" value={data.timing_summary.total_ms} total={data.timing_summary.total_ms} tone="acc-blue" />
              {data.timings_latest_at && (
                <p className="small muted">Newest sample finished {formatDateTime(data.timings_latest_at)}.</p>
              )}
            </section>
          </>
        )}
      </PresenterState>
    </>
  );
}
