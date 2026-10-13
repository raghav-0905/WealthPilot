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

from shared.storage import clear_local_storage
from schemas.validate import validate_data
from tax_calculator import (
    calc_ltcg,
    calc_stcg,
    calc_surcharge,
    find_harvestable_lots,
    check_lrs_limit,
    check_suitability
)

def load_actor_module(actor_dir_name: str):
    actor_path = PROJECT_ROOT / "actors" / actor_dir_name / "src" / "main.py"
    spec = importlib.util.spec_from_file_location(actor_dir_name.replace("-", "_"), actor_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

orchestrator_mod = load_actor_module("wp-orchestrator")
evaluator_mod = load_actor_module("wp-evaluator")
tax_compliance_mod = load_actor_module("wp-tax-compliance")
client_context_mod = load_actor_module("wp-client-context")

@pytest.fixture(autouse=True)
def clean_storage():
    clear_local_storage()
    yield
    clear_local_storage()

# ==============================================================================
# 1. Exact Threshold Boundary Surcharge Tests
# ==============================================================================

def test_surcharge_exact_threshold_boundaries():
    """Tests exact edge boundaries of income surcharge slabs (50L, 1Cr, 2Cr, 5Cr)."""
    base_tax = 100000.0

    # Exactly ₹50,00,000 -> 0% surcharge
    r1 = calc_surcharge(total_income=5000000.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert r1["effectiveSurchargeRatePct"] == 0.0

    # Exactly ₹50,00,001 -> 10% surcharge
    r2 = calc_surcharge(total_income=5000001.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert r2["effectiveSurchargeRatePct"] == 10.0

    # Exactly ₹1,00,00,000 -> 10% surcharge
    r3 = calc_surcharge(total_income=10000000.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert r3["effectiveSurchargeRatePct"] == 10.0

    # Exactly ₹1,00,00,001 -> 15% surcharge
    r4 = calc_surcharge(total_income=10000001.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert r4["effectiveSurchargeRatePct"] == 15.0

    # Exactly ₹2,00,00,000 -> 15% surcharge
    r5 = calc_surcharge(total_income=20000000.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert r5["effectiveSurchargeRatePct"] == 15.0

    # Exactly ₹2,00,00,001:
    # Equity gain remains capped at 15%
    r6_eq = calc_surcharge(total_income=20000001.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert r6_eq["effectiveSurchargeRatePct"] == 15.0
    # General income escalates to 25%
    r6_gen = calc_surcharge(total_income=20000001.0, base_tax=base_tax, is_equity_capital_gain=False)
    assert r6_gen["effectiveSurchargeRatePct"] == 25.0

    # Exactly ₹5,00,00,000 general income -> 25% surcharge
    r7_gen = calc_surcharge(total_income=50000000.0, base_tax=base_tax, is_equity_capital_gain=False)
    assert r7_gen["effectiveSurchargeRatePct"] == 25.0

    # Exactly ₹5,00,00,001 general income -> 37% surcharge
    r8_gen = calc_surcharge(total_income=50000001.0, base_tax=base_tax, is_equity_capital_gain=False)
    assert r8_gen["effectiveSurchargeRatePct"] == 37.0

# ==============================================================================
# 2. Section 112A LTCG Exemption & Holding Period Boundaries
# ==============================================================================

def test_ltcg_annual_exemption_cliff():
    """Tests the ₹1,25,000 Section 112A LTCG exemption threshold."""
    cost = 1000000.0

    # Gain exactly ₹1,24,999 -> Below exemption -> 0 tax
    tax_below = calc_ltcg(sale_amount=cost + 124999.0, cost_basis=cost, asset_class="listed_equity", holding_period_months=24)
    assert tax_below == 0.0

    # Gain exactly ₹1,25,000 -> At exemption -> 0 tax
    tax_exact = calc_ltcg(sale_amount=cost + 125000.0, cost_basis=cost, asset_class="listed_equity", holding_period_months=24)
    assert tax_exact == 0.0

    # Gain exactly ₹1,25,008 -> Taxable = 8 -> 8 * 0.125 = 1.0 tax
    tax_above = calc_ltcg(sale_amount=cost + 125008.0, cost_basis=cost, asset_class="listed_equity", holding_period_months=24)
    assert tax_above == 1.0

def test_ltcg_holding_period_boundary_validation():
    """Tests that holding period below 12 months is rejected by calc_ltcg."""
    # 11 months -> Invalid for LTCG
    with pytest.raises(ValueError, match="less than 12m required"):
        calc_ltcg(sale_amount=2000000.0, cost_basis=1000000.0, asset_class="listed_equity", holding_period_months=11)

    # 12 months -> Valid
    tax_12m = calc_ltcg(sale_amount=2000000.0, cost_basis=1000000.0, asset_class="listed_equity", holding_period_months=12)
    assert tax_12m > 0

def test_zero_gain_and_capital_loss_tax():
    """Verifies that sales at zero gain or at a loss result in 0 tax."""
    # Zero gain
    tax_zero_gain = calc_stcg(sale_amount=500000.0, cost_basis=500000.0, asset_class="listed_equity")
    assert tax_zero_gain == 0.0

    # Loss
    tax_loss = calc_stcg(sale_amount=400000.0, cost_basis=500000.0, asset_class="listed_equity")
    assert tax_loss == 0.0

# ==============================================================================
# 3. RBI LRS Ceilings & TCS 20% Thresholds
# ==============================================================================

def test_lrs_remittance_limits_boundary():
    """Tests RBI LRS USD 250,000 annual ceiling boundary."""
    # Exactly at limit
    res_at_limit = check_lrs_limit(amount_usd=200000.0, already_remitted_usd=50000.0)
    assert res_at_limit["compliant"] is True
    assert res_at_limit["exceedsLimit"] is False
    assert res_at_limit["totalRemittedUSD"] == 250000.0

    # 1 dollar over limit
    res_over_limit = check_lrs_limit(amount_usd=200001.0, already_remitted_usd=50000.0)
    assert res_over_limit["compliant"] is False
    assert res_over_limit["exceedsLimit"] is True
    assert res_over_limit["totalRemittedUSD"] == 250001.0

def test_lrs_tcs_threshold_boundary():
    """Tests TCS applicability on foreign remittances above ₹7,00,000 threshold."""
    # Small remittance below ₹7L threshold (~₹4.15L) -> 0 TCS
    res_small = check_lrs_limit(amount_usd=5000.0, already_remitted_usd=0.0)
    assert res_small["estimatedTCS_INR"] == 0.0

    # Remittance exceeding ₹7,00,000 threshold (e.g. $50,000 = ~₹41.5L)
    res_large = check_lrs_limit(amount_usd=50000.0, already_remitted_usd=0.0)
    assert res_large["tcsRatePct"] == 20.0
    assert res_large["estimatedTCS_INR"] > 0.0

# ==============================================================================
# 4. Agentic Revision Budget & Edge Input Tests
# ==============================================================================

def test_orchestrator_zero_revision_budget():
    """Verifies orchestrator completes even if maxRevisionRounds is 0."""
    report = orchestrator_mod.run_orchestrator({
        "clientId": "CLIENT_001",
        "goal": "Rebalance portfolio",
        "maxRevisionRounds": 0
    })
    assert validate_data(report, "FinalReport") is True
    assert report["taskGraph"]["revisionRounds"] == 0

def test_evaluator_handles_empty_candidates():
    """Verifies that wp-evaluator handles an empty candidates list gracefully."""
    res = evaluator_mod.run_evaluator({
        "clientId": "CLIENT_001",
        "candidates": []
    })
    assert validate_data(res, "EvaluationResult") is True
    assert len(res["ranking"]) == 0
    assert len(res["rejected"]) == 0

def test_tax_compliance_handles_empty_actions_proposal():
    """Verifies that proposal with zero actions is approved with zero tax."""
    empty_prop = {
        "id": "S_EMPTY",
        "name": "No Actions Strategy",
        "actions": []
    }
    verdict = tax_compliance_mod.run_tax_compliance({
        "clientId": "CLIENT_001",
        "proposal": empty_prop
    })
    assert validate_data(verdict, "TaxVerdict") is True
    assert verdict["verdict"] in ["APPROVE", "APPROVE_WITH_CONDITIONS"]
    assert verdict["estimatedTaxINR"] == 0.0

def test_suitability_check_blocks_locked_aif_liquidation():
    """Verifies suitability check blocks liquidation of locked-in Category II AIF holdings."""
    proposal_with_aif_exit = {
        "id": "S_BAD_AIF",
        "actions": [
            {
                "type": "SELL",
                "asset": "STELLAR_INDIA_CREDIT_AIF",
                "assetClass": "aif",
                "amountINR": 5000000.0,
                "holdingPeriodMonths": 12 # Less than mandatory 36m lock-in
            }
        ]
    }
    res = check_suitability(proposal_with_aif_exit, risk_profile="moderate")
    assert res["passed"] is False
    assert any("lock-in" in v.lower() for v in res["violations"])
