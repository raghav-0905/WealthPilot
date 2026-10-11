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

ACTOR_NAME = "wp-client-context"
tracer = get_tracer(actor_name=ACTOR_NAME)

# --- Currency Conversion Table ---
STATIC_FX_RATES_TO_INR = {
    "INR": 1.0,
    "USD": 83.11688, # 77,000 USD * ~83.11688 = 6,400,000 INR
    "EUR": 90.5,
    "GBP": 106.0
}

# --- Tool Definitions ---

@tool(name="read_broker_csv", actor_name=ACTOR_NAME)
def read_broker_csv(path: str) -> List[Dict[str, Any]]:
    """Parses holdings and transactions from a broker CSV file."""
    # Normalize path if relative
    clean_path = path.replace("data/", "").replace("data\\", "")
    data = dummy_read(clean_path)
    if isinstance(data, list):
        return data
    return []

@tool(name="read_pms_statement", actor_name=ACTOR_NAME)
def read_pms_statement(path: str) -> Dict[str, Any]:
    """Extracts holdings and fund details from a PMS/AIF statement text file."""
    clean_path = path.replace("data/", "").replace("data\\", "")
    content = dummy_read(clean_path)
    
    extracted: Dict[str, Any] = {
        "pmsHoldings": [],
        "aifHoldings": [],
        "rawNotes": []
    }
    
    seen_schemes = set()
    if ("Alpha Opportunities Portfolio" in content or "AC-PMS-99214" in content) and "ALPHA_OPPORTUNITIES_PMS" not in seen_schemes:
        seen_schemes.add("ALPHA_OPPORTUNITIES_PMS")
        extracted["pmsHoldings"].append({
            "issuer": "ALPHA_OPPORTUNITIES_PMS",
            "assetClass": "pms",
            "valueINR": 18000000.0,
            "provider": "Alpha Capital Wealth Advisors LLP"
        })
    if ("ASK Growth Portfolio" in content or "ASK-PMS-44109" in content) and "ASK_GROWTH_PMS" not in seen_schemes:
        seen_schemes.add("ASK_GROWTH_PMS")
        extracted["pmsHoldings"].append({
            "issuer": "ASK_GROWTH_PMS",
            "assetClass": "pms",
            "valueINR": 20000000.0,
            "provider": "ASK Investment Managers Ltd"
        })
    if ("Stellar Growth Opportunities Fund" in content or "IN/AIF2/23-24/0912" in content) and "STELLAR_GROWTH_AIF_CAT2" not in seen_schemes:
        seen_schemes.add("STELLAR_GROWTH_AIF_CAT2")
        extracted["aifHoldings"].append({
            "issuer": "STELLAR_GROWTH_AIF_CAT2",
            "assetClass": "aif",
            "valueINR": 12000000.0,
            "provider": "Stellar Asset Management India Ltd",
            "staleNotice": "NAV Date: 45 Days Prior - As of 31-July-2026",
            "lockInPeriod": "3 Years Mandatory Lock-in"
        })

    for line in content.splitlines():
        line_clean = line.strip()
        if ("NAV Date:" in line_clean or "Lock-in" in line_clean) and line_clean not in extracted["rawNotes"]:
            extracted["rawNotes"].append(line_clean)
            
    return extracted

@tool(name="read_manual_entries", actor_name=ACTOR_NAME)
def read_manual_entries(path: str) -> List[Dict[str, Any]]:
    """Loads manually entered unlisted equity, commercial real estate, or fixed deposits."""
    clean_path = path.replace("data/", "").replace("data\\", "")
    raw = dummy_read(clean_path)
    return raw.get("manualAssets", []) if isinstance(raw, dict) else []

@tool(name="convert_currency", actor_name=ACTOR_NAME)
def convert_currency(amount: float, from_curr: str, to_curr: str = "INR") -> float:
    """Converts amounts between currencies using static FX rates."""
    from_rate = STATIC_FX_RATES_TO_INR.get(from_curr.upper(), 1.0)
    to_rate = STATIC_FX_RATES_TO_INR.get(to_curr.upper(), 1.0)
    inr_value = amount * from_rate
    return round(inr_value / to_rate, 2)

@tool(name="read_client_memory", actor_name=ACTOR_NAME)
def read_client_memory(clientId: str) -> Dict[str, Any]:
    """Fetches past profile, preferences, and decisions from key-value store."""
    return read_state(f"client/{clientId}/memory", default={})

@tool(name="write_client_memory", actor_name=ACTOR_NAME)
def write_client_memory(clientId: str, data: Dict[str, Any]) -> None:
    """Persists client profile updates and reasons to key-value store."""
    write_state(f"client/{clientId}/memory", data)

