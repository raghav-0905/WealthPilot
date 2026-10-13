import sys
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

# Ensure schemas are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from schemas.validate import validate_data

def _sanitize_trace_payload(data: Any) -> Any:
    """Masks secret tokens and credentials from trace logs to prevent telemetry leakage."""
    import re
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if any(s in str(k).lower() for s in ("token", "api_key", "secret", "password", "auth")):
                sanitized[k] = "***REDACTED***"
            else:
                sanitized[k] = _sanitize_trace_payload(v)
        return sanitized
    elif isinstance(data, list):
        return [_sanitize_trace_payload(item) for item in data]
    elif isinstance(data, str):
        masked = re.sub(r'apify_api_[A-Za-z0-9_]+', 'apify_api_***REDACTED***', data)
        masked = re.sub(r'gsk_[A-Za-z0-9_]+', 'gsk_***REDACTED***', masked)
        return masked
    return data

class TraceLogger:
    """Logs agent execution traces and validates against TraceEntry.schema.json."""

    def __init__(self, actor_name: str = "wp-system"):
        self.actor_name = actor_name
        self.entries: List[Dict[str, Any]] = []

    def log_step(
        self,
        step: Any,
        thought: str,
        tool: str,
        args: Dict[str, Any],
        result_summary: str,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """Creates, validates and records a single trace entry."""
        if timestamp is None:
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        entry = {
            "actor": self.actor_name,
            "step": step,
            "thought": _sanitize_trace_payload(thought),
            "tool": tool,
            "args": _sanitize_trace_payload(args or {}),
            "result_summary": _sanitize_trace_payload(result_summary),
            "timestamp": timestamp
        }

        # Validate against schema
        validate_data(entry, "TraceEntry")

        self.entries.append(entry)

        # Write to storage
        from shared.storage import append_trace
        append_trace(entry)

        return entry

    def get_traces(self) -> List[Dict[str, Any]]:
        return list(self.entries)

    def clear(self):
        self.entries.clear()

# Global default tracer
_default_tracer: Optional[TraceLogger] = None

def get_tracer(actor_name: Optional[str] = None) -> TraceLogger:
    global _default_tracer
    if actor_name:
        return TraceLogger(actor_name=actor_name)
    if _default_tracer is None:
        _default_tracer = TraceLogger(actor_name="wp-global")
    return _default_tracer
