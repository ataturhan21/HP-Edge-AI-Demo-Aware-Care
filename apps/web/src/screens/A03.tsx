// A03 Describe concern (M03; R07, R08, R15). Required concern and red-flag checklist (ADR-003); the server
// decides intake, urgent or limited. In local mode the server also screens the concern for warning signs (#153), so a
// written emergency goes to urgent help at once, with the reviewed level the server recorded; and (#154) text that
// describes no health matter at all is refused, so the person is asked here to describe a health concern.
// #342: a failed Continue shows an error summary at the top of the form and moves focus to it; the field messages stay
// next to their fields, without role="alert", so the problems are announced once (through the focused summary).
// #392 (R15): a ticked warning sign goes to urgent help at once, even when no concern is written; the server stores the
// case as urgent with an empty concern. #408: the form is shown only once the session is confirmed (A01 otherwise).
// #412: when this page has no profile from A02 (for example after a reload), it says so before the case is created.
// #594: a create that finishes after the person left the form does not navigate (the case is in History).
// #630 (owner decision): when that late result is urgent, a notice on whatever page they are on links to its urgent help.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { ErrorSummary, type ErrorSummaryItem } from "../components/ErrorSummary";
import { RED_FLAGS_KIND, RedFlagChecklist, redFlagContext, type RedFlagAnswer } from "../components/RedFlags";
import { Button, ErrorBanner, LoadingState, PageHead, StatusBanner } from "../components/ui";
import { useAppState } from "../state/AppState";

// #305, #452: whitespace, control and format characters, the other default-ignorable characters (such as U+00AD, the
// Hangul fillers or variation selectors) and the Braille blank U+2800 are not a concern; the server uses the same set.
const BLANK = /[\p{White_Space}\p{Cc}\p{Cf}\p{Default_Ignorable_Code_Point}\u2800]/gu;

/** #305: true when the text has at least one visible character. */
export function hasConcernText(text: string): boolean {
  return text.replace(BLANK, "") !== "";
}

