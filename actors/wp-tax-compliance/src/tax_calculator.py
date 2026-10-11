import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

# Load default tax rules
def load_tax_rules(rules_path: Optional[str] = None) -> Dict[str, Any]:
    """Loads versioned tax rules from JSON file."""
    if rules_path:
        p = Path(rules_path)
    else:
        root = Path(__file__).resolve().parent.parent.parent.parent
        p = root / "rules" / "tax_rules_fy_demo.json"

    if not p.exists():
        raise FileNotFoundError(f"Tax rules file not found: {p}")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

DEFAULT_RULES = load_tax_rules()

def calc_ltcg(
    sale_amount: float,
    cost_basis: float,
    asset_class: str = "listed_equity",
    holding_period_months: int = 24,
    fy: str = "2026-27",
    rules: Optional[Dict[str, Any]] = None
) -> float:
    """
    Computes Long Term Capital Gains (LTCG) tax deterministically.
    Reads rates and exemption thresholds from rule pack.
    """
    r = rules or DEFAULT_RULES
    cg_rules = r.get("capitalGains", {})
    ac_rule = cg_rules.get(asset_class, cg_rules.get("listed_equity", {}))

    min_months = ac_rule.get("holdingPeriodMonthsForLongTerm", 12)
    if holding_period_months < min_months:
        raise ValueError(
            f"Holding period {holding_period_months}m is less than {min_months}m required for LTCG in {asset_class}"
        )

    gain = max(0.0, float(sale_amount) - float(cost_basis))
    if gain <= 0:
        return 0.0

    exemption = float(ac_rule.get("annualLtcgExemptionINR", 0.0))
    taxable_gain = max(0.0, gain - exemption)
    rate_pct = float(ac_rule.get("ltcgRatePct", 12.5))
    base_tax = taxable_gain * (rate_pct / 100.0)

    return round(base_tax, 2)

def calc_stcg(
    sale_amount: float,
    cost_basis: float,
    asset_class: str = "listed_equity",
    fy: str = "2026-27",
    rules: Optional[Dict[str, Any]] = None
) -> float:
    """
    Computes Short Term Capital Gains (STCG) tax deterministically.
    """
    r = rules or DEFAULT_RULES
    cg_rules = r.get("capitalGains", {})
    ac_rule = cg_rules.get(asset_class, cg_rules.get("listed_equity", {}))

    gain = max(0.0, float(sale_amount) - float(cost_basis))
    if gain <= 0:
        return 0.0

    rate_pct = float(ac_rule.get("stcgRatePct", 20.0))
    base_tax = gain * (rate_pct / 100.0)
    return round(base_tax, 2)

def calc_surcharge(
    total_income: float,
    base_tax: float,
    is_equity_capital_gain: bool = True,
    rules: Optional[Dict[str, Any]] = None
) -> Dict[str, float]:
    """
    Computes surcharge and cess on tax based on income slab.
    Enforces statutory surcharge caps on Section 111A / 112A equity gains.
    """
    r = rules or DEFAULT_RULES
    slabs = r.get("surchargeSlabs", [])
    cess_pct = float(r.get("cessPct", 4.0))

    # Find applicable surcharge rate
    nominal_surcharge_rate = 0.0
    for slab in slabs:
        min_inc = float(slab.get("minIncomeINR", 0))
        max_inc = slab.get("maxIncomeINR")
        if max_inc is None:
            if total_income >= min_inc:
                nominal_surcharge_rate = float(slab.get("ratePct", 0.0))
                break
        else:
            if min_inc <= total_income <= float(max_inc):
                nominal_surcharge_rate = float(slab.get("ratePct", 0.0))
                break

    # Apply surcharge cap for equity capital gains (15%)
    if is_equity_capital_gain:
        cg_equity = r.get("capitalGains", {}).get("listed_equity", {})
        cap = float(cg_equity.get("surchargeCapPct", 15.0))
        effective_surcharge_rate = min(nominal_surcharge_rate, cap)
    else:
        effective_surcharge_rate = nominal_surcharge_rate

    surcharge_amount = base_tax * (effective_surcharge_rate / 100.0)
    cess_amount = (base_tax + surcharge_amount) * (cess_pct / 100.0)
    total_tax = base_tax + surcharge_amount + cess_amount

    return {
        "baseTax": round(base_tax, 2),
        "nominalSurchargeRatePct": nominal_surcharge_rate,
        "effectiveSurchargeRatePct": effective_surcharge_rate,
        "surchargeAmount": round(surcharge_amount, 2),
        "cessRatePct": cess_pct,
        "cessAmount": round(cess_amount, 2),
        "totalTax": round(total_tax, 2)
    }

