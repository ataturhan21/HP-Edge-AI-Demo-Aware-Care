// #340: one way back to where the patient left off. When a guest session is open, the target is the current screen of
// its most recently changed consultation (questions, review, guidance, urgent help, limits), mapped with the same
// state-to-screen rule as History (A13, `caseNextStep`); with a session but no consultation, a new one (A03). The
// session's own case list (GET /cases, operation listCases) proves the session: it is read quietly, so without a
// session nothing is shown and no error is reported. No new endpoint, and nothing is kept in browser storage.
// #345: "Continue consultation" resumes; "Start a new consultation" is the one name for starting one.
// #688 (owner decision B1): a demo patient's consultations (this browser's demo cases, components/mode.tsx) are never
// resumed: a session that holds only demo cases counts as none, and a patient start puts the tab in Patient mode.
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, type S } from "../api/client";
import { screenForState } from "./useCase";
import { demoCaseIds, setTabMode } from "./mode";

export const START_LABEL = "Start a new consultation";
export const CONTINUE_LABEL = "Continue consultation";

// A13's row action, named for what happens next. #282: a limited case whose guidance failed recoverably ("retry"
// allowed) opens A07, which offers Retry.
const NEXT_LABEL: Record<string, string> = {
  draft: "Continue questions",
  intake: "Continue questions",
  review: "Review answers",
  reviewed: "Review answers",
  generating: "View guidance",
  guided: "View guidance",
  urgent: "View urgent help",
  limited: "View limits",
};
const RETRY_LABEL = "View guidance";

/** The next step for an owned case: the screen it continues on and the action's name (A13 and the resume target). */
export function caseNextStep(c: Pick<S["CaseMetadata"], "id" | "state">, allowedActions?: readonly string[]) {
  const retry = c.state === "limited" && Boolean(allowedActions?.includes("retry"));
  return {
    to: screenForState(c.id, c.state, allowedActions),
    label: retry ? RETRY_LABEL : NEXT_LABEL[c.state] ?? "Open",
  };
}

/** `open: false` without a session (or when the check failed); otherwise where "Continue consultation" leads. */
export type Resume = { open: false } | { open: true; to: string };

async function findResume(): Promise<Resume> {
  const list = await api.listCasesQuietly().catch(() => null);
  if (!list || !Array.isArray(list.items)) return { open: false };
  const demo = demoCaseIds();
  const all = list.items.filter((c) => c.state !== "deleting" && c.state !== "deleted");
  const live = all.filter((c) => !demo.includes(c.id));
  // #688: only a demo patient's consultations: not this person's session to continue
  if (all.length > 0 && live.length === 0) return { open: false };
  // The list is newest first; the consultation the patient worked on last is the one most recently changed.
  const latest = live.reduce<S["CaseMetadata"] | null>(
    (best, c) => (best === null || c.updated_at > best.updated_at ? c : best), null);
  if (!latest) return { open: true, to: "/app/new" };
  // #282: only a limited case needs its allowed actions (retry or not); every other state maps directly.
  const actions = latest.state === "limited"
    ? await api.getCaseQuietly(latest.id).then((r) => r.allowed_actions, () => undefined)
    : undefined;
  return { open: true, to: caseNextStep(latest, actions).to };
}

// Components that mount together (the header, the page's banner and its buttons) share one check; the next screen
// that asks checks again, so the target follows the consultation as it moves on. The last answer of this page load
// (memory only) is shown meanwhile, so the label does not flip on every screen.
let inflight: Promise<Resume> | null = null;
let lastKnown: Resume | null = null;
export function loadResume(): Promise<Resume> {
  if (!inflight) {
    inflight = findResume().then((r) => (lastKnown = r));
    const done = () => {
      inflight = null;
    };
    inflight.then(done, done);
  }
  return inflight;
}

/** null until the first check of this page load has answered. */
export function useResume(): Resume | null {
  const [resume, setResume] = useState<Resume | null>(lastKnown);
  useEffect(() => {
    let live = true;
    void loadResume().then((r) => live && setResume(r));
    return () => {
      live = false;
    };
  }, []);
  return resume;
}

/** How long a page waits for the first check before it offers the start action anyway (a server that does not answer
 * must not hide the way in). */
const FIRST_CHECK_WAIT_MS = 1500;

/** "Continue consultation" to the resume target while a session is open; otherwise "Start a new consultation".
 * Until the first check of a page load answers, the button keeps its place but is hidden, so a quick tap never opens
 * consent for someone whose consultation is open. */
export function ConsultationLink({ className = "btn", children }: { className?: string; children?: ReactNode }) {
  const resume = useResume();
  const [waited, setWaited] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setWaited(true), FIRST_CHECK_WAIT_MS);
    return () => window.clearTimeout(timer);
  }, []);
  const open = resume?.open === true;
  const pending = resume === null && !waited;
  return (
    <Link className={className} to={open ? resume.to : "/app/start"} onClick={() => setTabMode("patient")}
      style={pending ? { visibility: "hidden" } : undefined} aria-hidden={pending || undefined}
      tabIndex={pending ? -1 : undefined}>
      {open ? CONTINUE_LABEL : START_LABEL}
      {children}
    </Link>
  );
}
