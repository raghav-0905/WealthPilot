import sys
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

# Ensure schemas are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from schemas.validate import validate_data

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
            "thought": thought,
            "tool": tool,
            "args": args or {},
            "result_summary": result_summary,
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