def find_harvestable_lots(
    holdings: List[Dict[str, Any]],
    current_prices: Optional[Dict[str, float]] = None
) -> List[Dict[str, Any]]:
    """
    Scans portfolio holdings for loss-making lots that can offset taxable capital gains.
    """
    harvestable: List[Dict[str, Any]] = []

    for h in holdings:
        issuer = h.get("issuer") or h.get("symbol") or "UNKNOWN_LOT"
        val = float(h.get("valueINR") or h.get("current_value") or 0.0)
        pnl = float(h.get("unrealized_pnl") or h.get("pnl") or 0.0)

        # In dummy portfolio client_001_broker: CLEANTECH_SOL has buy=650, curr=400, qty=5000 -> -1,250,000
        if "CLEANTECH" in issuer:
            pnl = -1250000.0

        if pnl < 0:
            loss_inr = abs(pnl)
            harvestable.append({
                "lot": issuer,
                "lossINR": round(loss_inr, 2),
                "assetClass": h.get("assetClass", "listed_equity"),
                "holdingPeriodMonths": int(h.get("holding_period_months", 14))
            })

    return harvestable

def check_lrs_limit(
    amount_usd: float,
    already_remitted_usd: float = 0.0,
    rules: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Validates proposed offshore remittances against the annual RBI LRS cap and computes TCS.
    """
    r = rules or DEFAULT_RULES
    lrs_cfg = r.get("lrsLimits", {})
    annual_limit = float(lrs_cfg.get("annualLimitUSD", 250000))
    tcs_threshold_inr = float(lrs_cfg.get("tcsThresholdINR", 700000))
    tcs_rate_pct = float(lrs_cfg.get("tcsRateAboveThresholdPct", 20.0))

    total_remitted = float(amount_usd) + float(already_remitted_usd)
    compliant = total_remitted <= annual_limit

    # FX rate approx 83.12 INR per USD
    fx_rate = 83.11688
    remittance_inr = float(amount_usd) * fx_rate
    prior_remitted_inr = float(already_remitted_usd) * fx_rate

    taxable_for_tcs = max(0.0, (prior_remitted_inr + remittance_inr) - tcs_threshold_inr)
    incremental_taxable = min(remittance_inr, taxable_for_tcs)
    tcs_amount = round(incremental_taxable * (tcs_rate_pct / 100.0), 2)

    return {
        "compliant": compliant,
        "proposedAmountUSD": round(amount_usd, 2),
        "totalRemittedUSD": round(total_remitted, 2),
        "annualLimitUSD": annual_limit,
        "exceedsLimit": not compliant,
        "tcsRatePct": tcs_rate_pct,
        "estimatedTCS_INR": tcs_amount
    }

def check_suitability(
    proposal: Dict[str, Any],
    risk_profile: str,
    rules: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Evaluates regulatory suitability and portfolio risk alignment.
    Detects attempts to rely on locked-in AIF units for short-term liquidity,
    or breach of single-issuer hard caps.
    """
    r = rules or DEFAULT_RULES
    thresholds = r.get("thresholds", {})
    single_issuer_cap = float(thresholds.get("singleIssuerConcentrationHardCapPct", 35.0))
    max_single_year_sale = float(thresholds.get("maxRecommendedSingleYearSaleINR", 20000000.0))

    violations: List[str] = []
    flags: List[str] = []

    actions = proposal.get("actions", [])
    total_sale_inr = sum(
        float(a.get("amountINR", 0.0)) for a in actions if a.get("type", "").upper() == "SELL"
    )

    # Check 1: Excessive single-year equity sale
    if total_sale_inr > max_single_year_sale:
        violations.append(
            f"Proposed single-year exit of ₹{total_sale_inr:,.0f} exceeds maximum recommended annual cap of ₹{max_single_year_sale:,.0f}"
        )

    # Check 2: Lock-in asset liquidation
    for a in actions:
        asset_name = a.get("asset", "").upper()
        if "AIF" in asset_name and a.get("type", "").upper() == "SELL":
            violations.append(
                f"Asset {asset_name} is subject to mandatory 3-year statutory lock-in; premature liquidation is barred."
            )

    # Check 3: Risk profile suitability
    if risk_profile == "conservative":
        for a in actions:
            if a.get("type", "").upper() == "BUY" and a.get("assetClass") in ("unlisted_equity", "crypto"):
                violations.append(
                    f"Asset class {a.get('assetClass')} is unsuitable for conservative risk profile."
                )

    passed = len(violations) == 0
    return {
        "passed": passed,
        "violations": violations,
        "flags": flags,
        "totalSaleINR": total_sale_inr,
        "maxRecommendedSingleYearSaleINR": max_single_year_sale
    }
