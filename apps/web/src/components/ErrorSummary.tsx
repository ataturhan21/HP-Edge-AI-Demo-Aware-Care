// Error summary for a failed submit (#342; WCAG 3.3.1, 2.4.3). Shown at the top of a form, it lists each problem as a
// link that moves focus to its field, and takes focus itself on every failed submit, so the person learns what is
// wrong wherever the button sat. It is announced once, through that focus: it is not a live region, and the screens
// that use it render their field messages without role="alert" while it is shown. Presentation only: the screen
// decides what is a problem, and the field messages stay next to their fields.
import { useEffect, useRef } from "react";

export type ErrorSummaryItem = {
  /** The id of the element the link moves focus to (a field, or the first choice of a group). */
  target: string;
  /** What to do, in plain words. */
  text: string;
};

export function ErrorSummary({ items, attempt, title = "Check these before you continue" }: {
  /** The problems still open; the summary disappears when the list is empty. */
  items: ErrorSummaryItem[];
  /** Incremented on each failed submit: the summary takes focus whenever it changes. */
  attempt: number;
  title?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const shown = items.length > 0;
  useEffect(() => {
    if (attempt > 0) ref.current?.focus();
  }, [attempt]);
  if (!shown) return null;
  return (
    <div className="error-summary" ref={ref} tabIndex={-1} role="group" aria-labelledby="error-summary-title">
      <h2 id="error-summary-title" className="error-summary-title">
        <span className="error-summary-mark" aria-hidden="true">!</span>
        {title}
      </h2>
      <ul>
        {items.map((item) => (
          <li key={item.target}>
            <a href={`#${item.target}`} onClick={(e) => {
              e.preventDefault();
              const field = document.getElementById(item.target);
              field?.scrollIntoView({ block: "center" });
              field?.focus({ preventScroll: true });
            }}>
              {item.text}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
