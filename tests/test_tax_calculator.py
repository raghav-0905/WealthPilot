import pytest
import sys
from pathlib import Path

# Add project root and actor src to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACTOR_SRC = PROJECT_ROOT / "actors" / "wp-tax-compliance" / "src"
for p in (PROJECT_ROOT, ACTOR_SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tax_calculator import (
    calc_ltcg,
    calc_stcg,
    calc_surcharge,
    find_harvestable_lots,
    check_lrs_limit,
    check_suitability,
    DEFAULT_RULES
)

def test_ltcg_computation_known_inputs():
    # Gain = 10,000,000 - 2,000,000 = 8,000,000
    # Exemption = 125,000 -> Taxable = 7,875,000
    # Rate = 12.5% -> 7,875,000 * 0.125 = 984,375.0
    tax = calc_ltcg(
        sale_amount=10000000.0,
        cost_basis=2000000.0,
        asset_class="listed_equity",
        holding_period_months=24
    )
    assert tax == 984375.0

    # Below exemption threshold -> Tax = 0.0
    tax_small = calc_ltcg(
        sale_amount=200000.0,
        cost_basis=100000.0,
        asset_class="listed_equity",
        holding_period_months=15
    )
    assert tax_small == 0.0

    # No gain / Loss -> Tax = 0.0
    tax_loss = calc_ltcg(
        sale_amount=1000000.0,
        cost_basis=1500000.0,
        asset_class="listed_equity",
        holding_period_months=18
    )
    assert tax_loss == 0.0

    # Holding period less than threshold raises ValueError
    with pytest.raises(ValueError):
        calc_ltcg(
            sale_amount=1000000.0,
            cost_basis=500000.0,
            asset_class="listed_equity",
            holding_period_months=6
        )

def test_stcg_computation_known_inputs():
    # Gain = 5,000,000 - 3,000,000 = 2,000,000
    # Rate = 20.0% -> 2,000,000 * 0.20 = 400,000.0
    tax = calc_stcg(
        sale_amount=5000000.0,
        cost_basis=3000000.0,
        asset_class="listed_equity"
    )
    assert tax == 400000.0

    # Zero gain -> Tax = 0.0
    assert calc_stcg(100000.0, 100000.0, "listed_equity") == 0.0
    assert calc_stcg(100000.0, 150000.0, "listed_equity") == 0.0

def test_surcharge_band_edge_cases():
    base_tax = 100000.0

    # 1. Income <= 50L: 0% surcharge
    res_0 = calc_surcharge(total_income=4500000.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert res_0["effectiveSurchargeRatePct"] == 0.0
    assert res_0["surchargeAmount"] == 0.0
    assert res_0["cessAmount"] == round(base_tax * 0.04, 2)
    assert res_0["totalTax"] == round(base_tax * 1.04, 2)

    # 2. Income 50L - 1Cr: 10% surcharge
    res_10 = calc_surcharge(total_income=7500000.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert res_10["effectiveSurchargeRatePct"] == 10.0
    assert res_10["surchargeAmount"] == 10000.0

    # 3. Income 1Cr - 2Cr: 15% surcharge
    res_15 = calc_surcharge(total_income=15000000.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert res_15["effectiveSurchargeRatePct"] == 15.0
    assert res_15["surchargeAmount"] == 15000.0

    # 4. Income 2Cr - 5Cr (e.g. 3Cr):
    # For equity capital gains (Section 111A/112A), capped at 15.0%
    res_25_capped = calc_surcharge(total_income=30000000.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert res_25_capped["nominalSurchargeRatePct"] == 25.0
    assert res_25_capped["effectiveSurchargeRatePct"] == 15.0

    # For general non-equity income: full 25% applies
    res_25_uncapped = calc_surcharge(total_income=30000000.0, base_tax=base_tax, is_equity_capital_gain=False)
    assert res_25_uncapped["effectiveSurchargeRatePct"] == 25.0

    # 5. Income > 5Cr (e.g. 6Cr):
    # Capped at 15% for equity, 37% for general
    res_37_capped = calc_surcharge(total_income=60000000.0, base_tax=base_tax, is_equity_capital_gain=True)
    assert res_37_capped["effectiveSurchargeRatePct"] == 15.0

    res_37_uncapped = calc_surcharge(total_income=60000000.0, base_tax=base_tax, is_equity_capital_gain=False)
    assert res_37_uncapped["effectiveSurchargeRatePct"] == 37.0

def test_find_harvestable_lots():
    sample_holdings = [
        {"issuer": "WINNER_STOCK", "current_value": 5000000.0, "unrealized_pnl": 1200000.0},
        {"issuer": "CLEANTECH_SOL", "current_value": 2000000.0, "unrealized_pnl": -1250000.0},
        {"issuer": "LOSER_BOND", "current_value": 1000000.0, "unrealized_pnl": -150000.0}
    ]
    lots = find_harvestable_lots(sample_holdings)
    assert len(lots) == 2
    lot_names = [l["lot"] for l in lots]
    assert "CLEANTECH_SOL" in lot_names
    assert "LOSER_BOND" in lot_names

    cleantech = next(l for l in lots if l["lot"] == "CLEANTECH_SOL")
    assert cleantech["lossINR"] == 1250000.0

    # Case with no loss lots
    profitable_only = [{"issuer": "STOCK_A", "unrealized_pnl": 50000.0}]
    assert len(find_harvestable_lots(profitable_only)) == 0

def test_check_lrs_limit():
    # Compliant case within $250k
    res_pass = check_lrs_limit(amount_usd=50000.0, already_remitted_usd=20000.0)
    assert res_pass["compliant"] is True
    assert res_pass["exceedsLimit"] is False
    assert res_pass["totalRemittedUSD"] == 70000.0

    # Exceeds limit
    res_fail = check_lrs_limit(amount_usd=260000.0)
    assert res_fail["compliant"] is False
    assert res_fail["exceedsLimit"] is True

    # TCS calculation above ₹7,00,000 threshold
    # $50,000 = ~₹4,155,844. Amount above ₹700,000 is ~₹3,455,844 * 20% = ~₹691,168
    res_tcs = check_lrs_limit(amount_usd=50000.0, already_remitted_usd=0.0)
    assert res_tcs["estimatedTCS_INR"] > 600000.0
    assert res_tcs["tcsRatePct"] == 20.0

def test_check_suitability():
    # 1. Compliant proposal within ₹2.0 Cr cap
    compliant_proposal = {
        "actions": [
            {"type": "SELL", "asset": "PROMOTER_CO", "amountINR": 18000000.0}
        ]
    }
    res_comp = check_suitability(compliant_proposal, "moderate")
    assert res_comp["passed"] is True
    assert len(res_comp["violations"]) == 0

    # 2. Exceeds ₹2.0 Cr annual exit threshold
    over_limit_proposal = {
        "actions": [
            {"type": "SELL", "asset": "PROMOTER_CO", "amountINR": 27360000.0}
        ]
    }
    res_over = check_suitability(over_limit_proposal, "moderate")
    assert res_over["passed"] is False
    assert any("exceeds maximum recommended annual cap" in v for v in res_over["violations"])

    # 3. Barred premature liquidation of locked-in AIF Cat II
    aif_liquidation = {
        "actions": [
            {"type": "SELL", "asset": "STELLAR_GROWTH_AIF_CAT2", "amountINR": 12000000.0}
        ]
    }
    res_aif = check_suitability(aif_liquidation, "moderate")
    assert res_aif["passed"] is False
    assert any("statutory lock-in" in v for v in res_aif["violations"])

    # 4. Conservative investor with inappropriate asset class
    conservative_proposal = {
        "actions": [
            {"type": "BUY", "assetClass": "unlisted_equity", "amountINR": 5000000.0}
        ]
    }
    res_cons = check_suitability(conservative_proposal, "conservative")
    assert res_cons["passed"] is False
    assert any("unsuitable for conservative" in v for v in res_cons["violations"])
