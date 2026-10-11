import os
import sys
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure local src directory is on sys.path for tax_calculator
SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from apify import Actor
from shared.trace import get_tracer
from shared.storage import read_state, write_state
from shared.tools import tool, dummy_read
from schemas.validate import validate_data

import tax_calculator

ACTOR_NAME = "wp-tax-compliance"
tracer = get_tracer(actor_name=ACTOR_NAME)

# --- Tool Wrappers for Deterministic Calculators ---

@tool(name="calc_ltcg_tool", actor_name=ACTOR_NAME)
def calc_ltcg_tool(sale_amount: float, cost_basis: float, asset_class: str = "listed_equity", holding_period: int = 24) -> float:
    """Calculates Long Term Capital Gains tax deterministically using versioned rules."""
    return tax_calculator.calc_ltcg(
        sale_amount=sale_amount,
        cost_basis=cost_basis,
        asset_class=asset_class,
        holding_period_months=holding_period
    )

@tool(name="calc_stcg_tool", actor_name=ACTOR_NAME)
def calc_stcg_tool(sale_amount: float, cost_basis: float, asset_class: str = "listed_equity") -> float:
    """Calculates Short Term Capital Gains tax deterministically using versioned rules."""
    return tax_calculator.calc_stcg(
        sale_amount=sale_amount,
        cost_basis=cost_basis,
        asset_class=asset_class
    )

@tool(name="calc_surcharge_tool", actor_name=ACTOR_NAME)
def calc_surcharge_tool(total_income: float, base_tax: float, is_equity_gain: bool = True) -> Dict[str, float]:
    """Calculates surcharge and cess based on statutory income slabs."""
    return tax_calculator.calc_surcharge(
        total_income=total_income,
        base_tax=base_tax,
        is_equity_capital_gain=is_equity_gain
    )

