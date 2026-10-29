// Public, patient and presenter shells. Every view carries the synthetic-demo
// banner; there is no real-patient service behind this application. #98: every view also carries the HP lockup and
// the truthful local-AI signature (components/Brand.tsx) in the header strip and the footer. #158: the demo notice,
// navigation and status strip form the page's banner landmark (<header>), so no content sits outside a landmark.
// #182: every shell uses one navigation with a Menu button on phones (the app and presenter links were clipped at
// 360 px). #189: on phones the demo notice is one line with its essentials; the full text stays for screen readers.
// #688 (owner decision B1): under the demo notice, every shell shows the mode strip (components/mode.tsx): "Presenter
// mode" or "Patient mode" with a Switch link, and in the Demo patient window "Back to presenter".
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { BrandLockup, DEVICE, HpLogo, LocalAISignature, RUNTIME } from "./Brand";
import { Icon } from "./Icon";
import { hasFlowRuns } from "./PresenterGate";
import { UrgentHelpLink } from "./ui";
import { SessionExpiryWarning } from "./SessionExpiryWarning";
import { JourneyProvider, JourneySteps } from "./JourneySteps";
import { LateUrgentNotice } from "./LateUrgentNotice";
import { useAppState } from "../state/AppState";
import { ConsultationLink, START_LABEL } from "./resume";
import { ModeStrip } from "./mode";

/** #322: the patient footer says how results are produced only as far as a server response has proved the mode. */
const APP_FOOTER_NOTE = {
  local: "synthetic demonstration · results written by the AI model on this device are labeled AI-generated",
  mock: "synthetic demonstration · scripted mock outcomes are labeled on each result",
  unknown: "synthetic demonstration · scripted mock outcomes are labeled on each result",
} as const;

function DemoBanner() {
  return (
    <div className="demo" role="note">
      <span className="demo-full">
        <b>Aware Care demonstration</b> · fictional people and doctors only · not medical advice · do not enter real
        health information
      </span>
      <span className="demo-short" aria-hidden="true">
        <b>Demo</b> · fictional people only · not medical advice
      </span>
    </div>
  );
}

// #427/#470: the presenter tools' own paths; in the presenter shell the brand, the footer and the navigation keep a
// presenter there. #487: one address serves both roles, and the role follows the page: a presenter who opens a patient
// page simply uses it as a patient (its requests go to the patient API), so no page needs a "wrong address" notice.
// The home page (W01) is where either role is chosen.
const PRESENTER_HOME = "/presenter/scenarios";
const PRESENTER_TELEMETRY = "/presenter/telemetry";

/** The site navigation: links in a row on wider screens, behind a Menu button on phones (#182). #474: any navigation
 * (a link in or outside the menu, Back/Forward) closes the menu, and Escape closes it with focus back on Menu. */
