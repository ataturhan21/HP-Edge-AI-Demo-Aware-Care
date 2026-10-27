// A04 Records (M06; R18-R20). Optional step. Mock mode uses only the bundled synthetic sample
// record (ADR-009); the server validates every upload and extracts facts only from that sample.
// Extracted facts stay unconfirmed, and unused, until the user confirms, corrects or rejects them.
// #402: keyboard focus never falls to the page body: it returns to the button that started an action (or the next
// usable one of that fact), moves into the correction editor when it opens and back to Correct when it closes.
// #413: the server reads sample records in mock mode only; once this tab knows the demo runs the AI model on this device
// (local mode), the page says up front that record reading is not available and offers no upload that can only fail.
// #450: an upload is offered only while the case accepts one (allowed action upload_record, before the questions are
// finished); otherwise the page says why, and the facts already extracted can still be reviewed.
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError, pollJob, type S } from "../api/client";
import { Button, CaseUnavailable, ErrorBanner, LoadingState, PageHead, StatusBanner, SyntheticBadge, useFocusReturn } from "../components/ui";
import { screenForState } from "../components/useCase";
import { useAppState } from "../state/AppState";
import sampleUrl from "../../../../fixtures/records/synthetic-sample-record-01.pdf?url";
import unreadableUrl from "../../../../fixtures/records/synthetic-unreadable-record.pdf?url";

const STATUS: Record<S["DocumentPublic"]["status"], string> = {
  queued: "Waiting to be read",
  processing: "Reading",
  review: "Ready for your review",
  failed: "Could not be read",
  rejected: "Rejected",
};

async function sampleFile(url: string, name: string): Promise<File> {
  const response = await fetch(url, { cache: "no-store" });
  return new File([await response.blob()], name, { type: "application/pdf" });
}

// #231: what a record fact is about, named for the person; the value itself is the record's own wording, never
// interpreted (R19: "No medications listed" is not read as "takes no medicines").
const FACT_TOPIC: Record<string, string> = {
  "record:medications": "Medications",
  "record:allergies": "Allergies",
  "record:lab_result": "Test result",
};

