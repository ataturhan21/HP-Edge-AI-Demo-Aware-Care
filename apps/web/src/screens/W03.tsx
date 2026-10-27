// W03 For healthcare (M12; R39). Benefits are hypotheses; outcomes are not measured.
// #331: local processing is a property of the architecture (By design, as on W06), not a hypothesis; a public reader
// gets working next steps (W06, W02). #487: the presenter tools are a choice on the home page (W01), so this page no
// longer asks the presenter API whether to link them (a public page never calls the presenter API).
// #473: its row is labeled By design in every layout (the column is "Benefit", each cell carries its own label at
// 360 px), and the table is not captioned as hypotheses only.
import { Link } from "react-router-dom";
import { Icon, type IconName } from "../components/Icon";
import { PageHead, ScrollTable, StatusBanner } from "../components/ui";

// #253: each stakeholder has its own hue and icon; "Not measured" is a chip so a hypothesis never reads as a result.
// The optional last value links the chip to where the row's fact is shown (#331).
type Row = [string, string, string, string, IconName, string?];
const ROWS: Row[] = [
  ["Patients", "Clearer preparation before a visit", "Not measured", "acc-sky", "user"],
  ["Clinicians", "Better-organized visit summaries", "Not measured", "acc-teal", "stethoscope"],
  ["Health systems", "Local processing at the healthcare edge", "By design: no cloud AI", "acc-violet", "building", "/telemetry#privacy"],
  ["Payers", "Potential reduction in avoidable visits", "Not measured — savings are a hypothesis", "acc-amber", "wallet"],
];

export default function W03() {
  return (
    <>
      <PageHead eyebrow="For healthcare leaders" title="A bounded demonstration of local AI">
        <p>
          The benefits for patients, clinicians and payers are hypotheses to test in a future pilot, not observed results.
          Local processing is not a hypothesis: it follows from how the system is built.
        </p>
      </PageHead>
      <StatusBanner tone="info" title="Outcomes are not measured">
        <p>Synthetic scenarios and summary downloads are never counted as avoided visits or savings.</p>
      </StatusBanner>
      <ScrollTable className="card" label="Benefits by stakeholder">
        <table className="stack-table">
          <caption className="sr-only">Benefits by stakeholder: three hypotheses, and local processing by design</caption>
          <thead>
            <tr>
              <th scope="col">Stakeholder</th>
              <th scope="col">Benefit</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([who, what, measured, accent, icon, link]) => (
              <tr key={who}>
                <td>
                  <span className={`stakeholder ${accent}`}>
                    <span className="card-icon" aria-hidden="true"><Icon name={icon} size={16} /></span>
                    {who}
                  </span>
                </td>
                <td data-label={link ? "By design" : "Hypothesis"}>{what}</td>
                <td data-label="Status">
                  {link ? (
                    <Link className={`chip chip-link ${accent}`} to={link}
                      aria-label={`${measured}: see the privacy figures on the telemetry page`}>{measured}</Link>
                  ) : (
                    <span className="chip acc-slate">{measured}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollTable>
      <div className="actions">
        <Link className="btn" to="/telemetry">See what is measured on this device</Link>
        <Link className="btn secondary" to="/how-it-works">How it works</Link>
      </div>
    </>
  );
}
