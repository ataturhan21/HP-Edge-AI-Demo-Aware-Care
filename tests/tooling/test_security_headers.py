"""#157: both gateways send one strict Content-Security-Policy and framing protection on every page, asset and the
device script, and the browser tests' `vite preview` sends the same policy, so the whole browser suite runs under it."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# #487: one gateway template; the presenter API is a location of it (presenter-api*.conf, included into its server).
TEMPLATES = [ROOT / "infra/deploy/web.conf.template"]
PRESENTER_SNIPPETS = [ROOT / "infra/deploy/presenter-api.conf.template", ROOT / "infra/deploy/presenter-api-disabled.conf"]
VITE = ROOT / "apps/web/vite.config.ts"
# #576 (QA #556): on every response of the gateway, the preview server and the dev server. The app uses no camera,
# microphone, location, payment or USB; the presenter's patient tab is this same origin, so it keeps its opener.
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
OPENER_POLICY = "same-origin"


def vite_policy() -> str:
    m = re.search(r'"Content-Security-Policy":\s*"([^"]+)"', VITE.read_text())
    assert m, "vite.config.ts has no Content-Security-Policy"
    return m.group(1)


def locations(text: str) -> dict[str, str]:
    """Each `location <path> { ... }` block (no nested braces in these templates)."""
    return {m.group(1): m.group(2) for m in re.finditer(r"location\s+(=?\s*\S+)\s*\{(.*?)\n    \}", text, re.S)}


class SecurityHeadersTest(unittest.TestCase):
    def test_the_policy_is_strict(self):
        policy = vite_policy()
        directives = dict(d.strip().split(" ", 1) for d in policy.split(";"))
        self.assertEqual(directives["default-src"], "'self'")
        self.assertEqual(directives["script-src"], "'self'")
        self.assertEqual(directives["frame-ancestors"], "'none'")
        self.assertEqual(directives["object-src"], "'none'")
        self.assertEqual(directives["base-uri"], "'none'")
        self.assertNotIn("unsafe-inline", policy)
        self.assertNotIn("unsafe-eval", policy)
        self.assertNotIn("http", policy)  # no remote host anywhere (R34, ADR-014)

    def test_every_gateway_location_but_the_api_sends_the_same_policy(self):
        policy = vite_policy()
        for template in TEMPLATES:
            blocks = locations(template.read_text())
            self.assertGreaterEqual(len(blocks), 4, template.name)
            for path, body in blocks.items():
                if path.strip() == "/api/":
                    continue
                with self.subTest(template=template.name, location=path):
                    self.assertIn(f'add_header Content-Security-Policy "{policy}" always;', body)
                    self.assertIn("add_header X-Frame-Options DENY always;", body)

    def test_every_gateway_response_sends_the_permissions_and_opener_policies(self):
        """#576: every location, the patient API and both presenter-api snippets included (a location with its own
        add_header inherits none from the server block, so each one names them)."""
        for template in [*TEMPLATES, *PRESENTER_SNIPPETS]:
            blocks = locations(template.read_text())
            self.assertTrue(blocks, template.name)
            for path, body in blocks.items():
                with self.subTest(template=template.name, location=path):
                    self.assertIn(f'add_header Permissions-Policy "{PERMISSIONS_POLICY}" always;', body)
                    self.assertIn(f"add_header Cross-Origin-Opener-Policy {OPENER_POLICY} always;", body)

    def test_the_preview_and_dev_servers_send_the_same_permissions_and_opener_policies(self):
        text = VITE.read_text()
        self.assertIn(f'"Permissions-Policy": "{PERMISSIONS_POLICY}"', text)
        self.assertIn(f'"Cross-Origin-Opener-Policy": "{OPENER_POLICY}"', text)
        self.assertRegex(text, r"SECURITY_HEADERS = \{[^}]*\.\.\.BROWSER_POLICY_HEADERS")
        dev = text[text.index("\n  server: {"):text.index("\n  preview: {")]
        self.assertIn("headers: BROWSER_POLICY_HEADERS", dev)

    def test_the_preview_server_used_by_the_browser_tests_applies_it(self):
        self.assertRegex(VITE.read_text(), r"preview:\s*\{[^}]*headers:\s*SECURITY_HEADERS")


class SingleEntryGatewayTest(unittest.TestCase):
    """#487 (ADR-005 amendment): one gateway, one port and one origin. /api/ strips any presenter assertion;
    /presenter-api/ signs a fresh one and proxies to the API's /api/, or refuses when presenter access is off."""

    def setUp(self):
        self.web = (ROOT / "infra/deploy/web.conf.template").read_text()
        self.enabled = (ROOT / "infra/deploy/presenter-api.conf.template").read_text()
        self.disabled = (ROOT / "infra/deploy/presenter-api-disabled.conf").read_text()

    def test_one_listener_and_the_root_is_the_home_page(self):
        self.assertEqual(len(re.findall(r"\n    listen ", self.web)), 1)
        self.assertIn("listen ${AWARECARE_WEB_BIND}:${AWARECARE_WEB_PORT};", self.web)
        blocks = locations(self.web)
        self.assertNotIn("= /", blocks)  # the home page (W01, the patient or presenter choice), no redirect
        self.assertNotIn("return 302", blocks["/"])
        self.assertFalse((ROOT / "infra/deploy/presenter.conf.template").exists())

    def test_the_patient_api_strips_any_presenter_assertion(self):
        api = locations(self.web)["/api/"]
        self.assertIn('proxy_set_header X-AwareCare-Presenter "";', api)
        self.assertNotIn("X-AwareCare-Gateway", api)

    def test_the_presenter_api_is_always_defined_inside_the_one_server(self):
        self.assertIn("include /tmp/aware-care/presenter-api.conf;", self.web)
        script = (ROOT / "infra/deploy/25-aware-care-presenter.sh").read_text()
        self.assertIn("> /tmp/aware-care/presenter-api.conf", script)
        self.assertIn("presenter-api-disabled.conf /tmp/aware-care/presenter-api.conf", script)

    def test_the_presenter_api_signs_a_fresh_assertion_and_proxies_to_the_api(self):
        loc = locations(self.enabled)["/presenter-api/"]
        self.assertIn("proxy_pass http://127.0.0.1:${AWARECARE_API_PORT}/api/;", loc)
        self.assertIn("proxy_set_header X-AwareCare-Presenter $aware_care_presenter_assertion;", loc)
        self.assertIn("add_header X-AwareCare-Gateway presenter always;", loc)
        self.assertIn("js_set $aware_care_presenter_assertion presenter.mint;", self.enabled)

    def test_the_disabled_presenter_api_refuses_without_reaching_the_api(self):
        loc = locations(self.disabled)["/presenter-api/"]
        self.assertNotIn("proxy_pass", loc)
        self.assertNotIn("X-AwareCare-Gateway", loc)
        self.assertIn("return 403", loc)
        self.assertIn('"code":"PRESENTER_REQUIRED"', loc)
        self.assertIn('add_header Cache-Control "no-store" always;', loc)

    def test_the_presenter_path_needs_a_loopback_bind_in_the_container_too(self):
        script = (ROOT / "infra/deploy/25-aware-care-presenter.sh").read_text()
        self.assertIn('127.0.0.1|localhost|::1|\'[::1]\') loopback=1', script)
        self.assertIn('[ "$loopback" = "1" ]', script)

    def test_no_second_port_remains_in_the_gateway_or_deploy_configuration(self):
        for path in [*(ROOT / "infra/deploy").glob("*.template"), *(ROOT / "infra/deploy").glob("*.conf"),
                     ROOT / "infra/deploy/25-aware-care-presenter.sh", ROOT / "infra/deploy/web.Dockerfile",
                     ROOT / "infra/deploy/demo-zgx-nano.json", ROOT / "infra/deploy/demo-zgx-fury.json"]:
            with self.subTest(path=path.name):
                text = path.read_text()
                self.assertNotIn("AWARECARE_PRESENTER_PORT", text)
                self.assertNotIn("presenter_port", text)
                self.assertNotIn("18181", text)


if __name__ == "__main__":
    unittest.main()
