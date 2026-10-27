// O02 Evidence and controls (M12; R22, R23, R34, R38). Missing evidence is shown as unverified: a control is
// "Verified" only when the server reports executed evidence for this build, never by default.
import { api } from "../api/client";
import { PresenterState, usePresenter } from "../components/PresenterGate";
import { formatDateTime, PageHead, ScrollTable, StatusBanner } from "../components/ui";

const STATUS: Record<string, string> = { verified: "Verified", failed: "Failed", unverified: "Unverified" };

export default function O02() {
  const { data, error, reload } = usePresenter(api.getControls);
  const unverified = data?.items.filter((i) => i.status !== "verified").length ?? 0;
  return (
    <>
      <PageHead eyebrow="Presenter" title="Evidence and controls" />
      <PresenterState error={error} loading={!data} reload={reload}>
        {data && (
          <>
            {unverified > 0 && (
              <StatusBanner tone="warn" title={`${unverified} of ${data.items.length} controls are not verified`}>
                <p>Unverified means no executed evidence is recorded for this build. It is not a pass.</p>
              </StatusBanner>
            )}
            <ScrollTable className="card" label="Control evidence for this build">
              <table>
                <caption className="sr-only">Control evidence for this build</caption>
                <thead>
                  <tr>
                    <th scope="col">Control</th>
                    <th scope="col">Status</th>
                    <th scope="col">Checked</th>
                    <th scope="col">Evidence</th>
                    <th scope="col">Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((i) => (
                    <tr key={i.control_id}>
                      <th scope="row">{i.control_id}</th>
                      <td>{STATUS[i.status] ?? i.status}</td>
                      <td>{i.checked_at ? formatDateTime(i.checked_at) : "Not checked"}</td>
                      <td>{i.evidence_id ?? "None recorded"}</td>
                      <td>{i.summary}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollTable>
            <section className="card">
              <h2>Outbound events (redacted)</h2>
              {data.outbound_events.length === 0 ? (
                <p>No outbound requests recorded. This build makes no outbound lookups.</p>
              ) : (
                <ul>
                  {data.outbound_events.map((e) => (
                    <li key={e.event_id}>
                      {e.timestamp}: {e.event_name} ({e.status})
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </PresenterState>
    </>
  );
}
