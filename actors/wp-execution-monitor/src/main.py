import os
import sys
import json
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

ACTOR_NAME = "wp-execution-monitor"
tracer = get_tracer(actor_name=ACTOR_NAME)

# --- Tool Definitions ---

@tool(name="submit_order", actor_name=ACTOR_NAME)
def submit_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simulates mock broker trade execution with fills, order IDs, and settlement rules.
    """
    order_id = f"ORD_{order.get('type', 'TRD')}_{abs(hash(str(order))) % 1000000:06d}"
    order_type = order.get("type", "BUY")
    asset = order.get("asset", "UNKNOWN")
    amount = float(order.get("amountINR", 0.0))
    
    # Simulate execution settlement
    settlement = "T+1" if "CO" in asset or "FUND" in asset else "T+0"
    
    return {
        "orderId": order_id,
        "type": order_type,
        "asset": asset,
        "amountINR": amount,
        "status": "FILLED",
        "fillPercentage": 100.0,
        "settlementCycle": settlement,
        "executionTimestamp": "2026-10-15T09:45:00Z"
    }

@tool(name="check_portfolio_drift", actor_name=ACTOR_NAME)
def check_portfolio_drift(
    current_allocations: Dict[str, float],
    target_allocations: Dict[str, float],
    tolerance_pct: float = 3.0
) -> Dict[str, Any]:
    """
    Compares live portfolio allocations against the approved strategic allocation target.
    Flags drift when variance on any asset class exceeds tolerance.
    """
    drift_details: Dict[str, float] = {}
    exceeded_classes: List[str] = []

    all_keys = set(current_allocations.keys()).union(set(target_allocations.keys()))
    for k in all_keys:
        curr = current_allocations.get(k, 0.0)
        targ = target_allocations.get(k, 0.0)
        diff = round(curr - targ, 2)
        drift_details[k] = diff
        if abs(diff) > tolerance_pct:
            exceeded_classes.append(k)

    max_drift = max((abs(v) for v in drift_details.values()), default=0.0)
    return {
        "maxDriftPct": max_drift,
        "driftDetails": drift_details,
        "tolerancePct": tolerance_pct,
        "driftExceeded": len(exceeded_classes) > 0,
        "flaggedAssetClasses": exceeded_classes
    }

@tool(name="read_event_feed", actor_name=ACTOR_NAME)
def read_event_feed() -> List[Dict[str, Any]]:
    """Loads trigger events feed from data/events/events.json."""
    return dummy_read("events/events.json")

@tool(name="assess_materiality", actor_name=ACTOR_NAME)
def assess_materiality(
    event: Dict[str, Any],
    portfolio_holdings: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Judges whether an external market or regulatory event is sufficiently material
    to warrant waking the Orchestrator for dynamic replanning.
    """
    event_id = event.get("eventId", "")
    event_type = event.get("eventType", "")
    affected = event.get("affectedIssuer", "")
    severity = event.get("severity", "LOW")
    
    # Check if client holds this issuer
    holding_match = next((h for h in portfolio_holdings if h.get("issuer") == affected), None)
    
    is_material = False
    action_required = "NO_ACTION"
    justification = ""

    if severity == "HIGH" and (holding_match or affected == "PROMOTER_CO"):
        is_material = True
        action_required = "WAKE_ORCHESTRATOR"
        justification = (
            f"HIGH severity event {event_type} on core holding {affected}. "
            f"Details: {event.get('details', {}).get('reason', '')}. "
            f"Breaches trigger threshold ({event.get('triggerCondition')})."
        )
    elif severity == "MEDIUM" and holding_match:
        is_material = True
        action_required = "NOTIFY_ADVISOR"
        justification = f"MEDIUM severity event {event_type} on active holding {affected}."
    else:
        justification = f"Informational {event_type} ({severity}); no portfolio rebalancing needed."

    return {
        "eventId": event_id,
        "isMaterial": is_material,
        "actionRequired": action_required,
        "affectedIssuer": affected,
        "justification": justification
    }

# --- Core Agent Execution Loop ---