function SiteNav({ label, children, home = "/" }: { label: string; children: ReactNode; home?: string }) {
  const [open, setOpen] = useState(false);
  const id = `navlinks-${label.toLowerCase()}`;
  const menuButton = useRef<HTMLButtonElement>(null);
  const { key } = useLocation();
  useEffect(() => setOpen(false), [key]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      menuButton.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
  return (
    <nav className="nav" aria-label={label}>
      <BrandLockup to={home} />
      <button type="button" className="mobilemenu" aria-expanded={open} aria-controls={id} ref={menuButton}
        onClick={() => setOpen(!open)}>
        Menu
      </button>
      <div id={id} className={`navlinks${open ? " menuopen" : ""}`} onClick={() => setOpen(false)}>
        {children}
      </div>
    </nav>
  );
}

/** The slim strip under the header: the local-AI signature, and urgent help always one tap away.
 * #445: the link opens Help, so its text says where it goes. It is deliberately not a tel: link: a tap during a demo
 * on a phone must never dial real emergency services. */
function SignatureStrip() {
  return (
    <div className="strip">
      <div className="strip-inner">
        <LocalAISignature />
        <Link className="strip-urgent" to="/help">
          <Icon name="alert" size={16} />
          Emergency help
        </Link>
      </div>
    </div>
  );
}

function Footer({ note, telemetry = "/telemetry" }: { note: string; telemetry?: string }) {
  return (
    <footer className="footer">
      <div className="footer-inner">
        <div className="footer-brand">
          <HpLogo size={28} />
          <div>
            <p className="footer-title">Aware Care</p>
            <p className="small muted">
              Built for {DEVICE} · local AI via {RUNTIME} · {note}
            </p>
          </div>
        </div>
        <LocalAISignature variant="footer" />
        <div className="footer-meta">
          <UrgentHelpLink />
          <p className="small">
            <Link to={telemetry}>Telemetry: usage, cost and privacy on this device</Link>
          </p>
        </div>
      </div>
    </footer>
  );
}

export function PublicLayout() {
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <DemoBanner />
        <ModeStrip shell="public" />
        <SiteNav label="Main">
            <NavLink to="/how-it-works">How it works</NavLink>
            <NavLink to="/healthcare">For healthcare</NavLink>
            <NavLink to="/privacy">Privacy</NavLink>
            <NavLink to="/help">Help</NavLink>
            <NavLink to="/telemetry" className="nav-telemetry">
              <Icon name="chart" size={16} />
              Telemetry
            </NavLink>
            {/* #340, #345: "Continue consultation" while a guest session is open, else "Start a new consultation". */}
            <ConsultationLink className="btn sm" />
        </SiteNav>
        <SignatureStrip />
      </header>
      {/* #399 (WCAG 2.2.1): the app navigation links here (Help, Telemetry), so an open guest session is warned about
          here too; the expiry comes from the resume check of the header (no extra request). */}
      <SessionExpiryWarning probe={false} />
      <main id="main" className="page">
        <LateUrgentNotice />
        <Outlet />
      </main>
      <Footer note="synthetic healthcare navigation demo" />
    </>
  );
}

export function AppLayout() {
  const { runtimeMode } = useAppState();
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <DemoBanner />
        <ModeStrip shell="app" />
        <SiteNav label="Main">
            {/* #408: A03 confirms the session first and sends anyone without one to A01; A16 links to the same place. */}
            <NavLink to="/app/new">{START_LABEL}</NavLink>
            <NavLink to="/app/history">History</NavLink>
            <NavLink to="/app/settings">Data settings</NavLink>
            <NavLink to="/help">Help</NavLink>
            <NavLink to="/telemetry" className="nav-telemetry">
              <Icon name="chart" size={16} />
              Telemetry
            </NavLink>
        </SiteNav>
        <SignatureStrip />
      </header>
      <SessionExpiryWarning />
      <JourneyProvider>
      <main id="main" className="page">
        <LateUrgentNotice />
        <JourneySteps />
        <Outlet />
      </main>
      </JourneyProvider>
      <Footer note={APP_FOOTER_NOTE[runtimeMode]} />
    </>
  );
}

export function PresenterLayout() {
  // #423: a quick flow that was running when this tab reloaded is followed to its end on any presenter page.
  useEffect(() => {
    if (hasFlowRuns()) void import("./presenterRuns").then((runs) => runs.resumeRuns());
  }, []);
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        {/* #688: the mode strip replaces the presenter toolbar: Presenter mode (separately authorized, synthetic demo)
            and "Switch to patient mode", which leads to the home page's choice (#487: one address for both). */}
        <DemoBanner />
        <ModeStrip shell="presenter" />
        <SiteNav label="Presenter" home={PRESENTER_HOME}>
            {/* #358: Scenarios first (the presenter address opens it); its secondary view last. #470: Telemetry opens
                in this shell (W06 at /presenter/telemetry), so the presenter keeps this navigation. #683 (owner
                decision, 28 Oct 2026): O02 Evidence and controls has no tab (it distracted in front of an audience);
                /presenter/controls still opens it directly, and the README describes it. */}
            <NavLink to="/presenter/scenarios" end>Scenarios</NavLink>
            <NavLink to="/presenter/runtime">Runtime</NavLink>
            <NavLink to={PRESENTER_TELEMETRY} className="nav-telemetry">
              <Icon name="chart" size={16} />
              Telemetry
            </NavLink>
            <NavLink to="/presenter/scenarios/more">More scenarios</NavLink>
        </SiteNav>
        <SignatureStrip />
      </header>
      <main id="main" className="page">
        <Outlet />
      </main>
      <Footer note="presenter tools, separately authorized" telemetry={PRESENTER_TELEMETRY} />
    </>
  );
}
