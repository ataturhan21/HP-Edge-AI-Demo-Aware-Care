// #220: a returning visitor with an open guest session is offered the way back to their consultations, instead of
// consent and the profile again. #340: the link opens the screen where the patient left off (the shared resume target,
// components/resume.tsx), not History. Without a session it shows nothing and reports no error. No new endpoint, and
// nothing is stored in the browser.
import { Link } from "react-router-dom";
import { CONTINUE_LABEL, useResume } from "./resume";
import { setTabMode } from "./mode";
import { StatusBanner } from "./ui";

export function ResumeSession() {
  const resume = useResume();
  if (!resume?.open) return null;
  return (
    <div className="resume-session">
      <StatusBanner tone="info" title="Your guest session is still open">
        <p>
          You do not need to start again. <Link to={resume.to} onClick={() => setTabMode("patient")}>{CONTINUE_LABEL}</Link>
        </p>
      </StatusBanner>
    </div>
  );
}
