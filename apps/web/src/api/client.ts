// Same-origin API client. All calls use relative URLs (Vite proxies them to the FastAPI app in development). The CSRF
// token is held in memory only; the session cookie is HttpOnly. No health data is written to localStorage, IndexedDB
// or caches. Types come from the generated schema.
//
// #487 (ADR-005 amendment): one address serves both roles. The gateway passes /api/v1 to the API with any presenter
// assertion stripped (the patient API) and signs every request under /presenter-api/v1 (the presenter API, the same
// operations). The role of a request follows the page that makes it: a presenter page (/presenter/...) uses the
// presenter API, every other page the patient API. Work started by the presenter tools that may outlive its page (a
// running quick flow) names the presenter role itself. The browser only chooses a path; the API authorizes.
import type { components } from "./schema";

export type S = components["schemas"];

export type Role = "patient" | "presenter";
export const PATIENT_API = "/api/v1";
export const PRESENTER_API = "/presenter-api/v1";
const BASES: Record<Role, string> = { patient: PATIENT_API, presenter: PRESENTER_API };

/** #487: whether a path is one of the presenter tools' pages (O01-O03 and their views under /presenter/). */
export function isPresenterPath(pathname: string): boolean {
  return pathname === "/presenter" || pathname.startsWith("/presenter/");
}

/** #487: the role of the page this code runs on, read at every request (so reloads, deep links and in-app navigation
 *  all agree with the address bar). */
export function pageRole(): Role {
  return isPresenterPath(globalThis.location?.pathname ?? "/") ? "presenter" : "patient";
}

// Each role has its own session (separate cookies), so its own CSRF token and session state, in memory only.
const csrfTokens: Record<Role, string | null> = { patient: null, presenter: null };
// #285: whether this page has seen a live session (an authenticated response carried X-Session-Expires-At). Only then
// does a later 401 mean "your session ended"; a first-time visitor is sent to the start page plainly. Memory only.
const sessionKnown: Record<Role, boolean> = { patient: false, presenter: false };
let onUnauthorized: ((hadSession: boolean) => void) | null = null;

export function setUnauthorizedHandler(handler: (hadSession: boolean) => void) {
  onUnauthorized = handler;
}

export function clearCsrf() {
  csrfTokens.patient = null;
  csrfTokens.presenter = null;
}

/** #285: the message for a response without a usable JSON error body (for example an HTML page from the gateway). */
function statusMessage(status: number): string {
  if (status === 413) return "This request is too large for the Aware Care service (413).";
  if (status >= 500) return `The Aware Care service had a problem (${status}). Your entries are kept on this page.`;
  return `Request failed (${status})`;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: S["Error"] | null,
  ) {
    super(body?.message ?? statusMessage(status));
  }
  get code() {
    return this.body?.code ?? "NETWORK_ERROR";
  }
}

/** #269: getGuidance and getCaseSources answer 404 when guidance was never generated, 409 when it is not current. Once the
 * case itself has been read, a screen shows both as "no current guidance" (the 409 state). */
export function asNoCurrentGuidance(err: unknown): ApiError | unknown {
  return err instanceof ApiError && err.status === 404 ? new ApiError(409, err.body) : err;
}

export function newKey(): string {
  return crypto.randomUUID();
}

// #42 (R36, ADR-013): every authenticated response reports the session's current expiry in X-Session-Expires-At,
// the earlier of the 30-minute idle and 8-hour absolute limits. The browser keeps the latest value with the server's
// clock offset (from the Date header), so a warning can show 2 minutes before the session ends. The server stays
// authoritative: this only decides when to warn.
export type SessionExpiry = { expiresAt: number; skewMs: number } | null;
let sessionExpiry: SessionExpiry = null;
const expiryListeners = new Set<(e: SessionExpiry) => void>();

export function currentSessionExpiry(): SessionExpiry {
  return sessionExpiry;
}

export function subscribeSessionExpiry(listener: (e: SessionExpiry) => void): () => void {
  expiryListeners.add(listener);
  return () => expiryListeners.delete(listener);
}

function setSessionExpiry(next: SessionExpiry) {
  sessionExpiry = next;
  for (const listener of expiryListeners) listener(next);
}

// #409: the tabs of one browser share one session (one cookie). Each tab tells the others the latest expiry it saw,
// with the server time of that response, so an idle tab does not warn about, or declare ended, a session that another
// tab keeps alive. Only these two times are sent, in memory, to this site's own tabs: nothing about the person.
type ExpiryMessage = { expiresAt: number; serverNow: number | null };
const sessionChannel: BroadcastChannel | null =
  typeof BroadcastChannel === "function" ? new BroadcastChannel("aware-care-session-expiry") : null;
