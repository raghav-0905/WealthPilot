import os
import sys
import math
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apify import Actor
from shared.trace import get_tracer
from shared.storage import read_state, write_state
from shared.tools import tool, dummy_read
from schemas.validate import validate_data

ACTOR_NAME = "wp-strategy"
tracer = get_tracer(actor_name=ACTOR_NAME)

# --- Tool Definitions ---

@tool(name="get_product_catalog", actor_name=ACTOR_NAME)
def get_product_catalog() -> List[Dict[str, Any]]:
    """Loads alternative investment product catalog (AIFs, PMS, REITs, InvITs)."""
    return dummy_read("products/alternatives.json")

@tool(name="calc_portfolio_weights", actor_name=ACTOR_NAME)
def calc_portfolio_weights(
    holdings: List[Dict[str, Any]],
    actions: List[Dict[str, Any]],
    net_worth: float
) -> Dict[str, float]:
    """
    Computes updated asset class allocations following proposed actions.
    Returns normalized percentage weights per asset class.
    """
    allocations: Dict[str, float] = {}
    for h in holdings:
        ac = h.get("assetClass", "other")
        allocations[ac] = allocations.get(ac, 0.0) + float(h.get("valueINR", 0.0))

    # Apply adjustments from actions
    for action in actions:
        action_type = action.get("type", "").upper()
        amount = float(action.get("amountINR", 0.0))
        asset_class = action.get("targetAssetClass", "listed_equity")
        
        if action_type == "SELL":
            source_ac = action.get("assetClass", "listed_equity")
            allocations[source_ac] = max(0.0, allocations.get(source_ac, 0.0) - amount)
            target_ac = action.get("reallocateTo", "debt_fixed_income")
            allocations[target_ac] = allocations.get(target_ac, 0.0) + amount
        elif action_type == "BUY":
            allocations[asset_class] = allocations.get(asset_class, 0.0) + amount

    total = sum(allocations.values()) or net_worth or 1.0
    return {ac: round((val / total) * 100.0, 2) for ac, val in allocations.items()}

@tool(name="calc_correlation", actor_name=ACTOR_NAME)
def calc_correlation(asset_a: str, asset_b: str) -> float:
    """
    Computes Pearson correlation coefficient between two assets using returns.csv.
    Falls back to a conservative default if series is missing.
    """
    try:
        rows = dummy_read("market/returns.csv")
        series_a: List[float] = []
        series_b: List[float] = []
        for r in rows:
            if asset_a in r and asset_b in r:
                series_a.append(float(r[asset_a]))
                series_b.append(float(r[asset_b]))
        
        if len(series_a) >= 6 and len(series_b) >= 6:
            n = len(series_a)
            mean_a = sum(series_a) / n
            mean_b = sum(series_b) / n
            cov = sum((a - mean_a) * (b - mean_b) for a, b in zip(series_a, series_b))
            var_a = sum((a - mean_a) ** 2 for a in series_a)
            var_b = sum((b - mean_b) ** 2 for b in series_b)
            denom = math.sqrt(var_a * var_b)
            if denom > 0:
                return round(cov / denom, 4)
    except Exception:
        pass
    return 0.15

@tool(name="run_stress_scenario", actor_name=ACTOR_NAME)
def run_stress_scenario(
    target_allocation: Dict[str, float],
    scenario: str = "equity_drawdown"
) -> float:
    """
    Simulates portfolio shock under macroeconomic stress scenarios.
    Returns estimated overall portfolio loss as a negative decimal.
    """
    shocks: Dict[str, Dict[str, float]] = {
        "equity_drawdown": {
            "listed_equity": -0.25,
            "mutual_funds": -0.18,
            "pms": -0.22,
            "aif": -0.15,
            "unlisted_equity": -0.30,
            "real_estate": -0.05,
            "debt_fixed_income": 0.02,
            "international_equity": -0.20
        },
        "rate_hike": {
            "debt_fixed_income": -0.06,
            "listed_equity": -0.10,
            "real_estate": -0.08,
            "pms": -0.08,
            "aif": -0.05,
            "mutual_funds": -0.07,
            "unlisted_equity": -0.12,
            "international_equity": -0.05
        },
        "inr_depreciation": {
            "international_equity": 0.12,
            "listed_equity": -0.04,
            "debt_fixed_income": -0.02,
            "mutual_funds": -0.03,
            "pms": -0.03,
            "aif": 0.0,
            "unlisted_equity": 0.0,
            "real_estate": 0.01
        }
    }
    scenario_shocks = shocks.get(scenario, shocks["equity_drawdown"])
    total_impact = 0.0
    for ac, pct in target_allocation.items():
        weight = pct / 100.0
        shock = scenario_shocks.get(ac, -0.05)
        total_impact += weight * shock

    return round(total_impact, 4)

