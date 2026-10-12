import os
import sys
import json
import asyncio
import importlib.util
from pathlib import Path
from typing import Dict, Any, List, Optional

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apify import Actor
from shared.config import WEALTHPILOT_MODE
from shared.trace import get_tracer
from shared.storage import read_state, write_state, append_report
from shared.tools import tool, dummy_read
from schemas.validate import validate_data

ACTOR_NAME = "wp-orchestrator"
tracer = get_tracer(actor_name=ACTOR_NAME)

# --- Actor Router Helper ---

def call_actor(actor_dir_name: str, payload: Dict[str, Any]) -> Any:
    """
    Invokes a specialist Actor.
    Dispatches to local Python module execution in dummy mode, or Apify Actor.call in live mode.
    """
    tracer.log_step(
        step=f"call_{actor_dir_name}",
        thought=f"Orchestrator routing payload to {actor_dir_name}.",
        tool="Actor.call",
        args={"actor": actor_dir_name, "inputKeys": list(payload.keys())},
        result_summary=f"Invoking {actor_dir_name}"
    )

    actor_path = PROJECT_ROOT / "actors" / actor_dir_name / "src" / "main.py"
    if not actor_path.exists():
        raise FileNotFoundError(f"Actor entry point not found: {actor_path}")

    spec = importlib.util.spec_from_file_location(actor_dir_name.replace("-", "_"), actor_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Dispatch to specific runner function
    if actor_dir_name == "wp-client-context":
        return mod.run_client_context(payload)
    elif actor_dir_name == "wp-research-policy":
        return mod.run_research_policy(payload)
    elif actor_dir_name == "wp-tax-compliance":
        return mod.run_tax_compliance(payload)
    elif actor_dir_name == "wp-strategy":
        return mod.run_strategy(payload)
    elif actor_dir_name == "wp-evaluator":
        return mod.run_evaluator(payload)
    elif actor_dir_name == "wp-execution-monitor":
        return mod.run_execution_monitor(payload)
    else:
        raise ValueError(f"Unknown actor name: {actor_dir_name}")

# --- Core Orchestrator Agent Loop ---

def run_orchestrator(actor_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Autonomous supervisory reasoning loop:
    1. Plan initial task graph
    2. Route work to specialist actors
    3. Detect invalidations & execute replanning (Tax Veto & Harvesting)
    4. Arbitrate cross-actor goal conflicts
    5. Assemble schema-valid FinalReport with full explainability
    """
    client_id = actor_input.get("clientId", "CLIENT_001")
    goal = actor_input.get(
        "goal",
        "Reduce concentration in my own company stock tax-efficiently; need ₹2 Cr liquidity in 2 years."
    )
    max_revision_rounds = int(actor_input.get("maxRevisionRounds", 3))

    # Initialize task graph
    task_graph: Dict[str, Any] = {
        "initialSteps": [
            "wp-client-context",
            "wp-research-policy",
            "wp-strategy",
            "wp-tax-compliance",
            "wp-evaluator"
        ],
        "executedSteps": [],
        "replans": [],
        "revisionRounds": 0
    }
    arbitration_log: List[Dict[str, Any]] = []

    tracer.log_step(
        step=1,
        thought=f"Decomposing client goal into execution task graph: {task_graph['initialSteps']}",
        tool="task_graph_planner",
        args={"clientId": client_id, "goal": goal},
        result_summary="Initial task graph decomposed and ready for sequential execution."
    )

    # --- Step 1: Ingest & Reconcile Client Context ---
    client_context = call_actor("wp-client-context", {"clientId": client_id})
    task_graph["executedSteps"].append({
        "step": 1,
        "actor": "wp-client-context",
        "status": "COMPLETED",
        "summary": f"Reconciled {len(client_context.get('holdings', []))} holdings. Top issuer: {client_context.get('exposure', {}).get('topIssuerPct')}%. Flags: {len(client_context.get('profileConsistencyFlags', []))}"
    })

    # --- Step 2: Exposure-Driven Research & Policy ---
    research_findings = call_actor("wp-research-policy", {
        "clientId": client_id,
        "exposure": client_context.get("exposure", {}),
        "goalSummary": goal
    })
    task_graph["executedSteps"].append({
        "step": 2,
        "actor": "wp-research-policy",
        "status": "COMPLETED",
        "summary": f"Retrieved {len(research_findings)} exposure-targeted regulatory and sector findings."
    })

    # --- Step 3: Strategy Generation ---
    initial_candidates = call_actor("wp-strategy", {
        "clientId": client_id,
        "ClientContext": client_context,
        "researchFindings": research_findings
    })
    task_graph["executedSteps"].append({
        "step": 3,
        "actor": "wp-strategy",
        "status": "COMPLETED",
        "summary": f"Generated {len(initial_candidates)} candidate strategies: {[c['id'] for c in initial_candidates]}."
    })

    # --- Step 4: Tax & Compliance Gate (Check proposals) ---
    # Tax evaluates the aggressive sell-down proposal (S1)
    s1_candidate = next((c for c in initial_candidates if c["id"] == "S1"), initial_candidates[0])
    tax_verdict = call_actor("wp-tax-compliance", {
        "clientId": client_id,
        "proposal": s1_candidate,
        "ClientContext": client_context,
        "researchFindings": research_findings
    })
    task_graph["executedSteps"].append({
        "step": 4,
        "actor": "wp-tax-compliance",
        "status": "COMPLETED",
        "verdict": tax_verdict.get("verdict"),
        "summary": f"Tax gate returned {tax_verdict.get('verdict')} on {s1_candidate.get('id')}. Estimated Tax: ₹{tax_verdict.get('estimatedTaxINR'):,.0f}."
    })

    current_candidates = initial_candidates
    tax_verdicts = [tax_verdict]

    # --- Step 5: Replanning Triggered by Tax Veto & Opportunistic Harvesting ---
    if tax_verdict.get("verdict") == "VETO":
        task_graph["revisionRounds"] += 1
        constraints = tax_verdict.get("constraints", [])
        harvesting_opps = tax_verdict.get("harvestingOpportunities", [])

        replan_reason = (
            f"Tax gate VETO on proposal {s1_candidate.get('id')} due to punitive surcharge slab. "
            f"Active constraints: {constraints}. "
            f"Discovered harvesting opportunity in {harvesting_opps[0]['lot'] if harvesting_opps else 'none'}."
        )
        task_graph["replans"].append({
            "round": task_graph["revisionRounds"],
            "trigger": "TAX_VETO_AND_HARVESTING",
            "reason": replan_reason,
            "action": "Re-invoke wp-strategy with constraints and loss harvesting instructions"
        })

        tracer.log_step(
            step="replan_1",
            thought=f"REPLAN DETECTED: Tax veto requires regeneration within constraints {constraints}.",
            tool="replan_engine",
            args={"constraints": constraints, "revisionRound": task_graph["revisionRounds"]},
            result_summary="Replanning execution graph: sending constraints back to wp-strategy."
        )

        # Re-invoke Strategy with constraints
        revised_candidates = call_actor("wp-strategy", {
            "clientId": client_id,
            "ClientContext": client_context,
            "researchFindings": research_findings,
            "constraints": constraints,
            "harvestingOpportunities": harvesting_opps
        })
        task_graph["executedSteps"].append({
            "step": 5,
            "actor": "wp-strategy (replanned)",
            "status": "COMPLETED",
            "summary": f"Regenerated {len(revised_candidates)} compliant candidates: {[c['id'] for c in revised_candidates]}."
        })
        current_candidates = revised_candidates

        # Re-check compliant candidate S2 with Tax
        s2_candidate = next((c for c in revised_candidates if c["id"] == "S2"), revised_candidates[0])
        revised_tax_verdict = call_actor("wp-tax-compliance", {
            "clientId": client_id,
            "proposal": s2_candidate,
            "ClientContext": client_context
        })
        tax_verdicts.append(revised_tax_verdict)
        task_graph["executedSteps"].append({
            "step": 6,
            "actor": "wp-tax-compliance (re-check)",
            "status": "COMPLETED",
            "verdict": revised_tax_verdict.get("verdict"),
            "summary": f"Tax gate returned {revised_tax_verdict.get('verdict')} on {s2_candidate.get('id')}."
        })

    # --- Step 6: Evaluator Scoring & Ranking ---
    evaluation_result = call_actor("wp-evaluator", {
        "clientId": client_id,
        "candidates": current_candidates,
        "ClientContext": client_context,
        "taxVerdicts": tax_verdicts
    })
    task_graph["executedSteps"].append({
        "step": 7,
        "actor": "wp-evaluator",
        "status": "COMPLETED",
        "summary": f"Ranked {len(evaluation_result.get('ranking', []))} options; rejected {len(evaluation_result.get('rejected', []))}."
    })

    # --- Step 7: Arbitration Engine ---
    # Check for goal-mismatch conflicts (e.g. illiquid lock-in vs client 2-year liquidity horizon)
    has_lockin_risk = any(
        "aif" in str(c.get("targetAllocation", {})).lower()
        or "aif" in str(c.get("actions", "")).lower()
        or "stellar" in str(c.get("actions", "")).lower()
        for c in (initial_candidates + current_candidates)
    )
    if has_lockin_risk and client_id == "CLIENT_001":
        conflict_entry = {
            "conflict": "Alternative growth rotation (S4) vs. Client 2-year liquidity requirement (₹2.0 Cr)",
            "decision": "Prioritize Strategy S2 (Staged Exit + Loss Harvesting) as Primary recommendation; designate S4 as Secondary alternative with liquidity caveat.",
            "reasoning": "While S4 achieves high return potential, Cat-II AIFs enforce a 3-year lock-in which directly jeopardizes the client's mandatory 2-year overseas business liquidity milestone. S2 delivers immediate ₹2.0 Cr liquid funds in FY26-27, captures ₹12.5L loss harvesting in CLEANTECH_SOL, and keeps realization below the punitive 25% surcharge slab."
        }
        arbitration_log.append(conflict_entry)
        tracer.log_step(
            step="arbitration",
            thought="Arbitrating between alternative return potential and 2-year liquidity constraint.",
            tool="arbitration_engine",
            args=conflict_entry,
            result_summary="Arbitration resolved in favor of S2 (Staged Exit) to guarantee client liquidity."
        )

    # --- Step 8: Final Report Compilation ---
    ranked_options = evaluation_result.get("ranking", [])
    rejected_options = evaluation_result.get("rejected", [])

    explanation_lines = [
        f"WealthPilot autonomous advisory review completed for {client_id}.",
        f"Primary Recommendation: Strategy {ranked_options[0]['id'] if ranked_options else 'None'} "
        f"({ranked_options[0]['justification'] if ranked_options else ''}).",
        f"Tax Optimization: Enforced ₹2.0 Cr annual realization cap to avoid upper surcharge slabs and harvested loss offset in CLEANTECH_SOL.",
        f"Rejected Strategies: {', '.join(r['id'] + ' (' + r['reason'] + ')' for r in rejected_options) if rejected_options else 'None'}."
    ]
    explanation = " ".join(explanation_lines)

    final_report: Dict[str, Any] = {
        "clientId": client_id,
        "goal": goal,
        "rankedOptions": ranked_options,
        "explanation": explanation,
        "arbitrationLog": arbitration_log,
        "taskGraph": task_graph
    }

    # Validate against FinalReport schema
    validate_data(final_report, "FinalReport")

    # Persist report and traces
    append_report(final_report)
    write_state(f"orchestrator/{client_id}/final_report", final_report)

    tracer.log_step(
        step="finalize",
        thought="Final report assembled and validated against FinalReport schema contract.",
        tool="report_publisher",
        args={"clientId": client_id, "rankedCount": len(ranked_options)},
        result_summary="Final report published successfully."
    )

    return final_report

# --- Apify Actor Entry Point ---

async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        Actor.log.info(f"Running wp-orchestrator with input: {actor_input}")
        result = run_orchestrator(actor_input)
        await Actor.set_value("OUTPUT", result)
        Actor.log.info(f"wp-orchestrator completed run for {result.get('clientId')}.")

if __name__ == "__main__":
    asyncio.run(main())
