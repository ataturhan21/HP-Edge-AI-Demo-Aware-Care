// In-memory application state only (never persisted to browser storage).
// Cleared on logout, deletion or a 401 from the server. #394: deleting one consultation (A13) or all of them (A14)
// drops what this tab holds for them (doctor searches with their criteria, issued questions), so nothing of a deleted
// case comes back through browser Back or a direct link.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, clearCsrf, setUnauthorizedHandler, type S } from "../api/client";

type ProviderSearchState = { result: S["ProviderSearchResult"]; criteria: S["ProviderCriteria"] };

/**
 * What the browser has actually observed about the runtime (#98), for the local-AI signature. Never health data.
 * - mode: "local" or "mock" only once a server response proves it; "unknown" until then. It survives a reset.
 *   #322: the first proof is the public telemetry identity (GET /telemetry, `identity.mode`), read once when the page
 *   loads, so every screen (presenter and quick-demo screens too, and after a reload) shows the same claim. A
 *   question's pathway version, a guidance result's model manifest and the presenter's runtime snapshot also prove it.
 *   If the telemetry request fails the mode stays "unknown" and the screens keep their neutral wording.
 * - readiness: GET /health/ready on load and every minute; "unreachable" when the request fails.
 * - guidanceTypicalMs (#323): the median time a guidance job took on this device in this mode over the last 7 days
 *   up to now (#638; telemetry `latency.total_ms_p50`), or null when the server has too few samples (for example on
 *   a new deployment); A07 then uses a per-device default.
 */
export type RuntimeMode = "unknown" | "local" | "mock";
export type Readiness = "checking" | S["Readiness"]["readiness"] | "unreachable";

/** #323: fewer guidance jobs than this in the window and the median is not used as the device's typical time. */
export const MIN_LATENCY_SAMPLES = 3;

type DeviceFacts = { mode: "local" | "mock" | null; guidanceTypicalMs: number | null };

/** #322/#323: what the public telemetry snapshot proves about this deployment; nothing else is taken from it. */
export function deviceFactsFrom(t: unknown): DeviceFacts {
  const v = t as { identity?: { mode?: unknown }; latency?: { samples?: unknown; total_ms_p50?: unknown } } | null;
  const mode = v?.identity?.mode === "local" || v?.identity?.mode === "mock" ? v.identity.mode : null;
  const samples = v?.latency?.samples;
  const p50 = v?.latency?.total_ms_p50;
  const usable = typeof samples === "number" && samples >= MIN_LATENCY_SAMPLES && typeof p50 === "number"
    && Number.isFinite(p50) && p50 > 0 && p50 < 600_000;
  return { mode, guidanceTypicalMs: usable ? p50 : null };
}

// One request per page load (the provider mounts once); a failure is remembered as "nothing proven".
let deviceFacts: Promise<DeviceFacts> | null = null;
function loadDeviceFacts(): Promise<DeviceFacts> {
  deviceFacts ??= api.getTelemetry("7d").then(deviceFactsFrom, () => ({ mode: null, guidanceTypicalMs: null }));
  return deviceFacts;
}

type AppState = {
  session: S["CreateSessionResponse"] | null;
  setSession: (s: S["CreateSessionResponse"] | null) => void;
  sessionContext: S["ConfirmedContextWrite"][];
  setSessionContext: (items: S["ConfirmedContextWrite"][]) => void;
  questions: Map<string, S["Question"]>;
  rememberQuestion: (q: S["Question"]) => void;
  searches: Map<string, ProviderSearchState>;
  rememberSearch: (caseId: string, s: ProviderSearchState) => void;
  /** #394: forget one deleted case (its id), or every case (no id) after "Delete all consultations". */
  forgetCases: (caseId?: string) => void;
  clearAll: () => void;
  runtimeMode: RuntimeMode;
  noteRuntimeMode: (mode: "local" | "mock") => void;
  readiness: Readiness;
  guidanceTypicalMs: number | null;
  /** #630: a consultation created after the person left A03 that was routed to urgent help; shown on every page. */
  lateUrgent: LateUrgent | null;
  noteLateUrgent: (urgent: LateUrgent | null) => void;
};

