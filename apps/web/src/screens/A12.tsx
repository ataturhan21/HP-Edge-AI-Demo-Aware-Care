// A12 Appointment summary (M10; R32, R33). Explicit review, real PDF job, owned expiring download.
// #418: the download link is followed by the page: a link the server refuses (deleted or changed case, expired link,
// ended session) shows that state here instead of the server's JSON error page. #420: Create PDF keeps keyboard focus
// while the PDF is made (aria-disabled), and focus moves to the download link when it is ready.
import { type MouseEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, asNoCurrentGuidance, currentSessionExpiry, pollJob, type S } from "../api/client";
import { Icon } from "../components/Icon";
import { Button, CaseUnavailable, EmptyState, ErrorBanner, LoadingState, PageHead, StatusBanner, SyntheticBadge } from "../components/ui";
import { useJourneyCase } from "../components/JourneySteps";
import { ResetActions } from "../components/ResetActions";
import { LABELS, showFact } from "./A06";
import { LEVEL_ICON, URGENCY } from "./A07";

export default function A12() {
  const { caseId = "" } = useParams();
  const [data, setData] = useState<{ read: S["CaseReadResponse"]; guidance: S["Guidance"]; ttlMinutes: number } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [reviewed, setReviewed] = useState(false);
  const [state, setState] = useState<"idle" | "generating" | "ready" | "failed" | "stale" | "expired" | "unavailable">("idle");
  const [exportId, setExportId] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [downloadError, setDownloadError] = useState<unknown>(null);
  const abort = useRef<AbortController | null>(null);
  // #420: where focus goes after an action whose control disappears (the link when it is ready, Create otherwise).
  const linkRef = useRef<HTMLAnchorElement>(null);
  const [focusTarget, setFocusTarget] = useState<"link" | "create" | null>(null);
  useEffect(() => {
    if (!focusTarget) return;
    (focusTarget === "link" ? linkRef.current : document.getElementById("create-summary"))?.focus();
    setFocusTarget(null);
  }, [focusTarget, state]);
  // #343: the preview's own case read decides whether the Guidance and Find care steps are links.
  useJourneyCase(caseId, data ? data.read.case.state === "guided" : error instanceof ApiError && error.status === 409 ? false : undefined);

  const load = useCallback(() => {
    setError(null);
    // #279: the link lifetime is the server's export retention (GET /settings), not a number in the browser.
    // #269: guidance never generated is 404; with the case readable it is the same "Review required" state as a 409.
    // A 404 for the case itself rejects getCase and shows the unavailable state (#288).
    Promise.all([
      api.getCase(caseId),
      api.getGuidance(caseId).then((g) => ({ g }), (err: unknown) => ({ err })),
      api.getSettings(),
    ]).then(
      ([read, result, settings]) =>
        "g" in result
          ? setData({ read, guidance: result.g, ttlMinutes: settings.settings.export_retention_minutes })
          : setError(asNoCurrentGuidance(result.err)),
      setError,
    );
  }, [caseId]);
  useEffect(() => {
    load();
    return () => abort.current?.abort();
  }, [load]);

  // #279: the ready link turns into "expired" on screen when its time is up, without waiting for a re-render.
  useEffect(() => {
    if (state !== "ready" || expiresAt === null) return;
    const timer = window.setTimeout(() => {
      if (document.activeElement === linkRef.current) setFocusTarget("create");
      setState("expired");
    }, Math.max(0, expiresAt - Date.now()));
    return () => window.clearTimeout(timer);
  }, [state, expiresAt]);

  async function create() {
    if (!data || state === "generating") return; // aria-disabled while generating: the button keeps focus
    setState("generating");
    setError(null);
    setDownloadError(null);
    abort.current?.abort();
    abort.current = new AbortController();
    try {
      // #279: a new Idempotency-Key for every Create, so "Create again" makes a new export instead of replaying the
      // earlier (possibly expired) one.
      const job = await api.createExport(caseId, data.read.case.revision, crypto.randomUUID());
      const done = await pollJob(job.id, abort.current.signal);
      if (done.status === "succeeded" && done.result_id) {
        // The server's clock: the export expires its retention after it was made, which is no earlier than the job's
        // creation. Converted to this browser's clock with the offset learned from the server's Date header.
        const skew = currentSessionExpiry()?.skewMs ?? 0;
        setExportId(done.result_id);
        setExpiresAt(Date.parse(done.created_at) + data.ttlMinutes * 60_000 - skew);
        setState("ready");
        setFocusTarget("link");
      } else {
        setState(done.status === "stale" ? "stale" : "failed");
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      setError(err);
      setState("failed");
    }
  }

  // #279: an expired link is never followed (it would open the server's error instead of the app). #418: neither is a
  // link the server refuses: the page reads the PDF itself and saves it, or shows why it cannot.
  async function download(e: MouseEvent<HTMLAnchorElement>) {
    e.preventDefault();
    if (!exportId) return;
    setDownloadError(null);
    if (expiresAt !== null && Date.now() >= expiresAt) {
      setState("expired");
      setFocusTarget("create");
      return;
    }
    try {
      const pdf = await api.downloadExport(exportId);
      const url = URL.createObjectURL(pdf);
      const save = document.createElement("a");
      save.href = url;
      save.download = "aware-care-appointment-summary.pdf";
      document.body.append(save);
      save.click();
      save.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (err) {
      // 401: the session ended; the app's session handler opens the start page and says so.
      if (err instanceof ApiError && err.status === 401) return;
      if (err instanceof ApiError && err.code === "EXPORT_EXPIRED") setState("expired");
      else if (err instanceof ApiError && err.status === 409) setState("stale");
      else if (err instanceof ApiError && err.status === 404) setState("unavailable");
      else return setDownloadError(err); // the link stays; the person can try again
      setFocusTarget("create");
      load(); // a deleted case shows "not available"; a changed one "Review required"
    }
  }

  if (error instanceof ApiError && error.status === 409)
    return (
      <EmptyState page title="Review required" action={<Link className="btn" to={`/app/cases/${caseId}/review`}>Go to review</Link>}>
        <p>A summary needs current, reviewed guidance.</p>
      </EmptyState>
    );
  if (error instanceof ApiError && error.status === 404) return <CaseUnavailable />;
  if (error && !data) return <ErrorBanner error={error} onRetry={load} />;
  if (!data) return <LoadingState label="Loading summary preview" />;
  const { read, guidance } = data;
  // #356: the level comes from the published guidance and the doctors from the case's current search (both read from
  // the server, which prints the same into the PDF); each section is shown only when it exists.
  const mock = guidance.model_manifest_id.startsWith("mock-");
  const doctors = read.found_doctors?.doctors ?? [];
  // #417: the preview shows every section the PDF prints (apps/api/app/modules/exports/service.py, _lines), under the
  // same titles, so the person reviews what will be exported. Explanations as the PDF lists them (never a suppressed one).
  const explanations = guidance.possible_explanations.filter(
    (c) => c.validation_status === "supported" || c.validation_status === "general_knowledge",
  );

  return (
    <>
      <PageHead eyebrow="Prepare for a visit" title="Appointment summary">
        <p>Review this preview, then create a PDF. It is not sent to anyone.</p>
      </PageHead>
      <article className="paper" aria-label="Summary preview">
        <p className="badge amber">Synthetic demo document · not a diagnosis</p>
        <h2 className="card-title acc-sky">
          <span className="card-icon" aria-hidden="true"><Icon name="chat" size={18} /></span>
          Main concern
        </h2>
        <p className="user-text">{read.case.concern}</p>
        <h2 className="card-title acc-teal">
          <span className="card-icon" aria-hidden="true"><Icon name="list" size={18} /></span>
          What you reported
        </h2>
        {read.case.confirmed_context.map((f) => (
          // #257: an unanswered or unknown item is set apart in slate, so the gaps stand out.
          <div className={f.value === null || f.value === "unknown" ? "datum gap" : "datum"} key={f.id}>
            {/* #395: an answer is labelled by its question; a record fact by its kind, never by its source text. */}
            <span className="user-text">{f.kind.startsWith("answer:") ? f.original_text ?? f.kind : LABELS[f.kind] ?? f.kind}</span>
            <b>{showFact(f)}</b>
          </div>
        ))}
        <h2 className="card-title acc-amber">
          <span className="card-icon" aria-hidden="true"><Icon name="alert" size={18} /></span>
          Unresolved or unknown details
        </h2>
        <ul className="bullets">
          {guidance.uncertainties.map((u) => (
            <li key={u}>{u}</li>
          ))}
          {guidance.uncertainties.length === 0 && <li>None recorded</li>}
        </ul>
        {guidance.urgency?.level && (
          <section aria-labelledby="summary-level">
            <h2 className="card-title acc-blue" id="summary-level">
              <span className="card-icon" aria-hidden="true"><Icon name="pulse" size={18} /></span>
              Suggested level of care
            </h2>
            <p className="level-badge level-summary">
              <Icon name={LEVEL_ICON[guidance.urgency.level]} size={20} />
              {URGENCY[guidance.urgency.level]}
            </p>
            <p className="small">
              {mock ? (
                <SyntheticBadge>Scripted synthetic outcome</SyntheticBadge>
              ) : (
                <span className="badge gray">AI-generated on this device</span>
              )}{" "}
              {mock ? "Selected by a demo scenario, not by a model." : "Check it with a clinician."} The same result as your
              guidance.
            </p>
          </section>
        )}
        <section aria-labelledby="summary-next">
          <h2 className="card-title acc-green" id="summary-next">
            <span className="card-icon" aria-hidden="true"><Icon name="arrow" size={18} /></span>
            {mock ? "Suggested next step" : "Suggested next steps"}
          </h2>
          <p className="small">
            {mock ? (
              <SyntheticBadge>Scripted synthetic outcome</SyntheticBadge>
            ) : (
              <span className="badge gray">AI-generated on this device</span>
            )}{" "}
            {mock ? "Selected by a demo scenario, not by a model." : "Check with a clinician."}
          </p>
          <ul className="bullets">
            {guidance.actions.map((a) => (
              <li key={a.id}>{a.text}</li>
            ))}
          </ul>
        </section>
        {explanations.length > 0 && (
          <section aria-labelledby="summary-explanations">
            <h2 className="card-title acc-slate" id="summary-explanations">
              <span className="card-icon" aria-hidden="true"><Icon name="info" size={18} /></span>
              Possible explanations
            </h2>
            {/* #456: mock mode's explanation is scripted, never "general medical knowledge"; the PDF says the same. */}
            <p className="small muted">
              {mock
                ? "Scripted illustrative text, not from an AI model or reviewed sources; not a diagnosis."
                : "General medical knowledge, not from reviewed sources; not a diagnosis."}
            </p>
            <ul className="bullets">
              {explanations.map((c) => (
                <li key={c.id}>{c.text}</li>
              ))}
            </ul>
          </section>
        )}
        <h2 className="card-title acc-violet">
          <span className="card-icon" aria-hidden="true"><Icon name="stethoscope" size={18} /></span>
          Questions for a clinician
        </h2>
        <ul className="bullets">
          {guidance.clinician_questions.map((q) => (
            <li key={q}>{q}</li>
          ))}
        </ul>
        <section aria-labelledby="summary-sooner">
          <h2 className="card-title acc-rose" id="summary-sooner">
            <span className="card-icon" aria-hidden="true"><Icon name="clock" size={18} /></span>
            When to seek help sooner
          </h2>
          <ul className="bullets">
            {guidance.escalation_advice.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </section>
        {doctors.length > 0 && (
          <section aria-labelledby="summary-doctors">
            <h2 className="card-title acc-coral" id="summary-doctors">
              <span className="card-icon" aria-hidden="true"><Icon name="users" size={18} /></span>
              Doctors you found
            </h2>
            <p className="small">
              <SyntheticBadge>Fictional doctors</SyntheticBadge> From your latest doctor search. Nothing was booked or
              sent; availability and credentials are unknown.
            </p>
            <ol className="summary-doctors">
              {doctors.map((d) => (
                <li key={d.provider_id}>
                  <b>{d.name}</b>
                  <span className="small">
                    {" "}
                    · {d.specialties.join(", ")} · {d.practice}
                    {d.distance_miles !== null && ` · ${d.distance_miles} mi (fictional)`}
                  </span>
                  <ul className="facts-confirmed small" aria-label={`Confirmed for ${d.name}`}>
                    {d.confirmed_matches.map((x) => (
                      <li key={x}>{x}</li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
          </section>
        )}
        <section aria-labelledby="summary-sources">
          <h2 className="card-title acc-slate" id="summary-sources">
            <span className="card-icon" aria-hidden="true"><Icon name="file" size={18} /></span>
            Sources
          </h2>
          <p>
            {mock
              ? "No approved evidence sources are loaded; the possible explanation is scripted illustrative text for this synthetic demo, not from an AI model."
              : "No approved evidence sources are loaded; possible explanations come from general medical knowledge."}
          </p>
        </section>
      </article>
      <section className="card" style={{ marginTop: 16 }}>
        <label className="check">
          <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />I reviewed this summary.
        </label>
        {state === "generating" && <LoadingState label="Creating your PDF" />}
        {state === "failed" && (
          <StatusBanner tone="error" title="The PDF could not be created. You can try again.">
            {/* #397: a busy or per-session limit refusal (429) says why and when to try again. */}
            {error instanceof ApiError && error.status === 429 && <p>{error.message}</p>}
          </StatusBanner>
        )}
        {state === "stale" && <StatusBanner tone="warn" title="Your case changed. Review it again before creating a summary." />}
        {state === "unavailable" && (
          <StatusBanner tone="warn" title="This summary is no longer available. Create a new one.">
            <p>The consultation may have been deleted, or the summary was removed from this device.</p>
          </StatusBanner>
        )}
        {state === "ready" && downloadError != null && <ErrorBanner error={downloadError} />}
        {state === "ready" && exportId && (
          <StatusBanner tone="success" title="Your summary is ready">
            <p>
              <a className="btn sm" href={api.exportUrl(exportId)} onClick={download} ref={linkRef}>
                Download summary (PDF)
              </a>
            </p>
            <p className="small">
              The link expires in 15 minutes or when your case changes. A downloaded copy is outside Aware Care’s deletion
              controls.
            </p>
          </StatusBanner>
        )}
        {state === "expired" && <StatusBanner tone="warn" title="The download link expired. Create a new summary." />}
        <div className="actions">
          <Link className="btn secondary" to={`/app/cases/${caseId}/guidance`}>
            Back to guidance
          </Link>
          {/* #190: a disabled button says why. */}
          {!reviewed && <p className="small muted" id="create-hint">Tick “I reviewed this summary” to create the PDF.</p>}
          <Button type="button" id="create-summary" disabled={!reviewed} aria-disabled={state === "generating" || undefined}
            onClick={create} aria-describedby={!reviewed ? "create-hint" : undefined}>
            {state === "ready" || state === "expired" ? "Create again" : "Create PDF"}
          </Button>
        </div>
      </section>
      <ResetActions />
    </>
  );
}
