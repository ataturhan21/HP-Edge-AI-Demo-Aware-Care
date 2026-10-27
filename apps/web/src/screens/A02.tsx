// A02 Health profile (M02; R04-R06). Unknown is explicit; guests use details for this session only.
// #344: "Skip — continue without a profile" near the top continues exactly as "Use for this session" with every field
// blank and allergies unknown (the same session context, no new request); it asks first if something was entered.
// #410: leaving with unsaved entries asks first (an in-app confirmation for links, the browser's own for reload/close).
// #451: the age is a whole number written in digits only; "0x1A", "1e2" or "25.0" get the field error.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBlocker, useNavigate } from "react-router-dom";
import { api, type S } from "../api/client";
import { ConfirmDialog, ErrorBanner, LoadingState, PageHead, StatusBanner } from "../components/ui";
import { useAppState } from "../state/AppState";

type Allergy = "unknown" | "none_reported" | "reported";

/** The session context A02 hands to A03; a blank field is unknown (null), never a negative fact. */
function profileContext(ageNum: number | null, history: string, medications: string, allergyStatus: Allergy,
  allergies: string): S["ConfirmedContextWrite"][] {
  const items: S["ConfirmedContextWrite"][] = [
    { kind: "age_years", value: ageNum, units: ageNum === null ? null : "years", origin: "user", profile_revision: null },
    { kind: "history", value: history.trim() || null, units: null, origin: "user", profile_revision: null },
    { kind: "medications", value: medications.trim() || null, units: null, origin: "user", profile_revision: null },
    { kind: "allergy_status", value: allergyStatus, units: null, origin: "user", profile_revision: null },
  ];
  if (allergyStatus === "reported") {
    items.push({ kind: "allergies", value: allergies.trim(), units: null, origin: "user", profile_revision: null });
  }
  return items;
}

