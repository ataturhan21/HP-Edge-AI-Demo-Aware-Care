import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Outlet, RouterProvider } from "react-router-dom";
import { SITE_TITLE } from "./components/Brand";
import { RootError } from "./components/NotFound";
import { routes } from "./routes";
import { AppStateProvider } from "./state/AppState";
// The typeface is bundled with the app (Inter, OFL), so pages render the same on an isolated network (R34, ADR-014).
import "@fontsource-variable/inter/wght.css";
import "./styles.css";

function Root() {
  return (
    <AppStateProvider>
      <Outlet />
    </AppStateProvider>
  );
}

// #339: a layout that fails to render still leaves a calm page with Reload (screens fail inside their layout).
const router = createBrowserRouter([{ element: <Root />, errorElement: <RootError />, children: routes }]);

// #107, #155: the site name on every screen. index.html carries the Nano's text, and PageHead sets it again, but
// screens without PageHead (empty, complete and loading states) must not keep index.html's text on the ZGX Fury.
document.title = SITE_TITLE;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