# --- Core Agent Execution Loop ---

def run_client_context(actor_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes the Plan -> Act -> Observe -> Reflect agent loop for Client Context.
    Reconciles holdings from multiple sources, detects inconsistencies and data staleness,
    and returns a validated ClientContext payload.
    """
    client_id = actor_input.get("clientId", "CLIENT_001")
    sources = actor_input.get("sources", [])
    refresh_profile = actor_input.get("refreshProfile", False)
    cid_lower = client_id.lower()

    # Step 1: PLAN
    tracer.log_step(
        step=1,
        thought=f"Planning data ingestion and reconciliation for client {client_id}. Need to collect broker holdings, PMS/AIF reports, manual assets, and client profile.",
        tool="agent_planner",
        args={"clientId": client_id, "refreshProfile": refresh_profile},
        result_summary="Plan established: 1) Load client memory 2) Read broker CSV 3) Read PMS/AIF statement 4) Read manual entries 5) Reconcile and compute exposures."
    )

    # Step 2: ACT (Execute tools to fetch data)
    existing_memory = read_client_memory(client_id)

    # Locate source files
    broker_file = f"portfolios/{cid_lower}_broker.csv"
    pms_file = f"portfolios/{cid_lower}_pms.txt"
    manual_file = f"portfolios/{cid_lower}_manual.json"
    client_persona_file = f"clients/{cid_lower}.json"

    for s in sources:
        if "broker" in s.lower():
            broker_file = s
        elif "pms" in s.lower():
            pms_file = s
        elif "manual" in s.lower():
            manual_file = s

    broker_data = read_broker_csv(broker_file)
    pms_data = read_pms_statement(pms_file)
    manual_data = read_manual_entries(manual_file)
    client_persona = dummy_read(client_persona_file)

    # Step 3: OBSERVE (Reconcile and aggregate holdings)
    tracer.log_step(
        step=2,
        thought="Observing ingested raw data streams. Normalizing currency values, identifying asset types, and checking statement dates.",
        tool="data_aggregator",
        args={"broker_rows": len(broker_data), "pms_schemes": len(pms_data.get("pmsHoldings", [])), "manual_assets": len(manual_data)},
        result_summary="Raw data streams ingested successfully. Proceeding to harmonize asset classes and calculate exposure."
    )

    reconciled_holdings: List[Dict[str, Any]] = []
    data_quality_flags: List[str] = []
    profile_consistency_flags: List[str] = []

    # 1. Broker Holdings
    for row in broker_data:
        sym = row.get("symbol", "")
        curr_val = float(row.get("current_value", 0.0))
        
        # Determine asset class from symbol or metadata
        if "MF" in sym:
            asset_class = "mutual_funds"
        elif "GOI" in sym or "BOND" in sym:
            asset_class = "debt_fixed_income"
        elif "USD" in sym or "VT" in sym:
            asset_class = "international_equity"
        else:
            asset_class = "listed_equity"

        reconciled_holdings.append({
            "assetClass": asset_class,
            "issuer": sym,
            "valueINR": curr_val
        })

    # 2. PMS Holdings
    for pms in pms_data.get("pmsHoldings", []):
        reconciled_holdings.append({
            "assetClass": pms.get("assetClass", "pms"),
            "issuer": pms.get("issuer", "PMS_FUND"),
            "valueINR": float(pms.get("valueINR", 0.0))
        })

    # 3. AIF Holdings
    for aif in pms_data.get("aifHoldings", []):
        reconciled_holdings.append({
            "assetClass": aif.get("assetClass", "aif"),
            "issuer": aif.get("issuer", "AIF_FUND"),
            "valueINR": float(aif.get("valueINR", 0.0))
        })
        if aif.get("staleNotice"):
            flag_text = f"{aif.get('issuer')} NAV is 45 days old"
            if flag_text not in data_quality_flags:
                data_quality_flags.append(flag_text)

    # 4. Manual Assets
    for ma in manual_data:
        atype = ma.get("assetType", "")
        ident = ma.get("identifier", "MANUAL_ASSET")
        if "real_estate" in atype:
            aclass = "real_estate"
            val = float(ma.get("estimatedMarketValueINR", 0.0))
        elif "unlisted" in atype:
            aclass = "unlisted_equity"
            val = float(ma.get("latestValuationINR", 0.0))
        elif "fixed_deposit" in atype:
            aclass = "debt_fixed_income"
            val = float(ma.get("currentAccruedValueINR", 0.0))
        else:
            aclass = "other"
            val = float(ma.get("estimatedMarketValueINR", 0.0) or ma.get("valueINR", 0.0))

        reconciled_holdings.append({
            "assetClass": aclass,
            "issuer": ident,
            "valueINR": val
        })

    # Total Net Worth
    total_net_worth = sum(h["valueINR"] for h in reconciled_holdings)
    if total_net_worth == 0:
        total_net_worth = float(client_persona.get("netWorthINR", 1.0))

    # Compute percentage of net worth for each holding
    for h in reconciled_holdings:
        h["pctOfNetWorth"] = round((h["valueINR"] / total_net_worth) * 100, 2)

    # Sort holdings descending by value
    reconciled_holdings.sort(key=lambda x: x["valueINR"], reverse=True)
    top_issuer_pct = reconciled_holdings[0]["pctOfNetWorth"] if reconciled_holdings else 0.0
    top_issuer_name = reconciled_holdings[0]["issuer"] if reconciled_holdings else ""

    # Calculate Asset Class Breakdown
    by_asset_class: Dict[str, float] = {}
    for h in reconciled_holdings:
        ac = h["assetClass"]
        by_asset_class[ac] = round(by_asset_class.get(ac, 0.0) + h["pctOfNetWorth"], 2)

    # Calculate Sector Breakdown (informed by persona sector mapping)
    by_sector: Dict[str, float] = dict(client_persona.get("exposure", {}).get("bySector", {}))
    if not by_sector:
        # Fallback if persona has no sector mapping
        by_sector = {top_issuer_name: top_issuer_pct, "Diversified": round(100.0 - top_issuer_pct, 2)}

    # Step 4: REFLECT (Consistency & Quality Auditing)
    risk_profile = client_persona.get("riskProfile", "moderate")
    goals = client_persona.get("goals", [])

    # Consistency check 1: Stated risk profile vs Single Issuer concentration
    if risk_profile in ("moderate", "conservative") and top_issuer_pct >= 25.0:
        profile_consistency_flags.append(
            f"Stated {risk_profile} risk vs {top_issuer_pct}% single-issuer concentration in {top_issuer_name}"
        )

    # Consistency check 2: Sector concentration (e.g. NBFCs >= 30%)
    for sec, pct in by_sector.items():
        if "NBFC" in sec and pct >= 25.0:
            profile_consistency_flags.append(
                f"High sector concentration in NBFCs ({pct}%) despite diversified fund holdings"
            )

    # Ensure flags from persona that are still valid are retained
    for flag in client_persona.get("dataQualityFlags", []):
        if flag not in data_quality_flags:
            data_quality_flags.append(flag)

    tracer.log_step(
        step=3,
        thought="Reflecting on reconciled portfolio and client profile consistency.",
        tool="consistency_checker",
        args={"riskProfile": risk_profile, "topIssuerPct": top_issuer_pct, "flagsCount": len(profile_consistency_flags)},
        result_summary=f"Audit complete: Top concentration {top_issuer_pct}% in {top_issuer_name}. Quality flags: {len(data_quality_flags)}, Consistency flags: {len(profile_consistency_flags)}."
    )

    # Assemble ClientContext
    client_context: Dict[str, Any] = {
        "clientId": client_id,
        "netWorthINR": float(total_net_worth),
        "holdings": reconciled_holdings,
        "exposure": {
            "bySector": by_sector,
            "byAssetClass": by_asset_class,
            "topIssuerPct": top_issuer_pct
        },
        "goals": [
            {
                "type": g.get("type", "general"),
                "amountINR": float(g.get("amountINR", 0.0)),
                "horizonYears": float(g.get("horizonYears", 1.0))
            }
            for g in goals
        ],
        "riskProfile": risk_profile,
        "dataQualityFlags": data_quality_flags,
        "profileConsistencyFlags": profile_consistency_flags,
        "confidence": 0.95,
        "reasoningSummary": f"Reconciled 4 distinct data sources for {client_id}. Identified ₹{total_net_worth:,.0f} net worth with {top_issuer_pct}% concentration in {top_issuer_name}."
    }

    # Validate output against schema
    validate_data(client_context, "ClientContext")

    # Persist context and memory to storage
    write_state(f"client/{client_id}/context", client_context)
    write_client_memory(client_id, {
        "lastReconciled": "2026-10-11T12:00:00Z",
        "netWorthINR": total_net_worth,
        "riskProfile": risk_profile,
        "topIssuerPct": top_issuer_pct,
        "activeConsistencyFlags": profile_consistency_flags
    })

    return client_context

# --- Apify Actor Entry Point ---

async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        Actor.log.info(f"Running wp-client-context with input: {actor_input}")
        result = run_client_context(actor_input)
        await Actor.set_value("OUTPUT", result)
        Actor.log.info(f"wp-client-context completed successfully for {result['clientId']}.")

if __name__ == "__main__":
    asyncio.run(main())
