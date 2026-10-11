import pytest
import os
from pathlib import Path

from shared.config import (
    WEALTHPILOT_MODE,
    DATA_DIR,
    RULES_DIR,
    SCHEMAS_DIR,
    PROJECT_ROOT
)
from shared.storage import (
    write_state,
    read_state,
    append_trace,
    append_report,
    clear_local_storage
)
from shared.trace import TraceLogger
from shared.tools import tool, dummy_read
from shared.llm import (
    get_llm_response,
    get_session_token_count,
    reset_session_token_count
)
from schemas.validate import validate_data

@pytest.fixture(autouse=True)
def setup_teardown():
    clear_local_storage()
    reset_session_token_count()
    yield
    clear_local_storage()

def test_config_paths():
    assert PROJECT_ROOT.exists()
    assert DATA_DIR.exists()
    assert RULES_DIR.exists()
    assert SCHEMAS_DIR.exists()
    assert WEALTHPILOT_MODE in ("dummy", "live")

def test_storage_read_write():
    payload = {"status": "active", "score": 95}
    write_state("test_key", payload)
    read_back = read_state("test_key")
    assert read_back == payload

def test_storage_default_missing():
    val = read_state("non_existent_key", default={"fallback": True})
    assert val == {"fallback": True}

def test_trace_logger_valid():
    logger = TraceLogger(actor_name="wp-test")
    entry = logger.log_step(
        step=1,
        thought="Testing tracer",
        tool="mock_tool",
        args={"param": "value"},
        result_summary="Success"
    )
    assert entry["actor"] == "wp-test"
    assert entry["step"] == 1
    assert len(logger.get_traces()) == 1

def test_trace_logger_invalid_schema():
    logger = TraceLogger(actor_name="wp-test")
    with pytest.raises(Exception):
        # Missing required field 'thought' or invalid format
        logger.log_step(
            step=1,
            thought=None, # thought must be string
            tool="mock_tool",
            args={},
            result_summary="Fail"
        )

def test_tool_decorator():
    tracer = TraceLogger(actor_name="wp-calc")
    
    @tool(name="add_numbers", actor_name="wp-calc")
    def add_numbers(a: int, b: int) -> int:
        return a + b

    result = add_numbers(10, 25)
    assert result == 35

def test_dummy_read():
    # Read json
    client_data = dummy_read("clients/client_001.json")
    assert client_data["clientId"] == "CLIENT_001"
    
    # Read csv
    returns = dummy_read("market/returns.csv")
    assert len(returns) == 36
    
    # Read markdown
    policy = dummy_read("kb/policy/sebi_circular_example.md")
    assert "SEBI Circular" in policy

def test_llm_dummy_mode():
    reset_session_token_count()
    response = get_llm_response(prompt="Evaluate client portfolio", schema="TaxVerdict")
    assert isinstance(response, dict)
    assert "verdict" in response
    assert response["verdict"] in ("APPROVE", "APPROVE_WITH_CONDITIONS", "VETO")
    assert get_session_token_count() > 0

def test_schema_validator_rejection():
    invalid_client = {"clientId": "BAD_CLIENT"} # missing netWorthINR, holdings, etc.
    with pytest.raises(Exception):
        validate_data(invalid_client, "ClientContext")
