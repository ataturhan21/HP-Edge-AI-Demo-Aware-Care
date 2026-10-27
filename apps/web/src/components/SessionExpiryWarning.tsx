// Guest session expiry warning (M01, M11; R36; #42, ADR-013). Shown in the patient app shell 2 minutes before the
// session ends: the earlier of 30 minutes without activity and 8 hours after it started. "Stay signed in" makes one
// authenticated request, which slides the idle window but can never pass the 8-hour limit. The server stays
// authoritative; when the session has ended, the next request reports it as before.
// #409: the expiry follows the latest one any tab of this browser saw (api/client.ts), and "Your session has ended" is
// shown only after one quiet authenticated read confirms it (401); if the session is still open, that read reports its
// new expiry instead. #399 (WCAG 2.2.1): the public pages (Help, Telemetry, Privacy ...) show the warning too while a
// guest session is open; they learn the expiry from the resume check they already make, so `probe` is off there.
// #586: only a 401 confirms the end. A read that gets no answer (offline, status 0) or another error is not the server
// saying anything: the page says it cannot confirm the session right now and asks again (every 15 s, when the browser
// is back online, or on "Check now") until the server answers; a live session's answer clears the notice.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, currentSessionExpiry, subscribeSessionExpiry, type SessionExpiry } from "../api/client";
import { Button, formatTime } from "./ui";

export const WARN_BEFORE_MS = 2 * 60 * 1000;
export const RECHECK_MS = 15 * 1000;

function remaining(expiry: NonNullable<SessionExpiry>, now: number): number {
  return expiry.expiresAt - (now + expiry.skewMs);
}

function clock(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function SessionExpiryWarning({ probe = true }: { probe?: boolean } = {}) {
  const [expiry, setExpiry] = useState<SessionExpiry>(currentSessionExpiry());
  const [now, setNow] = useState(() => Date.now());
  const [dismissedFor, setDismissedFor] = useState<number | null>(null);
  const [limitFor, setLimitFor] = useState<number | null>(null);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  // #409: the expiry this tab asked the server about once it passed, and whether the server confirmed the end.
  const [checkedFor, setCheckedFor] = useState<number | null>(null);
  const [ended, setEnded] = useState(false);
  // #586: the passed expiry whose check got no answer from the server, and whether a check is in flight.
  const [unconfirmedFor, setUnconfirmedFor] = useState<number | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => subscribeSessionExpiry(setExpiry), []);
  // After a page load the expiry is unknown until an authenticated response arrives; ask once (a load is activity).
  useEffect(() => {
    if (probe && !currentSessionExpiry()) api.probeSession().catch(() => undefined);
  }, [probe]);
  useEffect(() => {
    if (!expiry) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [expiry]);

  const passed = expiry !== null && remaining(expiry, now) <= 0;
  const passedFor = passed ? expiry.expiresAt : null;
  // One quiet read: a 401 confirms the end; a live session answers with its new expiry, which replaces this one.
  const check = useCallback((expiresAt: number) => {
    setCheckedFor(expiresAt);
    setChecking(true);
    api.probeSession().then(
      () => {
        setEnded(false);
        setUnconfirmedFor(null);
      },
      (e) => {
        const confirmed = e instanceof ApiError && e.status === 401;
        setEnded(confirmed);
        setUnconfirmedFor(confirmed ? null : expiresAt);
      },
    ).finally(() => setChecking(false));
  }, []);
  useEffect(() => {
    if (passedFor === null || checkedFor === passedFor) return;
    check(passedFor);
  }, [passedFor, checkedFor, check]);
  // #586: while the end is unconfirmed, ask again until the server answers.
  const unconfirmed = passedFor !== null && unconfirmedFor === passedFor;
  useEffect(() => {
    if (!unconfirmed || checking || passedFor === null) return;
    const again = () => check(passedFor);
    const timer = window.setTimeout(again, RECHECK_MS);
    window.addEventListener("online", again);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("online", again);
    };
  }, [unconfirmed, checking, passedFor, check]);
  // A new session (or a later expiry) clears an earlier end.
  useEffect(() => {
    if (expiry && !passed) setEnded(false);
  }, [expiry, passed]);

  if (ended && (!expiry || passed))
    return (
      <section className="notice warn expiry" role="alert" aria-labelledby="expiry-title">
        <div>
          <strong id="expiry-title">Your session has ended</strong>
          <p>For privacy, a guest session ends after 30 minutes without activity or 8 hours in total. Start a new consultation to continue.</p>
          <Link className="btn sm" to="/app/start">Start a new consultation</Link>
        </div>
      </section>
    );
  if (!expiry) return null;
  const left = remaining(expiry, now);
  if (left > WARN_BEFORE_MS || (left > 0 && dismissedFor === expiry.expiresAt)) return null;
  // #305: the same output whatever the browser locale. #347: the shared 24-hour time style.
  const endsAt = formatTime(expiry.expiresAt - expiry.skewMs);

  // #409: past the expiry this tab knew, while the server is asked: nothing is claimed yet. #586: nor when the server
  // could not be asked; the page says so and keeps asking.
  if (left <= 0)
    return unconfirmed ? (
      <section className="notice expiry" role="status" aria-labelledby="expiry-title">
        <div>
          <strong id="expiry-title">We can't confirm your session right now</strong>
          <p>This page could not check with Aware Care whether your session is still open. Check your connection; the page tries again automatically.</p>
          <div className="row">
            <Button type="button" className="btn secondary sm" pending={checking} onClick={() => check(expiry.expiresAt)}>
              Check now
            </Button>
          </div>
        </div>
      </section>
    ) : null;

  async function stay() {
    if (!expiry) return;
    const before = expiry.expiresAt;
    setPending(true);
    setFailed(false);
    try {
      await api.getSettings();
      const after = currentSessionExpiry();
      // The idle window moved on; if the expiry did not, the 8-hour limit is the one that applies.
      if (after && after.expiresAt <= before + 1000) setLimitFor(after.expiresAt);
    } catch {
      setFailed(true);
    } finally {
      setPending(false);
    }
  }

  const atLimit = limitFor === expiry.expiresAt;
  return (
    <section className="notice warn expiry" role="alert" aria-labelledby="expiry-title">
      <div>
        <strong id="expiry-title">
          Your session ends at {endsAt}
          <span className="tabular" aria-hidden="true"> (in {clock(left)})</span>
        </strong>
        {atLimit ? (
          <p>This session has reached its 8-hour limit and cannot be extended. Your answers and results are deleted when it ends; download your summary first if you need it.</p>
        ) : (
          <p>For privacy, guest sessions end after 30 minutes without activity. Your answers and results are deleted when it ends.</p>
        )}
        {failed && <p className="field-error">The session could not be extended. Check your connection and try again.</p>}
        <div className="row">
          {!atLimit && (
            <Button type="button" className="btn sm" pending={pending} onClick={stay}>
              Stay signed in
            </Button>
          )}
          <button type="button" className="btn secondary sm" onClick={() => setDismissedFor(expiry.expiresAt)}>
            Dismiss
          </button>
        </div>
      </div>
    </section>
  );
}
