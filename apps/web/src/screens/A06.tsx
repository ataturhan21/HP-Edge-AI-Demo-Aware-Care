// A06 Review your case (M03; R09, R20, R24). Confirmation applies to the current revision only;
// any edit returns the case to intake and invalidates derived results on the server.
// #388 (WCAG 3.3.7): "Change" opens the editor with the saved answer filled in, so only the part that changes is entered
// again; an answer saved unchanged sends nothing. #411: after a concern edit the case is asked for its next step, as
// after an answer edit, so it lands back in review with the confirmation; a concern saved unchanged sends nothing.
import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, type S } from "../api/client";
import { RED_FLAGS_KIND, redFlagSummary } from "../components/RedFlags";
import { Button, CaseUnavailable, EmptyState, ErrorBanner, LoadingState, PageHead, StatusBanner } from "../components/ui";
import { useJourneyCase } from "../components/JourneySteps";
import { screenForState, useCase } from "../components/useCase";
import { useAppState } from "../state/AppState";
import { AnswerInput, answerPayload, hasValue, type Value } from "./A05";
import { hasConcernText } from "./A03";
// #304: the reviewed question templates (pathway content, not patient data), so an answer can be changed with its real
// choices after a reload, when the in-memory copy of the issued question is gone. The case read carries no question
// definitions; the template is used only when the answer's template ID and wording match it exactly.
import reviewedQuestions from "../../../../content/pathways/general-adult-4/questions.json";

export const LABELS: Record<string, string> = {
  red_flags: "Urgent warning signs",
  age_years: "Age",
  history: "Relevant history",
  medications: "Current medications",
  allergy_status: "Allergies",
  allergies: "Reported allergies",
  "record:medications": "Medications (from a record you confirmed)",
  "record:allergies": "Allergies (from a record you confirmed)",
  "record:lab_result": "Test result (from a record you confirmed)",
};

/** A confirmed fact's value as shown to the person; the red-flag answer reads as the approved wording, and a test
 * result keeps its printed unit and reference range, or says they were not readable (R19). */
export function showFact(f: S["Fact"]): string {
  if (f.kind === RED_FLAGS_KIND) return redFlagSummary(f.value);
  if (f.kind !== "record:lab_result" && f.reference_range == null) return showValue(f.value, f.units);
  const value = showValue(f.value, f.units) + (f.units == null && f.value !== null ? " (unit not readable)" : "");
  return `${value}; reference range ${f.reference_range ?? "not readable"}`;
}

export function showValue(value: S["Fact"]["value"], units?: string | null): string {
  if (value === null) return "Unknown / not answered";
  if (Array.isArray(value)) return value.join(", ");
  if (value === "none_reported") return "None reported";
  if (value === "unknown") return "Unknown";
  if (value === "reported") return "Reported";
  return `${value}${units ? ` ${units}` : ""}`;
}

type Template = {
  template_id: string;
  text: string;
  response_type: S["Question"]["response_type"];
  choice_seed_ids?: { id: string; label: string }[];
  mutually_exclusive_seed_choice_ids?: string[];
  required?: boolean;
  why?: string;
  constraints?: { minimum?: number; maximum?: number; max_length?: number; anchors?: Record<string, string>; allowed_units?: string[] };
};
const DURATION_UNITS = ["hours", "days", "weeks", "months", "years"];

/** #388: an answer as its editor shows it, rebuilt from the confirmed answer fact (the server stores the shown wording:
 * choice labels, the text, the scale number or "<amount> <unit>"). Null for a skipped or "not sure" answer, or when a
 * value no longer matches the question (the editor then starts empty, as before). */
