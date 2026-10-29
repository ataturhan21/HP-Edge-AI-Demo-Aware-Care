// #688 (owner decision B1, 28 Oct 2026): presenter and patient are fully separate modes. A browser tab is in one mode
// at a time: presenter pages put it in Presenter mode; a patient start (the home page's Patient choice, Accept and
// begin, Continue consultation) puts it in Patient mode; the strip's Switch link changes it. A quick flow's result, and
// a full journey from More scenarios, open in the presenter's own window as the "Demo patient", with "Back to
// presenter" (no pop-up). Nothing here grants a role: the server decides on every request (the patient API for patient
// pages, the presenter API for presenter pages); this only says which mode the tab shows and where Back leads.
//
// What is kept, IDs and paths only, and every storage call may fail (the app then works as before, without labels):
// - per tab (sessionStorage): Presenter mode (Patient mode is the default: nothing kept), and the last presenter page
//   (Back to presenter returns there);
// - per browser (localStorage): the demo cases this browser's presenter tools know (the runtime snapshot's
//   `demo.live_case_ids`, and each case a load opened). The tabs of one browser share one patient cookie, so these
//   are the cases that cookie may hold for a synthetic demo patient. Patient pages never resume them and History in
//   Patient mode does not list them: the patient's own consultations are the others.
import { useEffect, useSyncExternalStore } from "react";
import { Link, useLocation } from "react-router-dom";
import { Icon } from "./Icon";

export type Mode = "presenter" | "patient";
export const PRESENTER_HOME = "/presenter/scenarios";
const MODE_KEY = "aware-care:mode";
const BACK_KEY = "aware-care:presenter-path";
const DEMO_KEY = "aware-care:demo-cases";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const PRESENTER_PATH = /^\/presenter\/[A-Za-z0-9/_-]{0,80}$/;
const MAX_DEMO_CASES = 200;

