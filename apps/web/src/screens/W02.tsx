// W02 How it works (M04; R11, R14). Three steps and an example question; no outcome claims.
import { ConsultationLink } from "../components/resume";
import { Icon } from "../components/Icon";
import { PageHead } from "../components/ui";

export default function W02() {
  return (
    <>
      <PageHead eyebrow="How it works" title="Three steps to a clearer next step">
        <p>Aware Care organizes what you share. It does not diagnose or guarantee any outcome.</p>
      </PageHead>
      <div className="grid3 steps-grid">
        <section className="card accent-card acc-blue">
          <span className="step-icon" aria-hidden="true"><Icon name="chat" size={20} /></span>
          <h2>1. Describe one concern</h2>
          <p>Tell us the main thing you would like help with. Optional profile details are clearly marked.</p>
        </section>
        <section className="card accent-card acc-teal">
          <span className="step-icon" aria-hidden="true"><Icon name="list" size={20} /></span>
          <h2>2. Answer up to 10 questions</h2>
          <p>Each question is shown one at a time. You can answer “Not sure” or skip.</p>
        </section>
        <section className="card accent-card acc-violet">
          <span className="step-icon" aria-hidden="true"><Icon name="check" size={20} /></span>
          <h2>3. Review and prepare</h2>
          <p>Confirm what you shared, see labeled guidance and its limits, compare fictional doctors and download a summary.</p>
        </section>
      </div>
      <section className="card accent-card acc-sky example-card" aria-labelledby="example">
        <h2 id="example" className="card-title"><span className="card-icon" aria-hidden="true"><Icon name="help" size={18} /></span>Example question</h2>
        <p>
          <strong>When did this concern begin?</strong>
        </p>
        <ul className="example-choices">
          <li>Within the last week</li>
          <li>One to four weeks ago</li>
          <li>More than a month ago</li>
          <li>Not sure</li>
        </ul>
      </section>
      <div className="actions">
        <ConsultationLink />
      </div>
    </>
  );
}
