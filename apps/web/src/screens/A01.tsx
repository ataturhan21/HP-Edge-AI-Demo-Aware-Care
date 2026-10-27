// A01 Start and consent (M01; R01, R02). Server assigns actor and role; decline/age route to A16.
// #342: a failed "Accept and begin" shows an error summary at the top of the form and moves focus to it; the message
// above the buttons stays, without role="alert", so the problem is announced once (through the focused summary).
import { useRef, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { ErrorSummary, type ErrorSummaryItem } from "../components/ErrorSummary";
import { Icon } from "../components/Icon";
import { Button, ErrorBanner, PageHead, StatusBanner } from "../components/ui";
import { ResumeSession } from "../components/ResumeSession";
import { useAppState } from "../state/AppState";

export const CONSENT_VERSION = "aware-care-demo-consent-1.0";

export default function A01() {
  const navigate = useNavigate();
  const location = useLocation();
  const { setSession } = useAppState();
  const [adult, setAdult] = useState<"" | "yes" | "no">("");
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [validation, setValidation] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const key = useRef(crypto.randomUUID());
  const expired = (location.state as { expired?: boolean } | null)?.expired;
  const reset = (location.state as { reset?: boolean } | null)?.reset;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (adult === "no") return navigate("/app/limits", { state: { reason: "unsupported_age" } });
    if (!adult || !consent) {
      setValidation("Confirm your age and accept the consent to continue.");
      setAttempt((n) => n + 1);
      return;
    }
    setValidation(null);
    setPending(true);
    setError(null);
    try {
      const body = { mode: "guest", consent_version: CONSENT_VERSION, adult_eligible: true } as const;
      let session;
      try {
        session = await api.createSession(body, key.current);
      } catch (err) {
        // A direct load or refresh of this route makes no earlier /api call, so the HttpOnly
        // pre-session nonce may be missing. Any API response issues it; retry once (same key).
        if (!(err instanceof ApiError && err.code === "PRESESSION_REQUIRED")) throw err;
        await api.readiness().catch(() => undefined);
        session = await api.createSession(body, key.current);
      }
      setSession(session);
      navigate("/app/profile");
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }

  // #342: the problems from the last attempt that are still open. Each closes as soon as it is fixed.
  const problems: ErrorSummaryItem[] = [];
  if (validation && !adult) problems.push({ target: "adult-yes", text: "Answer whether you are 18 or older" });
  if (validation && !consent) problems.push({ target: "consent", text: "Tick “I understand and accept these terms.”" });

  return (
    <div className="narrow">
      <PageHead eyebrow="Start" title="Before you begin">
        <p>Aware Care is a demonstration for adults. Please do not enter real health information.</p>
      </PageHead>
      {expired && (
        <StatusBanner tone="warn" title="Your session ended">
          <p>
            For privacy, your earlier demo information is no longer available. Accept below to start a new
            consultation.
          </p>
        </StatusBanner>
      )}
      {reset && (
        // #290: the server accepted the deletion (202); it is reported as under way, never as finished.
        <StatusBanner tone="info" title="Session ended">
          <p>
            Its synthetic cases, answers and summaries are being deleted from this device. Accept below to start a new
            consultation.
          </p>
        </StatusBanner>
      )}
      {error != null && <ErrorBanner error={error} />}
      {!expired && !reset && <ResumeSession />}
      <form className="card" onSubmit={submit} noValidate>
        <ErrorSummary items={problems} attempt={attempt} />
        <fieldset aria-describedby={validation && !adult ? "consent-error" : undefined}>
          <legend>Are you 18 or older?</legend>
          <label className="choice">
            <input type="radio" id="adult-yes" name="adult" checked={adult === "yes"} onChange={() => setAdult("yes")} /> Yes, I am 18 or
            older
          </label>
          <label className="choice">
            <input type="radio" name="adult" checked={adult === "no"} onChange={() => setAdult("no")} /> No
          </label>
        </fieldset>
        {/* #212: guest is the only mode this build offers, so it is stated, not offered as a one-option choice. */}
        <section className="mode-note" aria-labelledby="mode-heading">
          <h2 id="mode-heading">You'll continue as a guest</h2>
          <p>What you enter is kept only for this session and deleted when it ends.</p>
          <p className="hint">Saved accounts need an approved local sign-in, which this demo build does not provide.</p>
        </section>
        {/* #255: violet while open; green with a check once the terms are accepted. */}
        <div className={`card consent-box accent-card ${consent ? "acc-green accepted" : "acc-violet"}`}>
          <h2 className="card-title">
            <span className="card-icon" aria-hidden="true"><Icon name={consent ? "check" : "shield"} size={18} /></span>
            Please read and agree
          </h2>
          <p className="small muted consent-version">Consent version {CONSENT_VERSION}</p>
          <ul className="bullets">
            <li>This is a synthetic demonstration, not medical advice, diagnosis or treatment.</li>
            <li>Information you enter is processed on this local device and deleted when your guest session ends.</li>
            <li>In an emergency, call 911 instead of using this demo.</li>
          </ul>
          <label className="check">
            <input type="checkbox" id="consent" checked={consent} onChange={(e) => setConsent(e.target.checked)}
              aria-invalid={(validation && !consent) || undefined}
              aria-describedby={validation && !consent ? "consent-error" : undefined} />I understand and
            accept these terms.
          </label>
        </div>
        {validation && (
          <p className="field-error" id="consent-error">
            {validation}
          </p>
        )}
        <div className="actions">
          <button type="button" className="btn secondary" onClick={() => navigate("/app/limits", { state: { reason: "declined" } })}>
            Decline
          </button>
          <Button type="submit" pending={pending}>
            Accept and begin
          </Button>
        </div>
      </form>
    </div>
  );
}