const listeners = new Set<() => void>();
let version = 0;
function changed() {
  version++;
  for (const listener of listeners) listener();
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (e: StorageEvent) => {
    if (e.key === DEMO_KEY || e.key === null) changed();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

function read(store: () => Storage, key: string): string | null {
  try {
    return store().getItem(key);
  } catch {
    return null;
  }
}
function write(store: () => Storage, key: string, value: string | null) {
  try {
    if (value === null) store().removeItem(key);
    else store().setItem(key, value);
  } catch {
    // storage blocked or full: the mode then follows the page, and demo cases are not hidden
  }
}
const session = () => window.sessionStorage;
const local = () => window.localStorage;

/** The mode this tab chose (null: none yet, the page decides). */
export function tabMode(): Mode | null {
  const value = read(session, MODE_KEY);
  return value === "presenter" || value === "patient" ? value : null;
}

/** Patient mode is the default, so it is kept as nothing: a patient's browser keeps no storage of its own. */
export function setTabMode(mode: Mode) {
  if ((tabMode() ?? "patient") === mode) return;
  write(session, MODE_KEY, mode === "presenter" ? mode : null);
  changed();
}

/** Where "Back to presenter" leads: the last presenter page of this tab, else Scenarios. */
export function presenterPath(): string {
  const path = read(session, BACK_KEY);
  return path && PRESENTER_PATH.test(path) ? path : PRESENTER_HOME;
}

export function notePresenterPath(path: string) {
  if (PRESENTER_PATH.test(path)) write(session, BACK_KEY, path);
}

/** The demo case IDs this browser's presenter tools know (IDs only). */
export function demoCaseIds(): string[] {
  try {
    const raw = read(local, DEMO_KEY);
    if (!raw) return [];
    const stored = JSON.parse(raw) as { v?: unknown; ids?: unknown };
    if (stored.v !== 1 || !Array.isArray(stored.ids)) return [];
    return stored.ids.filter((id): id is string => typeof id === "string" && UUID.test(id)).slice(0, MAX_DEMO_CASES);
  } catch {
    return [];
  }
}

export const isDemoCase = (id: string) => demoCaseIds().includes(id);

/** Note demo cases: `replace` with a fresh runtime snapshot's live list; otherwise add one a load just opened. */
export function rememberDemoCases(ids: readonly string[], replace = false) {
  const valid = ids.filter((id) => UUID.test(id));
  const before = demoCaseIds();
  const next = replace ? valid : [...new Set([...valid, ...before])];
  const trimmed = next.slice(0, MAX_DEMO_CASES);
  if (trimmed.length === before.length && trimmed.every((id, i) => id === before[i])) return;
  write(local, DEMO_KEY, trimmed.length ? JSON.stringify({ v: 1, ids: trimmed }) : null);
  changed();
}

/** A clear for the next audience removed every demo of this browser's presenter tools. */
export function forgetDemoCases() {
  if (demoCaseIds().length === 0) return;
  write(local, DEMO_KEY, null);
  changed();
}

/** Re-renders on any mode or demo-case change (this tab, or the demo cases from another tab). */
export function useModeVersion(): number {
  return useSyncExternalStore(subscribe, () => version);
}

const CASE_PATH = /^\/app\/cases\/([0-9a-f-]{36})(\/|$)/;

/** The mode a page shows. Presenter pages: Presenter mode. A patient page in a Presenter-mode tab is the Demo patient
 *  window (a case page only for a demo case this browser knows). Any other page: the tab's mode, else Patient mode. */
export function shownMode(shell: "public" | "app" | "presenter", pathname: string): { mode: Mode; demo: boolean } {
  if (shell === "presenter") return { mode: "presenter", demo: false };
  if (tabMode() !== "presenter") return { mode: "patient", demo: false };
  if (shell === "public") return { mode: "presenter", demo: false };
  const ids = demoCaseIds();
  const onCase = CASE_PATH.exec(pathname)?.[1];
  const demo = onCase ? ids.includes(onCase) : ids.length > 0;
  return demo ? { mode: "presenter", demo: true } : { mode: "patient", demo: false };
}

/** The colored strip at the top of every page: which mode this is, and the way to the other one. */
export function ModeStrip({ shell }: { shell: "public" | "app" | "presenter" }) {
  useModeVersion();
  const { pathname } = useLocation();
  useEffect(() => {
    if (shell !== "presenter") return;
    setTabMode("presenter");
    notePresenterPath(pathname);
  }, [shell, pathname]);
  const { mode, demo } = shownMode(shell, pathname);
  const presenter = mode === "presenter";
  return (
    <div className={`mode-strip ${presenter ? "mode-presenter" : "mode-patient"}`} data-testid="mode-strip"
      data-mode={mode}>
      <div className="mode-strip-inner">
        <p className="mode-name">
          <Icon name={presenter ? "sliders" : "user"} size={18} />
          <span>
            <b>{presenter ? "Presenter mode" : "Patient mode"}</b>
            {demo && <span className="mode-detail"> · Demo patient</span>}
            {shell === "presenter" && <span className="mode-detail mode-extra"> · separately authorized</span>}
          </span>
        </p>
        <p className="mode-actions">
          {presenter && shell !== "presenter" && (
            <Link className="btn secondary sm mode-back" to={presenterPath()} onClick={() => window.scrollTo(0, 0)}>
              <Icon name="arrow" size={16} />
              Back to presenter
            </Link>
          )}
          {presenter ? (
            <Link className="mode-switch" to="/" onClick={() => setTabMode("patient")}>
              Switch<span className="mode-switch-to"> to patient mode</span>
            </Link>
          ) : (
            <Link className="mode-switch" to={PRESENTER_HOME} onClick={() => setTabMode("presenter")}>
              Switch<span className="mode-switch-to"> to presenter mode</span>
            </Link>
          )}
        </p>
      </div>
    </div>
  );
}
