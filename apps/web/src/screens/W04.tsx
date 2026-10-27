// W04 Privacy (M11; R34-R36). Local boundary, retrieval and retention; download boundary.
// #440/#471: the Retention card names every kind of record the device keeps and for how long, as the API enforces it
// (apps/api/app/modules/privacy/service.py; spec/engineering/05-privacy-and-security.md).
import { Link } from "react-router-dom";
import { Icon } from "../components/Icon";
import { PageHead } from "../components/ui";

export default function W04() {
  return (
    <>
      <PageHead eyebrow="Privacy" title="How your demo information is handled" />
      <div className="grid2">
        <section className="card accent-card acc-teal">
          <h2 className="card-title"><span className="card-icon" aria-hidden="true"><Icon name="chip" size={18} /></span>Local processing</h2>
          <p>The application, database and model runtime run on one local device. No cloud model is used as a fallback.</p>
          <p>This build makes no online lookups. Provider data comes from a fictional, dated snapshot.</p>
        </section>
        <section className="card accent-card acc-sky">
          <h2 className="card-title"><span className="card-icon" aria-hidden="true"><Icon name="clock" size={18} /></span>Retention</h2>
          <ul className="bullets">
            <li>Guest information ends after 30 minutes idle or 8 hours, whichever comes first.</li>
            <li>Summary downloads expire after 15 minutes and after any change to your answers.</li>
            <li>Operational events contain no health content and are kept for 30 days.</li>
            <li>
              Job records, the status and timing of each task such as preparing guidance, a summary or a deletion,
              contain no health content. When your session ends they lose any link to you and keep only the hour; they
              are deleted after 30 days.
            </li>
            <li>
              AI usage counts are kept for 90 days: the task, outcome, duration, token counts and energy of each AI call,
              by the hour. They contain no health content, case or person.
            </li>
            <li>Patient-content backups are disabled.</li>
            <li>
              Your access ends the moment your session or a download expires; a cleanup every 5 minutes then deletes
              what has expired.
            </li>
          </ul>
        </section>
        <section className="card accent-card acc-amber">
          <h2 className="card-title"><span className="card-icon" aria-hidden="true"><Icon name="download" size={18} /></span>Downloads and links</h2>
          <p>
            A PDF you download is saved on your own computer and is outside Aware Care’s deletion controls. Opening an
            external link reveals your network address to that site.
          </p>
        </section>
        <section className="card accent-card acc-violet">
          <h2 className="card-title"><span className="card-icon" aria-hidden="true"><Icon name="sliders" size={18} /></span>Your controls</h2>
          <p>You can delete a consultation or all of your demo health information at any time.</p>
          <div className="actions">
            <Link className="btn" to="/app/settings">
              Review data controls
            </Link>
          </div>
        </section>
      </div>
    </>
  );
}