sessionChannel?.addEventListener("message", (event: MessageEvent) => {
  // #610: another tab ended this browser's patient session or started a new one: this tab's session is over.
  if ((event.data as { sessionEnded?: unknown } | null)?.sessionEnded === true) {
    // On a page outside the app (Help, Telemetry) the tab's next request to the app finds the change instead.
    const inApp = (globalThis.location?.pathname ?? "").startsWith("/app/");
    if (inApp && pageRole() === "patient" && (sessionKnown.patient || csrfTokens.patient !== null)) sessionReplaced();
    return;
  }
  const m = event.data as Partial<ExpiryMessage> | null;
  if (!m || typeof m.expiresAt !== "number" || !Number.isFinite(m.expiresAt)) return;
  if (sessionExpiry && m.expiresAt <= sessionExpiry.expiresAt) return; // the later expiry is the current one
  sessionKnown.patient = true;
  const skewMs = typeof m.serverNow === "number" && Number.isFinite(m.serverNow)
    ? m.serverNow - Date.now() : sessionExpiry?.skewMs ?? 0;
  setSessionExpiry({ expiresAt: m.expiresAt, skewMs });
});

// #610: the tabs of one browser share the patient session cookie, but each tab holds in memory what belongs to the
// session it knew (the profile entered for it, issued questions, its CSRF token). When that session ends or another
// one replaces it (ended in another tab, a new guest started there), the tab's state is that ended session's and must
// never be written under the new one. The CSRF token is the session's own (one per session, unchanged while it lasts),
// so a response carrying another token, or a write refused for this tab's token, means the session changed. The tab
// then ends as on a 401 ("Your session ended", in-memory state cleared); the request is never replayed. A tab that
// ends or starts the session itself tells the other tabs at once (`sessionEnded`), with nothing else in the message.
function sessionReplaced() {
  csrfTokens.patient = null;
  sessionKnown.patient = false;
  setSessionExpiry(null);
  onUnauthorized?.(true);
}

/** #688: the presenter opens a demo in this window (the Demo patient): the browser's patient cookie now holds the
 *  synthetic demo patient's session, so this tab forgets the patient session it knew (its CSRF token and expiry)
 *  without ending anything; the demo page's first read brings the demo session's own token. */
export function forgetPatientSession() {
  csrfTokens.patient = null;
  sessionKnown.patient = false;
  setSessionExpiry(null);
}

function tellOtherTabsTheSessionEnded() {
  try {
    sessionChannel?.postMessage({ sessionEnded: true });
  } catch {
    // A closed channel: the other tabs find out from their next response instead.
  }
}

// #487: the expiry warning and the cross-tab channel are the patient session's (the presenter tools show no expiry
// warning; a presenter tab on the same address must not move a patient tab's clock). A presenter response only
// records that its own session is known.
function noteSessionExpiry(response: Response, method: string, path: string, role: Role) {
  const ended = response.status === 401 || (method === "DELETE" && path === "/sessions/current" && response.ok);
  if (role === "presenter") {
    if (ended && response.ok) sessionKnown.presenter = false;
    else if (!ended && response.headers.get("X-Session-Expires-At")) sessionKnown.presenter = true;
    return;
  }
  if (ended) {
    if (response.ok) {
      sessionKnown.patient = false;
      tellOtherTabsTheSessionEnded(); // #610
    }
    setSessionExpiry(null);
    return;
  }
  if (method === "POST" && path === "/sessions" && response.ok) tellOtherTabsTheSessionEnded(); // #610: a new session
  const header = response.headers.get("X-Session-Expires-At");
  const expiresAt = header ? Date.parse(header) : NaN;
  if (!Number.isFinite(expiresAt)) return;
  sessionKnown.patient = true;
  const serverNow = Date.parse(response.headers.get("Date") ?? "");
  setSessionExpiry({ expiresAt, skewMs: Number.isFinite(serverNow) ? serverNow - Date.now() : 0 });
  try {
    sessionChannel?.postMessage({ expiresAt, serverNow: Number.isFinite(serverNow) ? serverNow : null } satisfies ExpiryMessage);
  } catch {
    // A closed channel only means the other tabs are not told; this tab keeps its own expiry.
  }
}

