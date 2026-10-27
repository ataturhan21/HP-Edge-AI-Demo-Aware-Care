"""#205: the gateway gzips static text for the browser, and never the API (small, session-bound responses); #487: on
either API path (/api/ and the presenter API /presenter-api/)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from test_security_headers import PRESENTER_SNIPPETS, TEMPLATES, locations


def server_directives(text: str) -> str:
    """The server block's own directives: the text outside every location block."""
    return re.sub(r"location\s+(=?\s*\S+)\s*\{.*?\n    \}", "", text, flags=re.S)


class GatewayCompressionTest(unittest.TestCase):
    def test_static_text_is_gzipped_on_both_gateways(self):
        for template in TEMPLATES:
            with self.subTest(template=template.name):
                server = server_directives(template.read_text())
                self.assertRegex(server, r"\n    gzip on;")
                types = re.search(r"\n    gzip_types ([^;]+);", server)
                self.assertIsNotNone(types)
                for kind in ("application/javascript", "text/css", "image/svg+xml"):
                    self.assertIn(kind, types.group(1).split())
                self.assertRegex(server, r"\n    gzip_vary on;")

    def test_the_api_is_never_compressed(self):
        for template in TEMPLATES:
            with self.subTest(template=template.name):
                self.assertIn("gzip off;", locations(template.read_text())["/api/"])
        # The signing presenter API proxies to the API: never compressed either. The disabled one sends a fixed refusal.
        self.assertIn("gzip off;", locations(PRESENTER_SNIPPETS[0].read_text())["/presenter-api/"])


if __name__ == "__main__":
    unittest.main()
