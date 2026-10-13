import functools
import json
import csv
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from shared.config import DATA_DIR, RULES_DIR, WEALTHPILOT_MODE
from shared.trace import get_tracer

def tool(name: Optional[str] = None, actor_name: Optional[str] = None):
    """
    Decorator for agent tools.
    Automatically captures input arguments, executes the tool,
    and logs a plan/act/observe step to the TraceLogger.
    """
    def decorator(func: Callable):
        tool_name = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tracer = get_tracer(actor_name)
            
            # Prepare arguments summary for logging
            bound_args = kwargs.copy()
            if args:
                bound_args["_args"] = [str(a) for a in args]

            thought = f"Executing tool {tool_name}"
            try:
                result = func(*args, **kwargs)
                result_summary = str(result)[:200]
                tracer.log_step(
                    step=tool_name,
                    thought=thought,
                    tool=tool_name,
                    args=bound_args,
                    result_summary=result_summary
                )
                return result
            except Exception as e:
                tracer.log_step(
                    step=tool_name,
                    thought=f"Error executing tool {tool_name}: {str(e)}",
                    tool=tool_name,
                    args=bound_args,
                    result_summary=f"FAILED: {str(e)}"
                )
                raise e

        wrapper.is_tool = True
        wrapper.tool_name = tool_name
        return wrapper

    return decorator

def dummy_read(relative_path: str) -> Any:
    """
    Universal reader for dummy mode datasets with Path Traversal protection.
    Locates files in DATA_DIR or RULES_DIR and parses them based on file extension.
    """
    data_dir_resolved = DATA_DIR.resolve()
    rules_dir_resolved = RULES_DIR.resolve()

    target = (DATA_DIR / relative_path).resolve()
    is_safe = target.is_relative_to(data_dir_resolved)

    if not is_safe or not target.exists():
        target = (RULES_DIR / relative_path).resolve()
        is_safe = target.is_relative_to(rules_dir_resolved)

    if not is_safe:
        raise PermissionError(f"Access denied: Path traversal attempted outside authorized roots: {relative_path}")

    if not target.exists():
        raise FileNotFoundError(f"File not found in DATA_DIR or RULES_DIR: {relative_path}")

    suffix = target.suffix.lower()
    if suffix == ".json":
        with open(target, "r", encoding="utf-8") as f:
            return json.load(f)
    elif suffix == ".csv":
        with open(target, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    elif suffix in (".md", ".txt"):
        with open(target, "r", encoding="utf-8") as f:
            return f.read()
    else:
        with open(target, "rb") as f:
            return f.read()