// quietUnauthorized: presenter reads surface 401/403 to PresenterGate instead of the patient session redirect.
// signal (#278): aborts the fetch itself; an aborted request rejects with an AbortError, never an ApiError.
// blob (#418): a successful response is returned as a Blob (a file such as the summary PDF), not parsed as JSON.
// role (#487): the API this request uses; by default the role of the current page (pageRole).
type Options = { body?: unknown; form?: FormData; idempotencyKey?: string; quietUnauthorized?: boolean; signal?: AbortSignal; blob?: boolean; role?: Role };

function abortError(): DOMException {
  return new DOMException("aborted", "AbortError");
}

/** #285: an error body is used only when it is the API's JSON error shape. */
function errorBody(data: unknown): S["Error"] | null {
  return data !== null && typeof data === "object" && typeof (data as { code?: unknown }).code === "string"
    ? (data as S["Error"]) : null;
}

async function request<T>(method: string, path: string, options: Options = {}, retried = false): Promise<T> {
  const role = options.role ?? pageRole();
  const headers: Record<string, string> = { Accept: "application/json" };
  // Multipart bodies set their own boundary Content-Type.
  if (options.body !== undefined && !options.form) headers["Content-Type"] = "application/json";
  const csrfToken = csrfTokens[role];
  if (csrfToken && method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
  let response: Response;
  try {
    response = await fetch(BASES[role] + path, {
      method,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      body: options.form ?? (options.body === undefined ? undefined : JSON.stringify(options.body)),
      signal: options.signal,
    });
  } catch {
    if (options.signal?.aborted) throw abortError();
    throw new ApiError(0, null);
  }
  const token = response.headers.get("X-CSRF-Token");
  // #610: the patient session this tab held a token for is not the one that answered (its own createSession aside).
  // A quiet read (a public page) only fails; the tab keeps its old token, so its next request ends the session.
  const heldToken = role === "patient" && csrfToken !== null && !(method === "POST" && path === "/sessions");
  if (heldToken && token !== null && token !== csrfToken) {
    if (!options.quietUnauthorized) sessionReplaced();
    throw new ApiError(401, null);
  }
  if (token) csrfTokens[role] = token;
  noteSessionExpiry(response, method, path, role);
  if (options.blob && response.ok) {
    try {
      return (await response.blob()) as T;
    } catch {
      if (options.signal?.aborted) throw abortError();
      throw new ApiError(0, null);
    }
  }
  let text: string;
  try {
    text = await response.text();
  } catch {
    if (options.signal?.aborted) throw abortError();
    throw new ApiError(0, null);
  }
  // #285: a body that is not JSON (an HTML 413 or 502 page from the gateway) still becomes an ApiError with the
  // status, so the 401 and 413 handling below applies; a successful response must be JSON.
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      if (response.ok) throw new ApiError(response.status, null);
    }
  }
  if (!response.ok && !(path === "/health/ready" && response.status === 503)) {
    if (response.status === 401) {
      csrfTokens[role] = null;
      const hadSession = sessionKnown[role];
      sessionKnown[role] = false;
      if (!options.quietUnauthorized) onUnauthorized?.(hadSession);
    }
    // The CSRF token lives only in memory, so a reload or direct load of a write screen loses it.
    // The server rejected this write before any effect; recover the token from an authenticated
    // GET (ADR-007 #7) and retry once with the same body and idempotency key.
    if (response.status === 403 && errorBody(data)?.code === "CSRF_REJECTED" && method !== "GET" && !retried) {
      // #610: only a tab that has no token (a reload lost it) recovers it and retries; a token this tab held was
      // refused because the session changed, and the write is never replayed under another session.
      if (heldToken) {
        sessionReplaced();
        throw new ApiError(401, null);
      }
      await request("GET", "/settings", { role });
      return request<T>(method, path, { ...options, role }, true);
    }
    throw new ApiError(response.status, errorBody(data));
  }
  return data as T;
}

export type LoadScenarioBody = Pick<S["LoadScenarioRequest"], "reset"> & Partial<S["LoadScenarioRequest"]>;

type LogsEntry = S["LogsSnapshot"]["entries"][number];
/** #577: getLogs filters; no levels means every level. */
export type LogsFilters = { levels?: LogsEntry["level"][]; kind?: LogsEntry["kind"]; q?: string; before?: string; limit?: number };

