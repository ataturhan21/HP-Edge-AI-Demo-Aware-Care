// Presenter gateway assertion signer (ADR-005 option A; M01/M12; R03, R37).
// Loaded by the presenter API location (/presenter-api/, #487) only. Every request proxied there gets
// X-AwareCare-Presenter: v1.<unix-seconds>.<128-bit random nonce hex>.<HMAC-SHA256 hex>
// keyed with /run/secrets/presenter.key (read-only mount, never in the image or Git).
// apps/api/app/modules/access/presenter.py verifies it; the format must stay in step.
import fs from 'fs';
import nodeCrypto from 'crypto';

const KEY_FILE = '/run/secrets/presenter.key';
let key = null;

function mint(r) {
  if (key === null) {
    key = fs.readFileSync(KEY_FILE).toString().trim();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  const nonce = Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
  const payload = `v1.${Math.floor(Date.now() / 1000)}.${nonce}`;
  return `${payload}.${nodeCrypto.createHmac('sha256', key).update(payload).digest('hex')}`;
}

export default { mint };
