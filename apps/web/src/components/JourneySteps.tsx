// #183: where the person is in a consultation. Shown on the patient-flow screens only (A02-A12); urgent help (A15),
// limits (A16), history and settings are not steps. Text labels carry the meaning; colour only reinforces it. On
// phones the list collapses to "Step n of N · <name>" with a bar.
// #343: once a case has guidance, the steps that can be reopened safely (Guidance, Find care, Summary) are links: in
// the list on wider screens, and in a compact row under "Step n of N" on phones. Profile, Concern, Records, Questions
// and Review cannot be revisited after the case moved on (A06 shows "This step is complete"), so they stay text.
// "Guided" is what a screen's own case read showed (useJourneyCase); nothing extra is requested or persisted.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, matchPath, useLocation } from "react-router-dom";

const STEPS: { name: string; paths: string[]; reopen?: string }[] = [
  { name: "Profile", paths: ["/app/profile"] },
  { name: "Concern", paths: ["/app/new"] },
  { name: "Records", paths: ["/app/cases/:caseId/records"] },
  { name: "Questions", paths: ["/app/cases/:caseId/questions"] },
  { name: "Review", paths: ["/app/cases/:caseId/review"] },
  { name: "Guidance", paths: ["/app/cases/:caseId/guidance", "/app/cases/:caseId/sources"], reopen: "guidance" },
  // The same destination as A07's "Find appropriate care".
  { name: "Find care", paths: ["/app/cases/:caseId/preferences", "/app/cases/:caseId/doctors", "/app/cases/:caseId/doctors/:providerId"], reopen: "preferences" },
  { name: "Summary", paths: ["/app/cases/:caseId/summary"], reopen: "summary" },
];

export function currentStep(pathname: string): number {
  return STEPS.findIndex((s) => s.paths.some((p) => matchPath(p, pathname)));
}

/** "Step n of N" for the screen at `pathname`, or null off the consultation steps (#348: A05's own indicator). */
export function stepOf(pathname: string): string | null {
  const i = currentStep(pathname);
  return i < 0 ? null : `Step ${i + 1} of ${STEPS.length}`;
}

type Journey = {
  hidden: number;
  setHidden: (update: (n: number) => number) => void;
  /** The case the shown screen has read as guided (#343), or null. */
  guided: string | null;
  setGuided: (update: (id: string | null) => string | null) => void;
  /** #348: the shown screen draws the phone indicator itself (A05). */
  inPage: number;
  setInPage: (update: (n: number) => number) => void;
};

// #232: a screen replaced by a page-level empty or not-found state is not a step in progress, so it hides the
// indicator (EmptyState with `page` calls useHideJourney); it reappears when that state goes away.
const JourneyVisibility = createContext<Journey>({
  hidden: 0,
  setHidden: () => undefined,
  guided: null,
  setGuided: () => undefined,
  inPage: 0,
  setInPage: () => undefined,
});

export function JourneyProvider({ children }: { children: ReactNode }) {
  const [hidden, setHidden] = useState(0);
  const [guided, setGuided] = useState<string | null>(null);
  const [inPage, setInPage] = useState(0);
  return (
    <JourneyVisibility.Provider value={{ hidden, setHidden, guided, setGuided, inPage, setInPage }}>
      {children}
    </JourneyVisibility.Provider>
  );
}

export function useHideJourney(active = true) {
  const { setHidden } = useContext(JourneyVisibility);
  useEffect(() => {
    if (!active) return;
    setHidden((n) => n + 1);
    return () => setHidden((n) => n - 1);
  }, [active, setHidden]);
}

/**
 * #343: a screen says what its own case read showed: `true` the case has current guidance (A07 showing it, A10 with a
 * search, A11 with a card, A12 with its preview), `false` it does not (A05, A06, A07 without a result), `undefined`
 * not known yet. The last observation is kept in memory while the patient shell is open (so A09, which reads no case,
 * keeps the links after A07), never in browser storage; a reload starts without links until a screen reads the case.
 * Every linked screen checks the case again itself (A07 routes by state, A12 says "Review required").
 */
export function useJourneyCase(caseId: string, guided: boolean | undefined) {
  const { setGuided } = useContext(JourneyVisibility);
  useEffect(() => {
    if (guided === undefined) return;
    setGuided((id) => (guided ? caseId : id === caseId ? null : id));
  }, [caseId, guided, setGuided]);
}

/** #394: after a deletion the deleted case (`caseId`), or every case (no id), no longer has step links. */
export function useForgetJourneyCase() {
  const { setGuided } = useContext(JourneyVisibility);
  return useCallback((caseId?: string) => setGuided((id) => (caseId === undefined || id === caseId ? null : id)), [setGuided]);
}

/** #348: while active, the phone "Step n of N" line and bar give way to the screen's own combined indicator. */
export function useJourneyInPage(active = true) {
  const { setInPage } = useContext(JourneyVisibility);
  useEffect(() => {
    if (!active) return;
    setInPage((n) => n + 1);
    return () => setInPage((n) => n - 1);
  }, [active, setInPage]);
}

export function JourneySteps() {
  const { pathname } = useLocation();
  const { hidden, guided, inPage } = useContext(JourneyVisibility);
  const current = currentStep(pathname);
  if (current < 0 || hidden > 0) return null;
  const caseId = matchPath("/app/cases/:caseId/*", pathname)?.params.caseId;
  const href = (i: number) => {
    const reopen = STEPS[i].reopen;
    return reopen && caseId && guided === caseId && i !== current ? `/app/cases/${caseId}/${reopen}` : null;
  };
  const links = STEPS.map((s, i) => ({ name: s.name, to: href(i) })).filter((s) => s.to !== null);
  return (
    <nav className={inPage > 0 ? "journey journey-inpage" : "journey"} aria-label="Consultation steps">
      <p className="journey-compact" aria-hidden="true">
        Step {current + 1} of {STEPS.length} · <b>{STEPS[current].name}</b>
        <span className="journey-bar"><i style={{ width: `${((current + 1) / STEPS.length) * 100}%` }} /></span>
      </p>
      <ol>
        {STEPS.map((s, i) => {
          const to = href(i);
          return (
            <li key={s.name} className={i < current ? "done" : i === current ? "current" : undefined}
              aria-current={i === current ? "step" : undefined}>
              <span className="journey-num" aria-hidden="true">{i < current ? "✓" : i + 1}</span>
              {to ? (
                <>
                  {/* The link on wider screens; on phones the list is for screen readers only, so it is text there
                      and the row below holds the link (no focus on something that is not shown). */}
                  <Link className="journey-link" to={to}>{s.name}</Link>
                  <span className="journey-plain">{s.name}</span>
                </>
              ) : (
                s.name
              )}
              {i < current && <span className="sr-only"> (done)</span>}
            </li>
          );
        })}
      </ol>
      {links.length > 0 && (
        <ul className="journey-links">
          {links.map((l) => (
            <li key={l.name}>
              <Link to={l.to!}>{l.name}</Link>
            </li>
          ))}
        </ul>
      )}
    </nav>
  );
}
