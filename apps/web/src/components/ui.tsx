// Shared presentational components. They render behavior only; authorization,
// clinical rules, ranking and persistence stay in the server-side owners.
import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { CONFIGURED_ORIGIN, SITE_TITLE } from "./Brand";
import { Icon, type IconName } from "./Icon";
import { useHideJourney } from "./JourneySteps";

type Tone = "info" | "warn" | "error" | "success" | "urgent";
const ICON: Record<Tone, IconName> = { info: "info", warn: "alert", error: "error", success: "check", urgent: "urgent" };
const LABEL: Record<Tone, string> = {
  info: "Information",
  warn: "Attention",
  error: "Problem",
  success: "Done",
  urgent: "Urgent",
};

export function StatusBanner({ tone = "info", title, children }: { tone?: Tone; title?: string; children?: ReactNode }) {
  return (
    <div className={`notice ${tone}`} role={tone === "error" || tone === "urgent" ? "alert" : "status"}>
      <span className="notice-icon" aria-hidden="true">
        <Icon name={ICON[tone]} size={22} />
      </span>
      <div>
        <span className="sr-only">{LABEL[tone]}: </span>
        {title && <strong>{title}</strong>}
        {children && <div>{children}</div>}
      </div>
    </div>
  );
}

/** #461/#487: the one tunnel to a demo device, one port for patients and presenters (placeholders only; the device's
 *  SSH details are not in the app). Then open http://127.0.0.1:18180. */
export const DEVICE_TUNNEL = "ssh -N -p <ssh-port> -L 18180:127.0.0.1:8180 <user>@<host>";

/**
 * #461: the API refused this page's address (ORIGIN_REJECTED): the device accepts requests only from the address it is
 * configured for. Says which one (from the gateway's device script; for "localhost" the 127.0.0.1 twin), how to reach
 * it through the tunnel, and how a different address is configured. #487: one address serves patient pages and the
 * presenter tools alike. Used by every write's error banner, and up front on the presenter gate at "localhost".
 */
export function OriginHelp({ refused = true }: { refused?: boolean }) {
  const here = window.location;
  const twin = here.hostname === "localhost" ? `${here.protocol}//127.0.0.1${here.port ? `:${here.port}` : ""}` : null;
  const target = CONFIGURED_ORIGIN ?? twin;
  const address = target && target !== here.origin ? `${target}${here.pathname}${here.search}` : null;
  return (
    <StatusBanner tone={refused ? "error" : "warn"} title="Open Aware Care at the address this device is set up for">
      <p>
        {refused ? "The device did not accept this address" : "This address will not work here"} ({here.origin}): it
        accepts requests only from {CONFIGURED_ORIGIN ? <b>{CONFIGURED_ORIGIN}</b> : "the address in its deploy configuration"},
        for patients and presenters alike.
        {address && <> Open <a href={address}>{address}</a> instead.</>}
      </p>
      <p className="small">Reach the device through one SSH tunnel, then open http://127.0.0.1:18180:</p>
      <code className="cmd">{DEVICE_TUNNEL}</code>
      <p className="small">
        To use a different address, deploy with <code>--origin</code> (or set <code>network.browser_origin</code> in
        the deploy configuration).
      </p>
    </StatusBanner>
  );
}

export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (error instanceof ApiError && error.code === "ORIGIN_REJECTED") return <OriginHelp />;
  const message =
    error instanceof ApiError
      ? error.status === 0
        ? "The Aware Care service could not be reached. Your entries are kept on this page."
        : error.message
      : "Something went wrong. Your entries are kept on this page.";
  return (
    <StatusBanner tone="error" title="This step did not complete">
      <p>{message}</p>
      {onRetry && (
        <button type="button" className="btn secondary sm" onClick={onRetry}>
          Try again
        </button>
      )}
    </StatusBanner>
  );
}

export function LoadingState({ label }: { label: string }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

// `page`: the state replaces the whole screen, so its title is the page's h1. #403: like PageHead, that heading takes
// focus when the state appears (the tab title is the same on every route, #107), so the change of page is announced.
// `headingId` (#420): a section-level state's heading can be named and focused by the screen that owns it.
export function EmptyState({ title, children, action, page, headingId }: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  page?: boolean;
  headingId?: string;
}) {
  useHideJourney(Boolean(page)); // #232: no step indicator over a page-level empty state
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (!page) return;
    document.title = SITE_TITLE;
    ref.current?.focus();
  }, [page, title]);
  return (
    <div className="card empty">
      {page ? (
        <h1 tabIndex={-1} ref={ref} id={headingId}>{title}</h1>
      ) : (
        <h2 tabIndex={headingId ? -1 : undefined} id={headingId}>{title}</h2>
      )}
      {children}
      {action && <div className="actions center">{action}</div>}
    </div>
  );
}

