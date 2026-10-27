"""The model lock (#544): scripts/dev/with_model_lock.sh lets one AI job at a time use the device model.

Nothing here contacts GitHub, a device or a model.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "scripts/dev/with_model_lock.sh"

# The gh stub: answers from files in $STUB (runners.tsv, busy-<workflow>, view.txt) and logs every call to calls.log.
GH = r"""#!/bin/bash
echo "gh $*" >> "$STUB/calls.log"
case "$*" in
  "auth status"*) exit 0;;
  "api repos/"*"/actions/runners"*) cat "$STUB/runners.tsv";;
  "run list"*"select(.status"*) for a in "$@"; do case $a in deploy-*.yml) wf=$a;; esac; done
    cat "$STUB/busy-$wf" 2>/dev/null; exit 0;;
  "run list"*) if [ -e "$STUB/dispatched" ]; then echo 101; else echo 100; fi;;
  "workflow run"*) touch "$STUB/dispatched";;
  "api -X POST"*) echo '{}';;
  "api repos/"*"/pending_deployments"*) echo demo-zgx-fury;;
  "run view"*"status,jobs"*) cat "$STUB/view.txt";;
  "run view"*"conclusion"*) if grep -q "run cancel" "$STUB/calls.log"; then echo cancelled; else echo success; fi;;
  "run cancel"*|"run download"*) ;;
  *) echo "gh stub: unexpected: $*" >&2; exit 1;;
