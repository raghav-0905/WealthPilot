import pytest
import sys
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.storage import read_state, clear_local_storage, TRACE_DATASET_DIR
from schemas.validate import validate_data

def load_actor_module(actor_dir_name: str):
    actor_path = PROJECT_ROOT / "actors" / actor_dir_name / "src" / "main.py"
    spec = importlib.util.spec_from_file_location(actor_dir_name.replace("-", "_"), actor_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

strategy_mod = load_actor_module("wp-strategy")
evaluator_mod = load_actor_module("wp-evaluator")
orchestrator_mod = load_actor_module("wp-orchestrator")
execution_monitor_mod = load_actor_module("wp-execution-monitor")

@pytest.fixture(autouse=True)
def clean_storage():
    clear_local_storage()
    yield
    clear_local_storage()

def test_scenario_001_end_to_end():
    """
    Validates complete Scenario 001 execution:
    - Planning
    - Context reconciliation
    - Research targeting
    - Initial strategy generation (S1-S4)
    - Tax veto on S1
    - Replanning with constraints and harvesting
    - Evaluator scoring and ranking
    - Arbitration of AIF lock-in vs 2-year liquidity goal
    - Final report generation and schema conformance
    """
    report = orchestrator_mod.run_orchestrator({
        "clientId": "CLIENT_001",
        "goal": "Reduce concentration in my own company stock tax-efficiently; need ₹2 Cr liquidity in 2 years.",
        "maxRevisionRounds": 3
    })

    # 1. Validate schema conformance
    assert validate_data(report, "FinalReport") is True
    assert report["clientId"] == "CLIENT_001"
    assert len(report["rankedOptions"]) >= 2

    # 2. Assert Replanning occurred
    replans = report["taskGraph"].get("replans", [])
    assert len(replans) >= 1, "Expected at least 1 replan triggered by Tax veto"
    assert "TAX_VETO" in replans[0]["trigger"]

    # 3. Assert Arbitration occurred
    arbitrations = report["arbitrationLog"]
    assert len(arbitrations) >= 1, "Expected at least 1 logged arbitration decision"
    assert "liquidity" in arbitrations[0]["conflict"].lower() or "lock-in" in arbitrations[0]["conflict"].lower()

    # 4. Assert Top Recommendation is S2
    top_option = report["rankedOptions"][0]
    assert top_option["id"] == "S2"
    assert top_option["rank"] == 1
    assert top_option["totalScore"] >= 0.75

    # 5. Assert S1 was rejected
    assert "S1" not in [r["id"] for r in report["rankedOptions"]]
    assert "S1" in report["explanation"]

def test_strategy_regeneration_on_constraints():
    """Verifies that wp-strategy produces distinct candidates and respects veto constraints."""
    # Initial run: generates 4 candidates including aggressive S1
    initial = strategy_mod.run_strategy({"clientId": "CLIENT_001"})
    assert len(initial) == 4
    for c in initial:
        assert validate_data(c, "CandidateStrategy") is True
    assert "S1" in [c["id"] for c in initial]

    # Regenerated run with constraint: excludes S1, produces revised compliant strategies
    constraints = ["Limit sale of PROMOTER_CO to ₹2.0 Cr in FY; remainder next FY"]
    revised = strategy_mod.run_strategy({
        "clientId": "CLIENT_001",
        "constraints": constraints,
        "harvestingOpportunities": [{"lot": "CLEANTECH_SOL", "lossINR": 1250000}]
    })
    assert len(revised) >= 3
    for c in revised:
        assert validate_data(c, "CandidateStrategy") is True
    assert "S1" not in [c["id"] for c in revised]
    
    # Check that S2 incorporates tax-loss harvesting
    s2 = next(c for c in revised if c["id"] == "S2")
    assert any(a["asset"] == "CLEANTECH_SOL" for a in s2["actions"])

def test_evaluator_independent_scoring_and_rejection():
    """Verifies wp-evaluator scores candidates and rejects non-compliant proposals."""
    candidates = strategy_mod.run_strategy({"clientId": "CLIENT_001"})
    eval_res = evaluator_mod.run_evaluator({
        "clientId": "CLIENT_001",
        "candidates": candidates
    })
    assert validate_data(eval_res, "EvaluationResult") is True

    # S1 should be rejected due to tax impact / compliance
    rejected_ids = [r["id"] for r in eval_res["rejected"]]
    assert "S1" in rejected_ids

    # Ranked options should have per-criterion scores
    ranked_ids = [r["id"] for r in eval_res["ranking"]]
    assert "S2" in ranked_ids
    for r in eval_res["ranking"]:
        assert 0.0 <= r["totalScore"] <= 1.0
        assert "postTaxReturn" in r["criteria"]
        assert "liquidity" in r["criteria"]
        assert len(r["justification"]) > 0

def test_execution_monitor_human_gate_and_events():
    """Verifies human-in-the-loop gate, simulated trades, drift check, and trigger events."""
    # 1. Unapproved: must be blocked by human gate
    blocked = execution_monitor_mod.run_execution_monitor({
        "clientId": "CLIENT_001",
        "approved": False
    })
    assert blocked["status"] == "AWAITING_APPROVAL"
    assert len(blocked["executionLog"]) == 0

    # 2. Approved: executes trades and monitors events
    approved_run = execution_monitor_mod.run_execution_monitor({
        "clientId": "CLIENT_001",
        "approved": True
    })
    assert approved_run["status"] == "EXECUTED_AND_MONITORING"
    assert len(approved_run["executionLog"]) >= 4
    for trade in approved_run["executionLog"]:
        assert trade["status"] == "FILLED"
        assert trade["orderId"].startswith("ORD_")

    # 3. Sentinel must detect EVT_001 promoter pledge increase and request Orchestrator re-engagement
    reengage = approved_run.get("reengageRequest")
    assert reengage is not None
    assert reengage["reengageRequired"] is True
    assert reengage["eventId"] == "EVT_001"
    assert reengage["affectedIssuer"] == "PROMOTER_CO"