def run_execution_monitor(actor_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes the Plan -> Act -> Observe -> Reflect cycle for Execution & Monitor.
    Enforces the HUMAN GATE: refuses to execute trades without approved: True.
    Simulates staged orders, calculates drift, and monitors external event triggers.
    """
    client_id = actor_input.get("clientId", "CLIENT_001")
    approved = bool(actor_input.get("approved", False))
    approved_plan = actor_input.get("approvedPlan", {})
    monitoring_config = actor_input.get("monitoringConfig", {})

    # Load ClientContext if available
    client_context = read_state(f"client/{client_id}/context")
    if not client_context:
        client_context = dummy_read(f"clients/{client_id.lower()}.json")

    holdings = client_context.get("holdings", [])

    # Step 1: Human Gate Check
    if not approved:
        tracer.log_step(
            step="human_gate_check",
            thought="Execution requested without advisor approval confirmation. Refusing trade submission.",
            tool="human_gate",
            args={"approved": approved},
            result_summary="BLOCKED: Human advisor approval (approved: true) required before trade execution."
        )
        return {
            "clientId": client_id,
            "status": "AWAITING_APPROVAL",
            "message": "Human advisor approval required (approved must be true) before trade execution.",
            "executionLog": [],
            "driftReport": {},
            "reengageRequest": None
        }

    # Step 2: Trade Execution Simulation
    tracer.log_step(
        step="execute_plan",
        thought="Advisor approval confirmed. Sequencing orders (liquidity-generating SELLs before BUYs).",
        tool="order_sequencer",
        args={"clientId": client_id, "actionsCount": len(approved_plan.get("actions", []))},
        result_summary="Sequencing approved strategy actions."
    )

    actions = approved_plan.get("actions", [])
    if not actions:
        # Fallback to sample staged actions from S2
        actions = [
            {"type": "SELL", "asset": "PROMOTER_CO", "amountINR": 20000000.0, "when": "FY26-27"},
            {"type": "SELL", "asset": "CLEANTECH_SOL", "amountINR": 2000000.0, "when": "FY26-27"},
            {"type": "BUY", "asset": "GOI_BONDS_7_18", "amountINR": 10000000.0, "when": "FY26-27"},
            {"type": "BUY", "asset": "HDFC_LARGE_CAP_FUND", "amountINR": 12000000.0, "when": "FY26-27"}
        ]

    # Sequence: SELLs first, then BUYs
    sells = [a for a in actions if a.get("type") == "SELL"]
    buys = [a for a in actions if a.get("type") != "SELL"]
    ordered_actions = sells + buys

    execution_log: List[Dict[str, Any]] = []
    for act in ordered_actions:
        res = submit_order(act)
        execution_log.append(res)

    # Step 3: Drift Monitoring
    target_alloc = approved_plan.get("targetAllocation", {
        "listed_equity": 21.33,
        "mutual_funds": 20.83,
        "pms": 15.0,
        "aif": 10.0,
        "debt_fixed_income": 20.33,
        "real_estate": 8.33,
        "unlisted_equity": 4.17
    })
    # Simulated current allocation after partial execution
    current_simulated = dict(target_alloc)
    current_simulated["listed_equity"] += 1.2
    current_simulated["mutual_funds"] -= 1.2

    drift_report = check_portfolio_drift(
        current_allocations=current_simulated,
        target_allocations=target_alloc,
        tolerance_pct=float(monitoring_config.get("tolerancePct", 3.0))
    )

    # Step 4: Event Sentinel & Re-engagement Evaluation
    events = read_event_feed()
    reengage_request: Optional[Dict[str, Any]] = None

    for evt in events:
        materiality = assess_materiality(evt, holdings)
        if materiality["isMaterial"] and materiality["actionRequired"] == "WAKE_ORCHESTRATOR":
            reengage_request = {
                "reengageRequired": True,
                "eventId": evt.get("eventId"),
                "eventType": evt.get("eventType"),
                "affectedIssuer": evt.get("affectedIssuer"),
                "urgency": "HIGH",
                "reason": materiality["justification"],
                "recommendedAction": "Wake Orchestrator for dynamic replan and risk budget recalculation."
            }
            break

    result: Dict[str, Any] = {
        "clientId": client_id,
        "status": "EXECUTED_AND_MONITORING",
        "executionLog": execution_log,
        "driftReport": drift_report,
        "reengageRequest": reengage_request
    }

    tracer.log_step(
        step="sentinel_complete",
        thought=f"Execution completed ({len(execution_log)} trades). Sentinel detected event: {reengage_request['eventId'] if reengage_request else 'None'}.",
        tool="monitor_summary",
        args={"executedTrades": len(execution_log), "reengageRequired": bool(reengage_request)},
        result_summary=f"Execution verified. Reengage required: {bool(reengage_request)}."
    )

    write_state(f"execution/{client_id}/monitor_state", result)
    return result

# --- Apify Actor Entry Point ---

async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        Actor.log.info(f"Running wp-execution-monitor with input: {actor_input}")
        result = run_execution_monitor(actor_input)
        await Actor.set_value("OUTPUT", result)
        Actor.log.info(f"wp-execution-monitor status: {result.get('status')}.")

if __name__ == "__main__":
    asyncio.run(main())
