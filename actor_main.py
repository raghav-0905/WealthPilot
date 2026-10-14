"""
WealthPilot — Apify Actor Main Entrypoint
==========================================
Unified multi-agent orchestrator entrypoint for Apify container runs.
Fetches input parameters via Actor.get_input(), runs the complete
autonomous multi-agent advisory loop, validates the schema contract,
and exports the FinalReport to the Apify Dataset and Key-Value Store.
"""

import sys
import os
import json
import asyncio
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from apify import Actor
from run import load_orchestrator
from schemas.validate import validate_data


async def main() -> None:
    async with Actor:
        # 1. Ingest input from Apify Actor invocation
        actor_input = await Actor.get_input() or {}
        Actor.log.info(f"WealthPilot initialized. Raw input received: {actor_input}")

        client_id = actor_input.get("clientId", "CLIENT_001")
        goal = actor_input.get(
            "goal",
            "Reduce concentration in own company stock tax-efficiently; need ₹2 Cr liquidity in 2 years."
        )
        max_revision_rounds = int(actor_input.get("maxRevisionRounds", 3))

        Actor.log.info(f"Target Client Mandate: {client_id}")
        Actor.log.info(f"Advisory Goal: {goal}")
        Actor.log.info(f"Max Feedback Rounds: {max_revision_rounds}")

        # 2. Invoke Autonomous Supervisory Orchestrator
        orchestrator_module = load_orchestrator()
        report = orchestrator_module.run_orchestrator({
            "clientId": client_id,
            "goal": goal,
            "maxRevisionRounds": max_revision_rounds
        })

        # 3. Validate against SEBI & Platform FinalReport JSON Schema contract
        validate_data(report, "FinalReport")
        Actor.log.info("FinalReport validated successfully against JSON schema.")

        # 4. Save results to Apify Dataset & Default Key-Value Store
        await Actor.push_data(report)
        await Actor.set_value("OUTPUT", report)
        Actor.log.info("Autonomous multi-agent advisory run completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())
