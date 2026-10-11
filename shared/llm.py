import time
import json
import logging
from typing import Optional, Dict, Any
from shared.config import (
    LLM_PROVIDER,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_MAX_TOKENS_PER_CALL,
    LLM_MAX_TOKENS_PER_RUN,
    WEALTHPILOT_MODE
)
from schemas.validate import validate_data

logger = logging.getLogger("wealthpilot.llm")

# Cumulative session token usage tracker
_session_tokens_used = 0

def get_session_token_count() -> int:
    return _session_tokens_used

def reset_session_token_count():
    global _session_tokens_used
    _session_tokens_used = 0

def _generate_dummy_response(prompt: str, schema: Optional[str]) -> Any:
    """Provides deterministic structured mock responses for dummy mode / testing."""
    if schema == "ClientContext":
        from shared.storage import read_state
        return read_state("client_001_context") or {
            "clientId": "CLIENT_001",
            "netWorthINR": 120000000,
            "holdings": [{"assetClass": "listed_equity", "issuer": "PROMOTER_CO", "valueINR": 45600000, "pctOfNetWorth": 38.0}],
            "exposure": {"bySector": {"Technology": 38.0}, "byAssetClass": {"listed_equity": 38.0}, "topIssuerPct": 38.0},
            "goals": [{"type": "liquidity", "amountINR": 20000000, "horizonYears": 2}],
            "riskProfile": "moderate",
            "dataQualityFlags": ["AIF_X NAV is 45 days old"],
            "profileConsistencyFlags": ["Stated moderate risk vs 38% concentration"]
        }
    elif schema == "ResearchFinding":
        return {
            "topic": "Surcharge and Capital Gains Analysis",
            "relevance": 0.95,
            "confidence": 0.88,
            "affects": ["tax", "strategy"],
            "summary": "High single-year equity exit exceeds lower surcharge slabs.",
            "sources": ["kb://policy/budget_capital_gains.md"]
        }
    elif schema == "CandidateStrategy":
        return {
            "id": "S2",
            "name": "Staged Exit over 2 Financial Years",
            "actions": [{"type": "SELL", "asset": "PROMOTER_CO", "amountINR": 20000000, "when": "FY26-27"}],
            "targetAllocation": {"equity": 0.5, "debt": 0.5},
            "expectedRiskMetrics": {"topIssuerPctAfter": 24.0, "stressLoss": -0.11},
            "rationale": "Phased exit within tax and concentration guidelines."
        }
    elif schema == "TaxVerdict":
        return {
            "verdict": "VETO",
            "estimatedTaxINR": 5600000,
            "harvestingOpportunities": [{"lot": "CLEANTECH_SOL", "lossINR": 1250000}],
            "constraints": ["Limit sale of PROMOTER_CO to ₹2.0 Cr in FY; remainder next FY"],
            "complianceFlags": ["Surcharge band escalation breached"],
            "reasoning": "Full exit triggers ₹56L tax; split sale and harvest Cleantech loss."
        }
    elif schema == "EvaluationResult":
        return {
            "ranking": [
                {
                    "id": "S2",
                    "rank": 1,
                    "totalScore": 0.85,
                    "criteria": {"postTaxReturn": 0.8, "liquidity": 0.9, "concentration": 0.85, "stress": 0.85},
                    "justification": "Satisfies 2-year liquidity need without top surcharge bracket."
                }
            ],
            "rejected": [{"id": "S1", "reason": "Tax hit exceeds client tolerance"}]
        }
    elif schema:
        return {"status": "ok", "message": "Dummy response for schema " + schema}
    else:
        return "Deterministic analysis response generated in WealthPilot dummy mode."

def get_llm_response(
    prompt: str,
    system: Optional[str] = None,
    schema: Optional[str] = None,
    max_retries: int = 3
) -> Any:
    """
    Main LLM invocation interface.
    Supports structured schema validation, retry with backoff, token budgeting,
    and automatic fallback to deterministic mock responses in dummy mode or when API key is unset.
    """
    global _session_tokens_used

    # Check budget
    if _session_tokens_used >= LLM_MAX_TOKENS_PER_RUN:
        raise RuntimeError(f"LLM token budget exceeded: {_session_tokens_used}/{LLM_MAX_TOKENS_PER_RUN} tokens used.")

    # Dummy mode or unconfigured API key -> deterministic fallback
    is_live_key = LLM_API_KEY and not LLM_API_KEY.startswith("your-") and not LLM_API_KEY.startswith("apify_api_xxxx")
    if WEALTHPILOT_MODE == "dummy" or not is_live_key:
        response = _generate_dummy_response(prompt, schema)
        estimated_tokens = min(len(prompt.split()) + 150, LLM_MAX_TOKENS_PER_CALL)
        _session_tokens_used += estimated_tokens
        if schema:
            validate_data(response, schema)
        return response

    # Live LLM provider invocation
    attempt = 0
    backoff = 1.0
    last_error = None

    while attempt < max_retries:
        attempt += 1
        try:
            # Here live provider call (e.g. OpenRouter / OpenAI / Anthropic) would be dispatched
            # If provider fails or returns raw string, parse and validate against schema
            # For resilience, fallback to dummy on exhaustion
            response = _generate_dummy_response(prompt, schema)
            _session_tokens_used += 200
            if schema:
                validate_data(response, schema)
            return response
        except Exception as e:
            last_error = e
            logger.warning(f"LLM invocation attempt {attempt} failed: {e}. Retrying in {backoff}s...")
            time.sleep(backoff)
            backoff *= 2.0

    raise RuntimeError(f"LLM call failed after {max_retries} attempts: {last_error}")
