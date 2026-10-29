// W01 Home (M01; R01). Explains purpose and local processing; help stays visible if unavailable. #98: the on-device
// story (HP ZGX Nano, ZRT) is told as architecture, never as a claim that a model is running right now; the live
// state is the signature in the header strip. #437: in mock mode the panel says no model runs (the results are
// scripted) and tells the on-device story as local mode's.
// #487 (ADR-005 amendment): the one address of the demo. The home page offers two large choices, Patient (start or
// continue a consultation, A01) and Presenter (the presenter tools, O03 with its quick flows first). Both are plain
// links: choosing sets no role. The role follows the page (patient pages use the patient API, presenter pages the
// presenter API), and the server alone grants the presenter role. This page never calls the presenter API.
// #688/#689 (owner decisions B1, B2, 28 Oct 2026): Presenter first; the Patient card always starts a fresh consultation
// (never a demo result) and offers "My consultations" (History); each choice sets this tab's mode (components/mode.tsx).
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { DEVICE, DEVICE_PLACE, HpLogo, RUNTIME } from "../components/Brand";
import { Icon } from "../components/Icon";
import { START_LABEL, useResume } from "../components/resume";
import { setTabMode } from "../components/mode";
import { PageHead, StatusBanner } from "../components/ui";
import { useAppState } from "../state/AppState";

const PRESENTER_START = "/presenter/scenarios";

