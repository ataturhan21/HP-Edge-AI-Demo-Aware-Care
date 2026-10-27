// HP branding and the local-AI signature (#98; R34, ADR-014). The HP logo is the official asset supplied by the
// product owner (assets/brand/HP_logo_2025.svg), never redrawn. Device and runtime names are as recorded in
// infra/device-inventory.json and infra/model-manifest.json (infra/fury/ for the ZGX Fury).
//
// ADR-018: one web image serves both devices. The gateway answers /aware-care-device.js with the deployment's device
// (from the deploy configuration), loaded by index.html before the app; without it the default is the ZGX Nano. #537:
// on any other NVIDIA machine, demo.sh names the device from its DMI product name (e.g. "HP Z8 Fury G5 Workstation").
//
// The signature says only what the browser has observed: the mode is "local" or "mock" once a server response proves
// it (#322: the public telemetry identity read when the page loads, see state/AppState.tsx), and readiness comes from
// GET /health/ready. It never claims a running model unless both say so.
import { Link } from "react-router-dom";
import hpLogo from "../assets/brand/HP_logo_2025.svg";
import { useAppState } from "../state/AppState";
import { Icon, type IconName } from "./Icon";

type DeviceInfo = { name: string; shortName: string };
const NANO: DeviceInfo = { name: "HP ZGX Nano", shortName: "ZGX Nano" };
const SAFE_NAME = /^[A-Za-z0-9 .-]{1,40}$/;

/** The deployment's device from /aware-care-device.js (ADR-018), or the Nano when it is absent or malformed. */
export function deviceFrom(value: unknown): DeviceInfo {
  const v = value as Partial<DeviceInfo> | undefined;
  const ok = (s: unknown): s is string => typeof s === "string" && SAFE_NAME.test(s);
  return v && ok(v.name) && ok(v.shortName) ? { name: v.name, shortName: v.shortName } : NANO;
}

const device = deviceFrom((globalThis as { AWARE_CARE_DEVICE?: unknown }).AWARE_CARE_DEVICE);
export const DEVICE = device.name;
export const DEVICE_SHORT = device.shortName;
export const RUNTIME = "ZRT";
/** #537: where patient data stays: "the ZGX" on the two ZGX devices, else the machine's own short name (from DMI). */
export function devicePlace(d: DeviceInfo): string {
  return /\bZGX\b/.test(d.name) ? "the ZGX" : `the ${d.shortName}`;
}
export const DEVICE_PLACE = devicePlace(device);

/**
 * #461/#487: the one address this deployment is configured for (deploy `--origin`, `network.browser_origin`), from the
 * gateway's /aware-care-device.js (`origin`); only a plain http(s) origin counts, anything else is null (then the page
 * names no address). Since #487 patients and presenters use the same address: the presenter tools are its
 * /presenter/... pages, so a presenter's patient tab opens /app/... on this same address.
 */
export function configuredOriginFrom(value: unknown): string | null {
  const v = (value as Record<string, unknown> | undefined)?.origin;
  if (typeof v !== "string" || !v) return null;
  try {
    const url = new URL(v);
    return (url.protocol === "http:" || url.protocol === "https:") && url.origin === v.replace(/\/$/, "") ? url.origin : null;
  } catch {
    return null;
  }
}
export const CONFIGURED_ORIGIN = configuredOriginFrom((globalThis as { AWARE_CARE_DEVICE?: unknown }).AWARE_CARE_DEVICE);

/** The browser tab title on every page (#107, product owner's wording); index.html carries the Nano's text. */
export const SITE_TITLE = `Aware Care - Local AI Healthcare Demo on ${DEVICE_SHORT} via ZRT`;

export function HpLogo({ size = 32 }: { size?: number }) {
  return <img className="hp-logo" src={hpLogo} width={size} height={size} alt="HP" />;
}

/** The product lockup: HP logo, divider, Aware Care, and the device it runs on. It leads to the home page (#487: the
 *  patient or presenter choice); the presenter shell passes the presenter tools' home instead (#427). #595 (WCAG 2.5.3
 *  Label in Name): its accessible name is its whole visible content, the HP logo's "HP" and "Aware Care on <device>",
 *  then where it leads. */
export function BrandLockup({ to = "/" }: { to?: string }) {
  return (
    <Link to={to} className="brand" aria-label={`HP Aware Care on ${DEVICE}, home`}>
      <HpLogo />
      <span className="brand-divider" aria-hidden="true" />
      <span className="brand-name">
        Aware Care{" "}
        <span className="brand-sub">on {DEVICE}</span>
      </span>
    </Link>
  );
}

type Signature = { tone: "ok" | "neutral" | "mock" | "warn" | "down"; icon: IconName; title: string; detail: string };

export function useLocalAISignature(): Signature {
  const { readiness, runtimeMode } = useAppState();
  const stays = `Patient data stays on ${DEVICE_PLACE}`;
  if (readiness === "unavailable")
    return { tone: "down", icon: "alert", title: `Local AI unavailable on ${DEVICE}`, detail: `Guidance is paused · ${stays}` };
  if (readiness === "degraded")
    return { tone: "warn", icon: "alert", title: `Local AI degraded on ${DEVICE}`, detail: `Some steps may be limited · ${stays}` };
  if (readiness === "unreachable")
    return { tone: "warn", icon: "alert", title: "Service status unknown", detail: `The Aware Care service on ${DEVICE} did not answer` };
  if (readiness === "checking")
    return { tone: "neutral", icon: "chip", title: `Aware Care on ${DEVICE}`, detail: "Checking the local service…" };
  if (runtimeMode === "mock")
    return { tone: "mock", icon: "info", title: `Mock mode on ${DEVICE}`, detail: `Scripted results, no AI model · ${stays}` };
  if (runtimeMode === "local")
    return { tone: "ok", icon: "chip", title: `AI runs locally on ${DEVICE} via ${RUNTIME}`, detail: `${stays} · no cloud inference` };
  return { tone: "neutral", icon: "chip", title: `Built to run AI locally on ${DEVICE} via ${RUNTIME}`, detail: `${stays} · no cloud inference` };
}

/** The local-AI status chip shown on every page (header strip and footer). */
export function LocalAISignature({ variant = "strip" }: { variant?: "strip" | "footer" }) {
  const s = useLocalAISignature();
  return (
    <p className={`signature signature-${variant} tone-${s.tone}`} data-testid={`local-ai-signature-${variant}`}>
      <span className="signature-dot" aria-hidden="true" />
      <Icon name={s.icon} size={18} />
      <span className="signature-text">
        <strong>{s.title}</strong>
        <span className="signature-detail">{s.detail}</span>
      </span>
    </p>
  );
}
