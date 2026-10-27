// A05 Adaptive questions (M04; R11-R14). One issued question at a time; "up to 10"; typed answers.
import { useCallback, useEffect, useRef, useState, type CSSProperties, type FormEvent } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, type S } from "../api/client";
import { Button, CaseUnavailable, ErrorBanner, LoadingState, PageHead, StatusBanner } from "../components/ui";
import { stepOf, useJourneyCase, useJourneyInPage } from "../components/JourneySteps";
import { screenForState } from "../components/useCase";
import { useAppState } from "../state/AppState";

/** A duration answer while it is being typed; it becomes {amount, unit} only when both parts are valid. */
export type DurationDraft = { kind: "duration"; amount: string; unit: string };
export type Value = string | number | string[] | DurationDraft | null;

const UNIT_LABELS: Record<string, string> = { hours: "Hours", days: "Days", weeks: "Weeks", months: "Months", years: "Years" };

function durationAmount(d: DurationDraft): number | null {
  const n = Number(d.amount.trim().replace(",", "."));
  return d.amount.trim() !== "" && Number.isFinite(n) && n >= 0 ? n : null;
}

/** The answer field a problem belongs to: the duration's amount or unit (API fields value.amount / value.unit), or the
 * answer as a whole ("answer": the choice group, the scale or the text field; #404). */
export type AnswerField = "amount" | "unit" | "answer";
type Problem = { field: AnswerField; message: string };

/** Field-specific problem with a duration answer, or null when it can be sent (R13). */
export function durationProblem(q: S["Question"], v: Value): Problem | null {
  if (q.response_type !== "duration") return null;
  const d = v as DurationDraft | null;
  if (!d || d.amount.trim() === "") return { field: "amount", message: "Enter how long, as a number." };
  if (durationAmount(d) === null) return { field: "amount", message: "How long must be a number of 0 or more." };
  if (!d.unit) return { field: "unit", message: "Choose a unit." };
  if (!q.constraints.allowed_units.includes(d.unit as never)) return { field: "unit", message: "Choose one of the listed units." };
  return null;
}

/** The AnswerWrite value for an answered question. */
export function answerPayload(q: S["Question"], v: Value): S["AnswerWrite"]["value"] {
  if (q.response_type === "duration") {
    const d = v as DurationDraft;
    return { amount: durationAmount(d) as number, unit: d.unit } as S["AnswerWrite"]["value"];
  }
  if (q.response_type === "text") return String(v).trim();
  return v as S["AnswerWrite"]["value"];
}

// #245: a cool-to-warm ramp for a 0-10 scale (green, teal, sky, blue, violet, rose, coral). The numbers and anchors stay;
// each colour is 4:1 or more on the surface, and the selected numeral is large text on it (scripts/check_contrast.py).
// #245: each value takes a step of the cool-to-warm ramp in styles.css (--scale-0 to --scale-10).
function scaleColour(n: number, min: number, max: number): string {
  const i = max > min ? Math.round(((n - min) / (max - min)) * 10) : 0;
  return `var(--scale-${Math.min(10, Math.max(0, i))})`;
}

// Reserved synthetic fixture trigger (ADR-008). Honored by the server only in mock mode during intake.
const URGENT_FIXTURE_TRIGGER = ["fixture:urgent-signal"];