export const api = {
  readiness: () => request<S["Readiness"]>("GET", "/health/ready"),
  // #487: the presenter gate names the presenter role; consent (A01) uses the page's role, which is the patient's.
  createSession: (body: S["CreateSessionRequest"], key: string, role?: Role) =>
    request<S["CreateSessionResponse"]>("POST", "/sessions", { body, idempotencyKey: key, role }),
  deleteSession: () => request<S["DeletionAccepted"]>("DELETE", "/sessions/current"),
  getProfile: () => request<S["ProfileResponse"]>("GET", "/profile"),
  createCase: (body: S["CaseWrite"], key: string) =>
    request<S["Case"]>("POST", "/cases", { body, idempotencyKey: key }),
  // #266: newest first, one page at a time; pass the previous page's next_cursor for older consultations.
  listCases: (cursor?: string | null, limit?: number) => {
    const query = new URLSearchParams();
    if (cursor) query.set("cursor", cursor);
    if (limit) query.set("limit", String(limit));
    const qs = query.toString();
    return request<S["CaseList"]>("GET", qs ? `/cases?${qs}` : "/cases");
  },
  // #340: the same case list, read without the expired-session redirect, for the resume target on public pages.
  listCasesQuietly: () => request<S["CaseList"]>("GET", "/cases", { quietUnauthorized: true }),
  getCase: (id: string) => request<S["CaseReadResponse"]>("GET", `/cases/${id}`),
  // #116: A15 must render without a session (R17), so its case read never triggers the expired-session redirect.
  getCaseQuietly: (id: string) => request<S["CaseReadResponse"]>("GET", `/cases/${id}`, { quietUnauthorized: true }),
  editCase: (id: string, body: S["CaseEdit"]) => request<S["Case"]>("PATCH", `/cases/${id}`, { body }),
  deleteCase: (id: string, revision: number) =>
    request<S["DeletionAccepted"]>("DELETE", `/cases/${id}?expected_revision=${revision}`),
  listRecords: (id: string) => request<S["RecordList"]>("GET", `/cases/${id}/records`),
  uploadRecord: (id: string, revision: number, file: File, key: string) => {
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("expected_revision", String(revision));
    return request<S["UploadRecordResponse"]>("POST", `/cases/${id}/records`, { form, idempotencyKey: key });
  },
  reviewFact: (id: string, factId: string, body: S["FactReview"]) =>
    request<S["FactReviewResponse"]>("PATCH", `/cases/${id}/facts/${factId}`, { body }),
  nextQuestion: (id: string, revision: number, key: string) =>
    request<S["NextQuestionResponse"]>("POST", `/cases/${id}/questions/next`, {
      body: { expected_revision: revision },
      idempotencyKey: key,
    }),
  saveAnswer: (id: string, questionId: string, body: S["AnswerWrite"]) =>
    request<S["SaveAnswerResponse"]>("PUT", `/cases/${id}/answers/${questionId}`, { body }),
  confirmReview: (id: string, revision: number) =>
    request<S["Case"]>("POST", `/cases/${id}/review`, { body: { expected_revision: revision, facts_confirmed: true } }),
  generateGuidance: (id: string, revision: number, key: string) =>
    request<S["Job"]>("POST", `/cases/${id}/guidance`, { body: { expected_revision: revision }, idempotencyKey: key }),
  getGuidance: (id: string) => request<S["Guidance"]>("GET", `/cases/${id}/guidance`),
  getSources: (id: string) => request<S["CaseSources"]>("GET", `/cases/${id}/sources`),
  searchProviders: (id: string, body: S["ProviderSearchRequest"]) =>
    request<S["ProviderSearchResult"]>("POST", `/cases/${id}/provider-search`, { body }),
  // #267: a card is read with the search it was opened from (409 when that search is no longer current).
  getProvider: (id: string, providerId: string, searchId: string) =>
    request<S["ProviderCard"]>("GET", `/cases/${id}/providers/${providerId}?search_id=${encodeURIComponent(searchId)}`),
  createExport: (id: string, revision: number, key: string) =>
    request<S["Job"]>("POST", `/cases/${id}/exports`, {
      body: { expected_revision: revision, user_reviewed: true },
      idempotencyKey: key,
    }),
  exportUrl: (exportId: string) => `${PATIENT_API}/exports/${exportId}/download`,
  // #418: the PDF read by the page, so a refusal (deleted or changed case, expired link, ended session) is shown in
  // the app instead of the server's JSON error page. The bytes stay in this tab until the browser saves them.
  downloadExport: (exportId: string) =>
    request<Blob>("GET", `/exports/${exportId}/download`, { blob: true }),
  // #460: a presenter's poll (quiet) shows the presenter gate on a 401, never the patient start page. #487: `role`
  // names the API for work that may outlive its page (a presenter's running quick flow).
  getJob: (jobId: string, signal?: AbortSignal, quiet = false, role?: Role) =>
    request<S["Job"]>("GET", `/jobs/${jobId}`, { signal, quietUnauthorized: quiet, role }),
  getSettings: () => request<S["SettingsResponse"]>("GET", "/settings"),
  // #42: learns the session expiry after a page load (any authenticated read reports it); a 401 stays quiet here.
  probeSession: () => request<S["SettingsResponse"]>("GET", "/settings", { quietUnauthorized: true }),
  deleteAll: (token: string, key: string) =>
    request<S["DeletionAccepted"]>("POST", "/privacy/delete-all", {
      body: { confirmation_token: token },
      idempotencyKey: key,
    }),
  // #487: the presenter operations always use the presenter API, whatever page they are called from.
  getRuntime: () => request<S["RuntimeSnapshot"]>("GET", "/presenter/runtime", { quietUnauthorized: true, role: "presenter" }),
  // W06 (ADR-017): public, content-free aggregates; no session involved.
  getTelemetry: (period: "24h" | "7d" | "release") =>
    request<S["TelemetrySnapshot"]>("GET", `/telemetry?period=${period}`, { quietUnauthorized: true }),
  getControls: () => request<S["ControlsResponse"]>("GET", "/presenter/controls", { quietUnauthorized: true, role: "presenter" }),
  // #548: the presenter's Logs view (O01): recent jobs, model calls, events, readiness and API errors, content-free.
  // #577: level (several), kind and the text search q filter every kept row on the server; before is the previous
  // page's next_before (Load older).
  getLogs: (filters: LogsFilters = {}) => {
    const query = new URLSearchParams({ limit: String(filters.limit ?? 500) });
    for (const level of filters.levels ?? []) query.append("level", level);
    if (filters.kind) query.set("kind", filters.kind);
    if (filters.q) query.set("q", filters.q);
    if (filters.before) query.set("before", filters.before);
    return request<S["LogsSnapshot"]>("GET", `/presenter/logs?${query}`, { quietUnauthorized: true, role: "presenter" });
  },
  // #316: reset=false adds the case to the presenter's live demo; prepare="result" readies a quick demo.
  // #358: the server defaults `prepare` and `urgency_input`; a request names only what it changes.
  loadScenario: (scenarioId: string, key: string, body: LoadScenarioBody = { reset: true, prepare: "start" }) =>
    request<S["ScenarioLoaded"]>("POST", `/presenter/scenarios/${scenarioId}/load`, {
      body,
      idempotencyKey: key,
      quietUnauthorized: true,
      role: "presenter",
    }),
  resetDemo: (key: string) =>
    request<S["DeletionAccepted"]>("POST", "/presenter/reset", { idempotencyKey: key, quietUnauthorized: true, role: "presenter" }),
};

