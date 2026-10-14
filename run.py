"""
WealthPilot CLI Runner
======================
Executes the autonomous multi-agent wealth advisory workflow and prints
both human-readable terminal summaries and structured JSON reports.

Usage:
    python run.py --scenario 1
    python run.py --scenario 2
    python run.py --client CLIENT_001
    python run.py --json-only
"""

import sys
import json
import argparse
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows consoles (handles Rupee symbol ₹ and emojis)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from schemas.validate import validate_data

def load_orchestrator():
    actor_path = PROJECT_ROOT / "actors" / "wp-orchestrator" / "src" / "main.py"
    spec = importlib.util.spec_from_file_location("wp_orchestrator", actor_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def print_banner():
    print("=" * 80)
    print("  WEALTHPILOT — Autonomous Multi-Agent Wealth Advisory System")
    print("  SEBI Regulatory Compliance & Indian Tax Optimization Engine")
    print("=" * 80)

def print_terminal_summary(report: dict):
    print("\n[+] 1. EXECUTION WORKFLOW COMPLETED")
    print("-" * 80)
    print(f"Client ID:            {report.get('clientId')}")
    print(f"Advisory Goal:        {report.get('goal')}")
    
    # Task Graph Steps
    tg = report.get("taskGraph", {})
    steps = tg.get("executedSteps", [])
    print(f"\n[+] 2. MULTI-AGENT TASK GRAPH ({len(steps)} steps executed):")
    for s in steps:
        step_num = s.get("step")
        actor = s.get("actor")
        status = s.get("status")
        summary = s.get("summary", "")
        print(f"  Step {step_num:<2} | {actor:<26} | [{status}] -> {summary}")

    # Replans
    replans = tg.get("replans", [])
    if replans:
        print(f"\n[!] 3. AUTONOMOUS REPLANNING LOOPS TRIGGERED ({len(replans)}):")
        for r in replans:
            print(f"  * Round {r.get('round')} Trigger: {r.get('trigger')}")
            print(f"    Reason:  {r.get('reason')}")
            print(f"    Action:  {r.get('action')}")
    else:
        print("\n[!] 3. REPLANNING LOOPS: None (Initial strategies fully compliant)")

    # Arbitrations
    arbitrations = report.get("arbitrationLog", [])
    if arbitrations:
        print(f"\n[⚖️] 4. GOAL ARBITRATION DECISIONS ({len(arbitrations)}):")
        for a in arbitrations:
            print(f"  * Conflict:  {a.get('conflict')}")
            print(f"    Decision:  {a.get('decision')}")
            print(f"    Reasoning: {a.get('reasoning')}")

    # Recommendations
    print("\n[🏆] 5. RANKED STRATEGY RECOMMENDATIONS:")
    print("-" * 80)
    for opt in report.get("rankedOptions", []):
        rank = opt.get("rank")
        sid = opt.get("id")
        score = opt.get("totalScore")
        crit = opt.get("criteria", {})
        print(f"  RANK #{rank}: Strategy {sid} (Overall Score: {score:.2f})")
        print(f"    - Post-Tax Return: {crit.get('postTaxReturn', 0):.2f} | Liquidity Fit: {crit.get('liquidity', 0):.2f}")
        print(f"    - Concentration:   {crit.get('concentration', 0):.2f} | Stress Test:   {crit.get('stress', 0):.2f}")
        print(f"    - Compliance:      {crit.get('compliance', 0):.2f}")
        print(f"    - Justification:   {opt.get('justification')}")
        print()

    # Final Explanation
    print("[📝] 6. ADVISOR EXPLANATION NARRATIVE:")
    print("-" * 80)
    print(report.get("explanation", ""))
    print("=" * 80)

def main():
    parser = argparse.ArgumentParser(description="WealthPilot Multi-Agent Runner")
    parser.add_argument("--scenario", type=int, choices=[1, 2], default=1, help="Select scenario: 1 (Promoter Tech) or 2 (Salaried Executive)")
    parser.add_argument("--client", type=str, help="Specific Client ID (e.g. CLIENT_001, CLIENT_002)")
    parser.add_argument("--input", type=str, help="Path to custom input JSON file")
    parser.add_argument("--json-only", action="store_true", help="Output only the structured JSON FinalReport")
    args = parser.parse_args()

    # Determine input payload
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            input_payload = json.load(f)
    elif args.client:
        cid = args.client.upper()
        if cid == "CLIENT_002":
            sample_file = PROJECT_ROOT / "data" / "sample_inputs" / "scenario_002_input.json"
        else:
            sample_file = PROJECT_ROOT / "data" / "sample_inputs" / "scenario_001_input.json"
        with open(sample_file, "r", encoding="utf-8") as f:
            input_payload = json.load(f)
    elif args.scenario == 2:
        sample_file = PROJECT_ROOT / "data" / "sample_inputs" / "scenario_002_input.json"
        with open(sample_file, "r", encoding="utf-8") as f:
            input_payload = json.load(f)
    else:
        sample_file = PROJECT_ROOT / "data" / "sample_inputs" / "scenario_001_input.json"
        with open(sample_file, "r", encoding="utf-8") as f:
            input_payload = json.load(f)

    # Execute Orchestrator
    orchestrator_mod = load_orchestrator()
    report = orchestrator_mod.run_orchestrator(input_payload)

    # Validate against FinalReport JSON Schema contract
    validate_data(report, "FinalReport")

    if args.json_only:
        print(json.dumps(report, indent=2))
    else:
        print_banner()
        print_terminal_summary(report)
        print("\n[>] TIP: Run with '--json-only' to inspect the exact structured JSON contract.")

if __name__ == "__main__":
    main()
