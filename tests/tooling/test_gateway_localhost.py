"""#690 (owner decision B3, 28 Oct 2026): http://localhost:<port> works as well as http://127.0.0.1:<port>.

The web gateway (infra/deploy/web.conf.template) and the Vite dev and preview servers (mock mode, the browser tests)
redirect a request whose Host is localhost to 127.0.0.1 on the same port, path and query; the API's Origin and CSRF
checks stay exact (apps/api is unchanged: tests/acceptance cover them). tests/ui/W01.spec.ts follows the redirect in a
real browser through the preview server.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "infra/deploy/web.conf.template"
VITE = ROOT / "apps/web/vite.config.ts"


def loopback_map(text: str) -> tuple[str, str]:
    """The map's (regex, value) entry that sends localhost to 127.0.0.1."""
    block = re.search(r"\nmap \$http_host \$aware_care_loopback \{\n(.*?)\n\}", text, re.S)
    assert block, "the localhost map is missing"
    entry = re.search(r'^\s*"~\*(\^localhost[^"]*)"\s+"([^"]+)";', block.group(1), re.M)
    assert entry, "the map has no localhost entry"
    return entry.group(1), entry.group(2)


def target(host: str, text: str) -> str:
    """What nginx's map gives for this Host header: the regex is PCRE, case-insensitive (~*), with named captures."""
    pattern, value = loopback_map(text)
    m = re.match(pattern.replace("(?<", "(?P<"), host, re.I)
    if not m:
        return ""
    return re.sub(r"\$(\w+)", lambda v: m.groupdict().get(v.group(1)) or "", value)


class LocalhostRedirectTest(unittest.TestCase):
    def test_the_gateway_maps_localhost_to_127_0_0_1_on_the_same_port(self):
        text = TEMPLATE.read_text()
        cases = {
            "localhost:18180": "http://127.0.0.1:18180",
            "localhost": "http://127.0.0.1",
            "LOCALHOST:28180": "http://127.0.0.1:28180",
            "127.0.0.1:18180": "",
            "localhost.example.com:18180": "",
            "evil.localhost:18180": "",
            "localhost:18180@evil": "",
            "[::1]:18180": "",
        }
        for host, expected in cases.items():
            with self.subTest(host=host):
                self.assertEqual(target(host, text), expected)

    def test_the_map_is_outside_the_server_and_the_redirect_comes_before_every_location(self):
        text = TEMPLATE.read_text()
        self.assertLess(text.index("map $http_host $aware_care_loopback"), text.index("server {"))
        server = text[text.index("server {"):]
        redirect = re.search(r"\n    if \(\$aware_care_loopback\) \{\n        return 307 \$aware_care_loopback\$request_uri;\n    \}",
                             server)
        self.assertIsNotNone(redirect, "server: if ($aware_care_loopback) { return 307 ...$request_uri; }")
        self.assertLess(redirect.start(), server.index("location "))
        # envsubst renders only AWARECARE_* names: the map's own variables stay nginx variables
        for name in re.findall(r"\$\{?(\w+)", text[:text.index("server {")]):
            self.assertFalse(name.startswith("AWARECARE_"), name)

    def test_the_vite_servers_redirect_the_same_way(self):
        text = VITE.read_text()
        self.assertIn("localhostRedirect()", re.search(r"plugins: \[([^\]]*)\]", text).group(1))
        for hook in ("configureServer", "configurePreviewServer"):
            self.assertRegex(text, rf"{hook}: \(server\) => void server\.middlewares\.use\(redirect\)")
        self.assertIn("res.statusCode = 307;", text)
        self.assertIn('`http://127.0.0.1${host[1] ?? ""}${req.url ?? "/"}`', text)
        pattern = re.search(r"export const LOCALHOST = /(.+)/i;", text).group(1).replace("\\\\", "\\")
        for host, match in (("localhost:15174", True), ("LocalHost", True), ("127.0.0.1:15174", False),
                            ("localhost.example.com", False)):
            self.assertEqual(bool(re.match(pattern, host, re.I)), match, host)


if __name__ == "__main__":
    unittest.main()
