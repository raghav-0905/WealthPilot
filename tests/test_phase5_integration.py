import pytest
import sys
import importlib.util
from pathlib import Path
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACTOR_TAX_SRC = PROJECT_ROOT / "actors" / "wp-tax-compliance" / "src"
for p in (PROJECT_ROOT, ACTOR_TAX_SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from shared.storage import clear_local_storage, TRACE_DATASET_DIR
from schemas.validate import validate_data
from tax_calculator import (
    calc_ltcg,
    calc_stcg,
    calc_surcharge,
    find_harvestable_lots,
    check_suitability
)

def load_actor_module(actor_dir_name: str):
    actor_path = PROJECT_ROOT / "actors" / actor_dir_name / "src" / "main.py"
    spec = importlib.util.spec_from_file_location(actor_dir_name.replace("-", "_"), actor_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

client_context_mod = load_actor_module("wp-client-context")
research_policy_mod = load_actor_module("wp-research-policy")
strategy_mod = load_actor_module("wp-strategy")
tax_compliance_mod = load_actor_module("wp-tax-compliance")
evaluator_mod = load_actor_module("wp-evaluator")
orchestrator_mod = load_actor_module("wp-orchestrator")
execution_monitor_mod = load_actor_module("wp-execution-monitor")

@pytest.fixture(autouse=True)
def clean_storage():
    clear_local_storage()
    yield
    clear_local_storage()

# ==============================================================================
# 1. Tax Calculator Boundary & Surcharge Cliff Tests
# ==============================================================================

def test_surcharge_equity_gain_cap_section_112a():
    """
    Verifies that Section 112A equity LTCG surcharge is capped at 15%,
    even when total capital gains exceed ₹2 Crore or ₹5 Crore.
    """
    base_tax = 1000000.0  # ₹10 Lakhs base tax
    
    # Tier 1: Gains <= 50L -> 0% surcharge
    res_below_50l = calc_surcharge(total_income=4000000.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert res_below_50l["effectiveSurchargeRatePct"] == 0.0
    assert res_below_50l["cessAmount"] == base_tax * 0.04

    # Tier 2: 50L < Gains <= 1 Cr -> 10% surcharge
    res_50l_to_1cr = calc_surcharge(total_income=7500000.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert res_50l_to_1cr["effectiveSurchargeRatePct"] == 10.0

    # Tier 3: 1 Cr < Gains <= 2 Cr -> 15% surcharge
    res_1cr_to_2cr = calc_surcharge(total_income=15000000.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert res_1cr_to_2cr["effectiveSurchargeRatePct"] == 15.0

    # Tier 4: Gains > 2 Cr -> MUST be capped at 15% for equity gains under Section 112A
    res_above_2cr_equity = calc_surcharge(total_income=30000000.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert res_above_2cr_equity["effectiveSurchargeRatePct"] == 15.0, "Equity gains must be capped at 15% surcharge"

    # For general (non-equity) income above ₹2 Cr, surcharge escalates to 25%
    res_above_2cr_general = calc_surcharge(total_income=30000000.0, base_tax=base_tax, is_equity_capital_gain=False)
    assert res_above_2cr_general["effectiveSurchargeRatePct"] == 25.0, "General income should reach 25% surcharge"

def test_ltcg_holding_period_threshold_and_exemption():
    """Verifies listed equity LTCG vs STCG boundaries and the ₹1.25L Section 112A exemption."""
    sale_value = 1000000.0
    cost_basis = 500000.0
    gain = 500000.0

    # Below 12 months -> STCG at 20%
    stcg_tax = calc_stcg(sale_value, cost_basis, "listed_equity")
    assert stcg_tax == gain * 0.20

    # At or above 12 months -> LTCG at 12.5% on gains exceeding ₹1.25 Lakhs
    ltcg_tax = calc_ltcg(sale_value, cost_basis, "listed_equity", holding_period_months=12)
    expected_taxable = gain - 125000.0
    expected_tax = expected_taxable * 0.125
    assert ltcg_tax == expected_tax

def test_tax_loss_harvesting_edge_cases():
    """Verifies harvesting detection on loss lots and graceful handling of all-gain portfolios."""
    # Portfolio with losses
    holdings_with_loss = [
        {"issuer": "TECH_WINNER", "valueINR": 5000000.0, "unrealized_pnl": 2000000.0},
        {"issuer": "LOSER_CO", "valueINR": 1000000.0, "unrealized_pnl": -1500000.0}
    ]
    lots = find_harvestable_lots(holdings_with_loss)
    assert len(lots) == 1
    assert lots[0]["lot"] == "LOSER_CO"
    assert lots[0]["lossINR"] == 1500000.0

    # Portfolio with only profitable lots
    holdings_all_profit = [
        {"issuer": "STOCK_A", "valueINR": 2000000.0, "unrealized_pnl": 1000000.0},
        {"issuer": "STOCK_B", "valueINR": 3000000.0, "unrealized_pnl": 500000.0}
    ]
    no_lots = find_harvestable_lots(holdings_all_profit)
    assert len(no_lots) == 0

# ==============================================================================
# 2. Multi-Currency Normalization & Client Context Reconciliation
# ==============================================================================

def test_client_context_currency_conversion():
    """Verifies that foreign currency assets are normalized to INR using static FX rates."""
    ctx = client_context_mod.run_client_context({"clientId": "CLIENT_001"})
    assert validate_data(ctx, "ClientContext") is True

    # Check for foreign asset in CLIENT_001 (e.g. US Equity / USD denominated)
    holdings = ctx["holdings"]
    usd_holding = next((h for h in holdings if "USD" in h.get("issuer", "") or "GLOBAL" in h.get("issuer", "") or h.get("assetClass") == "international_equity"), None)
    if usd_holding:
        assert usd_holding["valueINR"] > 0
        assert usd_holding["valueINR"] >= 6000000.0

    assert ctx["netWorthINR"] >= 100000000.0

# ==============================================================================
# 3. Multi-Round Replanning Resilience & Revision Limits
# ==============================================================================

def test_orchestrator_max_revision_rounds_bound():
    """Verifies that orchestrator never loops indefinitely and respects maxRevisionRounds."""
    report = orchestrator_mod.run_orchestrator({
        "clientId": "CLIENT_001",
        "goal": "Rebalance portfolio",
        "maxRevisionRounds": 1
    })

    assert validate_data(report, "FinalReport") is True
    task_graph = report["taskGraph"]
    assert task_graph["revisionRounds"] <= 1
    assert len(task_graph["replans"]) <= 1

def test_orchestrator_preserves_ranked_candidates_after_replan():
    """Verifies that all candidates in rankedOptions are compliant and properly scored."""
    report = orchestrator_mod.run_orchestrator({
        "clientId": "CLIENT_001",
        "goal": "Tax efficient exit",
        "maxRevisionRounds": 3
    })

    ranked = report["rankedOptions"]
    assert len(ranked) >= 2
    for r in ranked:
        assert r["totalScore"] > 0.0
        assert r["rank"] >= 1
        assert "postTaxReturn" in r["criteria"]

    # S1 was vetoed, so must not appear in recommendations
    assert "S1" not in [r["id"] for r in ranked]

# ==============================================================================
# 4. Human Approval Gating & Execution Sentinel Trigger Events
# ==============================================================================

def test_execution_monitor_blocks_unapproved_trades():
    """Verifies that trade execution is strictly gated behind advisor approval."""
    unapproved = execution_monitor_mod.run_execution_monitor({
        "clientId": "CLIENT_001",
        "approved": False
    })
    assert unapproved["status"] == "AWAITING_APPROVAL"
    assert len(unapproved["executionLog"]) == 0

def test_execution_monitor_sentinel_detects_promoter_pledge_spike():
    """Verifies that monitoring sentinel flags EVT_001 trigger event and requests re-engagement."""
    approved = execution_monitor_mod.run_execution_monitor({
        "clientId": "CLIENT_001",
        "approved": True
    })
    assert approved["status"] == "EXECUTED_AND_MONITORING"
    assert len(approved["executionLog"]) > 0

    reengage = approved.get("reengageRequest")
    assert reengage is not None
    assert reengage["reengageRequired"] is True
    assert reengage["eventId"] == "EVT_001"
    assert reengage["affectedIssuer"] == "PROMOTER_CO"

# ==============================================================================
# 5. Full Pipeline Cross-Actor Contract & Trace Integrity
# ==============================================================================

def test_cross_actor_trace_entries_schema_validity():
    """Verifies that every trace entry logged during full pipeline execution conforms to TraceEntry schema."""
    clear_local_storage()
    orchestrator_mod.run_orchestrator({
        "clientId": "CLIENT_001",
        "goal": "Comprehensive portfolio advisory",
        "maxRevisionRounds": 3
    })

    trace_files = list(TRACE_DATASET_DIR.glob("*.json"))
    assert len(trace_files) >= 15, "Expected substantial trace generation across specialist actors"

    import json
    for tf in trace_files:
        with open(tf, "r", encoding="utf-8") as f:
            entry = json.load(f)
            assert validate_data(entry, "TraceEntry") is True
            assert "actor" in entry
            assert "thought" in entry
            assert "tool" in entry
            assert "result_summary" in entry
