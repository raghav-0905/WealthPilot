#!/usr/bin/env python3
"""
WealthPilot Frontend & API Server
=================================
Lightweight server that bridges the web frontend with the WealthPilot
multi-agent advisory system and Apify Actor execution engine.

Serves the frontend static files at http://localhost:8000 and exposes
REST API endpoints to trigger live orchestrator runs, inspect execution
traces, and manage simulated trade orders.

Zero external dependencies required (uses Python standard library).
"""

import sys
import os
import json
import mimetypes
import importlib.util
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Set up project root on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.config import WEALTHPILOT_MODE, PROJECT_ROOT as ROOT_DIR
from shared.storage import read_state, clear_local_storage, TRACE_DATASET_DIR
from schemas.validate import validate_data

FRONTEND_DIR = Path(__file__).resolve().parent

def load_actor(actor_name: str):
    actor_path = ROOT_DIR / "actors" / actor_name / "src" / "main.py"
    if not actor_path.exists():
        raise FileNotFoundError(f"Actor entry point not found: {actor_path}")
    spec = importlib.util.spec_from_file_location(actor_name.replace("-", "_"), actor_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class WealthPilotAPIHandler(SimpleHTTPRequestHandler):
    """Handles frontend static asset delivery and REST API requests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def _send_json(self, status_code: int, data: dict):
        response_bytes = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # API Routes
        if path == "/api/health":
            self._send_json(200, {
                "status": "healthy",
                "system": "WealthPilot Multi-Agent Advisory",
                "mode": WEALTHPILOT_MODE,
                "version": "1.0.0"
            })
            return

        elif path == "/api/scenarios":
            scenarios = [
                {
                    "id": "scenario_001",
                    "clientId": "CLIENT_001",
                    "title": "Rajesh Varma — Promoter & Family Office",
                    "persona": "Founder & Promoter | 38% Concentrated IT Equity",
                    "netWorthINR": 120000000,
                    "defaultGoal": "Tax-efficient concentration de-risking; ₹2 Cr liquidity required in 2 years for overseas expansion.",
                    "traceFile": "docs/trace_examples/scenario_001_trace.json"
                },
                {
                    "id": "scenario_002",
                    "clientId": "CLIENT_002",
                    "title": "Ananya Sen — Corporate Executive Wealth",
                    "persona": "Senior Corporate Executive | 30% NBFC Concentration & Offshore LRS",
                    "netWorthINR": 80000000,
                    "defaultGoal": "De-risk NBFC exposure and diversify globally via RBI LRS window while maintaining wealth compounding.",
                    "traceFile": "docs/trace_examples/scenario_002_trace.json"
                },
                {
                    "id": "scenario_custom",
                    "clientId": "CLIENT_CUSTOM",
                    "title": "Vikram Malhotra — Healthcare Founder & Angel",
                    "persona": "Healthcare Founder | 45% Concentration & Hospital Expansion",
                    "netWorthINR": 150000000,
                    "defaultGoal": "Tax-efficient healthcare founder concentration exit; ₹3.5 Cr liquidity needed for hospital expansion.",
                    "traceFile": "docs/trace_examples/scenario_custom_trace.json"
                }
            ]
            self._send_json(200, {"scenarios": scenarios})
            return

        elif path.startswith("/api/trace/"):
            scenario_id = path.replace("/api/trace/", "").strip()
            trace_path = ROOT_DIR / "docs" / "trace_examples" / f"{scenario_id}_trace.json"
            if not trace_path.exists():
                self._send_json(404, {"error": f"Trace file not found for scenario: {scenario_id}"})
                return
            with open(trace_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._send_json(200, data)
            return

        elif path.startswith("/api/client/"):
            client_id = path.replace("/api/client/", "").strip().lower()
            client_path = ROOT_DIR / "data" / "clients" / f"{client_id}.json"
            if not client_path.exists():
                self._send_json(404, {"error": f"Client profile not found: {client_id}"})
                return
            with open(client_path, "r", encoding="utf-8") as f:
                client_data = json.load(f)
            self._send_json(200, client_data)
            return

        # Default static file handler (index.html, style.css, app.js)
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON request payload"})
            return

        if path == "/api/run":
            # Live Orchestrator Execution
            try:
                client_id = payload.get("clientId", "CLIENT_001")
                goal = payload.get("goal", "Optimize portfolio tax-efficiently")
                max_rounds = int(payload.get("maxRevisionRounds", 3))

                clear_local_storage()
                orchestrator_mod = load_actor("wp-orchestrator")
                report = orchestrator_mod.run_orchestrator({
                    "clientId": client_id,
                    "goal": goal,
                    "maxRevisionRounds": max_rounds
                })

                # Fetch generated traces from dataset
                trace_files = sorted(TRACE_DATASET_DIR.glob("*.json"))
                traces = []
                for tf in trace_files:
                    with open(tf, "r", encoding="utf-8") as f:
                        traces.append(json.load(f))

                self._send_json(200, {
                    "scenarioId": client_id,
                    "clientId": client_id,
                    "goal": goal,
                    "finalReport": report,
                    "traceEntries": traces,
                    "totalTraceSteps": len(traces),
                    "taskGraph": report.get("taskGraph", {})
                })
            except Exception as e:
                self._send_json(500, {"error": f"Execution failed: {str(e)}"})
            return

        elif path == "/api/execute":
            # Simulated Execution & Monitoring Gate
            try:
                client_id = payload.get("clientId", "CLIENT_001")
                approved = bool(payload.get("approved", False))

                monitor_mod = load_actor("wp-execution-monitor")
                result = monitor_mod.run_execution_monitor({
                    "clientId": client_id,
                    "approved": approved
                })
                self._send_json(200, result)
            except Exception as e:
                self._send_json(500, {"error": f"Execution monitor failed: {str(e)}"})
            return

        self._send_json(404, {"error": "Endpoint not found"})

def run_server(port: int = 8000):
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, WealthPilotAPIHandler)
    print("=" * 70)
    print("  WEALTHPILOT FRONTEND & ADVISOR COCKPIT SERVER")
    print(f"  Running locally at: http://127.0.0.1:{port}")
    print("  Press Ctrl+C to stop the server")
    print("=" * 70)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run_server(port)