export function factValue(q: S["Question"], f: S["Fact"]): Value {
  const v = f.value;
  if (v === null) return null;
  const idOf = (label: unknown) => q.choices.find((c) => c.label === label)?.id;
  switch (q.response_type) {
    case "single_choice":
      return idOf(v) ?? null;
    case "multiple_choice": {
      if (!Array.isArray(v)) return null;
      const ids = v.map(idOf);
      return ids.every((id): id is string => id !== undefined) && ids.length > 0 ? ids : null;
    }
    case "scale":
      return typeof v === "number" ? v : null;
    case "text":
      return typeof v === "string" ? v : null;
    case "duration": {
      const m = typeof v === "string" ? /^(\S+) (\S+)$/.exec(v) : null;
      return m && q.constraints.allowed_units.includes(m[2] as never) ? { kind: "duration", amount: m[1], unit: m[2] } : null;
    }
    default:
      return null;
  }
}

/** #388: whether an edited value would store the answer the editor opened with. */
function sameValue(q: S["Question"], a: Value, b: Value): boolean {
  if (!hasValue(q, a) || !hasValue(q, b)) return false;
  const norm = (v: unknown) => JSON.stringify(Array.isArray(v) ? [...v].sort() : v);
  return norm(answerPayload(q, a)) === norm(answerPayload(q, b));
}

/** #304: the issued question behind an answer, rebuilt from the reviewed template the server issued it from (the
 * answer's kind is `answer:<template_id>` and its wording is the template's). Null when no template matches exactly. */
export function questionForAnswer(f: S["Fact"]): S["Question"] | null {
  const templateId = f.kind.startsWith("answer:") ? f.kind.slice("answer:".length) : null;
  const t = (reviewedQuestions.questions as Template[]).find((q) => q.template_id === templateId);
  if (!t || !f.source_id || t.text !== f.original_text) return null;
  const kind = t.response_type;
  const raw = t.constraints ?? {};
  const exclusive = new Set(t.mutually_exclusive_seed_choice_ids ?? []);
  const choices = (t.choice_seed_ids ?? []).map((c) => ({ id: c.id, label: c.label, exclusive: exclusive.has(c.id) }));
  return {
    id: f.source_id, case_id: f.case_id, slot: 1, template_id: t.template_id, pathway_version: reviewedQuestions.package,
    issued_revision: 1, response_type: kind, text: t.text, choices, required: Boolean(t.required), reason: t.why ?? "",
    status: "answered",
    constraints: {
      minimum: kind === "scale" ? raw.minimum ?? null : null,
      maximum: kind === "scale" ? raw.maximum ?? null : null,
      min_selections: kind === "single_choice" || kind === "multiple_choice" ? 1 : null,
      max_selections: kind === "single_choice" ? 1 : kind === "multiple_choice" ? choices.length : null,
      max_characters: kind === "text" ? raw.max_length ?? 2000 : null,
      lower_anchor: kind === "scale" ? raw.anchors?.[String(raw.minimum)] ?? null : null,
      upper_anchor: kind === "scale" ? raw.anchors?.[String(raw.maximum)] ?? null : null,
      allowed_units: kind === "duration" ? DURATION_UNITS.filter((u) => !raw.allowed_units || raw.allowed_units.includes(u)) : [],
    },
  } as S["Question"];
}

/** #580: one review per consultation: moving to another case's review (Back, History) starts a fresh page, so no
 * open editor, confirmation or generation key of the case shown before carries over to it. */
export default function A06() {
  const { caseId = "" } = useParams();
  return <Review key={caseId} caseId={caseId} />;
}

