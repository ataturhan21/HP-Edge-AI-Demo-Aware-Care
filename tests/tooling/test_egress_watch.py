"""scripts/egress_watch.sh (ADR-002 stage 6) with stand-ins for pgrep and ss on PATH (#295).

QA 2026-10-19: the watcher's own command line contains the pattern, so `pgrep -f` always matched the watcher and
`no_process` was never written; and with a state filter `ss -tunpH` drops the State column, so the peer is field 5,
not 6. The pgrep stand-in follows procps semantics (an ERE over the full command line, excluding itself); the ss
stand-in prints crafted sockets for one dummy "model" process. Nothing touches the network.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WATCH = ROOT / "scripts/egress_watch.sh"

PGREP = """\
#!/usr/bin/env python3
import os, re, sys
pat = re.compile(sys.argv[-1]); me = os.getpid()
for p in os.listdir('/proc'):
    if not p.isdigit() or int(p) == me:
        continue
    try:
        cmd = open(f'/proc/{p}/cmdline', 'rb').read().replace(b'\\0', b' ').decode(errors='replace').strip()
    except OSError:
        continue
    if cmd and pat.search(cmd):
        print(p)
"""

SS = """\
#!/bin/sh
pid=${FAKE_MODEL_PID:-0}
case "$*" in
  *established*)
    echo "tcp 0 0 127.0.0.1:8080 127.0.0.1:50000 users:((\\"python3\\",pid=$pid,fd=3))"
    echo "tcp 0 0 192.168.1.5:40000 10.0.0.5:443 users:((\\"python3\\",pid=$pid,fd=4))" ;;
  *)
    echo "tcp LISTEN 0 4096 127.0.0.1:8080 0.0.0.0:* users:((\\"python3\\",pid=$pid,fd=5))" ;;
esac
"""


class EgressWatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="egress-watch-"))
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, text in (("pgrep", PGREP), ("ss", SS)):
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        self.marker = f"aware-care-fake-model-{uuid.uuid4().hex[:12]}"

    def watch(self, argv: list[str], seconds: float = 2.6) -> list[str]:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=self.env,
                                start_new_session=True)
        time.sleep(seconds)
        os.killpg(proc.pid, signal.SIGTERM)
        out, _ = proc.communicate(timeout=10)
        lines = [line for line in out.splitlines() if line.strip()]
        self.assertTrue(lines, "the watcher wrote no sample")
        return lines

    def test_no_model_process_is_recorded_as_no_process(self):
        lines = self.watch(["bash", str(WATCH), self.marker])
        samples = [line for line in lines if "sockets=" in line]
        self.assertTrue(samples)
        self.assertTrue(all(line.endswith(" no_process") for line in samples), samples)

    def test_the_shell_that_started_the_watcher_is_not_a_model_process(self):
        # `bash -c '...; true'` stays alive as the watcher's parent with the pattern in its command line.
        lines = self.watch(["bash", "-c", f"bash {WATCH} '{self.marker}'; true"])
        self.assertTrue(all("no_process" in line for line in lines if "sockets=" in line), lines)

    def test_the_peer_column_is_checked_and_local_to_peer_printed(self):
        model = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", self.marker])
        self.addCleanup(model.kill)
        self.env["FAKE_MODEL_PID"] = str(model.pid)
        lines = self.watch(["bash", str(WATCH), self.marker])
        samples = [line for line in lines if "sockets=" in line]
        self.assertTrue(samples)
        for line in samples:
            self.assertTrue(line.endswith("sockets=2 non_loopback=1 listen=1 listen_non_loopback=0"), line)
        details = [line.strip() for line in lines if line.startswith("  conn")]
        self.assertTrue(details)
        self.assertEqual(set(details), {"conn 192.168.1.5:40000 -> 10.0.0.5:443"})

    def test_the_script_parses(self):
        subprocess.run(["bash", "-n", str(WATCH)], check=True)


if __name__ == "__main__":
    unittest.main()
