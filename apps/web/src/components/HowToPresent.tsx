// #692 (owner decision B5, 28 Oct 2026): a short "How to present" help panel inside the presenter tools (O03
// Scenarios), with the same steps as README "Present it": the same titles, in the same order
// (tests/tooling/test_docs_consistency.py keeps them in sync), each with one or two plain sentences for the screen.
// A disclosure: one button (aria-expanded, aria-controls) that opens and closes the list; keyboard and screen-reader
// friendly, closed by default so the flows stay the first thing on the page.
import { useId, useState } from "react";
import { DEVICE } from "./Brand";
import { Icon } from "./Icon";

/** The steps of README "Present it": [title, what to do]. */
export const HOW_TO_PRESENT: readonly (readonly [string, string])[] = [
  ["Open the presenter tools",
    "Through the SSH tunnel, open http://127.0.0.1:18180, choose Open the presenter tools, then Start presenter session. " +
    "The status line says AI ready when the model answers."],
  ["Type consultations by hand in another browser",
    "Use a separate browser or a private window for consultations typed by hand: a quick flow in this browser ends " +
    "one (the presenter screen asks first)."],
  ["Run a quick flow",
    `Choose Run on ${DEVICE}. Open the result shows it in this window as the Demo patient; Back to presenter returns ` +
    "here, and Show again opens it once more."],
  ["Clear demos between audiences",
    "Clear demos for the next audience (here once a demo ran, and on More scenarios) removes this browser's demos. " +
    "Consultations typed by hand stay."],
  ["Show Telemetry",
    "Basic for five headline figures, Advanced for every figure and the break-even, Download PNG for a slide. A figure " +
    "that is Not measured says when it will appear."],
  ["Use any screen",
    "Everything works with the keyboard only, on a phone (the navigation is behind Menu) and on large screens and " +
    "projectors."],
  ["Show the controls when asked",
    "Evidence and controls has no tab: open /presenter/controls directly. Unverified means no proof is recorded for " +
    "this build, not that a control failed."],
];

export function HowToPresent() {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <section className="how-to-present" aria-label="How to present">
      <button type="button" className="btn secondary sm how-toggle" aria-expanded={open} aria-controls={id}
        onClick={() => setOpen(!open)}>
        <Icon name="info" size={18} />
        How to present
      </button>
      <ol id={id} className="how-steps" hidden={!open}>
        {HOW_TO_PRESENT.map(([title, text]) => (
          <li key={title}>
            <b>{title}.</b> {text}
          </li>
        ))}
      </ol>
    </section>
  );
}
