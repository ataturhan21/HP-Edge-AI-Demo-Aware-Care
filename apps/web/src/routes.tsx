// Canonical route registry: exactly the 25 screen IDs and routes in spec/screens.json (W06 added by ADR-017).
// #339: each layout also has a not-found fallback for unknown addresses under it and a route-level error page; both
// render inside that layout (header, emergency strip, footer). They are not screens and add no screen route.
import { lazy, Suspense, type ReactNode } from "react";
import type { RouteObject } from "react-router-dom";
import { LoadingState } from "./components/ui";
import { AppLayout, PresenterLayout, PublicLayout } from "./components/Layout";
import { NotFound, RouteError } from "./components/NotFound";
import W01 from "./screens/W01";
import W02 from "./screens/W02";
import W03 from "./screens/W03";
import W04 from "./screens/W04";
import W05 from "./screens/W05";
import A01 from "./screens/A01";
import A02 from "./screens/A02";
import A03 from "./screens/A03";
import A04 from "./screens/A04";
import A05 from "./screens/A05";
import A06 from "./screens/A06";
import A07 from "./screens/A07";
import A08 from "./screens/A08";
import A09 from "./screens/A09";
import A10 from "./screens/A10";
import A11 from "./screens/A11";
import A12 from "./screens/A12";
import A13 from "./screens/A13";
import A14 from "./screens/A14";
import A15 from "./screens/A15";
import A16 from "./screens/A16";

// #206: the telemetry page (with its slide export) and the presenter tools load on demand, so patient and public
// visitors never download them; the existing loading state shows while a chunk arrives.
const W06 = lazy(() => import("./screens/W06"));
const O01 = lazy(() => import("./screens/O01"));
const O02 = lazy(() => import("./screens/O02"));
const O03 = lazy(() => import("./screens/O03"));
const onDemand = (label: string, screen: ReactNode) => (
  <Suspense fallback={<LoadingState label={label} />}>{screen}</Suspense>
);

export const SCREEN_ROUTES = {
  W01: "/",
  W02: "/how-it-works",
  W03: "/healthcare",
  W04: "/privacy",
  W05: "/help",
  W06: "/telemetry",
  A01: "/app/start",
  A02: "/app/profile",
  A03: "/app/new",
  A04: "/app/cases/:caseId/records",
  A05: "/app/cases/:caseId/questions",
  A06: "/app/cases/:caseId/review",
  A07: "/app/cases/:caseId/guidance",
  A08: "/app/cases/:caseId/sources",
  A09: "/app/cases/:caseId/preferences",
  A10: "/app/cases/:caseId/doctors",
  A11: "/app/cases/:caseId/doctors/:providerId",
  A12: "/app/cases/:caseId/summary",
  A13: "/app/history",
  A14: "/app/settings",
  A15: "/app/cases/:caseId/urgent",
  A16: "/app/limits",
  O01: "/presenter/runtime",
  O02: "/presenter/controls",
  O03: "/presenter/scenarios",
} as const;

export const routes: RouteObject[] = [
  {
    element: <PublicLayout />,
    children: [{ errorElement: <RouteError />, children: [
      { path: SCREEN_ROUTES.W01, element: <W01 /> },
      { path: SCREEN_ROUTES.W02, element: <W02 /> },
      { path: SCREEN_ROUTES.W03, element: <W03 /> },
      { path: SCREEN_ROUTES.W04, element: <W04 /> },
      { path: SCREEN_ROUTES.W05, element: <W05 /> },
      { path: SCREEN_ROUTES.W06, element: onDemand("Loading telemetry", <W06 />) },
      { path: SCREEN_ROUTES.A01, element: <A01 /> },
      { path: "*", element: <NotFound /> },
    ] }],
  },
  {
    element: <AppLayout />,
    children: [{ errorElement: <RouteError />, children: [
      { path: SCREEN_ROUTES.A02, element: <A02 /> },
      { path: SCREEN_ROUTES.A03, element: <A03 /> },
      { path: SCREEN_ROUTES.A04, element: <A04 /> },
      { path: SCREEN_ROUTES.A05, element: <A05 /> },
      { path: SCREEN_ROUTES.A06, element: <A06 /> },
      { path: SCREEN_ROUTES.A07, element: <A07 /> },
      { path: SCREEN_ROUTES.A08, element: <A08 /> },
      { path: SCREEN_ROUTES.A09, element: <A09 /> },
      { path: SCREEN_ROUTES.A10, element: <A10 /> },
      { path: SCREEN_ROUTES.A11, element: <A11 /> },
      { path: SCREEN_ROUTES.A12, element: <A12 /> },
      { path: SCREEN_ROUTES.A13, element: <A13 /> },
      { path: SCREEN_ROUTES.A14, element: <A14 /> },
      { path: SCREEN_ROUTES.A15, element: <A15 /> },
      { path: SCREEN_ROUTES.A16, element: <A16 /> },
      { path: "/app/*", element: <NotFound /> },
    ] }],
  },
  {
    element: <PresenterLayout />,
    children: [{ errorElement: <RouteError presenter />, children: [
      { path: SCREEN_ROUTES.O01, element: onDemand("Loading runtime", <O01 />) },
      { path: SCREEN_ROUTES.O02, element: onDemand("Loading controls", <O02 />) },
      { path: SCREEN_ROUTES.O03, element: onDemand("Loading scenarios", <O03 />) },
      // #358: O03's secondary view (full journeys and reset); the same screen, not a new screen route.
      { path: `${SCREEN_ROUTES.O03}/more`, element: onDemand("Loading scenarios", <O03 />) },
      // #470: W06 opened from the presenter tools, in the presenter shell (the same screen, not a new screen route).
      { path: "/presenter/telemetry", element: onDemand("Loading telemetry", <W06 />) },
      { path: "/presenter/*", element: <NotFound presenter /> },
    ] }],
  },
];
