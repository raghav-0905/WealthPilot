import pytest
import sys
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.storage import read_state, clear_local_storage, TRACE_DATASET_DIR
from schemas.validate import validate_data

# Helper to dynamically load actor main modules
def load_actor_module(actor_dir_name: str):
    actor_path = PROJECT_ROOT / "actors" / actor_dir_name / "src" / "main.py"
    spec = importlib.util.spec_from_file_location(actor_dir_name, actor_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

client_context_mod = load_actor_module("wp-client-context")
research_policy_mod = load_actor_module("wp-research-policy")
tax_compliance_mod = load_actor_module("wp-tax-compliance")

@pytest.fixture(autouse=True)
def clean_storage():
    clear_local_storage()
    yield
    clear_local_storage()

def test_client_context_contract():
    # Execute client context for CLIENT_001
    ctx = client_context_mod.run_client_context({"clientId": "CLIENT_001"})
    
    # 1. Validate schema conformance
    assert validate_data(ctx, "ClientContext") is True

    # 2. Verify required fields and contract properties
    assert ctx["clientId"] == "CLIENT_001"
    assert ctx["netWorthINR"] == 120000000.0
    assert len(ctx["holdings"]) >= 5
    assert ctx["exposure"]["topIssuerPct"] == 38.0
    assert ctx["riskProfile"] == "moderate"
    assert "confidence" in ctx and ctx["confidence"] > 0
    assert "reasoningSummary" in ctx and len(ctx["reasoningSummary"]) > 0

    # 3. Verify scenario flags
    assert any("45 days old" in f for f in ctx["dataQualityFlags"])
    assert any("38.0%" in f for f in ctx["profileConsistencyFlags"])

    # 4. Verify contract for CLIENT_002
    ctx2 = client_context_mod.run_client_context({"clientId": "CLIENT_002"})
    assert validate_data(ctx2, "ClientContext") is True
    assert ctx2["clientId"] == "CLIENT_002"
    assert ctx2["netWorthINR"] == 80000000.0
    assert any("NBFC" in f for f in ctx2["profileConsistencyFlags"])

def test_research_policy_contract():
    # Execute research for CLIENT_001
    findings_1 = research_policy_mod.run_research_policy({"clientId": "CLIENT_001"})
    assert len(findings_1) >= 2
    for f in findings_1:
        assert validate_data(f, "ResearchFinding") is True
        assert 0.0 <= f["relevance"] <= 1.0
        assert 0.0 <= f["confidence"] <= 1.0
        assert isinstance(f["affects"], list)
        assert len(f["sources"]) > 0

    # Execute research for CLIENT_002
    findings_2 = research_policy_mod.run_research_policy({"clientId": "CLIENT_002"})
    assert len(findings_2) >= 2
    for f in findings_2:
        assert validate_data(f, "ResearchFinding") is True

    # Verify exposure-driven topic differentiation
    topics_1 = [f["topic"] for f in findings_1]
    topics_2 = [f["topic"] for f in findings_2]
    assert topics_1 != topics_2
    assert any("Mid-Cap" in t or "Promoter" in t for t in topics_1)
    assert any("NBFC" in t or "LRS" in t for t in topics_2)

def test_tax_compliance_contract():
    # 1. Over-limit sale proposal: sell 60% of PROMOTER_CO
    over_limit_proposal = {
        "id": "S1_OVER_LIMIT",
        "actions": [
            {
                "type": "SELL",
                "asset": "PROMOTER_CO",
                "assetClass": "listed_equity",
                "amountINR": 27360000.0,
                "costBasisINR": 3648000.0,
                "holdingPeriodMonths": 48
            }
        ]
    }
    verdict = tax_compliance_mod.run_tax_compliance({
        "clientId": "CLIENT_001",
        "proposal": over_limit_proposal
    })

    # Validate against TaxVerdict schema
    assert validate_data(verdict, "TaxVerdict") is True
    assert verdict["verdict"] == "VETO"
    assert verdict["estimatedTaxINR"] > 0
    assert len(verdict["constraints"]) > 0
    assert any("2.0 Cr" in c for c in verdict["constraints"])
    assert any("breaches" in f or "exceeds" in f for f in verdict["complianceFlags"])
    assert len(verdict["harvestingOpportunities"]) > 0
    assert any(h["lot"] == "CLEANTECH_SOL" for h in verdict["harvestingOpportunities"])

    # 2. Compliant proposal within ₹2.0 Cr
    compliant_proposal = {
        "id": "S2_COMPLIANT",
        "actions": [
            {
                "type": "SELL",
                "asset": "PROMOTER_CO",
                "assetClass": "listed_equity",
                "amountINR": 20000000.0,
                "costBasisINR": 2666667.0,
                "holdingPeriodMonths": 48
            }
        ]
    }
    comp_verdict = tax_compliance_mod.run_tax_compliance({
        "clientId": "CLIENT_001",
        "proposal": compliant_proposal
    })
    assert validate_data(comp_verdict, "TaxVerdict") is True
    assert comp_verdict["verdict"] in ("APPROVE", "APPROVE_WITH_CONDITIONS")

def test_back_to_back_execution_no_collision():
    # Run all three actors in sequence
    ctx = client_context_mod.run_client_context({"clientId": "CLIENT_001"})
    findings = research_policy_mod.run_research_policy({"clientId": "CLIENT_001", "exposure": ctx["exposure"]})
    verdict = tax_compliance_mod.run_tax_compliance({
        "clientId": "CLIENT_001",
        "ClientContext": ctx,
        "researchFindings": findings
    })

    # Assert distinct keys persist without colliding in KV store
    stored_ctx = read_state("client/CLIENT_001/context")
    stored_mem = read_state("client/CLIENT_001/memory")
    stored_findings = read_state("research/CLIENT_001/findings")
    stored_verdict = read_state("tax/CLIENT_001/verdict")

    assert stored_ctx is not None and stored_ctx["netWorthINR"] == 120000000.0
    assert stored_mem is not None and stored_mem["topIssuerPct"] == 38.0
    assert stored_findings is not None and len(stored_findings) >= 2
    assert stored_verdict is not None and stored_verdict["verdict"] == "VETO"

def test_trace_logging_for_tool_calls():
    # Run actors and check that trace files were generated and validate against schema
    client_context_mod.run_client_context({"clientId": "CLIENT_001"})
    research_policy_mod.run_research_policy({"clientId": "CLIENT_001"})
    tax_compliance_mod.run_tax_compliance({"clientId": "CLIENT_001"})

    trace_files = list(TRACE_DATASET_DIR.glob("*.json"))
    assert len(trace_files) >= 6, f"Expected at least 6 trace entries, found {len(trace_files)}"

    import json
    actors_found = set()
    tools_found = set()

    for tf in trace_files:
        with open(tf, "r", encoding="utf-8") as f:
            entry = json.load(f)
        assert validate_data(entry, "TraceEntry") is True
        actors_found.add(entry["actor"])
        tools_found.add(entry["tool"])

    # Verify all 3 actors logged traces
    assert "wp-client-context" in actors_found
    assert "wp-research-policy" in actors_found
    assert "wp-tax-compliance" in actors_found

    # Verify specific tools were traced
    assert "read_broker_csv" in tools_found or "data_aggregator" in tools_found
    assert "search_market_kb" in tools_found or "search_policy_kb" in tools_found
    assert "check_suitability_tool" in tools_found or "calc_ltcg_tool" in tools_found
