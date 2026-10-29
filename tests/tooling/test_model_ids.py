"""#528: the same model is recognised under every name ZRT may serve it under; only another model is not.

ZRT lists a model by its --label (our serve scripts: qwen3.6-35b-a3b-fp8) or, started without one, by its canonical
name (Qwen/Qwen3.6-35B-A3B-FP8); its listings write the URI as hf:<repo>@<revision>, and its cache keeps a copy under
<home>/models/hf/<org>/<name>/<revision>/. Observed on the Nano with ZRT, 2026-10-23.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "apps/api/app/runtime/model_ids.py"
spec = importlib.util.spec_from_file_location("model_ids_under_test", MODULE)
ids = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ids
spec.loader.exec_module(ids)

NANO = "qwen3.6-35b-a3b-fp8"
NANO_REF = "hf:Qwen/Qwen3.6-35B-A3B-FP8@95a723d08a9490559dae23d0cff1d9466213d989"
FURY = NANO  # #646: the Fury serves the Nano's model
FURY_REF = NANO_REF

SAME_NANO = {  # served id -> the revision it names
    NANO: None,
    "Qwen/Qwen3.6-35B-A3B-FP8": None,
    "qwen/qwen3.6-35b-a3b-fp8": None,
    "QWEN/QWEN3.6-35B-A3B-FP8": None,
    "Qwen/Qwen3.6-35B-A3B-FP8@main": "main",
    "Qwen/Qwen3.6-35B-A3B-FP8@95a723d": "95a723d",
    "hf:Qwen/Qwen3.6-35B-A3B-FP8": None,
    "hf:Qwen/Qwen3.6-35B-A3B-FP8@main": "main",
    "HF:qwen/qwen3.6-35b-a3b-fp8@v2": "v2",
    NANO_REF: "95a723d08a9490559dae23d0cff1d9466213d989",
    "/opt/hp/zrt/models/hf/Qwen/Qwen3.6-35B-A3B-FP8/main": "main",
}
OTHER_MODELS = ["Qwen/Qwen3.6-35B-A3B", "Qwen/Qwen3.6-35B-A3B-FP8-Instruct", "Qwen/Qwen3.8-27B-FP8@main",
                "otherorg/Qwen3.6-35B-A3B-FP8", "qwen3.6-35b-a3b", "Qwen/Qwen2.5-0.5B-Instruct",
                "qwen3.8-flash-next-fp8", ""]  # #646: the Fury's former model


class Matching(unittest.TestCase):
    def test_every_name_of_the_same_model_matches_with_its_revision(self):
        for served, revision in SAME_NANO.items():
            with self.subTest(served=served):
                match = ids.find_served(["Qwen/Qwen2.5-0.5B-Instruct", served], NANO, NANO_REF)
                self.assertIsNotNone(match)
                self.assertEqual(match.served_id, served)  # requests use exactly what ZRT lists
                self.assertEqual(match.revision, revision)

    def test_a_different_model_never_matches(self):
        for other in OTHER_MODELS:
            with self.subTest(other=other):
                self.assertIsNone(ids.find_served([other], NANO, NANO_REF))
        self.assertIsNone(ids.find_served([], NANO, NANO_REF))
        self.assertIsNone(ids.find_served([None, 3, {"id": NANO}], NANO, NANO_REF))

    def test_without_the_repository_only_the_names_of_the_configured_id_match(self):
        self.assertIsNotNone(ids.find_served(["QWEN3.6-35B-A3B-FP8@main"], NANO))
        self.assertIsNone(ids.find_served(["Qwen/Qwen3.6-35B-A3B-FP8"], NANO))
        self.assertIsNotNone(ids.find_served(["Qwen/Qwen3.6-35B-A3B-FP8@main"], "Qwen/Qwen3.6-35B-A3B-FP8"))

    def test_the_exact_configured_id_wins(self):
        match = ids.find_served(["Qwen/Qwen3.6-35B-A3B-FP8@main", NANO], NANO, NANO_REF)
        self.assertEqual(match.served_id, NANO)

    def test_the_fury_model(self):
        for served in (FURY, "Qwen/Qwen3.6-35B-A3B-FP8", "hf:Qwen/Qwen3.6-35B-A3B-FP8@main"):
            self.assertEqual(ids.find_served([served], FURY, FURY_REF).served_id, served)
        self.assertIsNone(ids.find_served(["Qwen/Qwen3.8-Flash-Next-FP8"], FURY, FURY_REF))  # its former model

    def test_the_manifest_names_the_repository_only_for_its_own_model(self):
        manifest = json.loads((ROOT / "infra/model-manifest.json").read_text())
        self.assertEqual(ids.manifest_ref(manifest, NANO), NANO_REF.removeprefix("hf:"))
        self.assertEqual(ids.manifest_ref(manifest, "Qwen/Qwen3.6-35B-A3B-FP8@main"), NANO_REF.removeprefix("hf:"))
        self.assertIsNone(ids.manifest_ref(manifest, "test-model"))
        self.assertIsNone(ids.manifest_ref(manifest, None))
        fury = json.loads((ROOT / "infra/fury/model-manifest.json").read_text())
        self.assertEqual(ids.manifest_ref(fury, FURY), FURY_REF.removeprefix("hf:"))


class Revisions(unittest.TestCase):
    def test_another_revision_is_a_note_and_the_qualified_one_none(self):
        q = "95a723d08a9490559dae23d0cff1d9466213d989"
        self.assertEqual(ids.revision_note("main", q), "serving revision main; this app was qualified on 95a723d…")
        self.assertIsNone(ids.revision_note(q, q))
        self.assertIsNone(ids.revision_note("95a723d0", q))
        self.assertIn("does not say which revision", ids.revision_note(None, q))

    def test_the_revision_behind_a_label_comes_from_zrt(self):
        proxy = {"services": [{"model_uri": "hf:Qwen/Qwen3.6-35B-A3B-FP8@main", "label": ""},
                              {"model_uri": NANO_REF, "label": NANO}]}
        self.assertEqual(ids.revision_from_zrt(NANO, proxy), "95a723d08a9490559dae23d0cff1d9466213d989")
        self.assertEqual(ids.revision_from_zrt("Qwen/Qwen3.6-35B-A3B-FP8", proxy), "main")
        services = ("│ 129042 │ hf:Qwen/Qwen3.6-35B-A3B-FP8@main │ Qwen/Qwen3.6-35B-A3B-FP8 │ - │ Ready │\n")
        self.assertEqual(ids.revision_from_zrt("Qwen/Qwen3.6-35B-A3B-FP8", None, services), "main")
        self.assertIsNone(ids.revision_from_zrt(NANO, None, ""))

    def test_local_copies_from_zrt_models_and_the_cache(self):
        listing = ("│ hf:Qwen/Qwen3.6-35B-A3B-FP8@main │ Qwen/Qwen3.6-35B-A3B-FP8 │ main │ 37.49 GB │\n"
                   "│ hf:Qwen/Qwen3.6-35B-A3B@main │ Qwen/Qwen3.6-35B-A3B │ main │ 71.93 GB │\n")
        self.assertEqual(ids.local_revisions(NANO_REF, listing), ["main"])
        with tempfile.TemporaryDirectory() as tmp:
            for rev, complete in (("v2", True), ("partial", False)):
                d = Path(tmp, "hf/Qwen/Qwen3.6-35B-A3B-FP8", rev)
                d.mkdir(parents=True)
                if complete:
                    (d / "config.json").write_text("{}")
            self.assertEqual(ids.local_revisions(NANO_REF, "", Path(tmp)), ["v2"])
        self.assertEqual(ids.choose_local(["v2", "main"], "95a723d0"), "main")
        self.assertEqual(ids.choose_local(["main", "95a723d0abc"], "95a723d0abc"), "95a723d0abc")
        self.assertEqual(ids.choose_local(["v2"], "95a723d0"), "v2")
        self.assertIsNone(ids.choose_local(["main"], "95a723d0", wanted="v3"))
        self.assertIsNone(ids.choose_local([], "95a723d0"))

    def test_the_command_line(self):
        def run(*args, stdin=""):
            return subprocess.run([sys.executable, "-I", str(MODULE), *args], input=stdin, capture_output=True,
                                  text=True, timeout=30)
        body = json.dumps({"data": [{"id": "Qwen/Qwen3.6-35B-A3B-FP8@main"}]})
        r = run("match", "--model", NANO, "--repo", NANO_REF, "--models", "-", stdin=body)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["Qwen/Qwen3.6-35B-A3B-FP8@main", "main",
                                                 "serving revision main; this app was qualified on 95a723d…"])
        r = run("match", "--model", NANO, "--repo", NANO_REF, "--models", "-",
                stdin=json.dumps({"data": [{"id": "Qwen/Qwen3.8-27B-FP8"}]}))
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertEqual(run("ids", "--models", "-", stdin=body).stdout, "Qwen/Qwen3.6-35B-A3B-FP8@main\n")
        self.assertEqual(run("note", "--served", "main", "--qualified", "95a723d08a").stdout,
                         "serving revision main; this app was qualified on 95a723d08a\n")


# #535: `zrt services` on an HP Z8 (a GPU column, MODEL URI and SERVED AS in one column over two lines) and on the Nano
# (no GPU column, SERVED AS a column of its own, no endpoint).
Z8_SERVICES = """\
┌─────┬───────┬──────────────────────────────────┬───────────────────────┬────────┬────────────────┬────────┐
│ GPU │ PID   │ MODEL URI / SERVED AS            │ API ENDPOINT          │ STATUS │ MEM USAGE      │ UPTIME │
├─────┼───────┼──────────────────────────────────┼───────────────────────┼────────┼────────────────┼────────┤
│ 0,1 │ 97820 │ hf:Qwen/Qwen3.6-35B-A3B-FP8@main │ http://127.0.0.1:9093 │ Ready  │ 65.3 GB (VRAM) │ 6m ago │
│     │       │ Qwen/Qwen3.6-35B-A3B-FP8         │                       │        │                │        │
│ 2   │ 4411  │ hf:prash/Prash@0.30.0            │ http://127.0.0.1:9094 │ Ready  │ 9.1 GB (VRAM)  │ 1h 2m ago │
│     │       │ Prash_0.30.0                     │                       │        │                │        │
└─────┴───────┴──────────────────────────────────┴───────────────────────┴────────┴────────────────┴────────┘
"""
NANO_SERVICES = """\
│ PID    │ MODEL URI                         │ SERVED AS           │ API ENDPOINT │ STATUS │ MEM USAGE      │ UPTIME │
│ 129042 │ hf:Qwen/Qwen3.6-35B-A3B-FP8@95a7… │ qwen3.6-35b-a3b-fp8 │ -            │ Ready  │ 47.0 GB (VRAM) │ 4d ago │
"""


class ZrtServices(unittest.TestCase):
    def test_both_table_layouts(self):
        qwen, prash = ids.parse_services(Z8_SERVICES)
        self.assertEqual((qwen.pid, qwen.endpoint, qwen.status, qwen.uptime),
                         ("97820", "http://127.0.0.1:9093", "Ready", "6m ago"))
        self.assertIn("Qwen/Qwen3.6-35B-A3B-FP8", qwen.names)
        self.assertTrue(ids.service_serves(qwen, NANO, NANO_REF))
        self.assertFalse(ids.service_serves(prash, NANO, NANO_REF))
        self.assertTrue(ids.service_serves(prash, "Prash_0.30.0"))
        self.assertEqual(ids.uptime_seconds(prash.uptime), 3720)
        (nano,) = ids.parse_services(NANO_SERVICES)
        self.assertEqual((nano.pid, nano.endpoint, nano.status), ("129042", "-", "Ready"))
        self.assertTrue(ids.service_serves(nano, NANO, NANO_REF))
        self.assertEqual(ids.uptime_seconds(nano.uptime), 4 * 86400)

    def test_only_a_loopback_endpoint_is_a_base_url(self):
        self.assertEqual(ids.loopback_api_url("http://127.0.0.1:9093"), "http://127.0.0.1:9093/v1")
        self.assertEqual(ids.loopback_api_url("http://localhost:9093/v1/"), "http://localhost:9093/v1")
        for bad in ("-", "", "http://192.0.2.1:9093", "https://127.0.0.1:9093", "http://127.0.0.1",
                    "http://u:p@127.0.0.1:9093", "http://127.0.0.1.evil.example:9093"):
            with self.subTest(endpoint=bad):
                self.assertIsNone(ids.loopback_api_url(bad))

    def test_the_services_command(self):
        r = subprocess.run([sys.executable, "-I", str(MODULE), "services", "--model", NANO, "--repo", NANO_REF,
                            "--services", "-"], input=Z8_SERVICES + NANO_SERVICES, capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([line.split("\t") for line in r.stdout.splitlines()], [
            ["1", "97820", "Ready", "http://127.0.0.1:9093", "http://127.0.0.1:9093/v1", "360", "Qwen/Qwen3.6-35B-A3B-FP8",
             "hf:Qwen/Qwen3.6-35B-A3B-FP8@main"],
            ["0", "4411", "Ready", "http://127.0.0.1:9094", "http://127.0.0.1:9094/v1", "3720", "Prash_0.30.0",
             "hf:prash/Prash@0.30.0"],
            ["1", "129042", "Ready", "-", "-", "345600", "qwen3.6-35b-a3b-fp8", "hf:Qwen/Qwen3.6-35B-A3B-FP8@95a7…"]])


if __name__ == "__main__":
    unittest.main()
