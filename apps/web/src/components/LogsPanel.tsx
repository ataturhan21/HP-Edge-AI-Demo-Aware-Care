// #548: the presenter's debug Logs view, a panel of O01 Runtime (/presenter/runtime?view=logs; no new route). It reads
// getLogs (presenter only): recent jobs with their timings, typed codes and #538 rejection reasons, model calls, the
// content-free events (sessions, red-flag routing, concern checks, demo, guidance), readiness changes and the API's
// recent error responses, newest first. Colour follows the level, always with its word: green ok, amber warning or
// retry, red failure, grey information. A monospace time (hh:xx for the rows the service keeps to the hour only),
// filters by level and kind, a text search, auto-refresh every 5 s with Pause, Copy as text and rows that expand to
// their detail. Content-free like the tables it reads: codes, job IDs, statuses and timings, never patient text.
// #577: the level, kind and search filters run on the server over every kept row, and Load older reads the next page.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, type LogsFilters, type S } from "../api/client";
import { Icon, type IconName } from "./Icon";
import { formatDate, formatTime } from "./ui";

type Entry = S["LogsSnapshot"]["entries"][number];
type Level = Entry["level"];
type Kind = Entry["kind"];

export const REFRESH_MS = 5_000;
const SEARCH_DELAY_MS = 300;
/** #616: getLogs refuses a longer q (logs.MAX_QUERY, maxLength in openapi.json); the field takes no more. */
const SEARCH_MAX = 100;
const LEVELS: { id: Level; label: string; icon: IconName }[] = [
  { id: "fail", label: "Failures", icon: "error" },
  { id: "warn", label: "Warnings", icon: "alert" },
  { id: "ok", label: "OK", icon: "check" },
  { id: "info", label: "Info", icon: "info" },
];
const LEVEL_WORD: Record<Level, string> = { ok: "OK", warn: "WARN", fail: "FAIL", info: "INFO" };
const KINDS: { id: Kind; label: string }[] = [
  { id: "job", label: "Jobs" }, { id: "model", label: "Model calls" }, { id: "guidance", label: "Guidance" },
  { id: "safety", label: "Red-flag routing" }, { id: "concern", label: "Concern checks" },
  { id: "session", label: "Sessions" }, { id: "demo", label: "Demo" }, { id: "case", label: "Patient journey" },
  { id: "health", label: "Readiness" }, { id: "error", label: "API errors" },
];
const KIND_LABEL = Object.fromEntries(KINDS.map((k) => [k.id, k.label])) as Record<Kind, string>;

/** The time as the log shows it: hh:mm:ss, or hh:xx (a local range in a half-hour zone) for a row kept to the hour only. */
export function logTime(entry: Entry): string {
  if (entry.precision !== "hour") return formatTime(entry.at, { seconds: true });
  // #570: in a time zone whose offset is not a whole hour, the stored UTC hour is a local range such as 01:30–02:29
  const start = formatTime(entry.at);
  if (start.endsWith(":00")) return `${start.slice(0, 2)}:xx`;
  return `${start}–${formatTime(new Date(Date.parse(entry.at) + 3_599_000).toISOString())}`;
}

/** The element ID of a row's detail (its summary button is `<id>-summary`). */
const rowId = (id: string) => `log-${id.replace(/[^A-Za-z0-9_-]/g, "-")}`;

function duration(ms: number | null): string | null {
  if (ms === null) return null;
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
}

/** One line of the plain-text copy (to paste into an issue or a chat). */
export function logLine(e: Entry): string {
  const parts = [formatDate(e.at), logTime(e), LEVEL_WORD[e.level].padEnd(4), e.kind.padEnd(8), e.name];
  if (e.status) parts.push(`status=${e.status}`);
  if (e.code) parts.push(`code=${e.code}`);
  const took = duration(e.duration_ms);
  if (took) parts.push(`took=${took.replace(" ", "")}`);
  if (e.reasons?.length) parts.push(`reasons=${e.reasons.join(",")}`);
  if (e.reason) parts.push(`reason="${e.reason}"`);
  for (const d of e.detail) parts.push(`${d.label.replace(/ /g, "_")}=${d.value}`);
  return parts.join(" ");
}