function FactReview({ fact, doc, onReview, pending }: {
  fact: S["Fact"];
  doc?: S["DocumentPublic"];
  pending: boolean;
  /** Resolves true when the server saved the review (#284). */
  onReview: (body: Pick<S["FactReview"], "action" | "corrected_value">) => Promise<boolean>;
}) {
  const [correcting, setCorrecting] = useState(false);
  const correctButton = useRef<HTMLButtonElement>(null);
  const opened = useRef(false);
  useEffect(() => {
    if (correcting) document.getElementById(`correct-${fact.id}`)?.focus();
    else if (opened.current) correctButton.current?.focus();
    opened.current = correcting;
  }, [correcting, fact.id]);
  const [text, setText] = useState(fact.value === null || Array.isArray(fact.value) ? "" : String(fact.value));
  const [unit, setUnit] = useState(fact.units ?? "");
  // Units and reference ranges belong to measurements: a lab result, or any fact that came with either printed.
  const measurement = fact.kind === "record:lab_result" || fact.units != null || fact.reference_range != null;
  const shownValue = fact.value === null ? "Not readable" : Array.isArray(fact.value) ? fact.value.join(", ") : String(fact.value);
  const label = fact.status === "unconfirmed" ? "Needs confirmation" : fact.status === "confirmed" ? "Confirmed" : "Rejected";
  return (
    <div className="fact-item" role="group" aria-label="Extracted fact">
      <h3 className="fact-topic">{FACT_TOPIC[fact.kind] ?? "Detail from your record"}</h3>
      <p>
        <strong>What the record says:</strong> “{fact.original_text}”
      </p>
      <p className="small muted">
        From {doc?.original_display_name ?? "a record"} · page {fact.page ?? "unknown"}
      </p>
      {measurement ? (
        <dl className="fact-detail">
          <div>
            <dt>Value</dt>
            <dd>{shownValue}</dd>
          </div>
          <div>
            <dt>Unit</dt>
            <dd>{fact.units ?? "Unit not readable"}</dd>
          </div>
          <div>
            <dt>Reference range</dt>
            <dd>{fact.reference_range ?? "Range not readable"}</dd>
          </div>
        </dl>
      ) : (
        fact.status === "confirmed" && fact.value !== fact.original_text && (
          <p>
            <strong>Your correction:</strong> {shownValue}
          </p>
        )
      )}
      <p>
        <span className={`badge ${fact.status === "rejected" ? "slate" : fact.status === "confirmed" ? "green" : "amber"}`}>
          {label}
        </span>
      </p>
      {correcting ? (
        <div className="field">
          <label htmlFor={`correct-${fact.id}`}>Corrected value</label>
          <input id={`correct-${fact.id}`} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} />
          <label htmlFor={`correct-unit-${fact.id}`}>Unit (optional)</label>
          <span className="hint" id={`correct-unit-hint-${fact.id}`}>
            Stored with your correction; the source text above is kept as it was printed.
          </span>
          <input id={`correct-unit-${fact.id}`} maxLength={100} value={unit} aria-describedby={`correct-unit-hint-${fact.id}`}
            onChange={(e) => setUnit(e.target.value)} />
          <div className="row">
            <Button type="button" className="btn sm" pending={pending} disabled={!text.trim()}
              onClick={async () => {
                // #284: the editor closes once the correction is saved, and stays open (with the error) otherwise.
                const saved = await onReview({ action: "correct", corrected_value: { value: text.trim(), units: unit.trim() || null } });
                if (saved) setCorrecting(false);
              }}>
              Save correction
            </Button>
            <button type="button" className="btn secondary sm" disabled={pending} onClick={() => setCorrecting(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="row" role="group" aria-describedby={`fact-actions-${fact.id}`}>
          <button type="button" className="btn secondary sm" disabled={pending || fact.status === "confirmed"}
            onClick={() => void onReview({ action: "confirm" })}>
            Confirm
          </button>
          <button type="button" className="btn secondary sm" disabled={pending} onClick={() => setCorrecting(true)} ref={correctButton}>
            Correct
          </button>
          <button type="button" className="btn secondary sm" disabled={pending || fact.status === "rejected"}
            onClick={() => void onReview({ action: "reject" })}>
            Reject
          </button>
          <p className="small muted fact-actions-hint" id={`fact-actions-${fact.id}`}>
            Confirm uses it as the record says. Correct lets you change it first. Reject leaves it out.
          </p>
        </div>
      )}
    </div>
  );
}

export default function A04() {
  const { caseId = "" } = useParams();
  const navigate = useNavigate();
  const { runtimeMode } = useAppState();
  const [records, setRecords] = useState<S["RecordList"] | null>(null);
  // #450: the case as last read (state and allowed actions), so upload is offered only where it can succeed.
  const [caseRead, setCaseRead] = useState<S["CaseReadResponse"] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<{ tone: "warn" | "error" | "success"; text: string } | null>(null);
  const [pending, setPending] = useState(false);
  const abort = useRef<AbortController | null>(null);
  useFocusReturn(pending, {
    fallback: (el) => el.closest(".fact-item")?.querySelector<HTMLElement>("button:not([disabled])"),
  });

  const load = useCallback(async () => {
    setError(null);
    try {
      const [list, read] = await Promise.all([api.listRecords(caseId), api.getCase(caseId)]);
      setRecords(list);
      setCaseRead(read);
    } catch (err) {
      setError(err);
    }
  }, [caseId]);

  useEffect(() => {
    void load();
    return () => abort.current?.abort();
  }, [load]);

  async function add(url: string, name: string) {
    setPending(true);
    setNotice(null);
    abort.current = new AbortController();
    try {
      const read = await api.getCase(caseId);
      const accepted = await api.uploadRecord(caseId, read.case.revision, await sampleFile(url, name), crypto.randomUUID());
      await load();
      const job = await pollJob(accepted.job_id, abort.current.signal);
      if (job.status === "succeeded") setNotice({ tone: "success", text: "Sample record read. Review the extracted fact below." });
      else if (job.status === "stale") setNotice({ tone: "warn", text: "Your consultation changed while the record was read. Add it again." });
      else setNotice({ tone: "error", text: "This record could not be read. Nothing from it is used." });
      await load();
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      if (err instanceof ApiError && [413, 415, 422].includes(err.status)) setNotice({ tone: "error", text: err.message });
      else if (err instanceof ApiError && err.code === "SERVICE_LIMITED") setNotice({ tone: "warn", text: err.message });
      else setError(err);
    } finally {
      setPending(false);
    }
  }

  async function review(fact: S["Fact"], body: Pick<S["FactReview"], "action" | "corrected_value">): Promise<boolean> {
    setPending(true);
    setNotice(null);
    setError(null);
    try {
      const read = await api.getCase(caseId);
      await api.reviewFact(caseId, fact.id, { expected_revision: read.case.revision, ...body } as S["FactReview"]);
      await load();
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setNotice({ tone: "warn", text: "This consultation changed. The list was refreshed; review again." });
        await load();
      } else setError(err);
      return false;
    } finally {
      setPending(false);
    }
  }

  if (error instanceof ApiError && error.status === 404)
    return <CaseUnavailable />;
  if (!records && error != null) return <ErrorBanner error={error} onRetry={load} />;
  if (!records || !caseRead) return <LoadingState label="Loading records" />;
  const docs = new Map(records.documents.map((d) => [d.id, d]));
  const unconfirmed = records.facts.filter((f) => f.status === "unconfirmed").length;
  const full = records.documents.length >= 3;
  const accepts = caseRead.allowed_actions.includes("upload_record");
  const local = runtimeMode === "local";
  const intake = caseRead.case.state === "intake";
  // Where Continue leads: the questions while the case is in intake, otherwise its current step (#450).
  const onward = intake ? `/app/cases/${caseId}/questions` : screenForState(caseId, caseRead.case.state, caseRead.allowed_actions);
  return (
    <div className="narrow">
      <PageHead eyebrow="Optional step" title="Add records">
        <p>You can skip this. Details from a record are separate from the questions and do not use up any of them.</p>
      </PageHead>
      {error != null && <ErrorBanner error={error} onRetry={load} />}
      {notice && <StatusBanner tone={notice.tone} title={notice.text} />}
      {local ? (
        <StatusBanner tone="info" title="Record reading is not available in this build">
          <p>This demo runs with the AI model on this device and does not read records. You can skip this optional step.</p>
        </StatusBanner>
      ) : !accepts ? (
        <StatusBanner tone="info" title="Records can no longer be added to this consultation">
          <p>
            Records can be added only before the questions are finished. You can still review the details already taken
            from your records below.
          </p>
        </StatusBanner>
      ) : (
        <section className="card" aria-labelledby="sample-heading">
          <h2 id="sample-heading">Choose a sample record</h2>
          <SyntheticBadge>Fictional document</SyntheticBadge>
          <p className="small">
            {runtimeMode === "mock"
              ? "This demo does not read your own files. A bundled fictional document is uploaded and checked like a real one"
              : "This demo does not read your own files. In the scripted demo, a bundled fictional document is uploaded and checked like a real one"}{" "}
            (PDF, PNG or JPEG; up to 3 files, 10 MB each, 30 pages in total). Scanned text is not read.
          </p>
          <div className="row">
            <Button type="button" className="btn secondary" pending={pending} disabled={full}
              onClick={() => add(sampleUrl, "Jordan_sample_record.pdf")}>
              Add sample PDF
            </Button>
            <button type="button" className="btn secondary" disabled={pending || full}
              onClick={() => add(unreadableUrl, "unreadable_sample.pdf")}>
              Try unreadable file
            </button>
          </div>
          {full && <p className="small">The 3-record limit for this consultation is reached.</p>}
        </section>
      )}
      {records.documents.length === 0 ? (
        <p className="muted">No records added.</p>
      ) : (
        <section className="card" aria-labelledby="docs-heading">
          <h2 id="docs-heading">Records</h2>
          {records.documents.map((d) => (
            <div className="datum" key={d.id}>
              <span>
                {d.original_display_name} · {d.page_count ?? "?"} page{d.page_count === 1 ? "" : "s"}
              </span>
              <b>{STATUS[d.status]}</b>
            </div>
          ))}
        </section>
      )}
      {records.facts.length > 0 && (
        <section className="card" aria-labelledby="facts-heading">
          <h2 id="facts-heading">Review extracted facts</h2>
          <p className="small">Nothing from a record is used until you confirm or correct it.</p>
          {records.facts.map((f) => (
            <FactReview key={f.id} fact={f} doc={f.source_id ? docs.get(f.source_id) : undefined} pending={pending}
              onReview={(body) => review(f, body)} />
          ))}
        </section>
      )}
      {unconfirmed > 0 && (
        <StatusBanner tone="warn" title={`${unconfirmed} fact${unconfirmed === 1 ? "" : "s"} not reviewed`}>
          <p>Unreviewed facts are not used in your guidance or summary.</p>
        </StatusBanner>
      )}
      <div className="actions">
        <span />
        <button type="button" className="btn" disabled={pending} onClick={() => navigate(onward)}>
          {!intake ? "Continue" : records.documents.length ? "Continue to questions" : "Skip and continue"}
        </button>
      </div>
    </div>
  );
}
