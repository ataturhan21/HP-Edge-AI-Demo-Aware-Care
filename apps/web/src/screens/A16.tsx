// A16 Service limits (M05; R16, R17). Explains unsupported scope, declined consent or unavailability.
import { Link, useLocation } from "react-router-dom";
import { PageHead, StatusBanner } from "../components/ui";

const REASONS: Record<string, { title: string; body: string }> = {
  declined: { title: "You chose not to continue", body: "No information was saved. You can return at any time." },
  unsupported_age: { title: "This demonstration is for adults", body: "Please talk with a parent, guardian or clinician." },
  unsupported: {
    title: "This concern is outside the demo scope",
    body: "Aware Care cannot assess this example. Please contact a clinician for advice.",
  },
  service_unavailable: {
    title: "The service is unavailable",
    body: "Guidance cannot be produced right now. This is not a finding about your health.",
  },
};

export default function A16() {
  const reason = (useLocation().state as { reason?: string } | null)?.reason ?? "unsupported";
  const content = REASONS[reason] ?? REASONS.unsupported;
  return (
    <div className="narrow">
      <PageHead eyebrow="Service limits" title={content.title} />
      <StatusBanner tone="warn" title="No answer was invented">
        <p>{content.body}</p>
      </StatusBanner>
      <section className="card">
        <h2>Other options</h2>
        <ul className="bullets">
          <li>Contact your usual clinician or a nurse line.</li>
          <li>In an emergency call 911.</li>
        </ul>
        {/* #219: the label is the screen contract's primary action; this line says where it leads. */}
        <p className="small muted" id="alternative-desc">
          Opens Help: when to get urgent care, and how to reach a clinician or a nurse line.
        </p>
        <div className="actions">
          <Link className="btn secondary" to="/help" aria-describedby="alternative-desc">
            Use reviewed alternative guidance
          </Link>
          {/* #408: the same target as the header link of this name; A03 sends anyone without a session to A01. */}
          <Link className="btn" to="/app/new">
            Start a new consultation
          </Link>
        </div>
      </section>
    </div>
  );
}
