// W05 Help (M05; R15, R16). Static urgent help that works without sign-in or a model.
// #340: the way back opens the open consultation's current screen (components/resume.tsx), not consent again.
// #475: "My consultations" only while a guest session is open; without one there is no history to show, and the only
// action is "Start a new consultation".
import { Link } from "react-router-dom";
import { ConsultationLink, useResume } from "../components/resume";
import { Icon } from "../components/Icon";
import { PageHead, StatusBanner } from "../components/ui";

export default function W05() {
  const resume = useResume();
  return (
    <>
      <PageHead eyebrow="Help" title="Help and urgent care" />
      <StatusBanner tone="urgent" title="If you think you may have a medical emergency, call 911 now.">
        <p>Do not wait for this demonstration. Aware Care cannot assess emergencies.</p>
      </StatusBanner>
      <section className="card accent-card acc-violet faq">
        <h2 className="card-title"><span className="card-icon" aria-hidden="true"><Icon name="help" size={18} /></span>Frequently asked questions</h2>
        <details>
          <summary>
            <Icon name="chevron" size={18} className="faq-chevron" />
            Is this real medical advice?
          </summary>
          <p>No. Aware Care is a demonstration using fictional data. It does not diagnose or prescribe.</p>
        </details>
        <details>
          <summary>
            <Icon name="chevron" size={18} className="faq-chevron" />
            What can it help with?
          </summary>
          <p>Organizing one adult, non-urgent concern and preparing questions for a clinician.</p>
        </details>
        <details>
          <summary>
            <Icon name="chevron" size={18} className="faq-chevron" />
            What is outside its scope?
          </summary>
          <p>Emergencies, children, pregnancy-specific concerns and specialized mental-health care.</p>
        </details>
        <details>
          <summary>
            <Icon name="chevron" size={18} className="faq-chevron" />
            Can it book an appointment?
          </summary>
          <p>No. Contact details are shown for you to use yourself; in this demo all doctors are fictional.</p>
        </details>
      </section>
      <div className="actions">
        <ConsultationLink />
        {resume?.open && (
          <Link className="btn secondary" to="/app/history">
            My consultations
          </Link>
        )}
      </div>
    </>
  );
}