esac
"""
class Stubbed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stub = Path(self.tmp.name)
        for name, text in (("gh", GH),):
            (self.stub / name).write_text(text)
            (self.stub / name).chmod(0o755)
        (self.stub / "calls.log").write_text("")
        self.env = {**os.environ, "STUB": str(self.stub), "PATH": f"{self.stub}:{os.environ['PATH']}",
                    "AWARE_CARE_RELEASE_DIR": str(self.stub / "out"), "AWARE_CARE_MODEL_LOCK": str(self.stub / "m.lock")}

    def tearDown(self):
        self.tmp.cleanup()

    def run_sh(self, *args: str, timeout: int = 60, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", *args], capture_output=True, text=True, env={**self.env, **env}, timeout=timeout)

    def calls(self) -> str:
        return (self.stub / "calls.log").read_text()


class ModelLock(Stubbed):
    def held_by(self, seconds: float) -> subprocess.Popen:
        p = subprocess.Popen(["bash", str(LOCK), "sleep", str(seconds)], env=self.env)
        for _ in range(50):
            if any(self.stub.glob("m.lock.holder.*")):
                break
            time.sleep(0.1)
        return p

    def test_a_second_job_waits_with_a_message_naming_the_holder(self):
        holder = self.held_by(3)
        r = self.run_sh(str(LOCK), "echo", "ran", AWARE_CARE_MODEL_LOCK_STEP="1")
        holder.wait()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "ran")
        self.assertRegex(r.stderr, rf"waiting for the model \(another AI job is running: {holder.pid} sleep 3\) \d+ s")
        self.assertIn("model lock: acquired after", r.stderr)

    def test_the_wait_has_a_limit_with_a_clear_failure(self):
        holder = self.held_by(5)
        r = self.run_sh(str(LOCK), "echo", "ran", AWARE_CARE_MODEL_LOCK_WAIT="1")
        holder.kill(); holder.wait()
        self.assertEqual(r.returncode, 75)
        self.assertNotIn("ran", r.stdout)
        self.assertIn("model lock: gave up after", r.stderr)

    def test_the_lock_is_released_on_exit_on_failure_and_on_a_kill(self):
        lock = str(self.stub / "m.lock")
        for cmd in (["true"], ["false"], ["sh", "-c", "kill -9 $PPID"]):
            r = self.run_sh(str(LOCK), *cmd)
            self.assertEqual(r.returncode == 0, cmd == ["true"], cmd)
            free = subprocess.run(["flock", "-n", lock, "true"], timeout=10)
            self.assertEqual(free.returncode, 0, f"lock still held after {cmd}")

    def test_the_command_holds_the_lock_and_a_nested_call_does_not_wait_for_itself(self):
        lock = str(self.stub / "m.lock")
        inner = f"flock -n {lock} true && echo free || echo held; bash {LOCK} echo nested"
        r = self.run_sh(str(LOCK), "bash", "-c", inner, timeout=20)
        self.assertEqual(r.stdout.split(), ["held", "nested"], r.stderr)

    def job_under_lock(self, job: str) -> tuple[subprocess.Popen, int]:
        """The wrapper running `bash -c job`; the job writes its pid to job.pid first. Returns (wrapper, job pid)."""
        pid_file = self.stub / "job.pid"
        pid_file.unlink(missing_ok=True)
        wrapper = subprocess.Popen(["bash", str(LOCK), "bash", "-c", f"echo $$ > {pid_file}; {job}"], env=self.env,
                                   stdin=subprocess.DEVNULL)
        for _ in range(100):
            if pid_file.exists() and pid_file.read_text().strip():
                break
            time.sleep(0.05)
        pid = int(pid_file.read_text())
        self.addCleanup(lambda: subprocess.run(["kill", "-KILL", str(pid)], stderr=subprocess.DEVNULL))
        return wrapper, pid

    def lock_free(self) -> bool:
        return subprocess.run(["flock", "-n", str(self.stub / "m.lock"), "true"], timeout=10).returncode == 0

    @staticmethod
    def alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"

    def test_a_kill_of_the_wrapper_reaches_its_job_and_the_lock_is_freed_only_after_the_job_exited(self):
        """#566: SIGTERM, SIGINT or SIGHUP to the wrapper goes to its job's whole process group (here a shell and its
        foreground sleep; a script's background child would ignore SIGINT); the wrapper waits for the job, returns its
        status, and only then is the lock free."""
        import signal
        done = self.stub / "done"
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            with self.subTest(signal=sig.name):
                done.unlink(missing_ok=True)
                job = f'trap "sleep 1; echo cleaned > {done}; exit 3" TERM INT HUP; sleep 30; exit 0'
                wrapper, pid = self.job_under_lock(job)
                wrapper.send_signal(sig)
                time.sleep(0.3)
                self.assertFalse(self.lock_free(), "the lock is held while the job cleans up")
                self.assertEqual(wrapper.wait(timeout=10), 3, "the wrapper returns the job's status")
                self.assertEqual(done.read_text().strip(), "cleaned", "the job got the signal and finished first")
                self.assertFalse(self.alive(pid))
                self.assertTrue(self.lock_free())

    def test_a_sigkilled_wrapper_does_not_free_the_lock_while_its_job_runs(self):
        """#566: SIGKILL cannot be passed on; the job holds the lock itself (an inherited descriptor) until it ends."""
        wrapper, pid = self.job_under_lock("sleep 30")
        wrapper.kill()
        wrapper.wait(timeout=10)
        self.assertTrue(self.alive(pid))
        self.assertFalse(self.lock_free(), "the running job still holds the lock")
        r = self.run_sh(str(LOCK), "echo", "second", AWARE_CARE_MODEL_LOCK_WAIT="1")
        self.assertEqual(r.returncode, 75, r.stdout)
        os.kill(pid, 9)
        for _ in range(100):
            if self.lock_free():
                break
            time.sleep(0.05)
        self.assertTrue(self.lock_free(), "the lock is free once the job is gone")

    def test_the_job_keeps_its_standard_input(self):
        r = subprocess.run(["bash", str(LOCK), "cat"], input="from stdin\n", capture_output=True, text=True,
                           env=self.env, timeout=20)
        self.assertEqual((r.returncode, r.stdout), (0, "from stdin\n"), r.stderr)

    def test_its_users_take_it(self):
        run = (ROOT / "scripts/ai_regression/run.sh").read_text()
        self.assertTrue('exec bash "$REPO/scripts/dev/with_model_lock.sh"' in run, "run.sh takes the local lock")
        self.assertTrue("bash ~/$FURY_DIR/scripts/dev/with_model_lock.sh" in run, "run.sh takes the Fury's lock there")
        self.assertTrue("with_model_lock.sh" in (ROOT / "demo.sh").read_text(), "check-model takes the lock")


if __name__ == "__main__":
    unittest.main()