export default function A03() {
  const navigate = useNavigate();
  const { sessionContext, runtimeMode, noteLateUrgent } = useAppState();
  const [concern, setConcern] = useState("");
  const [empty, setEmpty] = useState(false);
  const [notHealth, setNotHealth] = useState(false);
  // #342: the concern text the server refused as not a health matter; its summary item closes once the text changes.
  const [refused, setRefused] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [flags, setFlags] = useState<RedFlagAnswer>(null);
  const [flagsMissing, setFlagsMissing] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const key = useRef(crypto.randomUUID());
  // #594: whether this form is still shown. A create whose response arrives after the person went elsewhere (Help, the
  // header, Back) stays in History but never takes them away from the page they chose.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  // #408 (A03 access guard): a valid session with current consent is confirmed before any entry. Without one, the
  // server's 401 sends the person to A01 (the shared handler), so nothing typed here is lost.
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    let live = true;
    api.getProfile().then(
      () => live && setChecked(true),
      (e) => {
        if (!live || (e instanceof ApiError && e.status === 401)) return;
        setError(e);
        setChecked(true);
      },
    );
    return () => {
      live = false;
    };
  }, []);
  // #412: the A02 profile lives in this tab's memory only; a reload or a direct visit has none.
  const noProfile = sessionContext.length === 0;
  const ticked = Array.isArray(flags) && flags.length > 0;

  async function submit(e: FormEvent) {
    e.preventDefault();
    // #392: a ticked warning sign needs no concern text; urgent help comes first.
    const blank = !hasConcernText(concern) && !ticked;
    setEmpty(blank);
    setFlagsMissing(flags === null);
    if (blank || flags === null) {
      setAttempt((n) => n + 1);
      return;
    }
    setPending(true);
    setError(null);
    setNotHealth(false);
    setRefused(null);
    try {
      const context = [...sessionContext.filter((c) => c.kind !== RED_FLAGS_KIND), redFlagContext(flags)];
      const text = hasConcernText(concern) ? concern.trim() : "";
      const created = await api.createCase({ concern: text, confirmed_context: context }, key.current);
      if (!mounted.current) {
        if (created.state === "urgent") noteLateUrgent({ caseId: created.id, level: created.urgent_level ?? null });
        return;
      }
      if (created.state === "urgent")
        navigate(`/app/cases/${created.id}/urgent`, { state: created.urgent_level ? { level: created.urgent_level } : null });
      else if (created.state === "limited") navigate("/app/limits", { state: { reason: "service_unavailable" } });
      else navigate(`/app/cases/${created.id}/records`);
    } catch (err) {
      const fields = err instanceof ApiError ? (err.body?.field_errors ?? []) : [];
      if (fields.some((f) => f.field === "concern" && f.code === "not_health_concern")) {
        setNotHealth(true);
        setRefused(concern);
        setAttempt((n) => n + 1);
      } else if (fields.some((f) => f.field === "concern" && f.code === "empty")) {
        // #452: the server found no visible character; the same field error as an empty field.
        setEmpty(true);
        setAttempt((n) => n + 1);
      } else setError(err);
    } finally {
      setPending(false);
    }
  }

  // #342: the problems from the last Continue that are still open. Each closes as soon as it is fixed.
  const problems: ErrorSummaryItem[] = [];
  if (empty && !hasConcernText(concern) && !ticked) problems.push({ target: "concern", text: "Describe your main concern" });
  else if (notHealth && refused === concern)
    problems.push({ target: "concern", text: "Describe a symptom or health question in your main concern" });
  if (flagsMissing) problems.push({ target: "red-flags-first", text: "Answer whether any warning signs apply to you" });

  if (!checked) return <LoadingState label="Checking your session" />;
  const showEmpty = empty && !ticked;
  return (
    <div className="narrow">
      <PageHead eyebrow="Your concern" title="What would you like help with?">
        <p>Describe one main concern in your own words.</p>
      </PageHead>
      <StatusBanner tone="info" title="Synthetic demonstration">
        {/* #236: plain words, and only the way this demo runs once that is known in this tab (#98: never claimed
            before a server response proves it). */}
        <p>
          Use fictional details only.{" "}
          {runtimeMode === "local"
            ? "The AI model on this device reads what you write and your answers."
            : runtimeMode === "mock"
              ? "This demo is running a scripted scenario: the result follows the scenario, and what you write is not analysed."
              : "Depending on how this demo is running, either the AI model on this device reads what you write, or a scripted scenario chooses the result."}
        </p>
      </StatusBanner>
      {noProfile && (
        <StatusBanner tone="info" title="No profile details on this page">
          <p>
            Age, history, medications and allergies are not available here (for example after the page was reloaded),
            so none will be used for this consultation, and they cannot be added to it later.{" "}
            <Link to="/app/profile">Add profile details first</Link>, or continue without them.
          </p>
        </StatusBanner>
      )}
      {error != null && <ErrorBanner error={error} />}
      <form className="card concern-card" onSubmit={submit} noValidate>
        <ErrorSummary items={problems} attempt={attempt} />
        <div className="field">
          <label htmlFor="concern">Main concern</label>
          <span className="hint" id="concern-hint">
            For example, how it affects your day and when it started. Up to 4,000 characters.
          </span>
          <textarea id="concern" maxLength={4000} value={concern} onChange={(e) => setConcern(e.target.value)}
            aria-describedby={showEmpty || notHealth ? "concern-hint concern-error" : "concern-hint"}
            aria-invalid={showEmpty || notHealth || undefined} />
          {showEmpty && (
            <span id="concern-error" className="field-error">
              Describe your main concern to continue.
            </span>
          )}
          {!showEmpty && notHealth && (
            <span id="concern-error" className="field-error">
              We could not find a health concern in this description. Describe a symptom or health question, for
              example what you notice and since when.
            </span>
          )}
        </div>
        <RedFlagChecklist value={flags} onChange={(next) => { setFlags(next); setFlagsMissing(false); }} error={flagsMissing}
          announce={false} />
        <div className="actions">
          <button type="button" className="btn secondary" onClick={() => navigate("/app/profile")}>
            Back to profile
          </button>
          <Button type="submit" pending={pending}>
            Continue
          </Button>
        </div>
      </form>
    </div>
  );
}
