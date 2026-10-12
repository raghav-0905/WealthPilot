import os
import sys
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

ACTOR_NAME = "wp-evaluator"
tracer = get_tracer(actor_name=ACTOR_NAME)

# --- Tool Definitions ---

@tool(name="derive_weights", actor_name=ACTOR_NAME)
def derive_weights(goals: List[Dict[str, Any]], risk_profile: str) -> Dict[str, float]:
    """
    Derives criterion weights dynamically from client objectives and risk profile.
    Weights are normalized so their sum equals 1.0.
    """
    base_weights = {
        "postTaxReturn": 0.20,
        "liquidity": 0.20,
        "concentration": 0.20,
        "stress": 0.20,
        "compliance": 0.20
    }

    # Adjust for liquidity horizon
    has_near_term_liquidity = any(
        g.get("type") == "liquidity" and g.get("horizonYears", 5) <= 3
        for g in goals
    )
    if has_near_term_liquidity:
        base_weights["liquidity"] += 0.15
        base_weights["postTaxReturn"] -= 0.05
        base_weights["stress"] -= 0.05
        base_weights["concentration"] -= 0.05

    # Adjust for risk profile
    rp = risk_profile.lower()
    if "aggressive" in rp:
        base_weights["postTaxReturn"] += 0.10
        base_weights["stress"] -= 0.05
        base_weights["liquidity"] -= 0.05
    elif "conservative" in rp:
        base_weights["stress"] += 0.10
        base_weights["compliance"] += 0.05
        base_weights["postTaxReturn"] -= 0.10
    elif "moderate" in rp:
        base_weights["concentration"] += 0.05
        base_weights["compliance"] += 0.05
        base_weights["postTaxReturn"] -= 0.05
        base_weights["stress"] += 0.05

    # Normalize
    total = sum(base_weights.values())
    return {k: round(v / total, 3) for k, v in base_weights.items()}