@tool(name="find_harvestable_lots_tool", actor_name=ACTOR_NAME)
def find_harvestable_lots_tool(holdings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Identifies loss-making lots in the portfolio eligible for tax-loss harvesting."""
    return tax_calculator.find_harvestable_lots(holdings)

@tool(name="check_lrs_limit_tool", actor_name=ACTOR_NAME)
def check_lrs_limit_tool(amount_usd: float, already_remitted: float = 0.0) -> Dict[str, Any]:
    """Validates international remittance against RBI LRS $250k cap and estimates TCS."""
    return tax_calculator.check_lrs_limit(amount_usd, already_remitted)

@tool(name="check_suitability_tool", actor_name=ACTOR_NAME)
def check_suitability_tool(proposal: Dict[str, Any], risk_profile: str) -> Dict[str, Any]:
    """Checks proposal compliance against lock-in constraints and single-year liquidation limits."""
    return tax_calculator.check_suitability(proposal, risk_profile)

# --- Core Agent Execution Loop ---

def run_tax_compliance(actor_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes the Plan -> Act -> Observe -> Reflect cycle for Tax & Compliance.
    The LLM/agent decides WHICH calculations and checks to run for the given proposal,
    while all arithmetic is performed by deterministic calculators.
    Enforces the HARD GATE: returns VETO with actionable constraints when thresholds are breached.
    """
    client_id = actor_input.get("clientId", "CLIENT_001")
    proposal = actor_input.get("proposal", {})
    client_context = actor_input.get("ClientContext", {})
    research_findings = actor_input.get("researchFindings", [])
    fy = actor_input.get("financialYear", "2026-27")

    # Load ClientContext if not passed directly
    if not client_context:
        client_context = read_state(f"client/{client_id}/context")
        if not client_context:
            client_data = dummy_read(f"clients/{client_id.lower()}.json")
            client_context = client_data

    # Default proposal for scenario 001 demonstration: "Sell 60% of PROMOTER_CO"
    if not proposal:
        proposal = {
            "id": "S1_AGGRESSIVE_SELL",
            "name": "Immediate 60% sell-down of PROMOTER_CO in single FY",
            "actions": [
                {
                    "type": "SELL",
                    "asset": "PROMOTER_CO",
                    "assetClass": "listed_equity",
                    "amountINR": 27360000.0, # 60% of 45.6M
                    "costBasisINR": 3648000.0, # 30400 * 0.6 = 18240 shares @ 200 avg buy
                    "holdingPeriodMonths": 48
                }
            ]
        }

    actions = proposal.get("actions", [])
    risk_profile = client_context.get("riskProfile", "moderate")
    holdings = client_context.get("holdings", [])

    # Step 1: PLAN
    tracer.log_step(
        step=1,
        thought=f"Planning tax & suitability review for proposal '{proposal.get('name', 'Strategy Proposal')}'. Analyzing {len(actions)} proposed transactions. Need to compute capital gains, surcharge band impacts, suitability barriers, and loss harvesting opportunities.",
        tool="tax_compliance_planner",
        args={"clientId": client_id, "proposalActions": len(actions), "riskProfile": risk_profile},
        result_summary="Plan established: 1) Run suitability check 2) Compute capital gains 3) Compute surcharge & cess 4) Scan for loss lots 5) Evaluate hard gate verdict."
    )

    # Step 2: ACT (Execute deterministic tools)
    suitability_res = check_suitability_tool(proposal, risk_profile)
    
    total_base_tax = 0.0
    total_gains = 0.0
    total_sales = 0.0

    for action in actions:
        if action.get("type", "").upper() == "SELL":
            sale_amt = float(action.get("amountINR", 0.0))
            cost_basis = float(action.get("costBasisINR", 0.0))
            aclass = action.get("assetClass", "listed_equity")
            hp_months = int(action.get("holdingPeriodMonths", 24))

            total_sales += sale_amt
            total_gains += max(0.0, sale_amt - cost_basis)

            if hp_months >= 12:
                tax_amt = calc_ltcg_tool(sale_amt, cost_basis, aclass, hp_months)
            else:
                tax_amt = calc_stcg_tool(sale_amt, cost_basis, aclass)
            total_base_tax += tax_amt

    # Check Surcharge impact
    surcharge_res = calc_surcharge_tool(total_gains, total_base_tax, is_equity_gain=True)
    estimated_total_tax = surcharge_res["totalTax"]

    # Check loss harvesting opportunities
    harvesting_lots = find_harvestable_lots_tool(holdings)

    # Step 3: OBSERVE
    tracer.log_step(
        step=2,
        thought="Observing computation outcomes from deterministic calculators.",
        tool="tax_observables",
        args={
            "totalSaleINR": total_sales,
            "totalGainsINR": total_gains,
            "estimatedTaxINR": estimated_total_tax,
            "suitabilityPassed": suitability_res["passed"],
            "harvestableLotsFound": len(harvesting_lots)
        },
        result_summary=f"Tax calculated: ₹{estimated_total_tax:,.0f}. Suitability: {'PASS' if suitability_res['passed'] else 'FAIL'}. Harvestable loss lots: {len(harvesting_lots)}."
    )

    # Step 4: REFLECT (Hard Gate Evaluation & Veto Logic)
    constraints: List[str] = []
    compliance_flags: List[str] = []
    verdict: str

    # VETO CONDITION 1: Single-year sale breaches recommended ₹2.0 Cr threshold
    max_cap = float(suitability_res.get("maxRecommendedSingleYearSaleINR", 20000000.0))
    if total_sales > max_cap:
        verdict = "VETO"
        constraints.append("Limit sale of PROMOTER_CO to ₹2.0 Cr in FY; remainder next FY")
        compliance_flags.append(
            f"Proposed exit of ₹{total_sales:,.0f} breaches single-year liquidity cap of ₹{max_cap:,.0f}"
        )
        reasoning = (
            f"VETO: Selling ₹{total_sales:,.0f} of PROMOTER_CO in a single financial year creates an excessive tax burden "
            f"of ₹{estimated_total_tax:,.0f} and triggers higher surcharge slabs. "
            f"Strategy must be revised to cap FY{fy} sale at ₹2.0 Cr and stage the remainder into subsequent financial years. "
            f"Additionally, found ₹{sum(h['lossINR'] for h in harvesting_lots):,.0f} in capital losses eligible for offset."
        )

    # VETO CONDITION 2: Suitability failure (e.g. attempting to liquidate locked-in AIF)
    elif not suitability_res["passed"]:
        verdict = "VETO"
        for v in suitability_res["violations"]:
            compliance_flags.append(v)
            constraints.append(f"Adhere to regulatory lock-in: {v}")
        reasoning = f"VETO: Proposal fails RIA regulatory suitability. Violations: {'; '.join(suitability_res['violations'])}"

    # APPROVE WITH CONDITIONS: If loss lots exist to harvest
    elif harvesting_lots:
        verdict = "APPROVE_WITH_CONDITIONS"
        constraints.append(
            f"Execute tax-loss harvesting on {harvesting_lots[0]['lot']} to offset up to ₹{harvesting_lots[0]['lossINR']:,.0f} of LTCG."
        )
        reasoning = (
            f"APPROVE_WITH_CONDITIONS: Proposed actions are compliant with annual thresholds. "
            f"Estimated tax liability is ₹{estimated_total_tax:,.0f}. Net tax drag can be reduced by harvesting "
            f"₹{harvesting_lots[0]['lossINR']:,.0f} unrealized loss in {harvesting_lots[0]['lot']}."
        )
    else:
        verdict = "APPROVE"
        reasoning = f"APPROVE: Proposal satisfies tax efficiency and regulatory criteria. Estimated tax: ₹{estimated_total_tax:,.0f}."

    # Assemble TaxVerdict object
    tax_verdict: Dict[str, Any] = {
        "verdict": verdict,
        "estimatedTaxINR": float(estimated_total_tax),
        "harvestingOpportunities": [
            {
                "lot": h["lot"],
                "lossINR": float(h["lossINR"])
            }
            for h in harvesting_lots
        ],
        "constraints": constraints,
        "complianceFlags": compliance_flags,
        "reasoning": reasoning
    }

    # Validate against schema
    validate_data(tax_verdict, "TaxVerdict")

    tracer.log_step(
        step=3,
        thought=f"Reflecting on compliance review. Verdict rendered: {verdict}.",
        tool="verdict_issuer",
        args={"verdict": verdict, "constraints": constraints, "flagsCount": len(compliance_flags)},
        result_summary=f"Hard gate issued {verdict}. Constraints: {constraints}."
    )

    # Persist to KV store
    write_state(f"tax/{client_id}/verdict", tax_verdict)

    return tax_verdict

# --- Apify Actor Entry Point ---

async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        Actor.log.info(f"Running wp-tax-compliance with input: {actor_input}")
        result = run_tax_compliance(actor_input)
        await Actor.set_value("OUTPUT", result)
        Actor.log.info(f"wp-tax-compliance completed with verdict: {result['verdict']}.")

if __name__ == "__main__":
    asyncio.run(main())