export type LateUrgent = { caseId: string; level: string | null };

const Ctx = createContext<AppState | null>(null);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [session, setSession] = useState<S["CreateSessionResponse"] | null>(null);
  const [sessionContext, setSessionContext] = useState<S["ConfirmedContextWrite"][]>([]);
  const questions = useRef(new Map<string, S["Question"]>());
  const searches = useRef(new Map<string, ProviderSearchState>());
  const [, force] = useState(0);
  const [runtimeMode, setRuntimeMode] = useState<RuntimeMode>("unknown");
  const [readiness, setReadiness] = useState<Readiness>("checking");
  const [guidanceTypicalMs, setGuidanceTypicalMs] = useState<number | null>(null);
  const [lateUrgent, setLateUrgent] = useState<LateUrgent | null>(null);

  useEffect(() => {
    let live = true;
    void loadDeviceFacts().then((facts) => {
      if (!live) return;
      if (facts.mode) setRuntimeMode(facts.mode);
      setGuidanceTypicalMs(facts.guidanceTypicalMs);
    });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    let live = true;
    const check = () =>
      api.readiness().then(
        (r) => live && setReadiness(r.readiness),
        // The server answers "unavailable" with HTTP 503; any other failure means it could not be reached.
        (e) => live && setReadiness(e instanceof ApiError && e.status === 503 ? "unavailable" : "unreachable"),
      );
    void check();
    const timer = window.setInterval(check, 60_000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);

  // Stable identities: screens list these in effect dependencies, so they must not change when state updates.
  const rememberQuestion = useCallback((q: S["Question"]) => {
    questions.current.set(q.id, q);
    setRuntimeMode(q.pathway_version.startsWith("mock-") ? "mock" : "local");
  }, []);
  const rememberSearch = useCallback((caseId: string, s: ProviderSearchState) => {
    searches.current.set(caseId, s);
    force((n) => n + 1);
  }, []);

  const forgetCases = useCallback((caseId?: string) => {
    if (caseId === undefined) {
      searches.current.clear();
      questions.current.clear();
    } else {
      searches.current.delete(caseId);
      for (const [id, q] of questions.current) if (q.case_id === caseId) questions.current.delete(id);
    }
    setLateUrgent((u) => (caseId === undefined || u?.caseId === caseId ? null : u));
    force((n) => n + 1);
  }, []);

  const clearAll = useCallback(() => {
    setSession(null);
    setSessionContext([]);
    questions.current.clear();
    searches.current.clear();
    setLateUrgent(null);
    clearCsrf();
  }, []);

  // #285: "Your session ended" only when this tab knew a session (created here, or proven by an authenticated
  // response since the page loaded); anyone else is sent to the start page plainly.
  const sessionRef = useRef(session);
  sessionRef.current = session;
  useEffect(() => {
    setUnauthorizedHandler((hadSession) => {
      const known = hadSession || sessionRef.current !== null;
      clearAll();
      navigate("/app/start", { replace: true, state: known ? { expired: true } : null });
    });
  }, [clearAll, navigate]);

  const value = useMemo<AppState>(
    () => ({
      session,
      setSession,
      sessionContext,
      setSessionContext,
      questions: questions.current,
      rememberQuestion,
      searches: searches.current,
      rememberSearch,
      forgetCases,
      clearAll,
      runtimeMode,
      noteRuntimeMode: setRuntimeMode,
      readiness,
      guidanceTypicalMs,
      lateUrgent,
      noteLateUrgent: setLateUrgent,
    }),
    [session, sessionContext, clearAll, rememberQuestion, rememberSearch, forgetCases, runtimeMode, readiness, guidanceTypicalMs,
      lateUrgent],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppState(): AppState {
  const value = useContext(Ctx);
  if (!value) throw new Error("AppStateProvider missing");
  return value;
}
