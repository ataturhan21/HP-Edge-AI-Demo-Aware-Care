// A15 Urgent action (M05; R15, R17). Static urgent instruction; no routine result or ranking.
// Renders without a session or a working model; it never displays private case details. When the case was routed
// by a ticked red flag (ADR-003), or by a red flag found in the person's own words (general-adult-3), it adds the
// reviewed message for that level, without naming the sign. Since #153 the case carries that level (`urgent_level`),
// so a reload keeps it; the level passed by the previous screen is the fallback.
// #116: the case is read quietly whenever there is a case ID, not only when this tab created the session, so a tab
// opened after a presenter scenario load, or a reloaded tab, shows the level too. Without a session the read fails
// quietly and the general page stays (no redirect).
// #457: the statements about "this consultation" (no routine guidance, doctor matching or summary) appear only once
// the case read shows it is urgent; for an owned case that is not urgent the page keeps the general urgent help and
// offers the way back to that consultation's current step.
import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api, type S } from "../api/client";
import { RED_FLAGS, RED_FLAGS_KIND, urgentLevel } from "../components/RedFlags";
import { EndSessionButton } from "../components/ResetActions";
import { caseNextStep } from "../components/resume";
import { Icon } from "../components/Icon";
import { PageHead, StatusBanner } from "../components/ui";
import { useAppState } from "../state/AppState";

type Level = keyof typeof RED_FLAGS.messages;

/** The reviewed level for this case: a ticked box or the recorded level from the case; otherwise the passed level,
 * once the case is urgent. */
function reviewedLevel(data: S["CaseReadResponse"] | null, described: Level | null): Level | null {
  if (!data) return null;
  const fact = data.case.confirmed_context.find((f) => f.kind === RED_FLAGS_KIND);
  const ticked = Array.isArray(fact?.value) ? urgentLevel(fact.value) : null;
  return (ticked ?? (data.case.state === "urgent" ? (data.case.urgent_level ?? described) : null)) as Level | null;
}

function ReviewedMessage({ data, described }: { data: S["CaseReadResponse"]; described: Level | null }) {
  const level = reviewedLevel(data, described);
  if (!level) return null;
  return (
    <StatusBanner tone="urgent" title={level === "emergency" ? "Emergency" : "Urgent: today"}>
      <p>{RED_FLAGS.messages[level]}</p>
    </StatusBanner>
  );
}

export default function A15() {
  const { session } = useAppState();
  const { caseId } = useParams();
  const passed = (useLocation().state as { level?: string } | null)?.level;
  const described = passed && Object.hasOwn(RED_FLAGS.messages, passed) ? (passed as Level) : null;
  const [data, setData] = useState<S["CaseReadResponse"] | null>(null);
  const [loaded, setLoaded] = useState(!caseId);
  useEffect(() => {
    if (!caseId) return;
    let live = true;
    api.getCaseQuietly(caseId).then((d) => live && setData(d), () => live && setData(null))
      .finally(() => live && setLoaded(true));
    return () => {
      live = false;
    };
  }, [caseId]);
  const hasSession = session !== null || data !== null;
  const urgentCase = data?.case.state === "urgent";
  const otherCase = data !== null && !urgentCase ? caseNextStep(data.case, data.allowed_actions) : null;
  return (
    <div className="narrow">
      <PageHead eyebrow="Urgent" title="Seek urgent help now" />
      {data && <ReviewedMessage data={data} described={described} />}
      {/* #233: the generic alert is the fallback for an unknown level; with a reviewed message it only repeated it. */}
      {loaded && !reviewedLevel(data, described) && (
        <StatusBanner tone="urgent" title="If this could be an emergency, call 911 or go to the nearest emergency department.">
          <p>Do not wait for online guidance.</p>
        </StatusBanner>
      )}
      <section className="card accent-card acc-red">
        <h2 className="card-title">
          <span className="card-icon" aria-hidden="true"><Icon name="alert" size={18} /></span>
          What to do
        </h2>
        {urgentCase && <p>Routine guidance and doctor matching are not available for this consultation.</p>}
        <ul className="bullets">
          <li>Call 911 if you have severe symptoms or feel unsafe.</li>
          <li>If it is not an emergency, contact a clinician or urgent care today.</li>
          <li>This is a synthetic demonstration; it is not an assessment of your health.</li>
        </ul>
        <div className="actions">
          <a className="btn urgent" href="tel:911">
            Seek urgent help (call 911)
          </a>
          <Link className="btn secondary" to="/help">
            Urgent help information
          </Link>
        </div>
      </section>
      <section className="card accent-card acc-slate" aria-labelledby="restart-heading">
        <h2 id="restart-heading" className="card-title">
          <span className="card-icon" aria-hidden="true"><Icon name="list" size={18} /></span>
          Start a new consultation
        </h2>
        {urgentCase ? (
          <p className="small">
            This urgent case cannot continue to routine questions, guidance, doctor matching or a summary. A different
            fictional example needs a new consultation.
          </p>
        ) : (
          <p className="small">A different fictional example needs a new consultation.</p>
        )}
        <div className="actions">
          {otherCase && (
            <Link className="btn secondary" to={otherCase.to}>
              Back to your consultation
            </Link>
          )}
          {hasSession ? (
            <>
              <EndSessionButton />
              <Link className="btn secondary" to="/app/new">
                Start a new consultation
              </Link>
            </>
          ) : (
            <Link className="btn secondary" to="/app/start">
              Start a new consultation
            </Link>
          )}
        </div>
      </section>
    </div>
  );
}
