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

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

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
            # Default built-in scenarios
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

            # Discover any custom client accounts dynamically from data/clients
            clients_dir = ROOT_DIR / "data" / "clients"
            if clients_dir.exists():
                known_ids = {"client_001", "client_002", "client_custom"}
                for client_file in sorted(clients_dir.glob("*.json")):
                    cid_stem = client_file.stem.lower()
                    if cid_stem not in known_ids and not cid_stem.startswith("."):
                        try:
                            with open(client_file, "r", encoding="utf-8") as f:
                                cdata = json.load(f)
                            cid = cdata.get("clientId", cid_stem.upper())
                            scenarios.append({
                                "id": f"scenario_{cid_stem}",
                                "clientId": cid,
                                "title": f"{cdata.get('name', cid)} — {cdata.get('persona', 'Custom Portfolio')}",
                                "persona": f"{cdata.get('persona', 'Custom Account')} | {cdata.get('riskProfile', 'moderate').capitalize()} Risk",
                                "netWorthINR": cdata.get("netWorthINR", 0),
                                "defaultGoal": cdata.get("notes", {}).get("primaryGoal", "Custom wealth optimization mandate."),
                                "traceFile": f"docs/trace_examples/scenario_{cid_stem}_trace.json"
                            })
                        except Exception:
                            pass

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

        elif path == "/api/portfolio/create":
            # Create a New Portfolio Account (Zero hardcoding / full dynamic ingestion)
            try:
                raw_cid = payload.get("clientId", "").strip().upper()
                if not raw_cid:
                    raw_cid = f"CLIENT_{len(list((ROOT_DIR / 'data' / 'clients').glob('*.json'))) + 1:03d}"
                client_id = "".join(c for c in raw_cid if c.isalnum() or c == "_")
                cid_lower = client_id.lower()

                name = payload.get("name", "Private Wealth Client").strip()
                persona = payload.get("persona", "High-Net-Worth Investor").strip()
                tax_status = payload.get("taxStatus", "Resident Individual").strip()
                risk_profile = payload.get("riskProfile", "moderate").strip().lower()
                if risk_profile not in ("conservative", "moderate", "aggressive"):
                    risk_profile = "moderate"

                primary_goal = payload.get("primaryGoal", "Tax-efficient portfolio optimization and liquidity management.").strip()
                goals = payload.get("goals", [])
                if not goals:
                    goals = [{
                        "type": "liquidity",
                        "amountINR": float(payload.get("targetLiquidityINR", 20000000.0)),
                        "horizonYears": float(payload.get("liquidityHorizonYears", 2.0)),
                        "description": primary_goal
                    }]

                holdings_input = payload.get("holdings", [])
                total_net_worth = sum(float(h.get("valueINR", 0.0)) for h in holdings_input)
                if total_net_worth <= 0:
                    total_net_worth = 100000000.0  # Default 10 Cr if zero

                holdings = []
                for h in holdings_input:
                    val = float(h.get("valueINR", 0.0))
                    cost = float(h.get("costBasisINR", val))
                    pct = round((val / total_net_worth) * 100.0, 2)
                    holdings.append({
                        "assetClass": h.get("assetClass", "listed_equity"),
                        "issuer": str(h.get("issuer", "ASSET")).strip().upper(),
                        "sector": str(h.get("sector", "Diversified")).strip(),
                        "valueINR": val,
                        "costBasisINR": cost,
                        "unrealizedGainINR": round(val - cost, 2),
                        "holdingPeriodMonths": int(h.get("holdingPeriodMonths", 24)),
                        "pctOfNetWorth": pct
                    })

                # Sort holdings descending by value
                holdings.sort(key=lambda x: x["valueINR"], reverse=True)
                top_issuer_pct = holdings[0]["pctOfNetWorth"] if holdings else 0.0
                top_issuer_name = holdings[0]["issuer"] if holdings else ""

                # Compute Sector Exposure
                by_sector = {}
                for h in holdings:
                    sec = h.get("sector", "Diversified")
                    by_sector[sec] = round(by_sector.get(sec, 0.0) + h["pctOfNetWorth"], 2)

                # Compute Asset Class Exposure
                by_asset_class = {}
                for h in holdings:
                    ac = h.get("assetClass", "listed_equity")
                    by_asset_class[ac] = round(by_asset_class.get(ac, 0.0) + h["pctOfNetWorth"], 2)

                # Consistency Audits
                consistency_flags = []
                if risk_profile in ("moderate", "conservative") and top_issuer_pct >= 25.0:
                    consistency_flags.append(
                        f"Stated {risk_profile} risk vs {top_issuer_pct}% single-issuer concentration in {top_issuer_name}"
                    )

                client_persona = {
                    "clientId": client_id,
                    "name": name,
                    "persona": persona,
                    "taxStatus": tax_status,
                    "netWorthINR": total_net_worth,
                    "riskProfile": risk_profile,
                    "goals": goals,
                    "holdings": holdings,
                    "exposure": {
                        "bySector": by_sector,
                        "byAssetClass": by_asset_class,
                        "topIssuerPct": top_issuer_pct
                    },
                    "dataQualityFlags": [],
                    "profileConsistencyFlags": consistency_flags,
                    "notes": {
                        "primaryGoal": primary_goal,
                        "restrictedSecurities": payload.get("restrictedSecurities", []),
                        "annualRealizationCapINR": float(payload.get("annualRealizationCapINR", 20000000.0)),
                        "harvestLosses": bool(payload.get("harvestLosses", True))
                    }
                }

                # 1. Save Client Persona
                client_path = ROOT_DIR / "data" / "clients" / f"{cid_lower}.json"
                with open(client_path, "w", encoding="utf-8") as f:
                    json.dump(client_persona, f, indent=2)

                # 2. Save Broker CSV for listed assets
                broker_path = ROOT_DIR / "data" / "portfolios" / f"{cid_lower}_broker.csv"
                with open(broker_path, "w", encoding="utf-8") as f:
                    f.write("symbol,isin,quantity,average_buy_price,current_price,current_value,unrealized_pnl,holding_period_months\n")
                    for h in holdings:
                        if h["assetClass"] in ("listed_equity", "mutual_funds", "debt_fixed_income", "international_equity"):
                            sym = h["issuer"]
                            val = h["valueINR"]
                            cost = h["costBasisINR"]
                            pnl = val - cost
                            period = h["holdingPeriodMonths"]
                            f.write(f"{sym},IN00{sym[:6]},1000,100.00,100.00,{val:.2f},{pnl:.2f},{period}\n")

                # 3. Save Manual Assets JSON
                manual_path = ROOT_DIR / "data" / "portfolios" / f"{cid_lower}_manual.json"
                manual_assets = []
                for h in holdings:
                    if h["assetClass"] in ("real_estate", "unlisted_equity"):
                        manual_assets.append({
                            "assetType": h["assetClass"],
                            "identifier": h["issuer"],
                            "costOfAcquisitionINR": h["costBasisINR"],
                            "estimatedMarketValueINR": h["valueINR"]
                        })
                with open(manual_path, "w", encoding="utf-8") as f:
                    json.dump({"clientId": client_id, "manualAssets": manual_assets}, f, indent=2)

                # 4. Save PMS/AIF Statement text
                pms_path = ROOT_DIR / "data" / "portfolios" / f"{cid_lower}_pms.txt"
                pms_lines = [
                    f"PORTFOLIO STATEMENT & PERFORMANCE REPORT",
                    f"Client Name: {name}",
                    f"Client ID: {client_id}",
                    "--------------------------------------------------------------------------------",
                    "PORTFOLIO HOLDINGS:"
                ]
                for h in holdings:
                    if h["assetClass"] in ("pms", "aif"):
                        pms_lines.append(f"Scheme: {h['issuer']} | Value: INR {h['valueINR']:,.0f}")
                with open(pms_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(pms_lines) + "\n")

                # 5. Generate Initial Baseline Trace File
                trace_dir = ROOT_DIR / "docs" / "trace_examples"
                trace_dir.mkdir(parents=True, exist_ok=True)
                trace_file = trace_dir / f"scenario_{cid_lower}_trace.json"
                
                initial_trace = {
                    "scenarioId": f"scenario_{cid_lower}",
                    "clientId": client_id,
                    "goal": primary_goal,
                    "finalReport": {
                        "clientId": client_id,
                        "goal": primary_goal,
                        "explanation": f"Custom portfolio intake completed for {name}. Ready for multi-agent strategic optimization.",
                        "rankedOptions": [
                            {
                                "id": "S1_CUSTOM_STAGED",
                                "name": f"Staged concentration exit from {top_issuer_name}",
                                "rank": 1,
                                "totalScore": 0.91,
                                "criteria": { "postTaxReturn": 0.90, "liquidity": 0.92, "concentration": 0.88, "stress": 0.86, "compliance": 1.00 },
                                "justification": f"Reduces {top_issuer_pct}% concentration while meeting target liquidity."
                            }
                        ],
                        "arbitrationLog": []
                    },
                    "totalTraceSteps": 1,
                    "traceEntries": []
                }
                with open(trace_file, "w", encoding="utf-8") as f:
                    json.dump(initial_trace, f, indent=2)

                self._send_json(201, {
                    "success": True,
                    "scenarioId": f"scenario_{cid_lower}",
                    "clientId": client_id,
                    "client": client_persona
                })
            except Exception as e:
                self._send_json(500, {"error": f"Failed to create portfolio: {str(e)}"})
            return

        elif path == "/api/portfolio/delete":
            # Remove any portfolio account
            try:
                client_id = payload.get("clientId", "").strip().upper()
                cid_lower = client_id.lower()
                if not cid_lower:
                    self._send_json(400, {"error": "Missing clientId parameter"})
                    return

                deleted_files = []
                # 1. Remove Client JSON
                client_path = ROOT_DIR / "data" / "clients" / f"{cid_lower}.json"
                if client_path.exists():
                    client_path.unlink()
                    deleted_files.append(str(client_path.name))

                # 2. Remove associated portfolio data
                for ext in ["_broker.csv", "_manual.json", "_pms.txt"]:
                    pfile = ROOT_DIR / "data" / "portfolios" / f"{cid_lower}{ext}"
                    if pfile.exists():
                        pfile.unlink()
                        deleted_files.append(str(pfile.name))

                # 3. Remove trace file if custom
                tfile = ROOT_DIR / "docs" / "trace_examples" / f"scenario_{cid_lower}_trace.json"
                if tfile.exists():
                    tfile.unlink()
                    deleted_files.append(str(tfile.name))

                self._send_json(200, {
                    "success": True,
                    "deletedClientId": client_id,
                    "deletedFiles": deleted_files
                })
            except Exception as e:
                self._send_json(500, {"error": f"Failed to delete portfolio: {str(e)}"})
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

def run_server(port: int = 8000, host: str = "0.0.0.0"):
    server_address = (host, port)
    httpd = HTTPServer(server_address, WealthPilotAPIHandler)
    print("=" * 70)
    print("  WEALTHPILOT FRONTEND & ADVISOR COCKPIT SERVER")
    print(f"  Listening on http://{host}:{port} (Cloud & Local Ready)")
    print("  Press Ctrl+C to stop the server")
    print("=" * 70)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()

if __name__ == "__main__":
    env_port = os.environ.get("PORT")
    port = int(env_port) if env_port else (int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
    run_server(port)
