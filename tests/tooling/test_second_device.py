"""ADR-018: the HP ZGX Fury is a second deployment target built from the same release images.

The Fury's deploy configuration names its device (shown by the web gateway) and selects the API's per-device files,
which the API image must contain. Its workflow uses its own environment, runner label and concurrency group, so a Fury
deployment can never land on the Nano. The gateway answers /aware-care-device.js from the deploy configuration (#487:
one gateway, one port and one origin for patients and presenters).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "infra/deploy"))
import nano_deploy  # noqa: E402

DEPLOY = ROOT / "infra/deploy"
NANO = json.loads((DEPLOY / "demo-zgx-nano.json").read_text())
FURY = json.loads((DEPLOY / "demo-zgx-fury.json").read_text())
GENERIC = json.loads((DEPLOY / "demo-generic.json").read_text())


def settings(config: dict) -> nano_deploy.Settings:
    args = argparse.Namespace(instance=None, data_root="/tmp/aware-care-test-root", api_port=None, web_port=None,
                              origin=None)
    return nano_deploy.Settings(config, args)


class SecondDeviceTest(unittest.TestCase):
    def test_each_config_names_its_device(self):
        self.assertEqual((settings(NANO).device_name, settings(NANO).device_short_name), ("HP ZGX Nano", "ZGX Nano"))
        self.assertEqual((settings(FURY).device_name, settings(FURY).device_short_name), ("HP ZGX Fury", "ZGX Fury"))
        self.assertEqual(settings(NANO).api_files, {})  # the Nano keeps the image's default files

    def test_the_fury_selects_its_own_api_files_and_the_image_contains_them(self):
        files = settings(FURY).api_files
        self.assertEqual(set(files), {"AWARECARE_MODEL_MANIFEST", "AWARECARE_DEVICE_INVENTORY",
                                      "AWARECARE_TELEMETRY_PRICING"})
        dockerfile = (DEPLOY / "api.Dockerfile").read_text()
        for container_path in files.values():
            source = container_path.removeprefix("/srv/aware-care/")
            with self.subTest(source=source):
                self.assertTrue((ROOT / source).is_file(), source)
                self.assertIn(source, dockerfile)
                json.loads((ROOT / source).read_text())

    def test_the_containers_get_the_device_and_the_per_device_files(self):
        import tempfile
        from unittest import mock
        calls = []
        with tempfile.TemporaryDirectory() as root, mock.patch.object(nano_deploy, "docker",
                                                                      side_effect=lambda *a, **k: calls.append(a)):
            fury = settings(FURY)
            fury.root = Path(root)
            nano_deploy.start_containers(fury, {"mode": "local", "release_tag": "v0.0.0-test", "app_commit": "abc",
                                                "model_id": "qwen3.8-flash-next-fp8", "api_image": "api@x",
                                                "web_image": "web@y"})
        api, web = calls
        self.assertIn("AWARECARE_MODEL_MANIFEST=/srv/aware-care/infra/fury/model-manifest.json", api)
        self.assertIn("AWARECARE_TELEMETRY_PRICING=/srv/aware-care/infra/fury/telemetry-pricing.json", api)
        self.assertIn("AWARECARE_MODEL_ID=qwen3.8-flash-next-fp8", api)
        self.assertIn("AWARECARE_DEVICE_NAME=HP ZGX Fury", web)
        self.assertIn("AWARECARE_DEVICE_SHORT_NAME=ZGX Fury", web)

    def test_537_another_machine_is_named_from_dmi_and_gets_its_own_device_files(self):
        """#537: demo.sh deploys any other NVIDIA machine with demo-generic.json, the device name it read from DMI and
        a directory with the detected inventory and neutral prices, mounted read-only for the API. The model manifest
        stays the image's default: the API selects the served catalogue model's manifest by its label."""
        import tempfile
        from unittest import mock
        calls: list = []
        with tempfile.TemporaryDirectory() as root, mock.patch.object(nano_deploy, "docker",
                                                                      side_effect=lambda *a, **k: calls.append(a)):
            files = Path(root) / "device"
            files.mkdir()
            args = argparse.Namespace(instance=None, data_root=root, api_port=None, web_port=None, origin=None,
                                      device_name="HP Z8 Fury G5 Workstation Desktop PC",
                                      device_short_name="Z8 Fury G5", device_files=str(files))
            with self.assertRaises(nano_deploy.DeployError):  # the files must be there
                nano_deploy.Settings(GENERIC, args)
            for name in ("device-inventory.json", "telemetry-pricing.json"):
                (files / name).write_text("{}")
            dev = nano_deploy.Settings(GENERIC, args)
            self.assertEqual((dev.device_name, dev.device_short_name), ("HP Z8 Fury G5 Workstation Desktop PC",
                                                                        "Z8 Fury G5"))
            nano_deploy.start_containers(dev, {"mode": "local", "release_tag": "local", "app_commit": "abc",
                                               "model_id": "qwen3-14b-fp8", "api_image": "api@x", "web_image": "web@y"})
            bad = argparse.Namespace(**{**vars(args), "device_name": "Z8 <script>"})
            with self.assertRaises(nano_deploy.DeployError):
                nano_deploy.Settings(GENERIC, bad)
        api, web = calls
        self.assertIn(f"{files.resolve()}:/run/aware-care/device:ro", api)
        self.assertIn("AWARECARE_DEVICE_INVENTORY=/run/aware-care/device/device-inventory.json", api)
        self.assertIn("AWARECARE_TELEMETRY_PRICING=/run/aware-care/device/telemetry-pricing.json", api)
        self.assertFalse([a for a in api if "AWARECARE_MODEL_MANIFEST" in str(a)])
        self.assertIn("AWARECARE_DEVICE_NAME=HP Z8 Fury G5 Workstation Desktop PC", web)
        self.assertIn("AWARECARE_DEVICE_SHORT_NAME=Z8 Fury G5", web)
        # The ZGX configurations ignore what they are not given.
        self.assertEqual(settings(NANO).device_files, None)

    def test_549_a_candidate_models_manifest_from_the_device_files_reaches_the_api(self):
        """#549: on another machine the served model is a candidate; hardware.py device-files writes its manifest next to
        the inventory, and the API reads it instead of the Nano's (which would show the Nano's qualification date). The
        deploy preflight reads the same file on the host side of the mount."""
        import tempfile
        from unittest import mock
        calls: list = []
        manifest = {"manifest_id": "qwen3.6-35b-a3b-fp8@95a723d0-candidate", "status": "candidate",
                    "model": {"repository_id": "Qwen/Qwen3.6-35B-A3B-FP8", "served_model_id": "qwen3.6-35b-a3b-fp8",
                              "revision": "95a723d08a9490559dae23d0cff1d9466213d989"},
                    "qualification": {"status": "candidate", "runtime_requalifications": []}}
        with tempfile.TemporaryDirectory() as root, mock.patch.object(nano_deploy, "docker",
                                                                      side_effect=lambda *a, **k: calls.append(a)):
            files = Path(root) / "device"
            files.mkdir()
            for name in ("device-inventory.json", "telemetry-pricing.json"):
                (files / name).write_text("{}")
            (files / "model-manifest.json").write_text(json.dumps(manifest))
            args = argparse.Namespace(instance=None, data_root=root, api_port=None, web_port=None, origin=None,
                                      device_name="HP Z8 Fury G5", device_short_name="Z8 Fury G5", device_files=str(files))
            dev = nano_deploy.Settings(GENERIC, args)
            self.assertEqual(nano_deploy._read_manifest(dev, "qwen3.6-35b-a3b-fp8")["manifest_id"],
                             "qwen3.6-35b-a3b-fp8@95a723d0-candidate")
            nano_deploy.start_containers(dev, {"mode": "local", "release_tag": "local", "app_commit": "abc",
                                               "model_id": "qwen3.6-35b-a3b-fp8", "api_image": "api@x",
                                               "web_image": "web@y"})
        api = calls[0]
        self.assertIn("AWARECARE_MODEL_MANIFEST=/run/aware-care/device/model-manifest.json", api)

    def test_the_presenter_gateway_gets_the_patient_origin_and_only_a_plain_one(self):
        """#315/#487: AWARECARE_ORIGIN is the configured browser_origin, the one address of both roles; it is rendered
        into a script, so anything but a plain http(s) origin is refused before a container starts."""
        calls = self.start(NANO, presenter=True)
        self.assertIn(f"AWARECARE_ORIGIN={NANO['network']['browser_origin']}", calls[1])
        for bad in ('http://127.0.0.1:18180"; alert(1); "', "javascript:alert(1)", "http://127.0.0.1:18180/app"):
            with self.subTest(origin=bad), self.assertRaises(nano_deploy.DeployError):
                settings({**NANO, "network": {**NANO["network"], "browser_origin": bad}})

    def start(self, config: dict, presenter: bool, bind_host: str | None = None, mode: str = "mock") -> list:
        """start_containers with a stub docker; returns the docker calls (api first, web second)."""
        import os
        import tempfile
        from unittest import mock
        calls: list = []
        net = {**config["network"], **({"bind_host": bind_host} if bind_host else {})}
        with tempfile.TemporaryDirectory() as root, mock.patch.object(nano_deploy, "docker",
                                                                      side_effect=lambda *a, **k: calls.append(a)):
            dev = settings({**config, "network": net})
            dev.root = Path(root)
            if presenter:
                dev.presenter_key.parent.mkdir(parents=True)
                dev.presenter_key.write_text("k")
                os.chmod(dev.presenter_key, 0o600)
            nano_deploy.start_containers(dev, {"mode": mode, "release_tag": "v0.0.0-test", "app_commit": "abc",
                                               "model_id": None, "api_image": "api@x", "web_image": "web@y"})
        return calls

    def test_487_a_deploy_config_without_a_presenter_port_is_valid_and_uses_one_port_and_origin(self):
        """#487: the shipped configurations name no presenter port or origin; with a presenter key the presenter path
        is enabled on the one gateway port, and the API allows exactly the one origin."""
        for config in (NANO, FURY):
            with self.subTest(environment=config["environment"]):
                for key in ("presenter_port", "presenter_origin", "presenter_tunnel_example"):
                    self.assertNotIn(key, config["network"])
                self.assertEqual(config["presenter"]["path"], "/presenter-api/")
                self.assertEqual(settings(config).legacy_presenter, [])
                for presenter in (False, True):
                    api, web = self.start(config, presenter)
                    self.assertIn(f"AWARECARE_ALLOWED_ORIGINS={config['network']['browser_origin']}", api)
                    self.assertIn(f"AWARECARE_PRESENTER_ENABLED={1 if presenter else 0}", web)
                    self.assertIn("AWARECARE_WEB_BIND=127.0.0.1", web)
                    self.assertFalse([a for a in web if "PRESENTER_PORT" in str(a) or "PRESENTER_ORIGIN" in str(a)])
                    self.assertEqual(any("presenter.key" in str(a) for a in web), presenter)

    def test_487_an_old_config_with_a_presenter_port_and_origin_stays_readable(self):
        """Configurations and commands from before #487 still load; their presenter port and origin are named as
        ignored, and nothing of them reaches a container."""
        old = {**NANO, "network": {**NANO["network"], "presenter_port": 8181,
                                   "presenter_origin": "http://127.0.0.1:18181",
                                   "presenter_tunnel_example": "ssh -N -L 18181:127.0.0.1:8181 u@h"}}
        dev = settings(old)
        self.assertEqual(dev.legacy_presenter,
                         ["network.presenter_origin", "network.presenter_port", "network.presenter_tunnel_example"])
        api, web = self.start(old, presenter=True)
        self.assertIn(f"AWARECARE_ALLOWED_ORIGINS={NANO['network']['browser_origin']}", api)
        self.assertFalse([a for a in (*api, *web) if "8181" in str(a)])
        args = argparse.Namespace(instance=None, data_root="/tmp/aware-care-test-root", api_port=None, web_port=None,
                                  origin=None, presenter_port=8181, presenter_origin="http://127.0.0.1:18181")
        self.assertEqual(nano_deploy.Settings(NANO, args).legacy_presenter, ["--presenter-origin", "--presenter-port"])

    def test_487_the_presenter_path_is_refused_on_a_non_loopback_bind(self):
        """ADR-005: presenter capability is SSH access to the device; without the still-open TLS / mTLS control it must
        never reach a network. A presenter key with a non-loopback bind fails before any container starts."""
        for bind in ("0.0.0.0", "192.0.2.10", "::"):
            with self.subTest(bind=bind):
                with self.assertRaises(nano_deploy.DeployError) as refused:
                    self.start(NANO, presenter=True, bind_host=bind)
                self.assertIn("loopback", str(refused.exception))
                # Without a key, nothing presenter is enabled and the patient gateway may bind there.
                _, web = self.start(NANO, presenter=False, bind_host=bind)
                self.assertIn("AWARECARE_PRESENTER_ENABLED=0", web)
        for bind in ("127.0.0.1", "localhost", "::1"):
            with self.subTest(bind=bind):
                _, web = self.start(NANO, presenter=True, bind_host=bind)
                self.assertIn("AWARECARE_PRESENTER_ENABLED=1", web)
                self.assertIn(f"AWARECARE_WEB_BIND={'[::1]' if bind == '::1' else bind}", web)
        for bad in ("127.0.0.1; rm -rf /", "example.com", ""):
            with self.subTest(bad=bad), self.assertRaises(nano_deploy.DeployError):
                settings({**NANO, "network": {**NANO["network"], "bind_host": bad or " "}})

    def test_487_the_preflight_refuses_a_non_loopback_presenter_before_touching_containers(self):
        """The guard runs in the deployment's preflight: no image is pulled and no container is stopped."""
        import os
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as root:
            dev = settings({**NANO, "network": {**NANO["network"], "bind_host": "0.0.0.0"}})
            dev.root = Path(root)
            dev.presenter_key.parent.mkdir(parents=True)
            dev.presenter_key.write_text("k")
            os.chmod(dev.presenter_key, 0o600)
            import subprocess
            calls = []

            def docker(*a, **k):
                calls.append(a)
                return subprocess.CompletedProcess(a, 1, "", "")
            with mock.patch.object(nano_deploy, "docker", side_effect=docker), \
                    mock.patch.object(nano_deploy, "inspect_image", side_effect=AssertionError("no image step")), \
                    mock.patch.object(nano_deploy, "write_evidence", lambda *a, **k: None, create=True):
                code = nano_deploy.deploy(dev, {"mode": "mock", "release_tag": "v0.0.0-test", "app_commit": "abc",
                                                "model_id": None, "api_image": "api@x", "web_image": "web@y"},
                                          pull=False, require_digest=False, guidance_timeout=1, evidence_out=None,
                                          action="deploy")
            self.assertNotEqual(code, 0)
            self.assertFalse([c for c in calls if c[:1] in (("run",), ("stop",), ("rename",), ("rm",))])

    def test_the_gateway_container_enables_the_presenter_path_only_on_loopback(self):
        """#487: 25-aware-care-presenter.sh, run as the container starts, is the second guard."""
        import os
        import subprocess
        import tempfile
        script = DEPLOY / "25-aware-care-presenter.sh"
        for bind, enabled, key in (("127.0.0.1", "1", True), ("[::1]", "1", True), ("0.0.0.0", "1", True),
                                   ("127.0.0.1", "0", True), ("127.0.0.1", "1", False)):
            with self.subTest(bind=bind, enabled=enabled, key=key), tempfile.TemporaryDirectory() as tmp:
                # Run a copy whose fixed container paths point into the temporary folder.
                text = script.read_text().replace("/tmp/aware-care", f"{tmp}/out").replace(
                    "/etc/nginx/aware-care", str(DEPLOY)).replace("/run/secrets/presenter.key", f"{tmp}/key")
                if key:
                    Path(f"{tmp}/key").write_text("k")
                env = {**os.environ, "AWARECARE_WEB_BIND": bind, "AWARECARE_PRESENTER_ENABLED": enabled,
                       "AWARECARE_API_PORT": "8100", "AWARECARE_WEB_PORT": "8180"}
                out = subprocess.run(["sh", "-c", text], env=env, capture_output=True, text=True, check=True)
                rendered = Path(f"{tmp}/out/presenter-api.conf").read_text()
                on = bind in ("127.0.0.1", "[::1]") and enabled == "1" and key
                self.assertEqual("presenter path enabled" in out.stdout, on)
                self.assertEqual("X-AwareCare-Presenter $aware_care_presenter_assertion" in rendered, on)
                self.assertEqual("return 403" in rendered, not on)
                if bind == "0.0.0.0":
                    self.assertIn("not loopback", out.stdout)

    def test_the_zrt_endpoint_must_be_this_devices_loopback(self):
        """#150: the deploy tool applies the API's parsed loopback rule before any container starts."""
        for config in (NANO, FURY):
            self.assertEqual(settings(config).zrt_base_url, "http://127.0.0.1:8080/v1")
        for bad in ("http://127.0.0.1:8080@remote.example/v1", "http://127.0.0.1.evil.example:8080/v1",
                    "https://127.0.0.1:8080/v1", "http://192.0.2.1:8080/v1", "http://127.0.0.1/v1"):
            with self.subTest(url=bad), self.assertRaises(nano_deploy.DeployError):
                settings({**FURY, "zrt": {**FURY["zrt"], "base_url": bad}})

    def test_a_device_name_that_could_break_the_gateway_script_is_refused(self):
        for bad in ('HP"; alert(1); "', "", "x" * 41, "HP ZGX\nFury"):
            config = {**FURY, "device": {"name": bad, "short_name": "ZGX Fury"}}
            with self.subTest(name=bad), self.assertRaises(nano_deploy.DeployError):
                settings(config)

    def test_the_environments_never_share_a_target(self):
        self.assertEqual(FURY["environment"], "demo-zgx-fury")
        self.assertEqual({k: v for k, v in FURY["network"].items() if k.endswith("_port")},
                         {k: v for k, v in NANO["network"].items() if k.endswith("_port")})  # same ports, other host

    def test_the_fury_serves_the_model_its_manifest_names(self):
        manifest = json.loads((ROOT / "infra/fury/model-manifest.json").read_text())
        script = (ROOT / "infra/fury/zrt/serve-model.sh").read_text()
        model = manifest["model"]
        self.assertIn(f"MODEL=hf:{model['repository_id']}@{model['revision']}", script)
        self.assertIn(f"LABEL={model['served_model_id']}", script)
        self.assertIn("--gpu-memory-fraction 0.9", script)  # the qualified setting (#137)
        self.assertIn("export VLLM_HOST_IP=127.0.0.1 GLOO_SOCKET_IFNAME=lo", script)  # #151, #176: all its sockets on loopback
        self.assertEqual(manifest["serving"]["environment"]["GLOO_SOCKET_IFNAME"].split()[0], "lo")
        # #175: vLLM's usage statistics stay off (they went to stats.vllm.ai every 10 minutes through the proxy).
        self.assertIn("export VLLM_NO_USAGE_STATS=1 VLLM_DO_NOT_TRACK=1 DO_NOT_TRACK=1 HF_HUB_OFFLINE=1", script)
        self.assertTrue(manifest["serving"]["environment"]["VLLM_NO_USAGE_STATS"].startswith("1"))

    def test_both_gateways_answer_the_device_script_from_the_configuration(self):
        text = (DEPLOY / "web.conf.template").read_text()
        self.assertIn("location = /aware-care-device.js", text)
        self.assertIn("${AWARECARE_DEVICE_NAME}", text)
        self.assertIn("${AWARECARE_DEVICE_SHORT_NAME}", text)
        # #315/#487: the script names the one configured address (O03's patient tab opens /app/... on it).
        self.assertIn('origin: "${AWARECARE_ORIGIN}" };', text)
        dockerfile = (DEPLOY / "web.Dockerfile").read_text()
        self.assertTrue(re.search(r'AWARECARE_DEVICE_NAME="HP ZGX Nano"', dockerfile))  # default when unset
        self.assertIn('AWARECARE_ORIGIN=""', dockerfile)
        self.assertIn("AWARECARE_PRESENTER_ENABLED=0", dockerfile)
        self.assertIn("AWARECARE_WEB_BIND=127.0.0.1", dockerfile)
        default = (ROOT / "apps/web/public/aware-care-device.js").read_text()
        self.assertIn('name: "HP ZGX Nano"', default)

    def test_461_both_device_scripts_name_the_configured_address_and_only_a_plain_one(self):
        """#461/#487: a refused address (ORIGIN_REJECTED) names the address the device is configured for: the device
        script carries `origin` from the deploy configuration (a validated plain origin), empty by default in the image,
        with or without presenter access."""
        for with_presenter in (False, True):
            with self.subTest(presenter=with_presenter):
                web_call = self.start(NANO, with_presenter)[1]
                self.assertIn(f"AWARECARE_ORIGIN={NANO['network']['browser_origin']}", web_call)


if __name__ == "__main__":
    unittest.main()
