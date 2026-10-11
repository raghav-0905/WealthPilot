import json
import re
from pathlib import Path
from typing import Any, Optional
from shared.config import LOCAL_STORAGE_DIR, WEALTHPILOT_MODE
from schemas.validate import validate_data

# Local storage roots
KV_STORE_DIR = LOCAL_STORAGE_DIR / "key_value_stores" / "wealthpilot-state"
TRACE_DATASET_DIR = LOCAL_STORAGE_DIR / "datasets" / "wealthpilot-trace"
REPORTS_DATASET_DIR = LOCAL_STORAGE_DIR / "datasets" / "wealthpilot-reports"

def _ensure_local_dirs():
    KV_STORE_DIR.mkdir(parents=True, exist_ok=True)
    TRACE_DATASET_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DATASET_DIR.mkdir(parents=True, exist_ok=True)

_ensure_local_dirs()

def _sanitize_key(key: str) -> str:
    return re.sub(r'[^\w\-]', '_', key)

def write_state(key: str, value: Any) -> None:
    """Writes state to the named KV store 'wealthpilot-state'."""
    _ensure_local_dirs()
    sanitized = _sanitize_key(key)
    file_path = KV_STORE_DIR / f"{sanitized}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2)

def read_state(key: str, default: Any = None) -> Any:
    """Reads state from the named KV store 'wealthpilot-state'."""
    sanitized = _sanitize_key(key)
    file_path = KV_STORE_DIR / f"{sanitized}.json"
    if not file_path.exists():
        return default
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def append_trace(entry: dict) -> None:
    """Appends an execution trace row to 'wealthpilot-trace' dataset."""
    _ensure_local_dirs()
    index = len(list(TRACE_DATASET_DIR.glob("*.json"))) + 1
    file_path = TRACE_DATASET_DIR / f"{index:06d}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)

def append_report(report: dict) -> None:
    """Appends a final report to 'wealthpilot-reports' dataset after validation."""
    validate_data(report, "FinalReport")
    _ensure_local_dirs()
    index = len(list(REPORTS_DATASET_DIR.glob("*.json"))) + 1
    file_path = REPORTS_DATASET_DIR / f"{index:06d}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

def clear_local_storage():
    """Utility to clear local storage between test suites."""
    import shutil
    if LOCAL_STORAGE_DIR.exists():
        shutil.rmtree(LOCAL_STORAGE_DIR)
    _ensure_local_dirs()