export default function W01() {
  const [readiness, setReadiness] = useState<string | null>(null);
  const mock = useAppState().runtimeMode === "mock";
  const resume = useResume(); // #688: a demo patient's session counts as none (components/resume.tsx)
  useEffect(() => {
    api.readiness().then((r) => setReadiness(r.readiness), () => setReadiness("unavailable"));
  }, []);
  return (
    <>
      {readiness === "unavailable" && (
        <StatusBanner tone="warn" title="The consultation service is unavailable right now.">
          <p>
            General help remains available. <Link to="/help">Open help and urgent-care information</Link>.
          </p>
        </StatusBanner>
      )}
      <section className="home-intro">
        <PageHead eyebrow="Synthetic healthcare navigation demo" title="Understand your concern and find the right care.">
          <p>
            A local AI healthcare demo on {DEVICE}, designed for future deployment at the healthcare edge. Aware Care
            asks a few focused questions, explains possible next steps with their limits, and helps you prepare for a
            visit.
          </p>
        </PageHead>
      </section>

      {/* #487: the role choice. Each card is one main link target (its button; the card's surface follows it for a pointer).
          #689 (owner decision B2): Presenter first, then Patient. #688 (B1): the Patient card always starts a fresh
          consultation (A01 creates a new guest session) and never resumes a demo; "My consultations" opens History. */}
      <section className="role-choice" aria-labelledby="role-choice-heading">
        <h2 id="role-choice-heading" className="role-choice-title">How would you like to use Aware Care?</h2>
        <div className="role-grid">
          <article className="role-card role-presenter" aria-labelledby="role-presenter-heading">
            <span className="role-icon" aria-hidden="true"><Icon name="sliders" size={28} /></span>
            <h3 id="role-presenter-heading">Presenter: run the demo for an audience</h3>
            <p className="role-lead">
              Run the live demonstration: one-click quick flows on the device, then runtime and telemetry.
            </p>
            <ul className="role-points">
              <li><Icon name="pulse" size={18} />Quick flows run live with synthetic people</li>
              <li><Icon name="chip" size={18} />Runtime and model status of the {DEVICE}</li>
              <li><Icon name="shield" size={18} />Separately authorized by the device</li>
            </ul>
            <Link className="btn role-action" to={PRESENTER_START} onClick={() => setTabMode("presenter")}>
              Open the presenter tools
              <Icon name="arrow" size={18} />
            </Link>
          </article>
          <article className="role-card role-patient" aria-labelledby="role-patient-heading">
            <span className="role-icon" aria-hidden="true"><Icon name="user" size={28} /></span>
            <h3 id="role-patient-heading">Patient: try it yourself</h3>
            <p className="role-lead">
              Describe a concern in your own words, answer up to ten focused questions and get clear next steps with
              their limits.
            </p>
            <ul className="role-points">
              <li><Icon name="check" size={18} />A few minutes, one question at a time</li>
              <li><Icon name="lock" size={18} />Answers stay on the {DEVICE}</li>
              <li><Icon name="phone" size={18} />Urgent help one tap away throughout</li>
            </ul>
            <Link className="btn role-action" to="/app/start" onClick={() => setTabMode("patient")}>
              {START_LABEL}
              <Icon name="arrow" size={18} />
            </Link>
            {/* #475's rule, as on Help: offered while this browser holds the person's own guest session */}
            {resume?.open && (
              <p className="role-more">
                <Link to="/app/history" onClick={() => setTabMode("patient")}>My consultations</Link>
              </p>
            )}
          </article>
        </div>
        <p className="small muted role-note">
          Both use this one address. The presenter tools ask the device for a presenter session first; nothing on this
          page grants it.
        </p>
      </section>

      <section className="hero home-story">
        <div>
          <h2 className="section-title home-story-title">Local AI at the healthcare edge</h2>
          <p className="muted">
            Everything runs on one device: the application, its database and the inference runtime. There is no cloud
            model and no cloud fallback.
          </p>
          <div className="row">
            <Link className="btn secondary" to="/how-it-works">
              How it works
            </Link>
            <Link className="btn secondary" to="/telemetry">
              <Icon name="chart" size={18} />
              See live telemetry
            </Link>
          </div>
        </div>
        <div className="card hero-panel">
          <p className="panel-kicker">
            <HpLogo size={28} />
            <span>On-device AI</span>
          </p>
          <h2>What stays local</h2>
          <p>
            The application, its database and the inference runtime run on one local device. This demonstration uses
            fictional people and doctors only.
          </p>
          <ul className="facts">
            <li>
              <Icon name="chip" />
              {mock ? (
                <span>
                  <strong>Mock mode: no language model runs</strong>
                  The results are scripted. In local mode the model runs on the {DEVICE}, served by {RUNTIME}; there is
                  no cloud model and no cloud fallback.
                </span>
              ) : (
                <span>
                  <strong>The language model runs on the {DEVICE}</strong>
                  Served by {RUNTIME} on the device. There is no cloud model and no cloud fallback.
                </span>
              )}
            </li>
            <li>
              <Icon name="lock" />
              <span>
                <strong>Patient data stays on {DEVICE_PLACE}</strong>
                Concerns, answers and guidance never leave the device.
              </span>
            </li>
            <li>
              <Icon name="shield" />
              <span>
                <strong>Clinically reviewed limits</strong>
                Questions and warning signs were approved by a clinician; urgent signs go straight to urgent help.
              </span>
            </li>
          </ul>
          <p className="small">Aware Care does not diagnose, prescribe or book appointments.</p>
        </div>
      </section>
      <section aria-labelledby="how-heading">
        <h2 id="how-heading" className="section-title">
          Three focused steps
        </h2>
        <p className="muted">A guided consultation that takes a few minutes, with urgent help one tap away throughout.</p>
        <ol className="steps">
          {/* #241: each step with its own hue and icon. */}
          <li className="step-blue">
            <span className="step-icon" aria-hidden="true"><Icon name="chat" size={20} /></span>
            <h3>Describe your concern</h3>
            <p className="muted">In your own words, and tick any urgent warning signs.</p>
          </li>
          <li className="step-teal">
            <span className="step-icon" aria-hidden="true"><Icon name="list" size={20} /></span>
            <h3>Answer up to ten questions</h3>
            <p className="muted">Clinically reviewed questions, one at a time. You can skip or say you are not sure.</p>
          </li>
          <li className="step-violet">
            <span className="step-icon" aria-hidden="true"><Icon name="check" size={20} /></span>
            <h3>Get clear next steps</h3>
            <p className="muted">Guidance with its limits, questions for a clinician and a summary for your visit.</p>
          </li>
        </ol>
      </section>
    </>
  );
}