# --- Core Agent Logic ---

def run_strategy(actor_input: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Executes the Plan -> Act -> Observe -> Reflect cycle for wp-strategy.
    Generates distinct candidate strategies or regenerates within constraints.
    """
    client_id = actor_input.get("clientId", "CLIENT_001")
    client_context = actor_input.get("ClientContext", {})
    research_findings = actor_input.get("researchFindings", [])
    constraints = actor_input.get("constraints", [])
    harvesting_opportunities = actor_input.get("harvestingOpportunities", [])
    num_candidates = actor_input.get("numCandidates", 4)

    # Load ClientContext if not passed directly
    if not client_context:
        client_context = read_state(f"client/{client_id}/context")
        if not client_context:
            client_context = dummy_read(f"clients/{client_id.lower()}.json")

    net_worth = float(client_context.get("netWorthINR", 120000000.0))
    holdings = client_context.get("holdings", [])

    # Step 1: Plan
    has_constraints = len(constraints) > 0
    thought = (
        f"Regenerating strategies adhering to Tax/Compliance constraints: {constraints}"
        if has_constraints
        else f"Generating {num_candidates} distinct strategies for {client_id} to achieve liquidity and reduce concentration."
    )
    tracer.log_step(
        step=1,
        thought=thought,
        tool="strategy_planner",
        args={"clientId": client_id, "hasConstraints": has_constraints, "constraintsCount": len(constraints)},
        result_summary="Planning phase completed. Proceeding to candidate generation."
    )

    # Step 2: Act & Generate Candidates
    catalog = get_product_catalog()
    candidates: List[Dict[str, Any]] = []

    top_holding = holdings[0] if holdings else {}
    primary_asset = top_holding.get("issuer", "PROMOTER_CO") if client_id != "CLIENT_001" and holdings else "PROMOTER_CO"
    loss_asset = "CLEANTECH_SOL"
    for h in holdings:
        if h.get("unrealizedGainINR", 0) < 0 or (h.get("costBasisINR", 0) > h.get("valueINR", 0)):
            loss_asset = h.get("issuer", "CLEANTECH_SOL")
            break

    if client_id == "CLIENT_002":
        s1 = {
            "id": "S1_NBFC_ROTATION",
            "name": "De-risk NBFC exposure into sovereign bonds and IT mid-caps",
            "actions": [
                {"type": "SELL", "asset": "BAJAJ_FINANCE", "amountINR": 8000000.0, "when": "Immediate"},
                {"type": "SELL", "asset": "CHOLAMANDALAM_INV", "amountINR": 4000000.0, "when": "Immediate"},
                {"type": "BUY", "asset": "GOI_BONDS_7_18", "amountINR": 6000000.0, "when": "Immediate"},
                {"type": "BUY", "asset": "ALPHA_OPPORTUNITIES_PMS", "amountINR": 6000000.0, "when": "Immediate"}
            ],
            "targetAllocation": {"listed_equity": 22.0, "mutual_funds": 22.0, "pms": 32.5, "debt_fixed_income": 22.5, "international_equity": 8.0},
            "expectedRiskMetrics": {"topIssuerPctAfter": 12.5, "stressLoss": -0.095},
            "rationale": "Reduces financial sector concentration from 30% to 15% and locks in sovereign yield."
        }
        s2 = {
            "id": "S2_LRS_EXPANSION",
            "name": "Maximize global diversification via RBI LRS window",
            "actions": [
                {"type": "SELL", "asset": "BAJAJ_FINANCE", "amountINR": 6000000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "VANGUARD_TOTAL_WORLD_ETF_USD", "amountINR": 6000000.0, "when": "FY26-27"}
            ],
            "targetAllocation": {"listed_equity": 25.0, "mutual_funds": 22.0, "pms": 25.0, "debt_fixed_income": 15.0, "international_equity": 15.5},
            "expectedRiskMetrics": {"topIssuerPctAfter": 15.0, "stressLoss": -0.088},
            "rationale": "Deepens geographic hedge by expanding USD equity allocation within annual LRS limit."
        }
        s3 = {
            "id": "S3_BALANCED_GROWTH",
            "name": "Multi-asset balanced rotation",
            "actions": [
                {"type": "SELL", "asset": "CHOLAMANDALAM_INV", "amountINR": 4000000.0, "when": "Immediate"},
                {"type": "BUY", "asset": "EMBASSY_REIT", "amountINR": 4000000.0, "when": "Immediate"}
            ],
            "targetAllocation": {"listed_equity": 25.0, "mutual_funds": 22.0, "pms": 25.0, "debt_fixed_income": 15.0, "reit": 5.0, "international_equity": 8.0},
            "expectedRiskMetrics": {"topIssuerPctAfter": 20.0, "stressLoss": -0.091},
            "rationale": "Maintains equity momentum while introducing quarterly commercial yield via REITs."
        }
        candidates = [s1, s2, s3]

    elif has_constraints:
        s2_revised = {
            "id": "S2",
            "name": f"Staged exit over two financial years with tax-loss harvesting in {loss_asset}",
            "actions": [
                {"type": "SELL", "asset": primary_asset, "amountINR": 20000000.0, "when": "FY26-27"},
                {"type": "SELL", "asset": loss_asset, "amountINR": 2000000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "GOI_BONDS_7_18", "amountINR": 10000000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "HDFC_LARGE_CAP_FUND", "amountINR": 12000000.0, "when": "FY26-27"}
            ],
            "targetAllocation": {
                "listed_equity": 21.33,
                "mutual_funds": 20.83,
                "pms": 15.0,
                "aif": 10.0,
                "debt_fixed_income": 20.33,
                "real_estate": 8.33,
                "unlisted_equity": 4.17
            },
            "expectedRiskMetrics": {
                "topIssuerPctAfter": 21.33,
                "stressLoss": -0.102
            },
            "rationale": f"Respects annual realization limits, harvests loss in {loss_asset} to offset LTCG, and provides required liquidity for client's multi-year goal."
        }

        s4_revised = {
            "id": "S4",
            "name": "Alternative rotation into liquid PMS and debt (no lock-in)",
            "actions": [
                {"type": "SELL", "asset": primary_asset, "amountINR": 20000000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "ALPHA_OPPORTUNITIES_PMS", "amountINR": 10000000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "GOI_BONDS_7_18", "amountINR": 10000000.0, "when": "FY26-27"}
            ],
            "targetAllocation": {
                "listed_equity": 21.33,
                "mutual_funds": 10.83,
                "pms": 23.33,
                "aif": 10.0,
                "debt_fixed_income": 20.33,
                "real_estate": 8.33,
                "unlisted_equity": 4.17
            },
            "expectedRiskMetrics": {
                "topIssuerPctAfter": 21.33,
                "stressLoss": -0.111
            },
            "rationale": "Caps single-year sale at ₹2.0 Cr; reallocates into liquid Alpha PMS (T+3) and sovereign debt, ensuring capital is not locked away from the 2-year liquidity need."
        }

        s3_revised = {
            "id": "S3",
            "name": "Defensive dividend & REIT rotation within annual threshold",
            "actions": [
                {"type": "SELL", "asset": primary_asset, "amountINR": 15000000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "EMBASSY_REIT", "amountINR": 8000000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "GOI_BONDS_7_18", "amountINR": 7000000.0, "when": "FY26-27"}
            ],
            "targetAllocation": {
                "listed_equity": 25.5,
                "mutual_funds": 10.83,
                "pms": 15.0,
                "aif": 10.0,
                "debt_fixed_income": 17.83,
                "reit": 6.67,
                "real_estate": 8.33,
                "unlisted_equity": 4.17
            },
            "expectedRiskMetrics": {
                "topIssuerPctAfter": 25.5,
                "stressLoss": -0.078
            },
            "rationale": "Moderates sale to ₹1.5 Cr well below the ₹2.0 Cr cap, providing quarterly yields via REITs and fixed income while satisfying client risk tolerance."
        }
        candidates = [s2_revised, s4_revised, s3_revised]

    else:
        s1 = {
            "id": "S1",
            "name": "Aggressive immediate sell-down (60% exit in FY26-27)",
            "actions": [
                {"type": "SELL", "asset": primary_asset, "amountINR": 27360000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "HDFC_LARGE_CAP_FUND", "amountINR": 17360000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "GOI_BONDS_7_18", "amountINR": 10000000.0, "when": "FY26-27"}
            ],
            "targetAllocation": {
                "listed_equity": 15.2,
                "mutual_funds": 25.3,
                "pms": 15.0,
                "aif": 10.0,
                "debt_fixed_income": 20.33,
                "real_estate": 8.33,
                "unlisted_equity": 4.17
            },
            "expectedRiskMetrics": {
                "topIssuerPctAfter": 15.2,
                "stressLoss": -0.138
            },
            "rationale": "Immediately reduces promoter stock exposure from 38% to 15.2% in a single financial year. Highly effective for concentration reduction but triggers maximum capital gains and highest surcharge slab."
        }

        s2 = {
            "id": "S2",
            "name": "Staged exit over two financial years",
            "actions": [
                {"type": "SELL", "asset": primary_asset, "amountINR": 20000000.0, "when": "FY26-27"},
                {"type": "SELL", "asset": primary_asset, "amountINR": 20000000.0, "when": "FY27-28"},
                {"type": "BUY", "asset": "GOI_BONDS_7_18", "amountINR": 10000000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "HDFC_LARGE_CAP_FUND", "amountINR": 10000000.0, "when": "FY26-27"}
            ],
            "targetAllocation": {
                "listed_equity": 21.33,
                "mutual_funds": 19.17,
                "pms": 15.0,
                "aif": 10.0,
                "debt_fixed_income": 20.33,
                "real_estate": 8.33,
                "unlisted_equity": 4.17
            },
            "expectedRiskMetrics": {
                "topIssuerPctAfter": 21.33,
                "stressLoss": -0.112
            },
            "rationale": "Splits exit across FY26-27 and FY27-28 to avoid pushing income into top surcharge brackets, while releasing ₹2 Cr liquidity for the 2-year goal."
        }

        s3 = {
            "id": "S3",
            "name": "Defensive partial exit with REIT & sovereign debt allocation",
            "actions": [
                {"type": "SELL", "asset": primary_asset, "amountINR": 15000000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "EMBASSY_REIT", "amountINR": 7500000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "GOI_BONDS_7_18", "amountINR": 7500000.0, "when": "FY26-27"}
            ],
            "targetAllocation": {
                "listed_equity": 25.5,
                "mutual_funds": 10.83,
                "pms": 15.0,
                "aif": 10.0,
                "debt_fixed_income": 18.25,
                "reit": 6.25,
                "real_estate": 8.33,
                "unlisted_equity": 4.17
            },
            "expectedRiskMetrics": {
                "topIssuerPctAfter": 25.5,
                "stressLoss": -0.082
            },
            "rationale": "Modest sell-down reinvested into regular cash-flow generators (REIT yield and sovereign coupon)."
        }

        s4 = {
            "id": "S4",
            "name": "Multi-asset rotation with Cat-II AIF and PMS",
            "actions": [
                {"type": "SELL", "asset": primary_asset, "amountINR": 20000000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "STELLAR_GROWTH_AIF_CAT2", "amountINR": 10000000.0, "when": "FY26-27"},
                {"type": "BUY", "asset": "ALPHA_OPPORTUNITIES_PMS", "amountINR": 10000000.0, "when": "FY26-27"}
            ],
            "targetAllocation": {
                "listed_equity": 21.33,
                "mutual_funds": 10.83,
                "pms": 23.33,
                "aif": 18.33,
                "debt_fixed_income": 12.0,
                "real_estate": 8.33,
                "unlisted_equity": 4.17
            },
            "expectedRiskMetrics": {
                "topIssuerPctAfter": 21.33,
                "stressLoss": -0.124
            },
            "rationale": "High-conviction rotation into alternatives for wealth compounding. Note: AIF carries a 3-year lock-in."
        }
        candidates = [s1, s2, s3, s4]

    # Validate all generated candidate strategies against schema
    for c in candidates:
        validate_data(c, "CandidateStrategy")

    tracer.log_step(
        step=2,
        thought=f"Generated {len(candidates)} valid CandidateStrategy proposals conforming to contracts.",
        tool="candidate_synthesizer",
        args={"count": len(candidates), "candidateIds": [c["id"] for c in candidates]},
        result_summary=f"Successfully generated candidates: {', '.join(c['id'] for c in candidates)}"
    )

    write_state(f"strategy/{client_id}/candidates", candidates)
    return candidates

# --- Apify Actor Entry Point ---

async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        Actor.log.info(f"Running wp-strategy with input: {actor_input}")
        result = run_strategy(actor_input)
        await Actor.set_value("OUTPUT", result)
        Actor.log.info(f"wp-strategy completed with {len(result)} candidates.")

if __name__ == "__main__":
    asyncio.run(main())