/** #232: the case behind this link cannot be shown. Says why it may be, and offers the two ways on. */
export function CaseUnavailable() {
  return (
    <EmptyState page title="This consultation is not available"
      action={
        <>
          <Link className="btn" to="/app/new">Start a new consultation</Link>
          <Link className="btn secondary" to="/app/history">Go to history</Link>
        </>
      }>
      <p>
        It may have ended with your guest session, been deleted, or belong to a different session. Nothing from it can
        be shown here.
      </p>
    </EmptyState>
  );
}

/**
 * #402: a control that is disabled while its action runs (or replaced by the action's result) drops keyboard focus to
 * the page body, so a keyboard or screen-reader user starts again from the top. Pass `true` while the action runs: the
 * element that had focus when it started is remembered (read while rendering, before the control is disabled), and
 * when it ends focus returns to that element if it is still on the page and enabled, otherwise to `fallback(element)`
 * or the page heading. Focus that something else took meanwhile (a dialog, an editor, a moved-to result) is kept.
 * `within`: only an element inside it is remembered (a Button minds only its own focus).
 */
export function useFocusReturn(busy: boolean, options: {
  within?: RefObject<HTMLElement | null>;
  fallback?: (opener: HTMLElement) => HTMLElement | null | undefined;
} = {}) {
  const opener = useRef<HTMLElement | null>(null);
  const was = useRef(busy);
  if (busy && !was.current && typeof document !== "undefined") {
    const active = document.activeElement;
    const scope = options.within?.current;
    opener.current = active instanceof HTMLElement && active !== document.body && (!options.within || Boolean(scope?.contains(active)))
      ? active : null;
  }
  was.current = busy;
  const fallback = useRef(options.fallback);
  fallback.current = options.fallback;
  useEffect(() => {
    if (busy || !opener.current) return;
    const el = opener.current;
    opener.current = null;
    const active = document.activeElement;
    if (active && active !== document.body) return;
    const usable = (node: HTMLElement | null | undefined): node is HTMLElement =>
      Boolean(node && node.isConnected && !(node as HTMLButtonElement).disabled);
    const next = usable(el) ? el : fallback.current?.(el);
    (usable(next) ? next : document.querySelector<HTMLElement>("main h1"))?.focus();
  }, [busy]);
}