const TERMINAL = new Set(["succeeded", "failed", "stale", "cancelled"]);

/** #202: how long to wait before the next job read. Short while a result is likely (a Fury guidance takes ~2 s, a Nano
 * one ~7-15 s, the deadline is 60 s), then ~3 s with jitter. A job read costs the server about 3 ms. */
export function pollDelay(elapsedMs: number, fast = false): number {
  // #548: a presenter's quick flow is read every 300 ms for its first minute (a job read costs ~3 ms), so its dialog
  // moves on, and its result is offered, without waiting most of a 750 ms interval.
  if (fast && elapsedMs < 60_000) return 300;
  if (elapsedMs < 2000) return 400;
  if (elapsedMs < 60_000) return 750;
  return 2500 + Math.random() * 1000;
}

/** Resolves after `ms`, or rejects with an AbortError as soon as `signal` aborts (#278: the listener is removed again). */
export function abortableDelay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) return reject(abortError());
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError());
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/** Poll a job on the `pollDelay` schedule. Stops on terminal state or abort. #278: the signal is checked on every loop
 * and passed to the request, so an abort during a read stops polling at once and a late result is never returned.
 * #453: `onRead` sees every read while the job runs (for example its created_at, for the elapsed time). #460: `quiet`
 * makes a presenter's poll show the presenter gate on a 401. #487: `role` pins the API (default: the page's role). */
export async function pollJob(jobId: string, signal: AbortSignal,
  options: { quiet?: boolean; onRead?: (job: S["Job"]) => void; role?: Role; fast?: boolean } = {}): Promise<S["Job"]> {
  const started = Date.now();
  for (;;) {
    if (signal.aborted) throw abortError();
    const job = await api.getJob(jobId, signal, options.quiet ?? false, options.role);
    if (signal.aborted) throw abortError();
    if (TERMINAL.has(job.status)) return job;
    options.onRead?.(job);
    await abortableDelay(pollDelay(Date.now() - started, options.fast), signal);
  }
}
