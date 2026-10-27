"""ZRT adapter behind the RuntimeAdapter interface (local mode only).

Talks only to the configured loopback OpenAI-compatible ZRT endpoint. There is
no fallback provider: transport, timeout and parse failures raise typed errors.
The owning service still runs schema, support, urgency and revision checks.
Clinical generation stays gated off until reviewed pathways/corpus exist.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping

import httpx

from app.runtime.adapter import RuntimeHealth
from app.runtime.metering import token_count
from pathlib import Path

from app.runtime.model_ids import ServedMatch, find_served, manifest_ref, selected_manifest, served_ids_from

REPO_ROOT = Path(__file__).resolve().parents[4]  # the repository (or the image's /srv/aware-care)

ADAPTER_VERSION = "zrt-adapter-1"


class RuntimeTransportError(RuntimeError):
    code = "MODEL_UNAVAILABLE"


class RuntimeOutputError(RuntimeError):
    code = "MODEL_OUTPUT_INVALID"


class RuntimeTimeoutError(RuntimeTransportError):
    """#550: the model did not answer within the call's time; a typed reason, not "unavailable"."""
    code = "TIMEOUT"


# #550: every request asks for the qualified chat-template setting itself, thinking off (ADR-002), instead of relying on
# the server's `--default-chat-template-kwargs`. A server started without it (the manager's Z8 serves
# `Qwen/Qwen3.6-35B-A3B-FP8@main` with its own settings) has the model think first: measured on the Nano with
# thinking on, the red-flag screen spent 441 reasoning tokens (7.5 s) and then answered `{}`, so every Quick flow
# failed as "guidance failed" (evidence/clinical-review/2026-10-26-selfcare-speed/). With the server's default already
# off, the request is the same prompt and the output is identical.
CHAT_TEMPLATE_KWARGS = {"enable_thinking": False}
# #551: an upper bound on each task's output tokens, about twice the longest output seen on the Nano (guidance 1113,
# certainty review 218, red-flag screen 20, concern check 8 tokens over 7,900 calls). It never shortens a real answer;
# it stops a runaway generation (a repetition loop) long before the deadline, and a cut-off answer is non-JSON, which
# fails closed as MODEL_OUTPUT_INVALID like any other invalid output.
MAX_TOKENS = {"guidance": 2048, "certainty_review": 512, "red_flag_screen": 256, "concern_check": 64}
DEFAULT_MAX_TOKENS = 2048


class ZrtRuntimeAdapter:
    def __init__(self, base_url: str, model_id: str | None, manifest_path, catalog_path=None):
        self._base_url = base_url
        self._model_id = model_id
        self._manifest_path = manifest_path
        self._catalog_path = catalog_path  # #537: the manifest of another catalogue model, selected by its label
        self._repository = _manifest_repository(self._read_manifest(), model_id)
        # #528: the ID ZRT actually serves this model under (our label, the repository id, with any revision);
        # requests use it. Found by health() or the first request, forgotten when a request fails.
        self._served: ServedMatch | None = None

    async def _served_model(self, client: httpx.AsyncClient) -> ServedMatch | None:
        response = await client.get(f"{self._base_url}/models")
        response.raise_for_status()
        self._served = find_served(served_ids_from(response.json()), self._model_id or "", self._repository)
        return self._served

    async def generate_json(self, task: str, prompt_version: str, input_snapshot: Mapping[str, Any],
                            schema_id: str, timeout_s: float) -> Mapping[str, Any]:
        output, _ = await self.generate_json_with_usage(task, prompt_version, input_snapshot, schema_id, timeout_s)
        return output

    async def generate_json_with_usage(self, task: str, prompt_version: str, input_snapshot: Mapping[str, Any],
                                       schema_id: str, timeout_s: float
                                       ) -> tuple[Mapping[str, Any], dict[str, int | None]]:
        """As generate_json, plus the token counts ZRT reports (`usage`), for the content-free telemetry (ADR-017)."""
        if not self._model_id:
            raise RuntimeTransportError("model id not configured")
        payload = {
            "model": None,
            "messages": [
                {"role": "system", "content": f"Task {task} prompt {prompt_version}. Return only JSON for {schema_id}."},
                {"role": "user", "content": json.dumps(input_snapshot)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": MAX_TOKENS.get(task, DEFAULT_MAX_TOKENS),
            "chat_template_kwargs": CHAT_TEMPLATE_KWARGS,
        }
        try:
            # #585: `timeout_s` is the call's total time. httpx applies its timeout to each operation (connect, each
            # read, ...), so model discovery plus the completion, or a body that keeps trickling in, could run past it.
            async with asyncio.timeout(timeout_s):
                async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
                    served = self._served or await self._served_model(client)
                    payload["model"] = served.served_id if served else self._model_id
                    response = await client.post(f"{self._base_url}/chat/completions", json=payload)
                    response.raise_for_status()
                    body = response.json()
                    content = body["choices"][0]["message"]["content"]
                    reported = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise RuntimeTimeoutError("zrt request timed out") from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            self._served = None  # ZRT may have been restarted under another name
            raise RuntimeTransportError("zrt request failed") from exc
        try:
            parsed = json.loads(_without_thinking(content))
        except (TypeError, ValueError) as exc:
            raise RuntimeOutputError("zrt returned non-JSON content") from exc
        if not isinstance(parsed, dict):
            raise RuntimeOutputError("zrt returned non-object JSON")
        # #605: a malformed optional count (negative, oversized, boolean) is unknown; the answer itself is unchanged.
        usage = {k: token_count(reported.get(k)) for k in ("prompt_tokens", "completion_tokens")}
        return parsed, usage

    async def health(self) -> RuntimeHealth:
        if not self._model_id:
            return {"status": "unavailable", "provider": "zrt", "model_id": None, "reason_code": "MODEL_ID_UNSET"}
        try:
            async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
                served = await self._served_model(client)
        except (httpx.HTTPError, ValueError, AttributeError):
            self._served = None
            return {"status": "unavailable", "provider": "zrt", "model_id": self._model_id,
                    "reason_code": "ENDPOINT_UNREACHABLE"}
        if served is None:  # only an entirely different model; another revision or name of it is ready
            return {"status": "unavailable", "provider": "zrt", "model_id": self._model_id,
                    "reason_code": "MODEL_NOT_SERVED"}
        return {"status": "ready", "provider": "zrt", "model_id": served.served_id, "reason_code": None}

    def _read_manifest(self) -> dict:
        return selected_manifest(Path(self._manifest_path), Path(self._catalog_path) if self._catalog_path else None,
                                 self._model_id, REPO_ROOT)

    async def manifest(self) -> Mapping[str, Any]:
        manifest = self._read_manifest()
        return {"manifest_id": manifest.get("manifest_id"), "adapter_version": ADAPTER_VERSION,
                "model": manifest.get("model")}


def _without_thinking(content: object) -> object:
    """#550: the answer after a leading `<think>...</think>` block, for a server whose chat template ignores the
    thinking switch and has no reasoning parser; any other content is returned unchanged."""
    if isinstance(content, str) and content.lstrip().startswith("<think>") and "</think>" in content:
        return content.split("</think>", 1)[1]
    return content


def _manifest_repository(manifest: dict, model_id: str | None) -> str | None:
    """The manifest's Hugging Face repository (with its qualified revision) when it describes the configured model."""
    try:
        return manifest_ref(manifest, model_id)
    except (AttributeError, TypeError):
        return None