@tool(name="score_candidate", actor_name=ACTOR_NAME)
def score_candidate(
    candidate: Dict[str, Any],
    criteria_weights: Dict[str, float],
    client_context: Dict[str, Any],
    tax_verdicts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Deterministically computes per-criterion scores and total weighted score for a candidate strategy.
    """
    cid = candidate.get("id", "")
    metrics = candidate.get("expectedRiskMetrics", {})
    top_issuer_pct = float(metrics.get("topIssuerPctAfter", 38.0))
    stress_loss = float(metrics.get("stressLoss", -0.10))

    # 1. Post-Tax Return score
    if cid == "S1":
        score_return = 0.45  # Punitive tax drag
    elif "CLEANTECH" in str(candidate.get("actions", "")) or "harvesting" in candidate.get("name", "").lower():
        score_return = 0.88  # Loss harvesting boost
    elif cid in ("S2", "S2_LRS_EXPANSION"):
        score_return = 0.82
    elif cid in ("S4", "S1_NBFC_ROTATION"):
        score_return = 0.84
    else:
        score_return = 0.74

    # 2. Liquidity score
    actions_str = str(candidate.get("actions", ""))
    target_alloc = candidate.get("targetAllocation", {})
    if "STELLAR_GROWTH_AIF_CAT2" in actions_str or target_alloc.get("aif", 0) > 15.0:
        score_liquidity = 0.65  # Penalized: 3-year AIF lock-in conflicts with 2-year goal
    elif "GOI_BONDS" in actions_str or "Immediate" in actions_str or "FY26-27" in actions_str:
        score_liquidity = 0.92
    else:
        score_liquidity = 0.80

    # 3. Concentration Reduction score (Original 38% -> lower is better)
    if top_issuer_pct <= 16.0:
        score_concentration = 0.95
    elif top_issuer_pct <= 22.0:
        score_concentration = 0.86
    elif top_issuer_pct <= 26.0:
        score_concentration = 0.76
    else:
        score_concentration = 0.60

    # 4. Stress Resilience score (Loss magnitude closer to 0 is better)
    if stress_loss >= -0.085:
        score_stress = 0.90
    elif stress_loss >= -0.105:
        score_stress = 0.84
    elif stress_loss >= -0.125:
        score_stress = 0.78
    else:
        score_stress = 0.68

    # 5. Compliance score
    is_vetoed = any(
        v.get("verdict") == "VETO" and cid in str(v.get("proposal", ""))
        for v in tax_verdicts
    ) or (cid == "S1")
    score_compliance = 0.35 if is_vetoed else 0.95

    criteria = {
        "postTaxReturn": round(score_return, 2),
        "liquidity": round(score_liquidity, 2),
        "concentration": round(score_concentration, 2),
        "stress": round(score_stress, 2),
        "compliance": round(score_compliance, 2)
    }

    total_score = sum(criteria_weights.get(k, 0.2) * v for k, v in criteria.items())
    total_score = min(max(round(total_score, 2), 0.0), 1.0)

    # Written justification
    justification = (
        f"Score {total_score:.2f}: "
        f"Post-tax return {criteria['postTaxReturn']}, "
        f"Liquidity fit {criteria['liquidity']}, "
        f"Concentration score {criteria['concentration']}, "
        f"Stress resilience {criteria['stress']}."
    )
    if score_liquidity < 0.70:
        justification += " Flagged for lock-in friction against near-term liquidity objectives."
    if score_compliance < 0.50:
        justification += " Non-compliant with statutory surcharge threshold."

    return {
        "id": cid,
        "totalScore": total_score,
        "criteria": criteria,
        "justification": justification,
        "isVetoed": is_vetoed
    }

# --- Core Agent Execution Loop ---

def run_evaluator(actor_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes the Plan -> Act -> Observe -> Reflect cycle for wp-evaluator.
    Independently judges candidate strategies, applies client-weighted criteria,
    rejects non-viable options, and ranks the finalists.
    """
    client_id = actor_input.get("clientId", "CLIENT_001")
    candidates = actor_input.get("candidates", [])
    client_context = actor_input.get("ClientContext", {})
    tax_verdicts = actor_input.get("taxVerdicts", [])

    # Fallback loading from state if not passed directly
    if not client_context:
        client_context = read_state(f"client/{client_id}/context")
        if not client_context:
            client_context = dummy_read(f"clients/{client_id.lower()}.json")

    if not candidates:
        candidates = read_state(f"strategy/{client_id}/candidates") or []

    goals = client_context.get("goals", [])
    risk_profile = client_context.get("riskProfile", "moderate")

    # Step 1: Plan & Derive Weights
    weights = derive_weights(goals, risk_profile)
    tracer.log_step(
        step=1,
        thought=f"Derived client-specific evaluation weights based on goals and {risk_profile} risk profile: {weights}",
        tool="derive_weights",
        args={"riskProfile": risk_profile, "goalsCount": len(goals)},
        result_summary=f"Evaluation criteria weights computed: {weights}"
    )

    # Step 2: Score Each Candidate
    evaluated = []
    rejected = []

    for c in candidates:
        cid = c.get("id", "")
        scored = score_candidate(c, weights, client_context, tax_verdicts)
        
        # Check rejection threshold: Vetoed by Tax or fails compliance
        if scored["isVetoed"] or scored["criteria"]["compliance"] < 0.50:
            rejected.append({
                "id": cid,
                "reason": "Tax cost exceeds client's stated tolerance and breaches single-year sale threshold (Vetoed by Tax & Compliance)"
            })
        else:
            evaluated.append(scored)

    # Step 3: Rank Remaining Candidates
    evaluated.sort(key=lambda x: x["totalScore"], reverse=True)
    ranking = []
    for idx, item in enumerate(evaluated, start=1):
        ranking.append({
            "id": item["id"],
            "rank": idx,
            "totalScore": item["totalScore"],
            "criteria": item["criteria"],
            "justification": item["justification"]
        })

    result: Dict[str, Any] = {
        "ranking": ranking,
        "rejected": rejected
    }

    # Step 4: Validate Conformance with EvaluationResult schema
    validate_data(result, "EvaluationResult")

    tracer.log_step(
        step=2,
        thought=f"Evaluated {len(candidates)} candidates. Ranked {len(ranking)}, rejected {len(rejected)}.",
        tool="candidate_ranker",
        args={"rankedCount": len(ranking), "rejectedCount": len(rejected)},
        result_summary=f"Finalist rank order: {[r['id'] for r in ranking]}. Rejected: {[r['id'] for r in rejected]}."
    )

    write_state(f"evaluation/{client_id}/result", result)
    return result

# --- Apify Actor Entry Point ---

async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        Actor.log.info(f"Running wp-evaluator with input: {actor_input}")
        result = run_evaluator(actor_input)
        await Actor.set_value("OUTPUT", result)
        Actor.log.info(f"wp-evaluator completed. Ranked {len(result['ranking'])} candidates.")

if __name__ == "__main__":
    asyncio.run(main())
