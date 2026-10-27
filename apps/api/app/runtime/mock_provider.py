"""Mock fixture adapter behind the RuntimeAdapter interface (mock mode only).

Returns scripted synthetic candidates selected by the case's explicit fixture
scenario. It never contacts ZRT or any network service and never assesses free
text. Output is still validated by the owning guidance service.
"""
from __future__ import annotations

from typing import Any, Mapping

from app.core.fixtures import FixturePack
from app.runtime.adapter import RuntimeHealth

ADAPTER_VERSION = "mock-fixture-adapter-1"


class MockGenerationFailure(RuntimeError):
    """Typed scripted failure for the `failure` fixture scenario."""

    code = "GENERATION_FAILED"


class MockRuntimeAdapter:
    def __init__(self, fixtures: FixturePack):
        self._fixtures = fixtures

    async def generate_json(self, task: str, prompt_version: str, input_snapshot: Mapping[str, Any],
                            schema_id: str, timeout_s: float) -> Mapping[str, Any]:
        if task != "guidance" or schema_id != "GuidanceCandidate":
            raise MockGenerationFailure("unsupported mock task")
        scenario = self._fixtures.scenarios[input_snapshot["scenario_id"]]
        outcomes = scenario.get("generation_outcomes")
        if outcomes and outcomes[0] == "scripted_failure" and input_snapshot["attempt"] == 1:
            raise MockGenerationFailure("scripted failure")
        selfcare = scenario["id"] == "selfcare"
        return {
            "urgency_level": "self_care_candidate" if selfcare else "routine_clinician",
            "reason_codes": [f"MOCK_SCENARIO_{scenario['id'].upper()}", "SYNTHETIC_NOT_CLINICALLY_REVIEWED"],
            "outcome_title": scenario["result"],
            "action": {
                "category": "self_care" if selfcare else "discuss_with_clinician",
                "text": ("Review the illustrative self-care screen; seek care if anything changes or worsens."
                         if selfcare else "Consider a primary care conversation about this concern."),
                "rationale": "Scripted synthetic fixture outcome selected by the demo scenario, not a medical analysis.",
            },
            # ADR-015: mock mode shows a scripted, illustrative explanation (labelled as scripted in A07).
            "possible_explanation": ("Scripted illustrative explanation: everyday factors such as workload, sleep and "
                                     "posture can contribute to concerns like this one."),
            "clinician_questions": [
                "What details would help you understand this concern?",
                "What should I track before a follow-up visit?",
            ],
            "escalation_advice": [
                "If symptoms become severe or you are worried about your safety, contact emergency services.",
            ],
        }

    async def health(self) -> RuntimeHealth:
        return {"status": "ready", "provider": "mock", "model_id": None, "reason_code": "SYNTHETIC_FIXTURES"}

    async def manifest(self) -> Mapping[str, Any]:
        return {"manifest_id": None, "adapter_version": ADAPTER_VERSION,
                "fixture_version": self._fixtures.fixture_version, "model": None}