export function AnswerInput({ q, value, onChange, invalid, errorId }: {
  q: S["Question"]; value: Value; onChange: (v: Value) => void; invalid?: AnswerField | null; errorId?: string;
}) {
  // #404: an answer error is tied to the whole answer (the group, the scale or the text field), as on A01-A03 and A09:
  // aria-invalid on the control and the error named by aria-describedby, so it is read when the person returns to it.
  const whole = invalid === "answer" && errorId ? errorId : null;
  const describedBy = (own: string) => (whole ? `${own} ${whole}` : own);
  if (q.response_type === "single_choice")
    return (
      <fieldset aria-describedby={describedBy(`how-${q.id}`)} aria-invalid={whole ? true : undefined}>
        <legend className="sr-only">{q.text}</legend>
        {/* #229: say how many answers the question takes. */}
        <p className="hint choose-how" id={`how-${q.id}`}>Choose one</p>
        {q.choices.map((c) => (
          <label className="choice" key={c.id}>
            <input type="radio" name={q.id} checked={value === c.id} onChange={() => onChange(c.id)} />
            {c.label}
          </label>
        ))}
      </fieldset>
    );
  if (q.response_type === "multiple_choice") {
    const selected = Array.isArray(value) ? value : [];
    return (
      <fieldset aria-describedby={describedBy(`how-${q.id}`)} aria-invalid={whole ? true : undefined}>
        <legend className="sr-only">{q.text}</legend>
        <p className="hint choose-how" id={`how-${q.id}`}>Choose all that apply</p>
        {q.choices.map((c) => (
          <label className="choice" key={c.id}>
            <input
              type="checkbox"
              checked={selected.includes(c.id)}
              onChange={(e) => {
                if (!e.target.checked) return onChange(selected.filter((id) => id !== c.id));
                if (c.exclusive) return onChange([c.id]);
                const exclusive = new Set(q.choices.filter((x) => x.exclusive).map((x) => x.id));
                onChange([...selected.filter((id) => !exclusive.has(id)), c.id]);
              }}
            />
            {c.label}
          </label>
        ))}
      </fieldset>
    );
  }
  if (q.response_type === "duration") {
    const d: DurationDraft = value && typeof value === "object" && !Array.isArray(value) ? value : { kind: "duration", amount: "", unit: "" };
    return (
      <fieldset aria-invalid={whole ? true : undefined} aria-describedby={whole ?? undefined}>
        <legend className="sr-only">{q.text}</legend>
        <div className="grid2">
          <div className="field">
            <label htmlFor={`duration-amount-${q.id}`}>How long (number)</label>
            <input id={`duration-amount-${q.id}`} name="value.amount" inputMode="decimal" autoComplete="off" value={d.amount}
              aria-invalid={invalid === "amount" || undefined} aria-describedby={invalid === "amount" ? errorId : undefined}
              onChange={(e) => onChange({ ...d, amount: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor={`duration-unit-${q.id}`}>Unit</label>
            <select id={`duration-unit-${q.id}`} name="value.unit" value={d.unit}
              aria-invalid={invalid === "unit" || undefined} aria-describedby={invalid === "unit" ? errorId : undefined}
              onChange={(e) => onChange({ ...d, unit: e.target.value })}>
              <option value="">Choose a unit</option>
              {q.constraints.allowed_units.map((u) => (
                <option key={u} value={u}>
                  {UNIT_LABELS[u] ?? u}
                </option>
              ))}
            </select>
          </div>
        </div>
      </fieldset>
    );
  }
  if (q.response_type === "scale") {
    const min = q.constraints.minimum ?? 0;
    const max = q.constraints.maximum ?? 10;
    // #228: one tap per value instead of a dropdown; the ends' meanings sit under the row. Native radios, so the
    // keyboard (arrow keys) and screen readers get a standard radio group.
    return (
      <fieldset className="scale" aria-describedby={describedBy(`anchors-${q.id}`)} aria-invalid={whole ? true : undefined}>
        <legend className="sr-only">
          {q.text} ({min} to {max})
        </legend>
        <p className="hint choose-how">Choose a number from {min} to {max}</p>
        <div className="scale-options">
          {Array.from({ length: max - min + 1 }, (_, i) => min + i).map((n) => (
            <label key={n} className={`scale-option${value === n ? " selected" : ""}`}
              style={{ "--scale-c": scaleColour(n, min, max) } as CSSProperties}>
              <input type="radio" name={`scale-${q.id}`} value={n} checked={value === n} onChange={() => onChange(n)} />
              <span>{n}</span>
            </label>
          ))}
        </div>
        <p className="scale-anchors" id={`anchors-${q.id}`}>
          <span>
            {min} = {q.constraints.lower_anchor}
          </span>
          <span>
            {max} = {q.constraints.upper_anchor}
          </span>
        </p>
      </fieldset>
    );
  }
  // #404: the label names the question (shown on screen as "Your answer"), so in forms mode the field is announced with it.
  return (
    <div className="field">
      <label htmlFor={`text-${q.id}`}>
        Your answer<span className="sr-only"> to: {q.text}</span>
      </label>
      <textarea id={`text-${q.id}`} maxLength={q.constraints.max_characters ?? 2000}
        aria-invalid={whole ? true : undefined} aria-describedby={whole ?? undefined}
        value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

/** #357: an earlier issued question with its current answer, as nextQuestion returns them (slot order). */
export type Earlier = { question: S["Question"]; answer: S["Answer"] };

/** The question's own "Not sure" choice, if it offers one (#185: choosing it records status unknown). */
function notSureChoice(q: S["Question"]) {
  return (q.choices ?? []).find((c) => c.label.trim().toLowerCase() === "not sure");
}

/** #357: a saved answer as the input shows it: the stored value, the question's "Not sure" choice for an unknown answer
 * where it offers one, and nothing for a skipped one. */
export function savedValue(q: S["Question"], a: S["Answer"]): Value {
  if (a.status === "unknown") {
    const ns = notSureChoice(q);
    return ns ? (q.response_type === "multiple_choice" ? [ns.id] : ns.id) : null;
  }
  if (a.status !== "answered" || a.value === null) return null;
  if (q.response_type === "duration" && typeof a.value === "object" && !Array.isArray(a.value))
    return { kind: "duration", amount: String(a.value.amount), unit: a.value.unit };
  return a.value as Value;
}

/** #357: whether sending (status, value) would store exactly the saved answer again. */
function sameAnswer(a: S["Answer"], status: S["AnswerWrite"]["status"], value: S["AnswerWrite"]["value"]): boolean {
  if (a.status !== status) return false;
  if (status !== "answered") return true;
  const norm = (v: unknown) => JSON.stringify(Array.isArray(v) ? [...v].sort() : v);
  return norm(a.value) === norm(value);
}

export function hasValue(q: S["Question"], v: Value): boolean {
  if (q.response_type === "duration") return durationProblem(q, v) === null;
  if (q.response_type === "multiple_choice") return Array.isArray(v) && v.length > 0;
  if (q.response_type === "text") return typeof v === "string" && v.trim().length > 0;
  return v !== null && v !== "";
}

export default function A05() {
  const { caseId = "" } = useParams();
  const navigate = useNavigate();
  const { rememberQuestion } = useAppState();
  const [question, setQuestion] = useState<S["Question"] | null>(null);
  const [revision, setRevision] = useState<number | null>(null);
  const [value, setValue] = useState<Value>(null);
  const [error, setError] = useState<unknown>(null);
  const [validation, setValidation] = useState<string | null>(null);
  const [invalidField, setInvalidField] = useState<AnswerField | null>(null);
  const [conflict, setConflict] = useState(false);
  const [pending, setPending] = useState(false);
  // #281: the shown question's answer is saved and the next question is being (or failed to be) loaded. A failure then
  // retries the load only, at the revision the save returned; it never sends the answer again.
  const [saved, setSaved] = useState(false);
  // The last answer that failed to send for another reason, so "Try again" re-sends exactly that.
  const lastSend = useRef<{ status: S["AnswerWrite"]["status"]; fixture?: string[] } | null>(null);
  const fetchKey = useRef<{ rev: number; key: string } | null>(null);
  // #357: the earlier issued questions with their current answers (from nextQuestion), and which one is shown instead
  // of the current question (null: the current one). The current question's unsent choice is kept in memory meanwhile.
  const [earlier, setEarlier] = useState<Earlier[]>([]);
  const [back, setBack] = useState<number | null>(null);
  const draft = useRef<{ questionId: string; value: Value } | null>(null);

  // `knownRevision`: the revision a save just returned (#204). The case is in intake, so the next question is asked for
  // at once; only a fresh load reads the case and its allowed actions first.
  const load = useCallback(async (knownRevision?: number) => {
    setError(null);
    setConflict(false);
    try {
      let rev = knownRevision;
      if (rev === undefined) {
        const read = await api.getCase(caseId);
        if (!read.allowed_actions.includes("next_question")) {
          navigate(screenForState(caseId, read.case.state, read.allowed_actions), { replace: true });
          return;
        }
        rev = read.case.revision;
      }
      if (fetchKey.current?.rev !== rev) fetchKey.current = { rev, key: crypto.randomUUID() };
      const next = await api.nextQuestion(caseId, rev, fetchKey.current.key);
      setRevision(next.case_revision);
      if (next.kind === "review_required") {
        navigate(`/app/cases/${caseId}/review`, { replace: true });
        return;
      }
      // A06 can then change the earlier answers with their choices. The current question goes last: the runtime mode
      // shown elsewhere follows the most recently remembered question.
      const before = next.earlier_questions ?? [];
      before.forEach((e) => rememberQuestion(e.question));
      rememberQuestion(next.question);
      setEarlier(before);
      setBack(null);
      setQuestion(next.question);
      setSaved(false);
      // #357: coming back from an earlier question restores what was chosen here and not yet sent.
      setValue(draft.current?.questionId === next.question.id ? draft.current.value : null);
      draft.current = null;
    } catch (err) {
      setError(err);
    }
  }, [caseId, navigate, rememberQuestion]);

  useEffect(() => {
    void load();
  }, [load]);

  // #348: while a question is shown, its line is the one progress indicator on phones ("Step 4 of 8 · Question n of
  // up to 10" and one bar); the journey's own phone line and bar give way. #343: an issued question means no guidance.
  const showsQuestion = question !== null && !(error instanceof ApiError && error.status === 404)
    && !(saved && (error != null || !pending));
  useJourneyInPage(showsQuestion);
  useJourneyCase(caseId, question ? false : undefined);
  const step = stepOf(useLocation().pathname);

  const viewing = back === null ? null : earlier[back] ?? null;
  const shown = viewing?.question ?? question;

  /** #357: show an earlier question (index into `earlier`) or, with null, the current one again. */
  function show(index: number | null) {
    if (back === null && index !== null && question) draft.current = { questionId: question.id, value };
    setValidation(null);
    setInvalidField(null);
    setConflict(false);
    setError(null);
    lastSend.current = null;
    setBack(index);
    if (index === null) {
      setValue(draft.current?.questionId === question?.id ? draft.current!.value : null);
      draft.current = null;
    } else setValue(savedValue(earlier[index].question, earlier[index].answer));
  }

  async function send(status: S["AnswerWrite"]["status"], fixture?: string[]) {
    const question = shown;
    if (!question || revision === null) return;
    // #185: choosing the question's own "Not sure" choice records uncertainty (status unknown), exactly as the
    // separate button does where a question has no such choice, so it still counts as a gap (R13, R14).
    const notSure = (question.choices ?? []).find((c) => c.label.trim().toLowerCase() === "not sure");
    const onlyNotSure = notSure && (Array.isArray(value) ? value.length === 1 && value[0] === notSure.id : value === notSure.id);
    if (status === "answered" && !fixture && onlyNotSure) status = "unknown";
    if (status === "answered" && !fixture && !hasValue(question, value)) {
      const problem = durationProblem(question, value);
      setValidation(problem?.message ?? "Choose or enter an answer, or use “Not sure” or “Skip”.");
      setInvalidField(problem?.field ?? "answer");
      return;
    }
    setValidation(null);
    setInvalidField(null);
    setError(null);
    const payload = fixture ?? (status === "answered" ? answerPayload(question, value) : null);
    // #357: an earlier answer sent unchanged is not saved again; the page returns to the current question.
    if (viewing && !fixture && sameAnswer(viewing.answer, status, payload)) return show(null);
    setPending(true);
    lastSend.current = { status, fixture };
    try {
      const body: S["AnswerWrite"] = { expected_revision: revision, status, value: payload } as S["AnswerWrite"];
      const result = await api.saveAnswer(caseId, question.id, body);
      lastSend.current = null;
      if (result.next_action === "urgent") return navigate(`/app/cases/${caseId}/urgent`);
      if (result.next_action === "limited") return navigate("/app/limits");
      // #281: the save moved the case on; keep its revision at once, so nothing later re-uses the old one.
      setRevision(result.case_revision);
      setSaved(true);
      // "review" also goes through nextQuestion: the server moves intake -> review only when it
      // reports review_required, and load() then routes to A06 with the review confirmable.
      await load(result.case_revision);
    } catch (err) {
      if (err instanceof ApiError && err.code === "REVISION_CONFLICT") setConflict(true);
      else if (err instanceof ApiError && err.status === 422) {
        const field = err.body?.field_errors?.[0]?.field;
        setInvalidField(field === "value.unit" ? "unit" : field === "value.amount" ? "amount" : "answer");
        setValidation(field === "value.unit" ? "That unit is not accepted for this question. Choose one of the listed units." : err.message);
      }
      else setError(err);
    } finally {
      setPending(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void send("answered");
  }

  if (error instanceof ApiError && error.status === 404)
    return <CaseUnavailable />;
  if (error != null && !question) return <ErrorBanner error={error} onRetry={() => void load()} />;
  if (!question) return <LoadingState label="Preparing your next question" />;
  if (saved && error != null)
    return (
      <div className="narrow">
        <PageHead eyebrow="Questions" title="Your answer was saved" />
        <p>The next question did not load. Your answer is kept; trying again only loads the next question.</p>
        <ErrorBanner error={error} onRetry={() => void load(revision ?? undefined)} />
      </div>
    );
  if (saved && !pending) return <LoadingState label="Preparing your next question" />;
  const mock = question.pathway_version.startsWith("mock-");
  const q = shown!;
  const offersNotSure = notSureChoice(q) !== undefined;
  // "Previous question" from question 2 on, and again on an earlier question while one before it exists.
  const previousIndex = back === null ? earlier.length - 1 : back - 1;
  return (
    <div className="narrow">
      <PageHead
        eyebrow={
          // #348: on phones the step joins the question line (the step list says it for screen readers).
          <span>
            {step && <span className="step-phone" aria-hidden="true">{`${step} · `}</span>}
            <span>{`Question ${q.slot} of up to 10`}</span>
          </span>
        }
        // A new key per shown question: the heading takes focus on every switch, also between equal wordings.
        key={q.id}
        title={q.text}>
        {q.reason && <p>{q.reason}</p>}
        {viewing && (
          // #357: the reviewed pathway's question order does not depend on answers, so no later answer is dropped.
          <p className="earlier-note">
            {viewing.answer.status === "skipped" ? "You skipped this question. "
              : viewing.answer.status === "unknown" ? "You answered “Not sure”. " : "Your saved answer is filled in. "}
            Changing it keeps your later answers and the questions that follow.
          </p>
        )}
      </PageHead>
      <div className="progress" aria-hidden="true">
        <i style={{ width: `${q.slot * 10}%` }} />
      </div>
      {conflict && (
        <StatusBanner tone="warn" title="This consultation changed elsewhere.">
          <p>Your answer was not saved. Reload to see the current version.</p>
          <button type="button" className="btn secondary sm" onClick={() => void load()}>
            Reload
          </button>
        </StatusBanner>
      )}
      {error != null && (
        <ErrorBanner error={error} onRetry={lastSend.current
          ? () => void send(lastSend.current!.status, lastSend.current!.fixture)
          : () => void load(revision ?? undefined)} />
      )}
      <form className="card question-card" onSubmit={submit} noValidate>
        <AnswerInput key={q.id} q={q} value={value} onChange={(v) => { setValue(v); setInvalidField(null); }}
          invalid={invalidField} errorId="answer-error" />
        {validation && (
          <p className="field-error" role="alert" id="answer-error">
            {validation}
          </p>
        )}
        <div className="actions">
          <div className="row">
            {/* #185: no second "Not sure" when the question already offers it as a choice (the choice is its answer). */}
            {!offersNotSure && (
              <button type="button" className="btn secondary" onClick={() => send("unknown")} disabled={pending}>
                Not sure
              </button>
            )}
            <button type="button" className="btn secondary" onClick={() => send("skipped")} disabled={pending}>
              Skip
            </button>
          </div>
          <Button type="submit" pending={pending}>
            Submit answer
          </Button>
        </div>
        {(previousIndex >= 0 || viewing) && (
          <div className="row earlier-nav">
            {previousIndex >= 0 && (
              <button type="button" className="btn secondary sm" disabled={pending} onClick={() => show(previousIndex)}>
                Previous question
              </button>
            )}
            {viewing && (
              <button type="button" className="btn secondary sm" disabled={pending} onClick={() => show(null)}>
                {`Back to question ${question.slot}`}
              </button>
            )}
          </div>
        )}
      </form>
      <p className="small muted">
        {mock ? (
          <>
            <span className="badge amber">Mock mode</span> Questions come from a fixed synthetic demo script; you may
            finish before 10.
          </>
        ) : (
          // #291: the reviewed pathway has no early stop, so local mode never promises finishing sooner.
          "Questions come from the reviewed pathway, up to 10 in all."
        )}
      </p>
      {mock && (
        <section className="card" aria-labelledby="urgent-sim">
          <h2 id="urgent-sim">Explore a safety interruption</h2>
          <p className="small">
            A preset synthetic urgent signal stops the routine pathway. It replaces this question’s answer and does not
            assess anything you typed.
          </p>
          <button type="button" className="btn secondary" disabled={pending}
            onClick={() => send("answered", URGENT_FIXTURE_TRIGGER)}>
            Simulate urgent answer
          </button>
        </section>
      )}
    </div>
  );
}
