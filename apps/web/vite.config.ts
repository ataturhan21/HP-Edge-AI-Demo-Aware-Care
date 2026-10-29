// Development server only (not the release gateway). Binds loopback 5173 and
// fails instead of silently moving ports. /api is proxied to the FastAPI app
// on 127.0.0.1:8000 with the /api prefix preserved (no rewrite). The browser
// reaches this server through the SSH tunnel at http://127.0.0.1:15173.
// AWARECARE_WEB_PORT / AWARECARE_API_TARGET exist only so the isolated browser-test
// stack (playwright.config.ts) can run beside the dev servers; defaults are unchanged.
// The browser tests serve a production build with `vite preview` (#66): the same port, loopback binding, strict
// port and /api proxy as the dev server, but no file watcher or dependency optimizer.
//
// One address for both roles (ADR-005 option A, amended by #487), mirroring infra/deploy/web.conf.template and
// presenter-api.conf.template: /api is the patient API and always strips any X-AwareCare-Presenter header;
// /presenter-api is the presenter API, proxied to the API's /api. Only when AWARECARE_PRESENTER_KEY_FILE names a key
// does /presenter-api sign every request with the same HMAC format as infra/deploy/presenter.js (the isolated test
// stack and local development); without a key it answers like the gateway's refusal (presenter-api-disabled.conf)
// and never reaches the API.
import { createHmac, randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import type { ServerResponse } from "node:http";
import { defineConfig, type Connect, type Plugin, type ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";

const target = process.env.AWARECARE_API_TARGET ?? "http://127.0.0.1:8000";
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(target)) throw new Error("AWARECARE_API_TARGET must be a loopback URL");

const keyFile = process.env.AWARECARE_PRESENTER_KEY_FILE;
const presenterKey = keyFile ? readFileSync(keyFile, "utf8").trim() : null;

function assertion(key: string): string {
  const payload = `v1.${Math.floor(Date.now() / 1000)}.${randomBytes(16).toString("hex")}`;
  return `${payload}.${createHmac("sha256", key).update(payload).digest("hex")}`;
}

const port = Number(process.env.AWARECARE_WEB_PORT ?? 5173);
const proxy: Record<string, ProxyOptions> = {
  // The patient API: never forwards a presenter assertion.
  "/api": {
    target,
    changeOrigin: false,
    configure: (proxy) => {
      proxy.on("proxyReq", (proxyReq) => {
        proxyReq.removeHeader("x-awarecare-presenter");
      });
    },
  },
};
if (presenterKey)
  // The presenter API: /presenter-api/v1/... is the API's /api/v1/..., with a fresh assertion on every request.
  proxy["/presenter-api"] = {
    target,
    changeOrigin: false,
    rewrite: (path) => path.replace(/^\/presenter-api\//, "/api/"),
    configure: (proxy) => {
      proxy.on("proxyReq", (proxyReq) => {
        proxyReq.removeHeader("x-awarecare-presenter");
        proxyReq.setHeader("X-AwareCare-Presenter", assertion(presenterKey));
      });
      proxy.on("proxyRes", (proxyRes) => {
        proxyRes.headers["x-awarecare-gateway"] = "presenter";
      });
    },
  };

/** #487: without a presenter key, /presenter-api answers like the gateway's presenter-api-disabled.conf. */
function presenterApiDisabled(): Plugin {
  const refuse: Connect.NextHandleFunction = (req, res: ServerResponse, next) => {
    if (presenterKey || !req.url?.startsWith("/presenter-api/")) return next();
    res.statusCode = 403;
    res.setHeader("Content-Type", "application/json");
    res.setHeader("Cache-Control", "no-store");
    res.end(JSON.stringify({ code: "PRESENTER_REQUIRED", message: "Presenter access is not enabled on this device.",
      field_errors: [], retryable: false }));
  };
  return {
    name: "aware-care-presenter-api-disabled",
    configureServer: (server) => void server.middlewares.use(refuse),
    configurePreviewServer: (server) => void server.middlewares.use(refuse),
  };
}

// #690 (owner decision B3): as the gateway (web.conf.template's map), a request for localhost[:port] is redirected to
// 127.0.0.1 on the same port, path and query (307), so both names work while the API's Origin check stays exact.
export const LOCALHOST = /^localhost(:\d{1,5})?$/i;
function localhostRedirect(): Plugin {
  const redirect: Connect.NextHandleFunction = (req, res: ServerResponse, next) => {
    const host = LOCALHOST.exec(req.headers.host ?? "");
    if (!host) return next();
    res.statusCode = 307;
    res.setHeader("Location", `http://127.0.0.1${host[1] ?? ""}${req.url ?? "/"}`);
    res.setHeader("Cache-Control", "no-store");
    res.end();
  };
  return {
    name: "aware-care-localhost-redirect",
    configureServer: (server) => void server.middlewares.use(redirect),
    configurePreviewServer: (server) => void server.middlewares.use(redirect),
  };
}

// #157: the gateways' Content-Security-Policy and framing protection (infra/deploy/*.conf.template), applied to the
// production build that the browser tests serve, so every browser test runs under the deployed policy. The dev server
// keeps no content policy (Vite's HMR needs inline scripts and a websocket), only BROWSER_POLICY_HEADERS (#576).
// #576 (QA #556): the gateway's Permissions-Policy and Cross-Origin-Opener-Policy, on the preview and the dev server
// too. The app uses no camera, microphone, location, payment or USB; the presenter's patient tab is this same origin
// (window.open), so same-origin keeps its opener.
export const BROWSER_POLICY_HEADERS = {
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  "Cross-Origin-Opener-Policy": "same-origin",
};
export const SECURITY_HEADERS = {
  "Content-Security-Policy":
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
  "X-Frame-Options": "DENY",
  ...BROWSER_POLICY_HEADERS,
};

// #207: the bundled Inter font is otherwise found only after the CSS has loaded (HTML -> CSS -> font). Preload the Latin
// subset, which every page uses, from index.html; the other subsets still load on demand (unicode-range).
export const LATIN_FONT = /^assets\/inter-latin-wght-normal-[\w-]+\.woff2$/;
function preloadLatinFont(): Plugin {
  return {
    name: "aware-care-preload-latin-font",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(_html, ctx) {
        const file = Object.keys(ctx.bundle ?? {}).find((f) => LATIN_FONT.test(f));
        if (!file) throw new Error("#207: the Latin Inter subset is missing from the build");
        const attrs = { rel: "preload", href: `/${file}`, as: "font", type: "font/woff2", crossorigin: "" };
        return [{ tag: "link", attrs, injectTo: "head" }];
      },
    },
  };
}

export default defineConfig({
  plugins: [react(), preloadLatinFont(), localhostRedirect(), presenterApiDisabled()],
  // #157: the bundled synthetic record PDFs (A04) stay separate same-origin files. Vite would inline them as data:
  // URLs, and the policy's connect-src 'self' rightly refuses to fetch() a data: URL.
  build: {
    assetsInlineLimit: (file: string) => (file.endsWith(".pdf") ? false : undefined),
    // #206: React, React DOM and the router in their own chunk, which stays cached across releases (the app chunk
    // changes with every release; these only when a dependency does).
    rollupOptions: {
      output: {
        advancedChunks: { groups: [{ name: "vendor", test: /node_modules[\\/](react|react-dom|react-router|react-router-dom|scheduler)[\\/]/ }] },
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port,
    strictPort: true,
    // The A04 mock flow uploads the bundled synthetic sample records from fixtures/records (single source).
    // #304: A06 reads the reviewed question templates from content/pathways (single source).
    fs: { allow: [".", "../../fixtures/records", "../../content/pathways"] },
    proxy,
    headers: BROWSER_POLICY_HEADERS,
  },
  preview: { host: "127.0.0.1", port, strictPort: true, proxy, headers: SECURITY_HEADERS },
});
