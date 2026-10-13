import pytest
import sys
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.storage import clear_local_storage
from schemas.validate import validate_data

def load_actor_module(actor_dir_name: str):
    actor_path = PROJECT_ROOT / "actors" / actor_dir_name / "src" / "main.py"
    spec = importlib.util.spec_from_file_location(actor_dir_name.replace("-", "_"), actor_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

client_context_mod = load_actor_module("wp-client-context")
research_policy_mod = load_actor_module("wp-research-policy")
strategy_mod = load_actor_module("wp-strategy")
tax_compliance_mod = load_actor_module("wp-tax-compliance")
evaluator_mod = load_actor_module("wp-evaluator")
orchestrator_mod = load_actor_module("wp-orchestrator")

@pytest.fixture(autouse=True)
def clean_storage():
    clear_local_storage()
    yield
    clear_local_storage()

def test_scenario_002_end_to_end():
    """
    Validates complete Scenario 002 execution for Salaried Executive persona:
    - Context reconciliation of NBFC exposure and foreign LRS holdings
    - Differentiated research targeting (NBFC risk weights, RBI LRS caps)
    - Distinct candidate generation (NBFC rotation, LRS expansion, balanced growth)
    - Clean tax compliance approval (no false-positive promoter veto)
    - Independent evaluator scoring and ranking
    - Final report validation against FinalReport schema
    """
    report = orchestrator_mod.run_orchestrator({
        "clientId": "CLIENT_002",
        "goal": "De-risk NBFC exposure and diversify globally via RBI LRS window while maintaining wealth compounding.",
        "maxRevisionRounds": 3
    })

    # 1. Validate FinalReport schema conformance
    assert validate_data(report, "FinalReport") is True
    assert report["clientId"] == "CLIENT_002"
    assert len(report["rankedOptions"]) == 3

    # 2. Check ranked candidates
    ranked_ids = [opt["id"] for opt in report["rankedOptions"]]
    assert "S1_NBFC_ROTATION" in ranked_ids
    assert "S2_LRS_EXPANSION" in ranked_ids
    assert "S3_BALANCED_GROWTH" in ranked_ids

    # Top recommendation should be S1_NBFC_ROTATION
    top_option = report["rankedOptions"][0]
    assert top_option["id"] == "S1_NBFC_ROTATION"
    assert top_option["rank"] == 1
    assert top_option["totalScore"] >= 0.85

    # 3. Assert no false-positive vetoes or replans occurred
    replans = report["taskGraph"].get("replans", [])
    assert len(replans) == 0, "Scenario 002 should execute cleanly without tax vetoes"

    # 4. Check dynamic explanation synthesis
    explanation = report["explanation"]
    assert "CLIENT_002" in explanation
    assert "S1_NBFC_ROTATION" in explanation
    assert "Verified compliance" in explanation or "compliance" in explanation.lower()
    assert "Rejected Strategies: None" in explanation

def test_scenario_002_research_differentiation():
    """Verifies research-policy selects macro/regulatory topics tailored to NBFC/LRS exposure."""
    findings = research_policy_mod.run_research_policy({
        "clientId": "CLIENT_002",
        "exposure": {
            "bySector": {"NBFC_Financials": 30.0, "Global_Equities": 8.0},
            "byAssetClass": {"listed_equity": 30.0, "international_equity": 8.0, "pms": 25.0},
            "topIssuerPct": 20.0
        },
        "goalSummary": "De-risk NBFC exposure and increase international allocation via LRS"
    })

    assert len(findings) == 3
    for f in findings:
        assert validate_data(f, "ResearchFinding") is True

    topics = [f["topic"] for f in findings]
    
    # Must investigate NBFC headwinds and LRS/TCS limits
    assert any("NBFC" in t for t in topics), "Expected NBFC research topic"
    assert any("LRS" in t for t in topics), "Expected LRS research topic"
    assert any("Rate Trajectory" in t or "Currency" in t for t in topics), "Expected Macro/Rate research topic"

    # Must NOT select CLIENT_001 topics (Tech concentration / promoter surcharge)
    assert not any("Mid-Cap Tech" in t for t in topics)
    assert not any("Promoter Concentration" in t for t in topics)

def test_scenario_002_strategy_generation():
    """Verifies strategy generator produces distinct, non-promoter strategies for CLIENT_002."""
    candidates = strategy_mod.run_strategy({"clientId": "CLIENT_002"})
    assert len(candidates) == 3

    for c in candidates:
        assert validate_data(c, "CandidateStrategy") is True

    candidate_ids = [c["id"] for c in candidates]
    assert candidate_ids == ["S1_NBFC_ROTATION", "S2_LRS_EXPANSION", "S3_BALANCED_GROWTH"]

    # Verify actions affect Bajaj Finance and Cholamandalam
    s1 = next(c for c in candidates if c["id"] == "S1_NBFC_ROTATION")
    sold_assets = [a["asset"] for a in s1["actions"] if a["type"] == "SELL"]
    assert "BAJAJ_FINANCE" in sold_assets
    assert "CHOLAMANDALAM_INV" in sold_assets

    # Verify S2 expands Vanguard USD ETF
    s2 = next(c for c in candidates if c["id"] == "S2_LRS_EXPANSION")
    bought_assets = [a["asset"] for a in s2["actions"] if a["type"] == "BUY"]
    assert "VANGUARD_TOTAL_WORLD_ETF_USD" in bought_assets

def test_scenario_002_tax_compliance_clean_approval():
    """Verifies tax gate approves valid NBFC rotation without false vetoes."""
    s1 = {
        "id": "S1_NBFC_ROTATION",
        "actions": [
            {
                "type": "SELL",
                "asset": "BAJAJ_FINANCE",
                "assetClass": "listed_equity",
                "amountINR": 8000000.0,
                "costBasisINR": 4000000.0,
                "holdingPeriodMonths": 36
            }
        ]
    }
    verdict = tax_compliance_mod.run_tax_compliance({
        "clientId": "CLIENT_002",
        "proposal": s1
    })

    assert validate_data(verdict, "TaxVerdict") is True
    assert verdict["verdict"] in ["APPROVE", "APPROVE_WITH_CONDITIONS"]
    assert verdict["estimatedTaxINR"] > 0
    assert len(verdict["complianceFlags"]) == 0