function Review({ caseId }: { caseId: string }) {
  const navigate = useNavigate();
  const { questions } = useAppState();
  const { data, error, loading, reload, notFound } = useCase(caseId);
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [editingConcern, setEditingConcern] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ q: S["Question"] | null; questionId: string; value: Value; initial: Value } | null>(null);
  // #230: focus moves into the editor when it opens, and back to that answer's Change button when it closes.
  const editorRef = useRef<HTMLDivElement | null>(null);
  const lastEdited = useRef<string | null>(null);
  const editingId = editing?.questionId ?? null;
  useEffect(() => {
    if (editingId) {
      lastEdited.current = editingId;
      editorRef.current?.focus();
    } else if (lastEdited.current) {
      document.querySelector<HTMLButtonElement>(`button[data-change-for="${lastEdited.current}"]`)?.focus();
      lastEdited.current = null;
    }
  }, [editingId]);
  // #402: the same for the concern: into its editor on Edit concern, back to Edit concern when the editor closes.
  const concernOpen = editingConcern !== null;
  const concernWasOpen = useRef(false);
  const editConcernButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (concernOpen) document.getElementById("concern-edit")?.focus();
    else if (concernWasOpen.current) editConcernButton.current?.focus();
    concernWasOpen.current = concernOpen;
  }, [concernOpen]);
  const [edited, setEdited] = useState(false);
  const genKey = useRef<{ rev: number; key: string } | null>(null);
  // #280: the review this page confirmed (revision before and after). If guidance then fails to start, the next click
  // goes straight to generation instead of confirming the same review again (which the server refuses with 409).
  const confirmedReview = useRef<{ from: number; to: number } | null>(null);
  // R20: record facts still awaiting review are surfaced here; they are never used until reviewed.
  const [unreviewed, setUnreviewed] = useState(0);
  const revision = data?.case.revision;
  useJourneyCase(caseId, data ? data.case.state === "guided" : undefined); // #343
  useEffect(() => {
    if (revision === undefined) return;
    let live = true;
    api.listRecords(caseId)
      .then((r) => live && setUnreviewed(r.facts.filter((f) => f.status === "unconfirmed").length))
      .catch(() => live && setUnreviewed(0));
    return () => {
      live = false;
    };
  }, [caseId, revision]);

  if (notFound)
    return <CaseUnavailable />;
  if (loading && !data) return <LoadingState label="Loading your review" />;
  if (!data) return <ErrorBanner error={error} onRetry={reload} />;
  const c = data.case;
  if (!["review", "reviewed", "intake"].includes(c.state)) {
    return (
      <EmptyState page title="This step is complete" action={<Link className="btn" to={screenForState(caseId, c.state, data.allowed_actions)}>Continue</Link>}>
        <p>The consultation has moved on. Continue from its current step.</p>
      </EmptyState>
    );
  }
  const profileFacts = c.confirmed_context.filter((f) => !f.kind.startsWith("answer:"));
  const answers = c.confirmed_context.filter((f) => f.kind.startsWith("answer:"));
  const gaps = answers.filter((f) => f.value === null);
  const editBusy = pending || editing !== null || editingConcern !== null;

  async function run(action: () => Promise<void>) {
    setPending(true);
    setActionError(null);
    try {
      await action();
    } catch (err) {
      setActionError(err);
      if (err instanceof ApiError && err.status === 409) await reload();
    } finally {
      setPending(false);
    }
  }

  /** After an edit the case is back in intake: ask for its next step. With every question asked, the server moves it to
   * review (the confirmation and Generate show again); an open question continues on A05. */
  async function afterEdit() {
    setEdited(true);
    setConfirmed(false);
    const read = await api.getCase(caseId);
    if (read.allowed_actions.includes("next_question") && read.case.state === "intake") {
      const next = await api.nextQuestion(caseId, read.case.revision, crypto.randomUUID());
      if (next.kind === "question") return navigate(`/app/cases/${caseId}/questions`);
    }
    await reload();
  }

  const saveConcern = () =>
    run(async () => {
      // #411: an unchanged concern is not a change; nothing is sent and the review stays as it is.
      if ((editingConcern ?? c.concern).trim() === c.concern) return setEditingConcern(null);
      const saved = await api.editCase(caseId, { expected_revision: c.revision, concern: editingConcern ?? c.concern });
      // #153: the edited concern is screened again in local mode; a described warning sign goes to urgent help.
      if (saved.state === "urgent")
        return navigate(`/app/cases/${caseId}/urgent`, { state: saved.urgent_level ? { level: saved.urgent_level } : null });
      setEditingConcern(null);
      if (saved.revision === c.revision) return; // the server found nothing changed
      await afterEdit();
    });

  const saveAnswer = (status: S["AnswerWrite"]["status"]) =>
    run(async () => {
      if (!editing) return;
      // #388: the answer the editor opened with, saved again unchanged, is not a change.
      if (status === "answered" && editing.q && sameValue(editing.q, editing.value, editing.initial)) return setEditing(null);
      const body = { expected_revision: c.revision, status, value: status === "answered" && editing.q ? answerPayload(editing.q, editing.value) : null } as S["AnswerWrite"];
      await api.saveAnswer(caseId, editing.questionId, body);
      setEditing(null);
      await afterEdit();
    });

  const generate = () =>
    run(async () => {
      let rev = c.revision;
      if (c.state === "review" && confirmedReview.current?.from === rev) rev = confirmedReview.current.to;
      else if (c.state === "review") {
        const updated = await api.confirmReview(caseId, rev);
        confirmedReview.current = { from: rev, to: updated.revision };
        rev = updated.revision;
      }
      if (genKey.current?.rev !== rev) genKey.current = { rev, key: crypto.randomUUID() };
      let job: S["Job"];
      try {
        job = await api.generateGuidance(caseId, rev, genKey.current.key);
      } catch (err) {
        await reload(); // the case is reviewed now; show it as it is on the server
        throw err;
      }
      navigate(`/app/cases/${caseId}/guidance`, { state: { jobId: job.id } });
    });

  return (
    <div className="narrow">
      <PageHead eyebrow="Review" title="Review your case">
        <p>Check what you shared. Guidance uses only this confirmed version.</p>
      </PageHead>
      {edited && <StatusBanner tone="info" title="Your change was saved. Please review again before continuing." />}
      {c.state === "intake" && (
        <StatusBanner tone="warn" title="More questions may be needed.">
          <Link to={`/app/cases/${caseId}/questions`}>Continue the questions</Link>
        </StatusBanner>
      )}
      {actionError != null && <ErrorBanner error={actionError} />}
      {unreviewed > 0 && (
        <StatusBanner tone="warn" title={`${unreviewed} fact${unreviewed === 1 ? "" : "s"} from your records not reviewed`}>
          <p>
            Unreviewed facts are not used in your guidance or summary.{" "}
            <Link to={`/app/cases/${caseId}/records`}>Review records</Link>
          </p>
        </StatusBanner>
      )}
      <section className="card">
        <h2>Main concern</h2>
        {editingConcern === null ? (
          <>
            <p className="user-text">{c.concern}</p>
            <button type="button" className="btn secondary sm" onClick={() => setEditingConcern(c.concern)} ref={editConcernButton}>
              Edit concern
            </button>
          </>
        ) : (
          <div className="field">
            <label htmlFor="concern-edit">Main concern</label>
            <textarea id="concern-edit" maxLength={4000} value={editingConcern} onChange={(e) => setEditingConcern(e.target.value)} />
            <div className="row">
              <Button type="button" className="btn sm" pending={pending} disabled={!hasConcernText(editingConcern)} onClick={saveConcern}>
                Save change
              </Button>
              <button type="button" className="btn secondary sm" disabled={pending} onClick={() => setEditingConcern(null)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>
      <section className="card">
        <h2>Profile details for this session</h2>
        {profileFacts.length === 0 ? (
          <p className="muted">None provided (unknown).</p>
        ) : (
          profileFacts.map((f) => (
            <div className="datum" key={f.id}>
              <span>{LABELS[f.kind] ?? f.kind}</span>
              <b>{showFact(f)}</b>
            </div>
          ))
        )}
      </section>
      <section className="card">
        <h2>Your answers ({c.issued_slots} question{c.issued_slots === 1 ? "" : "s"} asked)</h2>
        {answers.map((f) => (
          <Fragment key={f.id}>
            <div className={`datum${f.value === null ? " datum-gap" : ""}`}>
              <span className="user-text">{f.original_text}</span>
              <span className="row">
                <b>{showValue(f.value, f.units)}</b>
                <button
                  type="button"
                  className="btn secondary sm"
                  data-change-for={f.source_id ?? undefined}
                  aria-expanded={editing?.questionId === f.source_id}
                  onClick={() => {
                    const q = (f.source_id && questions.get(f.source_id)) || questionForAnswer(f);
                    const initial = q ? factValue(q, f) : null;
                    setEditing({ q, questionId: f.source_id!, value: initial, initial });
                  }}
                >
                  Change<span className="sr-only"> answer to {f.original_text}</span>
                </button>
              </span>
            </div>
            {/* #230: the editor opens right under the answer it changes, and takes focus. */}
            {editing && editing.questionId === f.source_id && (
          <div className="card answer-editor" ref={editorRef} tabIndex={-1} role="group" aria-label={`Change answer: ${f.original_text}`}>
            {editing.q ? (
              <>
                <h3>{editing.q.text}</h3>
                <AnswerInput q={editing.q} value={editing.value} onChange={(v) => setEditing({ ...editing, value: v })} />
                <div className="row">
                  <Button type="button" className="btn sm" pending={pending} onClick={() => saveAnswer("answered")} disabled={!hasValue(editing.q, editing.value)}>
                    Save answer
                  </Button>
                  <button type="button" className="btn secondary sm" disabled={pending} onClick={() => saveAnswer("unknown")}>
                    Mark not sure
                  </button>
                  <button type="button" className="btn secondary sm" disabled={pending} onClick={() => setEditing(null)}>
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <>
                <p>The answer choices for this question are not available on this page. You can mark this answer as “not sure”.</p>
                <div className="row">
                  <Button type="button" className="btn sm" pending={pending} onClick={() => saveAnswer("unknown")}>
                    Mark not sure
                  </Button>
                  <button type="button" className="btn secondary sm" disabled={pending} onClick={() => setEditing(null)}>
                    Cancel
                  </button>
                </div>
              </>
            )}
          </div>
            )}
          </Fragment>
        ))}
      </section>
      {gaps.length > 0 && (
        <StatusBanner tone="warn" title={`${gaps.length} ${gaps.length === 1 ? "question was" : "questions were"} skipped or answered “Not sure”`}>
          <ul className="bullets">
            {gaps.map((g) => (
              <li key={g.id}>{g.original_text}</li>
            ))}
          </ul>
          {/* #237: what an unanswered question does (R14, the reviewed rule), and what the person can do about it. */}
          <p>
            While any question is unanswered, the guidance will not suggest self-care: it points you to a clinician
            instead. These details stay visible as unknown in your guidance and summary. If you know an answer, change it
            above.
          </p>
        </StatusBanner>
      )}
      {c.state !== "intake" && (
        <section className="card">
          {/* #148: no confirmation while an edit is open or saving; finishing the edit resets it anyway. */}
          <label className="check">
            <input type="checkbox" checked={confirmed || c.state === "reviewed"} disabled={c.state === "reviewed" || editBusy}
              onChange={(e) => setConfirmed(e.target.checked)} />
            I confirm this information is complete as far as I know.
          </label>
          <div className="actions">
            {/* #190: a disabled button says why. */}
            {editBusy ? (
              <p className="small muted" id="generate-hint">Save or cancel the open change first.</p>
            ) : !(confirmed || c.state === "reviewed") ? (
              <p className="small muted" id="generate-hint">Tick the confirmation above to continue.</p>
            ) : (
              <span />
            )}
            <Button type="button" pending={pending} disabled={editBusy || !(confirmed || c.state === "reviewed")} onClick={generate}
              aria-describedby={editBusy || !(confirmed || c.state === "reviewed") ? "generate-hint" : undefined}>
              Generate guidance
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}
