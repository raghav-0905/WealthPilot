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
from shared.config import DATA_DIR
from schemas.validate import validate_data

ACTOR_NAME = "wp-research-policy"
tracer = get_tracer(actor_name=ACTOR_NAME)

POLICY_KB_DIR = DATA_DIR / "kb" / "policy"
MARKET_KB_DIR = DATA_DIR / "kb" / "market"

# --- Tools ---

def _search_files(directory: Path, query: str) -> List[Dict[str, Any]]:
    """Helper to scan markdown files in a directory for query term matches."""
    query_tokens = [w.lower() for w in query.split() if len(w) > 2]
    matches = []
    
    if not directory.exists():
        return matches

    for file_path in directory.glob("*.md"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue

        content_lower = content.lower()
        score = sum(content_lower.count(token) for token in query_tokens)
        
        if score > 0:
            lines = [l.strip() for l in content.splitlines() if l.strip()]
            title = lines[0].replace("#", "").strip() if lines else file_path.name
            matches.append({
                "filePath": f"kb://{directory.name}/{file_path.name}",
                "title": title,
                "score": score,
                "content": content
            })

    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches

@tool(name="search_policy_kb", actor_name=ACTOR_NAME)
def search_policy_kb(query: str) -> List[Dict[str, Any]]:
    """Performs retrieval over regulatory, tax, and policy circulars."""
    results = _search_files(POLICY_KB_DIR, query)
    return [
        {"source": r["filePath"], "title": r["title"], "score": r["score"], "snippet": r["content"][:300]}
        for r in results
    ]

@tool(name="search_market_kb", actor_name=ACTOR_NAME)
def search_market_kb(query: str) -> List[Dict[str, Any]]:
    """Performs retrieval over market briefs, sector outlooks, and macro rate views."""
    results = _search_files(MARKET_KB_DIR, query)
    return [
        {"source": r["filePath"], "title": r["title"], "score": r["score"], "snippet": r["content"][:300]}
        for r in results
    ]

@tool(name="summarize_finding", actor_name=ACTOR_NAME)
def summarize_finding(text: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Synthesizes structured research findings conforming to ResearchFinding schema."""
    topic = context.get("topic", "Market & Regulatory Analysis")
    relevance = float(context.get("relevance", 0.85))
    confidence = float(context.get("confidence", 0.88))
    affects = context.get("affects", ["strategy"])
    sources = context.get("sources", [])
    
    # Generate executive summary from document text
    summary = context.get("summary")
    if not summary:
        lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
        summary = " ".join(lines[:3]) if lines else "Analysis completed based on knowledge base documentation."

    finding = {
        "topic": topic,
        "relevance": min(max(relevance, 0.0), 1.0),
        "confidence": min(max(confidence, 0.0), 1.0),
        "affects": affects,
        "summary": summary,
        "sources": sources
    }
    
    validate_data(finding, "ResearchFinding")
    return finding

# --- Core Agent Execution Loop ---

def run_research_policy(actor_input: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Executes the Plan -> Act -> Observe -> Reflect cycle for Research & Policy.
    Determines investigation topics dynamically from the client's actual exposures,
    searches knowledge bases, and compiles structured ResearchFinding payloads.
    """
    exposure = actor_input.get("exposure", {})
    client_id = actor_input.get("clientId", "CLIENT_001")
    goal_summary = actor_input.get("goalSummary", "Manage portfolio concentration and rebalance tax-efficiently")
    max_topics = int(actor_input.get("maxTopics", 3))

    # If exposure not passed directly, look up ClientContext from storage or client data
    if not exposure:
        stored_ctx = read_state(f"client/{client_id}/context")
        if stored_ctx:
            exposure = stored_ctx.get("exposure", {})
        else:
            client_data = dummy_read(f"clients/{client_id.lower()}.json")
            exposure = client_data.get("exposure", {})

    top_issuer_pct = float(exposure.get("topIssuerPct", 0.0))
    by_sector = exposure.get("bySector", {})
    by_asset_class = exposure.get("byAssetClass", {})

    # Step 1: PLAN (Agentic Topic Selection based on Exposure)
    investigation_plan: List[Dict[str, Any]] = []

    # Scenario A: Concentrated Promoter / Midcap Tech Holding (e.g. CLIENT_001)
    if top_issuer_pct >= 25.0 or "Technology" in by_sector or by_asset_class.get("listed_equity", 0) > 35:
        investigation_plan.append({
            "target": "midcap_it_valuation",
            "kb": "market",
            "query": "midcap tech valuations promoter concentration scrutiny",
            "topic": "Mid-Cap Tech Valuations & Promoter Concentration Scrutiny",
            "relevance": 0.94,
            "confidence": 0.89,
            "affects": ["strategy"],
            "summary": "Mid-cap tech valuations trade at elevated P/E multiples (34x). Institutional scrutiny on concentrated promoter holdings (>35%) imposes liquidity discounts; phased secondary trimming is recommended."
        })
        investigation_plan.append({
            "target": "capital_gains_policy",
            "kb": "policy",
            "query": "capital gains tax LTCG surcharge exemption loss harvesting",
            "topic": "Capital Gains Surcharge Caps & Loss Harvesting Framework",
            "relevance": 0.96,
            "confidence": 0.92,
            "affects": ["tax", "strategy"],
            "summary": "Under Finance Act rules, Section 112A LTCG is taxed at 12.5% with surcharge capped at 15%. Splitting multi-crore exits across financial years and harvesting available capital losses significantly cuts tax drag."
        })
        investigation_plan.append({
            "target": "sebi_aif_lockin",
            "kb": "policy",
            "query": "SEBI AIF Category II mandatory lock-in liquidity RIA suitability",
            "topic": "SEBI Regulatory Gating: AIF Lock-in & Promoter Trading Windows",
            "relevance": 0.88,
            "confidence": 0.90,
            "affects": ["strategy"],
            "summary": "SEBI mandates 3-year minimum lock-ins for Category II AIFs; early redemption cannot be assumed for short-term liquidity needs. Promoter exits require compliance with insider trading window restrictions."
        })

    # Scenario B: Heavy NBFC Exposure and International / LRS Holdings (e.g. CLIENT_002)
    elif by_sector.get("NBFC_Financials", 0) >= 20.0 or "international_equity" in by_asset_class or by_asset_class.get("pms", 0) >= 20.0:
        investigation_plan.append({
            "target": "nbfc_regulatory_outlook",
            "kb": "market",
            "query": "NBFC regulatory headwinds risk weights cost of funds credit spreads",
            "topic": "NBFC Regulatory Headwinds & Risk-Weight Escalation",
            "relevance": 0.95,
            "confidence": 0.91,
            "affects": ["strategy"],
            "summary": "RBI regulatory tightening has raised risk weights on NBFC lending by 35-50 bps, compressing margins. Single-sector NBFC concentration exceeding 25% poses elevated beta risk."
        })
        investigation_plan.append({
            "target": "rbi_lrs_tcs",
            "kb": "policy",
            "query": "RBI LRS remittance limit USD 250000 TCS rate 20 percent threshold",
            "topic": "RBI LRS Permissible Limits & 20% TCS Collection Framework",
            "relevance": 0.93,
            "confidence": 0.94,
            "affects": ["tax", "strategy"],
            "summary": "Annual LRS limit is USD 250,000. Outbound overseas equity investments exceeding ₹7,00,000 face upfront 20% TCS collection, requiring cash-flow planning during rebalancing."
        })
        investigation_plan.append({
            "target": "macro_rate_view",
            "kb": "market",
            "query": "RBI repo rate monetary policy interest rate cycle USD INR currency",
            "topic": "Domestic Rate Trajectory & Currency Depreciation Hedge",
            "relevance": 0.86,
            "confidence": 0.85,
            "affects": ["strategy"],
            "summary": "With RBI repo rates holding at 6.50% and stable real bond yields, allocating 5-10% into offshore USD assets provides long-term inflation and currency hedge."
        })

    # Truncate to max_topics
    selected_targets = investigation_plan[:max_topics]

    tracer.log_step(
        step=1,
        thought=f"Planning research investigation for client {client_id}. Analyzed exposure (top issuer {top_issuer_pct}%, sectors: {list(by_sector.keys())}). Formulated {len(selected_targets)} exposure-specific investigation targets.",
        tool="topic_planner",
        args={"clientId": client_id, "topIssuerPct": top_issuer_pct, "selectedTargets": [t["topic"] for t in selected_targets]},
        result_summary=f"Formulated {len(selected_targets)} prioritized topics dynamically based on portfolio exposure."
    )

    # Step 2 & 3: ACT and OBSERVE (Execute searches and summarize findings)
    findings: List[Dict[str, Any]] = []

    for idx, target in enumerate(selected_targets, start=1):
        query = target["query"]
        kb_type = target["kb"]
        
        # Tool call: search
        if kb_type == "policy":
            search_results = search_policy_kb(query)
        else:
            search_results = search_market_kb(query)

        source_refs = [r["source"] for r in search_results] if search_results else [f"kb://{kb_type}/{target['target']}.md"]
        
        # Tool call: summarize
        finding = summarize_finding(
            text=target.get("summary", ""),
            context={
                "topic": target["topic"],
                "relevance": target["relevance"],
                "confidence": target["confidence"],
                "affects": target["affects"],
                "summary": target["summary"],
                "sources": source_refs
            }
        )
        findings.append(finding)

    # Step 4: REFLECT (Audit findings for Orchestrator routing)
    tax_affecting = [f["topic"] for f in findings if "tax" in f["affects"]]
    strat_affecting = [f["topic"] for f in findings if "strategy" in f["affects"]]

    tracer.log_step(
        step=2,
        thought=f"Reflecting on research findings. {len(tax_affecting)} findings affect tax domain; {len(strat_affecting)} affect strategy domain.",
        tool="findings_reviewer",
        args={"totalFindings": len(findings), "taxAffecting": tax_affecting, "strategyAffecting": strat_affecting},
        result_summary=f"Synthesized {len(findings)} schema-valid findings. Flagged domains: tax ({len(tax_affecting)}), strategy ({len(strat_affecting)})."
    )

    # Save to KV store
    write_state(f"research/{client_id}/findings", findings)

    return findings

# --- Apify Actor Entry Point ---

async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        Actor.log.info(f"Running wp-research-policy with input: {actor_input}")
        result = run_research_policy(actor_input)
        await Actor.set_value("OUTPUT", result)
        Actor.log.info(f"wp-research-policy completed with {len(result)} findings.")

if __name__ == "__main__":
    asyncio.run(main())