export function LogsPanel({ onSessionEnded }: { onSessionEnded: () => void }) {
  const [data, setData] = useState<S["LogsSnapshot"] | null>(null);
  const [older, setOlder] = useState<Entry[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [failed, setFailed] = useState(false);
  const [paused, setPaused] = useState(false);
  const [levels, setLevels] = useState<Set<Level>>(() => new Set(LEVELS.map((l) => l.id)));
  const [kind, setKind] = useState<Kind | "all">("all");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [copied, setCopied] = useState<string | null>(null);
  const ended = useRef(onSessionEnded);
  ended.current = onSessionEnded;
  const asked = useRef(0);
  const focusRow = useRef<string | null>(null);

  // The search reaches the server once typing pauses.
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim()), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [query]);

  const filters = useMemo<LogsFilters>(() => ({
    levels: levels.size === LEVELS.length || levels.size === 0 ? undefined : [...levels],
    kind: kind === "all" ? undefined : kind,
    q: search || undefined,
  }), [levels, kind, search]);

  const fail = useCallback((err: unknown) => {
    if (err instanceof ApiError && (err.status === 401 || (err.status === 403 && err.code === "PRESENTER_REQUIRED")))
      ended.current();
    else setFailed(true);
  }, []);

  // The newest page for these filters; it replaces any older pages shown before.
  const load = useCallback(() => {
    const id = ++asked.current;
    return api.getLogs(filters).then((snapshot) => {
      if (id !== asked.current) return;
      setData(snapshot);
      setOlder([]);
      setNext(snapshot.next_before);
      setFailed(false);
    }, (err) => {
      if (id === asked.current) fail(err);
    });
  }, [filters, fail]);

  const loadOlder = () => {
    if (!next || loadingOlder) return; // aria-disabled while loading, so keyboard focus stays on the button (#615)
    const id = ++asked.current;
    setLoadingOlder(true);
    setPaused(true); // a refresh would drop the older rows: it waits until the presenter resumes or refreshes
    api.getLogs({ ...filters, before: next }).then((page) => {
      if (id !== asked.current) return;
      focusRow.current = page.entries[0]?.id ?? null;
      setOlder((now) => [...now, ...page.entries]);
      setNext(page.next_before);
      setFailed(false);
    }, (err) => {
      if (id === asked.current) fail(err);
    }).finally(() => setLoadingOlder(false));
  };

  useEffect(() => {
    void load();
  }, [load]);
  // #615: after Load older, focus moves to the first row it loaded (the button may be gone: that was the last page)
  useEffect(() => {
    const id = focusRow.current;
    focusRow.current = null;
    if (id) document.getElementById(`${rowId(id)}-summary`)?.focus();
  }, [older]);
  useEffect(() => {
    if (paused) return;
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [paused, load]);

  const shown = useMemo(() => (levels.size === 0 ? [] : [...(data?.entries ?? []), ...older]), [data, older, levels]);
  const counts = data?.level_counts ?? { ok: 0, warn: 0, fail: 0, info: 0 };
  const total = levels.size === 0 ? 0 : data?.total ?? 0;

  const toggleLevel = (id: Level) => setLevels((now) => {
    const next = new Set(now);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
  const toggleRow = (id: string) => setOpen((now) => {
    const next = new Set(now);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });

  const copy = async () => {
    const header = data ? `Aware Care logs · ${data.mode} mode · readiness ${data.readiness} · observed ${data.observed_at}` : "";
    const body = [header, ...shown.map(logLine)].join("\n");
    try {
      await navigator.clipboard.writeText(body);
      setCopied(`Copied ${shown.length} ${shown.length === 1 ? "line" : "lines"} as text.`);
    } catch {
      setCopied("The browser did not allow copying. Select the rows and copy them instead.");
    }
  };

  return (
    <section className="logs" aria-labelledby="logs-title">
      <div className="logs-head">
        <h2 id="logs-title">Logs</h2>
        <p className="small muted">
          Newest first: jobs, model calls, sessions, red-flag routing, concern checks, readiness and API errors. Codes,
          IDs and timings only, never patient text. Rows marked hh:xx (or an hour range such as 01:30–02:29) are kept to the hour only.
        </p>
      </div>

      {data && (
        <p className={`logs-health ${data.readiness === "ready" ? "ok" : data.readiness === "degraded" ? "warn" : "fail"}`}>
          <Icon name={data.readiness === "ready" ? "check" : "alert"} size={16} />
          <span>
            <b>Readiness: {data.readiness}</b> · {data.mode} mode · queue {data.queue_depth} · active {data.active_jobs}
            <span className="muted"> · observed {formatTime(data.observed_at, { seconds: true })}</span>
          </span>
        </p>
      )}

      <div className="logs-tools">
        <div className="logs-levels" role="group" aria-label="Show levels">
          {LEVELS.map((l) => (
            <button key={l.id} type="button" className={`log-chip lvl-${l.id}`} aria-pressed={levels.has(l.id)}
              onClick={() => toggleLevel(l.id)}>
              <Icon name={l.icon} size={16} />
              {l.label} <span className="log-count">{counts[l.id]}</span>
            </button>
          ))}
        </div>
        <div className="logs-fields">
          <label className="logs-field">
            <span>Kind</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as Kind | "all")}>
              <option value="all">All kinds</option>
              {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
            </select>
          </label>
          <label className="logs-field logs-search">
            <span>Search</span>
            <input type="search" value={query} maxLength={SEARCH_MAX} onChange={(e) => setQuery(e.target.value)}
              placeholder="code, job ID, task…" />
          </label>
        </div>
        <div className="logs-actions">
          <button type="button" className="btn secondary sm" aria-pressed={paused} onClick={() => setPaused((p) => !p)}>
            {paused ? "Resume auto-refresh" : "Pause auto-refresh"}
          </button>
          <button type="button" className="btn secondary sm" onClick={() => void load()}>Refresh now</button>
          <button type="button" className="btn secondary sm" onClick={() => void copy()} disabled={!data}>
            Copy as text
          </button>
        </div>
      </div>
      <p className="small muted logs-status">
        {/* Announced only when the presenter changes something (pause, copy), not on every refresh. */}
        <span role="status" aria-live="polite">
          {paused ? `Auto-refresh paused${older.length ? " while older rows are shown" : ""}.` : `Auto-refresh every ${REFRESH_MS / 1000} s.`}
          {copied && ` ${copied}`}
        </span>
        {data && ` Showing ${shown.length} of ${total}${shown.length < total ? " (the newest)" : ""}.`}
      </p>
      {failed && <p className="logs-error small" role="alert">The logs could not be read just now; the next refresh tries again.</p>}

      {data && shown.length === 0 && <p className="logs-empty">No entries match these filters.</p>}
      {shown.length > 0 && (
        <ol className="log-list" aria-label="Log entries, newest first">
          {shown.map((e) => {
            const expanded = open.has(e.id);
            const detailId = rowId(e.id);
            const took = duration(e.duration_ms);
            return (
              <li key={e.id} className={`log-row lvl-${e.level}`}>
                <button type="button" className="log-summary" id={`${detailId}-summary`} aria-expanded={expanded}
                  aria-controls={detailId}
                  onClick={() => toggleRow(e.id)}>
                  <time className="log-time" dateTime={e.at}
                    title={e.precision === "hour" ? "Kept to the hour only (content-free)" : undefined}>{logTime(e)}</time>
                  <span className={`log-level lvl-${e.level}`}>{LEVEL_WORD[e.level]}</span>
                  <span className="log-kind">{KIND_LABEL[e.kind]}</span>
                  <span className="log-name">{e.name}</span>
                  <span className="log-meta">
                    {e.status && <span>{e.status}</span>}
                    {e.code && <code>{e.code}</code>}
                    {took && <span>{took}</span>}
                  </span>
                  <Icon name="chevron" size={16} className="log-chevron" />
                  {e.reason && <span className="log-reason">{e.reason}</span>}
                </button>
                {expanded && (
                  <dl className="log-detail" id={detailId}>
                    <div><dt>Time</dt><dd>{formatDate(e.at)} {logTime(e)}{e.precision === "hour" ? " (hour only)" : ""}</dd></div>
                    <div><dt>Source</dt><dd>{e.source.replace("_", " ")}</dd></div>
                    {e.reason && <div><dt>Why it failed</dt><dd>{e.reason}</dd></div>}
                    {e.reasons && e.reasons.length > 0 && (
                      <div><dt>Rejection reasons</dt><dd><ul>{e.reasons.map((r) => <li key={r}><code>{r}</code></li>)}</ul></dd></div>
                    )}
                    {e.detail.map((d) => <div key={d.label}><dt>{d.label}</dt><dd><code>{d.value}</code></dd></div>)}
                  </dl>
                )}
              </li>
            );
          })}
        </ol>
      )}
      {next && shown.length > 0 && (
        <p className="logs-more">
          <button type="button" className="btn secondary sm" onClick={loadOlder} aria-disabled={loadingOlder || undefined}>
            {loadingOlder ? "Loading older rows…" : "Load older"}
          </button>
        </p>
      )}
    </section>
  );
}