export default function A02() {
  const navigate = useNavigate();
  const { sessionContext, setSessionContext } = useAppState();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const initial = (kind: string) => sessionContext.find((c) => c.kind === kind)?.value;
  const [age, setAge] = useState(String(initial("age_years") ?? ""));
  const [history, setHistory] = useState(String(initial("history") ?? ""));
  const [medications, setMedications] = useState(String(initial("medications") ?? ""));
  const [allergyStatus, setAllergyStatus] = useState<Allergy>((initial("allergy_status") as Allergy) ?? "unknown");
  const [allergies, setAllergies] = useState(String(initial("allergies") ?? ""));
  const [dirty, setDirty] = useState(false);
  const [ageError, setAgeError] = useState<string | null>(null);
  // #287: each submit with "I have allergies to report" and no allergy announces the error and moves focus to the field.
  const [allergyAttempt, setAllergyAttempt] = useState(0);
  const allergiesRef = useRef<HTMLInputElement>(null);
  const [confirmSkip, setConfirmSkip] = useState(false);
  const hasEntries = age.trim() !== "" || history.trim() !== "" || medications.trim() !== "" || allergyStatus !== "unknown";
  // #410: set just before this page's own navigation (Use for this session, Skip), which is never blocked.
  const leaving = useRef(false);
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    dirty && !leaving.current && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {
    api
      .getProfile()
      .then(() => setLoading(false))
      .catch((e) => {
        setError(e);
        setLoading(false);
      });
  }, []);

  function submit(e: FormEvent) {
    e.preventDefault();
    const ageText = age.trim();
    const ageNum = ageText === "" ? null : /^[0-9]+$/.test(ageText) ? Number(ageText) : NaN;
    if (ageNum !== null && (!Number.isInteger(ageNum) || ageNum < 18 || ageNum > 130)) {
      setAgeError("Enter a whole number from 18 to 130, or leave it blank if unknown.");
      return;
    }
    if (allergyStatus === "reported" && !allergies.trim()) {
      setAgeError(null);
      setAllergyAttempt((n) => n + 1);
      allergiesRef.current?.focus();
      return;
    }
    setSessionContext(profileContext(ageNum, history, medications, allergyStatus, allergies));
    setDirty(false);
    leaving.current = true;
    navigate("/app/new");
  }

  // #344: exactly what "Use for this session" hands on with every field blank and allergies unknown.
  function skip() {
    setSessionContext(profileContext(null, "", "", "unknown", ""));
    setDirty(false);
    leaving.current = true;
    navigate("/app/new");
  }

  if (loading) return <LoadingState label="Loading your profile" />;
  return (
    <div className="narrow">
      <PageHead eyebrow="Optional profile" title="Health profile">
        <p>Everything here is optional. Blank means unknown, not “none”.</p>
      </PageHead>
      {error != null && <ErrorBanner error={error} />}
      <StatusBanner tone="info" title="Used for this session only">
        <p>Saving a profile needs a saved account, which this demo build does not offer.</p>
      </StatusBanner>
      <div className="skip-profile">
        <button type="button" className="btn secondary" aria-describedby="skip-profile-hint"
          onClick={() => (hasEntries ? setConfirmSkip(true) : skip())}>
          Skip — continue without a profile
        </button>
        <p className="small muted" id="skip-profile-hint">Everything on this page is then treated as unknown.</p>
      </div>
      {confirmSkip && (
        <ConfirmDialog title="Continue without a profile?" confirmLabel="Continue without a profile"
          cancelLabel="Keep my details" onConfirm={skip} onCancel={() => setConfirmSkip(false)}>
          <p>What you entered on this page will not be used. Everything here is then treated as unknown.</p>
        </ConfirmDialog>
      )}
      {blocker.state === "blocked" && (
        <ConfirmDialog title="Leave without using your details?" confirmLabel="Leave this page"
          cancelLabel="Stay on this page" onConfirm={() => blocker.proceed()} onCancel={() => blocker.reset()}>
          <p>What you entered on this page has not been used yet and will be cleared. To keep it, stay and choose “Use for this session”.</p>
        </ConfirmDialog>
      )}
      {dirty && <StatusBanner tone="warn" title="You have unsaved changes on this page." />}
      <form className="card" onSubmit={submit} onChange={() => setDirty(true)} noValidate>
        <div className="field">
          <label htmlFor="age">Age in years</label>
          <input id="age" inputMode="numeric" value={age} onChange={(e) => setAge(e.target.value)}
            aria-describedby={ageError ? "age-error" : undefined} aria-invalid={ageError ? true : undefined} />
          {ageError && (
            <span id="age-error" className="field-error" role="alert">
              {ageError}
            </span>
          )}
        </div>
        <div className="field">
          <label htmlFor="history">Relevant history</label>
          <span className="hint">Leave blank if unknown.</span>
          <textarea id="history" maxLength={500} value={history} onChange={(e) => setHistory(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="medications">Current medications</label>
          <span className="hint">Leave blank if unknown.</span>
          <textarea id="medications" maxLength={500} value={medications} onChange={(e) => setMedications(e.target.value)} />
        </div>
        <fieldset>
          <legend>Allergies</legend>
          {(
            [
              ["unknown", "Unknown"],
              ["none_reported", "None reported"],
              ["reported", "I have allergies to report"],
            ] as const
          ).map(([value, label]) => (
            <label className="choice" key={value}>
              <input type="radio" name="allergy" checked={allergyStatus === value} onChange={() => setAllergyStatus(value)} />
              {label}
            </label>
          ))}
          {allergyStatus === "reported" && (
            <div className="field">
              <label htmlFor="allergies">Allergies to report</label>
              <input id="allergies" ref={allergiesRef} maxLength={500} value={allergies} onChange={(e) => setAllergies(e.target.value)}
                aria-invalid={!allergies.trim() || undefined} aria-describedby={!allergies.trim() ? "allergies-error" : undefined} />
              {!allergies.trim() && (
                <span id="allergies-error" className="field-error" key={allergyAttempt}
                  role={allergyAttempt > 0 ? "alert" : undefined}>
                  Enter at least one allergy, or choose another option.
                </span>
              )}
            </div>
          )}
        </fieldset>
        {/* #213: the reason sits next to the disabled button, as on A06 and A12 (#190). */}
        <p className="small muted" id="save-hint">
          Saving needs a saved account, which this demo build does not offer. Use these details for this session instead.
        </p>
        <div className="actions">
          <button type="button" className="btn secondary" disabled aria-describedby="save-hint">
            Save to profile
          </button>
          <button type="submit" className="btn">
            Use for this session
          </button>
        </div>
      </form>
    </div>
  );
}
