// #630 (owner decision on #594): a consultation created after the person left the form never takes them elsewhere, but
// when it was routed to urgent help they are told so on the page they are on now (role=alert), with a link to that
// consultation's urgent help. Routine results show nothing. The notice goes once its urgent page is opened or dismissed.
import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAppState } from "../state/AppState";
import { StatusBanner } from "./ui";

export function LateUrgentNotice() {
  const { lateUrgent, noteLateUrgent } = useAppState();
  const { pathname } = useLocation();
  const target = lateUrgent ? `/app/cases/${lateUrgent.caseId}/urgent` : null;
  useEffect(() => {
    if (target && pathname === target) noteLateUrgent(null);
  }, [target, pathname, noteLateUrgent]);
  if (!lateUrgent || !target || pathname === target) return null;
  return (
    <div className="late-urgent">
      <StatusBanner tone="urgent" title="Your new consultation needs urgent help">
        <p>
          The consultation you started was sent to urgent help. In an emergency call <strong>911</strong> now.
        </p>
        <p className="row">
          <Link className="btn urgent" to={target} state={lateUrgent.level ? { level: lateUrgent.level } : null}>
            Open urgent help for this consultation
          </Link>
          <button type="button" className="btn secondary" onClick={() => noteLateUrgent(null)}>
            Dismiss
          </button>
        </p>
      </StatusBanner>
    </div>
  );
}
