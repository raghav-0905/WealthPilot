import os
import sys
import json
import jsonschema

SCHEMAS_DIR = os.path.dirname(os.path.abspath(__file__))

def load_schema(schema_name: str) -> dict:
    if not schema_name.endswith('.schema.json'):
        schema_file = f"{schema_name}.schema.json"
    else:
        schema_file = schema_name
    schema_path = os.path.join(SCHEMAS_DIR, schema_file)
    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)

def validate_data(data: dict, schema_name: str) -> bool:
    schema = load_schema(schema_name)
    jsonschema.validate(instance=data, schema=schema)
    return True

def run_tests():
    sample_client_context = {
        "clientId": "CLIENT_001",
        "netWorthINR": 120000000,
        "holdings": [
            {
                "assetClass": "listed_equity",
                "issuer": "PROMOTER_CO",
                "valueINR": 45600000,
                "pctOfNetWorth": 38.0
            }
        ],
        "exposure": {
            "bySector": {"Technology": 38.0},
            "byAssetClass": {"listed_equity": 38.0},
            "topIssuerPct": 38.0
        },
        "goals": [
            {
                "type": "liquidity",
                "amountINR": 20000000,
                "horizonYears": 2
            }
        ],
        "riskProfile": "moderate",
        "dataQualityFlags": ["AIF_X NAV is 45 days old"],
        "profileConsistencyFlags": ["Stated moderate risk vs 38% single-issuer exposure"]
    }

    sample_research_finding = {
        "topic": "Surcharge / capital gains rule change",
        "relevance": 0.91,
        "confidence": 0.8,
        "affects": ["tax", "strategy"],
        "summary": "Recent budget announcements introduce changes to surcharge on LTCG.",
        "sources": ["kb://policy/budget_summary_example"]
    }

    sample_candidate_strategy = {
        "id": "S2",
        "name": "Staged exit over two financial years",
        "actions": [
            {
                "type": "SELL",
                "asset": "PROMOTER_CO",
                "amountINR": 20000000,
                "when": "FY26-27"
            }
        ],
        "targetAllocation": {"equity": 0.5, "debt": 0.5},
        "expectedRiskMetrics": {
            "topIssuerPctAfter": 24.0,
            "stressLoss": -0.11
        },
        "rationale": "Mitigate immediate tax impact while cutting single-issuer risk."
    }

    sample_tax_verdict = {
        "verdict": "APPROVE_WITH_CONDITIONS",
        "estimatedTaxINR": 2450000,
        "harvestingOpportunities": [
            {
                "lot": "LOT_XYZ",
                "lossINR": 310000
            }
        ],
        "constraints": [
            "Limit sale of PROMOTER_CO to ₹2.0 Cr in FY; remainder next FY"
        ],
        "complianceFlags": [],
        "reasoning": "Large sale in single year breaches higher surcharge slab."
    }

    sample_evaluation_result = {
        "ranking": [
            {
                "id": "S2",
                "rank": 1,
                "totalScore": 0.82,
                "criteria": {
                    "postTaxReturn": 0.74,
                    "liquidity": 0.9,
                    "concentration": 0.85,
                    "stress": 0.8
                },
                "justification": "Optimal balance between liquidity requirement and tax impact."
            }
        ],
        "rejected": [
            {
                "id": "S1",
                "reason": "Tax cost exceeds client's stated tolerance"
            }
        ]
    }

    sample_final_report = {
        "clientId": "CLIENT_001",
        "goal": "Reduce concentration in my own company stock tax-efficiently",
        "rankedOptions": [sample_evaluation_result["ranking"][0]],
        "explanation": "Staged exit plan satisfies 2-year liquidity need without high tax surcharge.",
        "arbitrationLog": [
            {
                "conflict": "Tax hit vs Concentration Risk",
                "decision": "Split sale across 2 FYs",
                "reasoning": "Saves ₹45L in tax while reducing exposure to 24%."
            }
        ],
        "taskGraph": {
            "steps": ["context", "research", "strategy", "tax", "evaluate"]
        }
    }

    sample_trace_entry = {
        "actor": "wp-orchestrator",
        "step": 1,
        "thought": "Decomposing goal into task graph",
        "tool": "Actor.call",
        "args": {"actorName": "wp-client-context", "clientId": "CLIENT_001"},
        "result_summary": "Retrieved ClientContext successfully",
        "timestamp": "2026-10-11T14:50:00Z"
    }

    test_cases = [
        ("ClientContext", sample_client_context),
        ("ResearchFinding", sample_research_finding),
        ("CandidateStrategy", sample_candidate_strategy),
        ("TaxVerdict", sample_tax_verdict),
        ("EvaluationResult", sample_evaluation_result),
        ("FinalReport", sample_final_report),
        ("TraceEntry", sample_trace_entry)
    ]

    print("Running schema validation tests...")
    all_passed = True
    for schema_name, payload in test_cases:
        try:
            validate_data(payload, schema_name)
            print(f"  [PASS] {schema_name}")
        except Exception as e:
            print(f"  [FAIL] {schema_name}: {e}")
            all_passed = False

    if all_passed:
        print("\nAll 7 schema validation tests passed successfully!")
        sys.exit(0)
    else:
        print("\nSome schema validation tests failed.")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_tests()
    else:
        print("Usage: python validate.py --test")
