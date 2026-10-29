// #677 (owner decision, 28 Oct 2026: warn first): a presenter action that gives this browser's patient pages a synthetic
// demo patient (a quick flow, its Try again, Load scenario) ends any consultation typed by hand in this browser, because
// the tabs of one browser share one patient cookie. When the browser holds one (presenterRuns.ts
// handTypedConsultationOpen), the presenter screen asks first: what happens to that consultation, the safe alternative
// (a separate browser or a private window for consultations typed by hand) and 2 choices, Continue anyway or Cancel.
// An alert dialog: focus starts on Cancel (the safe choice), Tab and Shift+Tab stay inside it, Escape cancels. The owner
// puts focus back on the button that asked on Cancel; on Continue anyway the action's own dialog or button takes it.
import { useEffect, useRef, type KeyboardEvent as ReactKeyboardEvent } from "react";

export type GuardedAction = "flow" | "scenario";

/** The warning's words, also for the tests: the title, what happens, and the safe alternative. */
export const HAND_TYPED_TITLE = "A consultation typed by hand is open in this browser";
export function handTypedEffect(action: GuardedAction): string {
  const doing = action === "flow" ? "Running this quick flow" : "Loading this scenario";
  return `${doing} ends it: this browser's patient pages get a synthetic demo patient instead, and the consultation ` +
    "typed by hand can no longer be opened here (its tab says “Your session ended”). Its answers stay on the device, " +
    "out of reach, until its session expires.";
}
export const HAND_TYPED_ALTERNATIVE = "To keep it, choose Cancel. Type consultations by hand in a separate browser or " +
  "a private window: presenter demos never touch them there.";

export function HandTypedWarning({ action, onCancel, onContinue }: {
  action: GuardedAction;
  onCancel: () => void;
  onContinue: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const cancel = useRef(onCancel);
  cancel.current = onCancel;

  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("[data-cancel]")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      cancel.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const trap = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab" || !ref.current) return;
    const items = Array.from(ref.current.querySelectorAll<HTMLElement>("button"));
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || !ref.current.contains(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || !ref.current.contains(active))) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="modalshade">
      <div className="modal hand-typed" role="alertdialog" aria-modal="true" ref={ref} onKeyDown={trap}
        aria-labelledby="hand-typed-title" aria-describedby="hand-typed-effect hand-typed-alternative"
        data-testid="hand-typed-warning">
        <p className="eyebrow">Presenter · this browser</p>
        <h2 id="hand-typed-title">{HAND_TYPED_TITLE}</h2>
        <p id="hand-typed-effect">{handTypedEffect(action)}</p>
        <p id="hand-typed-alternative">{HAND_TYPED_ALTERNATIVE}</p>
        <div className="actions">
          <button type="button" className="btn secondary" data-cancel onClick={onCancel}>Cancel</button>
          <button type="button" className="btn danger" onClick={onContinue}>Continue anyway</button>
        </div>
      </div>
    </div>
  );
}
