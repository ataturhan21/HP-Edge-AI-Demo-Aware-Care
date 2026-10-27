// #339: an unknown address and a screen that fails to render keep the site around them: the header with the
// "Emergency help" strip, the footer, and ways on (the open consultation or a new one, home, help, and in the
// presenter tools the scenarios page; #487: elsewhere the home page offers the presenter choice). Neither page names the error, shows developer text or a stack trace, or
// shows any result in place of the page that failed (local mode fails closed). Not a screen of its own: the 25-screen
// registry (spec/screens.json) is unchanged; routes.tsx renders these as the fallback inside each layout.
import { isRouteErrorResponse, Link, useRouteError } from "react-router-dom";
import { useHideJourney } from "./JourneySteps";
import { ConsultationLink, CONTINUE_LABEL, useResume } from "./resume";
import { PageHead } from "./ui";

/** The ways on from a page that has nothing to show. `presenter`: the presenter layout, where only an open
 * consultation is offered (not a new one). */
function WaysOn({ presenter = false }: { presenter?: boolean }) {
  const resume = useResume();
  return (
    <nav className="actions" aria-label="Ways on">
      {presenter ? (
        resume?.open && <Link className="btn secondary" to={resume.to}>{CONTINUE_LABEL}</Link>
      ) : (
        <ConsultationLink />
      )}
      {presenter && (
        <Link className="btn" to="/presenter/scenarios">
          Presenter scenarios
        </Link>
      )}
      <Link className="btn secondary" to="/">
        Go to the home page
      </Link>
      <Link className="btn secondary" to="/help">
        Help and urgent care
      </Link>
    </nav>
  );
}

export function NotFound({ presenter = false }: { presenter?: boolean }) {
  useHideJourney();
  return (
    <div className="narrow">
      <PageHead eyebrow="Not found" title="Page not found">
        <p>
          There is no page at this address. It may have been mistyped, or it may be from an older version of this
          demonstration.
        </p>
      </PageHead>
      <WaysOn presenter={presenter} />
    </div>
  );
}

function PageProblem({ presenter }: { presenter: boolean }) {
  useHideJourney();
  return (
    <div className="narrow">
      <PageHead eyebrow="Problem" title="This page could not be shown">
        <p>
          Something went wrong while showing this page, so nothing from it is shown. Reloading usually helps. Answers
          you already submitted stay with your consultation while your session is open.
        </p>
      </PageHead>
      <p className="actions">
        <button type="button" className="btn" onClick={() => window.location.reload()}>
          Reload
        </button>
      </p>
      <WaysOn presenter={presenter} />
    </div>
  );
}

/** The route-level error page, rendered in the layout's main area. The error itself is never shown or logged here. */
export function RouteError({ presenter = false }: { presenter?: boolean }) {
  const error = useRouteError();
  return isRouteErrorResponse(error) && error.status === 404
    ? <NotFound presenter={presenter} />
    : <PageProblem presenter={presenter} />;
}

/** Last resort when a layout itself fails: no layout to render into, so a plain page with the same essentials. Plain
 * links reload the application. */
export function RootError() {
  return (
    <main id="main" className="page">
      <div className="narrow">
        <h1>This page could not be shown</h1>
        <p>Something went wrong while showing this page, so nothing from it is shown. Reloading usually helps.</p>
        <p className="actions">
          <button type="button" className="btn" onClick={() => window.location.reload()}>
            Reload
          </button>
          <a className="btn secondary" href="/">
            Go to the home page
          </a>
          <a className="btn secondary" href="/help">
            Help and urgent care
          </a>
        </p>
        <p>
          In an emergency <a href="tel:911">call 911</a> now.
        </p>
      </div>
    </main>
  );
}
