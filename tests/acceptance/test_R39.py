"""R39 demo metrics stay separate from outcome evidence: the W06 telemetry reports measurements, reviewed prices and
assumptions, and never a healthcare saving (ADR-017). M12."""
REQUIREMENT = "R39"


def test_outcomes_stay_not_measured_and_no_savings_figure_is_reported(api):
    t = api.ok("GET", "/telemetry", 200, "TelemetrySnapshot")
    assert t["outcomes"]["status"] == "NOT_MEASURED"
    flat = str(t).lower()
    assert "avoided_visits" not in flat and "savings" not in [k.lower() for k in t]


def test_estimates_rest_on_reviewed_prices_with_sources_and_dates(api):
    pricing = api.ok("GET", "/telemetry", 200, "TelemetrySnapshot")["pricing"]
    assert pricing["currency"] == "USD"
    refs = pricing["cloud_references"]
    assert {r["comparison"] for r in refs} == {"like_for_like", "frontier"}
    assert sum(r["default"] for r in refs) == 1
    for r in refs:
        assert r["source_url"].startswith("https://") and r["retrieved"] and r["input_usd_per_mtok"] > 0
    for key in ("device_price_usd", "electricity_usd_per_kwh"):
        assert pricing["assumptions"][key]["source_url"].startswith("https://")
        assert pricing["assumptions"][key]["retrieved"]


def test_privacy_facts_report_no_patient_data_and_no_cloud_call(api):
    privacy = api.ok("GET", "/telemetry", 200, "TelemetrySnapshot")["privacy"]
    assert privacy["patient_data_sent_off_device_bytes"] == 0 and privacy["cloud_inference_calls"] == 0


def test_two_frontier_references_and_a_labeled_system_power_assumption(api):
    """#127: GPT-6 Astra joins Claude Sonnet 5.5 as a frontier reference; whole-system power is an assumption (0 W by
    default) because the Nano reports GPU power only."""
    pricing = api.ok("GET", "/telemetry", 200, "TelemetrySnapshot")["pricing"]
    frontier = {r["model"]: r for r in pricing["cloud_references"] if r["comparison"] == "frontier"}
    assert set(frontier) == {"claude-sonnet-5-5", "gpt-6-astra"}
    gpt = frontier["gpt-6-astra"]
    assert (gpt["input_usd_per_mtok"], gpt["output_usd_per_mtok"]) == (10.0, 50.0)
    assert gpt["source_url"] == "https://developers.openai.com/api/docs/pricing" and gpt["retrieved"] == "2026-10-17"
    power = pricing["assumptions"]["other_system_power_w"]
    assert power["value"] == 0 and "not measured" in power["label"]
