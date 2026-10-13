import pytest
import sys
import json
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.storage import clear_local_storage, TRACE_DATASET_DIR, KV_STORE_DIR
from schemas.validate import validate_data

def load_actor_module(actor_dir_name: str):
    actor_path = PROJECT_ROOT / "actors" / actor_dir_name / "src" / "main.py"
    spec = importlib.util.spec_from_file_location(actor_dir_name.replace("-", "_"), actor_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

orchestrator_mod = load_actor_module("wp-orchestrator")
execution_monitor_mod = load_actor_module("wp-execution-monitor")

@pytest.fixture(autouse=True)
def clean_storage():
    clear_local_storage()
    yield
    clear_local_storage()

# ==============================================================================
# End-to-End Multi-Scenario Comprehensive Matrix
# ==============================================================================

def test_e2e_scenario_001_complete_lifecycle():
    """
    End-to-End Lifecycle for Scenario 001:
    Ingestion -> Exposure Research -> Strategy Gen -> Tax Veto -> Replanning -> Scoring -> Arbitration -> Audit
    """
    input_payload = {
        "clientId": "CLIENT_001",
        "goal": "Reduce concentration in my own company stock tax-efficiently; need ₹2 Cr liquidity in 2 years.",
        "maxRevisionRounds": 3
    }
    report = orchestrator_mod.run_orchestrator(input_payload)

    # 1. FinalReport schema validation
    assert validate_data(report, "FinalReport") is True
    assert report["clientId"] == "CLIENT_001"

    # 2. Replan and Veto presence
    assert len(report["taskGraph"]["replans"]) >= 1
    assert "TAX_VETO" in report["taskGraph"]["replans"][0]["trigger"]

    # 3. Arbitration logged
    assert len(report["arbitrationLog"]) >= 1
    assert "liquidity" in report["arbitrationLog"][0]["conflict"].lower() or "lock-in" in report["arbitrationLog"][0]["conflict"].lower()

    # 4. Top Recommendation is S2
    top_option = report["rankedOptions"][0]
    assert top_option["id"] == "S2"
    assert top_option["rank"] == 1
    assert "S1" not in [r["id"] for r in report["rankedOptions"]]

    # 5. KV store state persistence
    saved_report_file = list(KV_STORE_DIR.glob("*orchestrator_CLIENT_001_final_report*"))
    assert len(saved_report_file) == 1

def test_e2e_scenario_002_complete_lifecycle():
    """
    End-to-End Lifecycle for Scenario 002:
    Ingestion -> NBFC/LRS Research -> Candidate Gen -> Clean Tax Gate -> Scoring -> Audit
    """
    input_payload = {
        "clientId": "CLIENT_002",
        "goal": "De-risk NBFC exposure and diversify globally via RBI LRS window while maintaining wealth compounding.",
        "maxRevisionRounds": 3
    }
    report = orchestrator_mod.run_orchestrator(input_payload)

    # 1. FinalReport schema validation
    assert validate_data(report, "FinalReport") is True
    assert report["clientId"] == "CLIENT_002"

    # 2. Clean approval: zero veto replans
    assert len(report["taskGraph"]["replans"]) == 0

    # 3. All candidates ranked
    ranked_ids = [opt["id"] for opt in report["rankedOptions"]]
    assert "S1_NBFC_ROTATION" in ranked_ids
    assert "S2_LRS_EXPANSION" in ranked_ids
    assert "S3_BALANCED_GROWTH" in ranked_ids
    assert report["rankedOptions"][0]["id"] == "S1_NBFC_ROTATION"

    # 4. Explanation contains verified compliance
    assert "Verified compliance" in report["explanation"]

def test_e2e_scenario_001_tight_revision_budget():
    """
    Verifies that system behaves deterministically and terminates safely
    when revision budget is strictly constrained (maxRevisionRounds = 1).
    """
    report = orchestrator_mod.run_orchestrator({
        "clientId": "CLIENT_001",
        "goal": "Tax-efficient portfolio restructuring",
        "maxRevisionRounds": 1
    })

    assert validate_data(report, "FinalReport") is True
    assert report["taskGraph"]["revisionRounds"] == 1
    assert len(report["taskGraph"]["replans"]) == 1
    assert len(report["rankedOptions"]) >= 2

def test_e2e_execution_monitor_gating_and_sentinel():
    """
    Verifies the complete execution phase:
    1. Human approval gate strictly blocks unapproved orders.
    2. Approval triggers mock order execution with FILLED status.
    3. Sentinel monitors real-time triggers and flags promoter pledge shock.
    """
    # 1. Unapproved
    blocked = execution_monitor_mod.run_execution_monitor({
        "clientId": "CLIENT_001",
        "approved": False
    })
    assert blocked["status"] == "AWAITING_APPROVAL"
    assert len(blocked["executionLog"]) == 0

    # 2. Approved execution
    executed = execution_monitor_mod.run_execution_monitor({
        "clientId": "CLIENT_001",
        "approved": True
    })
    assert executed["status"] == "EXECUTED_AND_MONITORING"
    assert len(executed["executionLog"]) >= 4
    for order in executed["executionLog"]:
        assert order["status"] == "FILLED"
        assert order["orderId"].startswith("ORD_")
        assert order["amountINR"] > 0
        assert order["fillPercentage"] == 100.0

    # 3. Trigger Sentinel
    sentinel = executed.get("reengageRequest")
    assert sentinel is not None
    assert sentinel["reengageRequired"] is True
    assert sentinel["eventId"] == "EVT_001"
    assert sentinel["affectedIssuer"] == "PROMOTER_CO"

def test_e2e_telemetry_trace_schema_and_confidentiality():
    """
    Validates the complete execution telemetry generated across specialist actors:
    - Asserts schema conformance of every single TraceEntry.
    - Asserts zero unmasked API keys or secrets in logs.
    - Asserts chronological monotonic timestamp sequence.
    """
    clear_local_storage()

    # Run scenario 001 to generate deep traces
    orchestrator_mod.run_orchestrator({
        "clientId": "CLIENT_001",
        "goal": "Audit Telemetry Test",
        "maxRevisionRounds": 3
    })

    trace_files = sorted(TRACE_DATASET_DIR.glob("*.json"))
    assert len(trace_files) >= 15, "Expected multi-actor trace logs"

    timestamps = []
    for tf in trace_files:
        with open(tf, "r", encoding="utf-8") as f:
            entry = json.load(f)
            # Schema contract
            assert validate_data(entry, "TraceEntry") is True

            # Confidentiality: No raw secret keys
            dumped = json.dumps(entry)
            assert "apify_api_" not in dumped or "apify_api_***REDACTED***" in dumped
            assert "gsk_" not in dumped or "gsk_***REDACTED***" in dumped

            timestamps.append(entry["timestamp"])

    # Monotonic timestamps
    assert timestamps == sorted(timestamps)