export function Button({
  pending,
  pendingLabel = "Working…",
  children,
  className = "btn",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { pending?: boolean; pendingLabel?: string }) {
  const ref = useRef<HTMLButtonElement>(null);
  useFocusReturn(Boolean(pending), { within: ref }); // #402: back on this button when its action ends
  return (
    <button {...rest} ref={ref} className={className} disabled={rest.disabled || pending} aria-busy={pending || undefined}>
      {pending ? pendingLabel : children}
    </button>
  );
}

/** #158: a table that may scroll sideways on narrow screens. The scroll region is focusable and named, so keyboard
 * users can reach and scroll it (WCAG 2.1.1; axe scrollable-region-focusable). */
export function ScrollTable({ label, className = "", children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <div className={`tablewrap ${className}`.trim()} tabIndex={0} role="region" aria-label={label}>
      {children}
    </div>
  );
}

export function SyntheticBadge({ children = "Synthetic demo data" }: { children?: ReactNode }) {
  return <span className="badge amber">{children}</span>;
}

/** #283: focus goes back to the element that opened a dialog; if that is gone or disabled (a deleted row, a button
 * disabled while its action runs), to the page heading, so it never falls back to the page body. */
function restoreFocus(opener: HTMLElement | null) {
  const usable = opener && opener.isConnected && !(opener as HTMLButtonElement).disabled && opener !== document.body;
  const target = usable ? opener : document.querySelector<HTMLElement>("main h1, h1");
  target?.focus();
}

/** Modal with focus containment and focus return to the opener.
 * #629: with `pendingLabel`, a pending action locks the dialog until it finishes or fails: Escape and Cancel do nothing
 * (Cancel is disabled), the confirm button reads `pendingLabel`, the dialog is `aria-busy` and says so to screen readers,
 * and focus stays in the dialog. Once unlocked (the owner shows any error inside), Cancel and Escape work again. */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel = "Cancel",
  destructive,
  onConfirm,
  onCancel,
  pending,
  pendingLabel,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm?: () => void;
  onCancel: () => void;
  pending?: boolean;
  pendingLabel?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const locked = Boolean(pending && pendingLabel);
  // #283: the latest cancel handler, read when a key is pressed, so a re-render of the owner (for example A13's 30 s
  // clock) never re-runs the focus effect: focus is set once on open and restored once on close.
  const cancel = useRef(onCancel);
  cancel.current = onCancel;
  const lockedRef = useRef(locked);
  lockedRef.current = locked;
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const node = ref.current;
    node?.querySelector<HTMLElement>("button, [href], input")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !lockedRef.current) cancel.current();
      if (e.key !== "Tab" || !node) return;
      const items = Array.from(node.querySelectorAll<HTMLElement>("button:not([disabled]), [href], input"));
      if (!items.length) {
        // #629: a locked dialog has nothing to tab to; focus stays on the dialog.
        e.preventDefault();
        node.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      restoreFocus(opener);
    };
  }, []);
  // #629: the focused button is disabled while locked, so focus moves to the dialog itself (not the page body); when
  // the action fails and the dialog stays, it goes back to the confirm button.
  const wasLocked = useRef(false);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (locked) {
      if (!node.contains(document.activeElement) || document.activeElement instanceof HTMLButtonElement) node.focus();
    } else if (wasLocked.current && (document.activeElement === node || document.activeElement === document.body)) {
      Array.from(node.querySelectorAll<HTMLElement>(".actions button:not([disabled])")).pop()?.focus();
    }
    wasLocked.current = locked;
  }, [locked]);
  return (
    <div className="modalshade">
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="dialog-title" ref={ref}
        tabIndex={-1} aria-busy={locked || undefined}>
        <h2 id="dialog-title">{title}</h2>
        {children}
        {/* The live region is there from the start, so its text is announced when the dialog locks. */}
        {pendingLabel && (
          <p className="sr-only" role="status">
            {locked ? pendingLabel : ""}
          </p>
        )}
        <div className="actions">
          <button type="button" className="btn secondary" onClick={onCancel} disabled={locked}>
            {cancelLabel}
          </button>
          {onConfirm && (
            <Button type="button" className={destructive ? "btn danger" : "btn"} onClick={onConfirm} pending={pending}
              pendingLabel={pendingLabel}>
              {confirmLabel}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export function PageHead({ eyebrow, title, children }: { eyebrow?: ReactNode; title: string; children?: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = SITE_TITLE; // #107: the site name, not the page heading
    ref.current?.focus();
  }, [title]);
  return (
    <header className="pagehead">
      {eyebrow && <p className="eyebrow">{eyebrow}</p>}
      <h1 tabIndex={-1} ref={ref}>
        {title}
      </h1>
      {children}
    </header>
  );
}

// #347: one date style ("16 Oct 2026") and one time style (24-hour "17:04") on the patient site, telemetry and
// presenter. Every displayed date or time goes through these helpers. Built from the date's own fields, not Intl, so
// the output is the same in every browser locale (#305: Latin digits; no "Sept"; no "24:05" hour-cycle quirk).
// Times are in the browser's time zone unless `utc` is set; then the time is labeled "UTC". Seconds only for
// technical status fields (`seconds`). A value that is not a date is shown as given (a string) or as "—", never hidden.
export type DateTimeStyle = { utc?: boolean; seconds?: boolean };
type When = string | number | Date | null | undefined;
export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const pad2 = (n: number) => String(n).padStart(2, "0");

const unknown = (value: When) => (typeof value === "string" && value.trim() ? value : "—");

function fields(value: When, utc: boolean) {
  const d = value == null || value === "" ? new Date(NaN) : new Date(value);
  return utc
    ? { y: d.getUTCFullYear(), mo: d.getUTCMonth(), day: d.getUTCDate(), h: d.getUTCHours(), mi: d.getUTCMinutes(), s: d.getUTCSeconds(), ok: Number.isFinite(d.getTime()) }
    : { y: d.getFullYear(), mo: d.getMonth(), day: d.getDate(), h: d.getHours(), mi: d.getMinutes(), s: d.getSeconds(), ok: Number.isFinite(d.getTime()) };
}

/** "16 Oct 2026". A calendar date such as "2026-10-16" is shown as that date in every time zone. */
export function formatDate(value: When, style: DateTimeStyle = {}): string {
  const f = fields(value, style.utc === true || (typeof value === "string" && DATE_ONLY.test(value)));
  return f.ok ? `${f.day} ${MONTHS[f.mo]} ${f.y}` : unknown(value);
}

/** "17:04" (24-hour); "17:04 UTC" with `utc`; "17:04:03" with `seconds` (technical fields only). */
export function formatTime(value: When, style: DateTimeStyle = {}): string {
  const f = fields(value, style.utc === true);
  if (!f.ok) return unknown(value);
  return `${pad2(f.h)}:${pad2(f.mi)}${style.seconds ? `:${pad2(f.s)}` : ""}${style.utc ? " UTC" : ""}`;
}

/** "16 Oct 2026, 17:04" ("…, 17:04 UTC" with `utc`). */
export function formatDateTime(value: When, style: DateTimeStyle = {}): string {
  if (!fields(value, false).ok) return unknown(value);
  return `${formatDate(value, { utc: style.utc })}, ${formatTime(value, style)}`;
}

export function UrgentHelpLink() {
  return (
    <p className="small">
      In an emergency call <strong>911</strong> now. <Link to="/help">Urgent help information</Link>
    </p>
  );
}
