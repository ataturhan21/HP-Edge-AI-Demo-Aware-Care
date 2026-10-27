// Loads the server-owned case projection for a route and maps states to screens.
// The server re-checks every guard; this only routes the UI to the right place.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type S } from "../api/client";

/** `allowedActions` (from the case read, when known): #282 a limited case whose guidance failed recoverably ("retry"
 * allowed) belongs on A07, which explains the failure and offers Retry; other limited cases go to A16. */
export function screenForState(caseId: string, state: S["Case"]["state"], allowedActions?: readonly string[]): string {
  if (state === "limited" && allowedActions?.includes("retry")) return `/app/cases/${caseId}/guidance`;
  switch (state) {
    case "draft":
    case "intake":
      return `/app/cases/${caseId}/questions`;
    case "review":
    case "reviewed":
      return `/app/cases/${caseId}/review`;
    case "generating":
    case "guided":
      return `/app/cases/${caseId}/guidance`;
    case "urgent":
      return `/app/cases/${caseId}/urgent`;
    case "limited":
      return "/app/limits";
    default:
      return "/app/history";
  }
}

/** The case read for `caseId`. #580: `data` is only ever this case's own successful read: a read of another case (the
 * route changed, e.g. by Back) is dropped as soon as the route names another case, and an answer that arrives after a
 * newer read started is ignored. A failed read of another case therefore shows its error, never the case shown before. */
export function useCase(caseId: string | undefined) {
  const [loaded, setLoaded] = useState<{ id: string; read: S["CaseReadResponse"] } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const latest = useRef(0);
  const reload = useCallback(async () => {
    if (!caseId) return;
    const mine = ++latest.current;
    setLoading(true);
    setError(null);
    setLoaded((prev) => (prev?.id === caseId ? prev : null));
    try {
      const read = await api.getCase(caseId);
      if (mine === latest.current) setLoaded(read.case.id === caseId ? { id: caseId, read } : null);
    } catch (e) {
      if (mine === latest.current) setError(e);
    } finally {
      if (mine === latest.current) setLoading(false);
    }
  }, [caseId]);
  useEffect(() => {
    void reload();
  }, [reload]);
  const data = loaded !== null && loaded.id === caseId ? loaded.read : null;
  const setData = useCallback(
    (read: S["CaseReadResponse"] | null) => setLoaded(read && caseId && read.case.id === caseId ? { id: caseId, read } : null),
    [caseId],
  );
  const notFound = error instanceof ApiError && error.status === 404;
  return { data, error, loading, reload, notFound, setData };
}
