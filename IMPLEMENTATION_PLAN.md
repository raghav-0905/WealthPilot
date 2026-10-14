# WealthPilot — Implementation Plan

> **Team size:** 4 members (A, B, C, D)
> **Workflow:** Sequential / iterative — no Git branches. Each phase is owned entirely by **one person**. Within a phase, the owner works through iterations on a single `main` branch, committing as they go. The next phase begins only after the previous one is complete.
> **Phases:** 4 (excluding final integration testing)

---

## Phase 1 — Foundation & Infrastructure (Owner: Member A)

**Goal:** Set up the entire project skeleton, define all data contracts, create dummy data, and build the shared utilities every Actor will depend on. Nothing "agentic" yet — this phase is pure groundwork so every subsequent phase has a solid base.

### Iteration 1 — Repo Scaffolding & Project Config

- Create the full directory tree from README §10:
  ```
  wealthpilot/
  ├── schemas/
  ├── data/  (clients/, portfolios/, market/, kb/policy/, kb/market/, products/, events/)
  ├── rules/
  ├── shared/
  ├── actors/
  │   ├── wp-orchestrator/  (.actor/actor.json, .actor/INPUT_SCHEMA.json, src/main.py stub)
  │   ├── wp-client-context/
  │   ├── wp-research-policy/
  │   ├── wp-tax-compliance/
  │   ├── wp-strategy/
  │   ├── wp-evaluator/
  │   └── wp-execution-monitor/
  ├── tests/
  └── docs/trace_examples/
  ```
- Set up `requirements.txt` — apify, langchain/langgraph, pydantic, jsonschema, pytest, python-dotenv.
- Create `.env.example` with `LLM_API_KEY` and `WEALTHPILOT_MODE=dummy`.
- Create stub `.actor/actor.json` and `.actor/INPUT_SCHEMA.json` inside every actor folder.
- `git init`, initial commit.

**✅ Checkpoint:** `pip install -r requirements.txt` succeeds, every actor folder has valid Apify config stubs.

### Iteration 2 — Shared JSON Schemas (Data Contracts)

- Create all schema files in `/schemas` as JSON Schema drafts:
  - `ClientContext.schema.json` — holdings, exposure, goals, risk profile, data quality flags (README §5.2)
  - `ResearchFinding.schema.json` — topic, relevance, confidence, affects, summary, sources (README §5.3)
  - `CandidateStrategy.schema.json` — id, name, actions, target allocation, risk metrics, rationale (README §5.5)
  - `TaxVerdict.schema.json` — verdict enum (APPROVE / APPROVE_WITH_CONDITIONS / VETO), estimated tax, constraints, harvesting opportunities (README §5.4)
  - `EvaluationResult.schema.json` — ranking with per-criterion scores, justifications, rejected list (README §5.6)
  - `FinalReport.schema.json` — ranked options + explanation + arbitration log
  - `TraceEntry.schema.json` — actor, step, thought, tool, args, result_summary, timestamp (README §6)
- Write `schemas/validate.py` — a helper that validates any dict against a named schema using the `jsonschema` library.

**✅ Checkpoint:** `python schemas/validate.py --test` validates sample dicts without errors.

### Iteration 3 — Dummy Data & Rule Packs

- Create all files listed in README §8:
  - `data/clients/client_001.json` — promoter-entrepreneur persona (₹12 Cr, 38% PROMOTER_CO, ₹2 Cr liquidity goal, moderate risk, succession note)
  - `data/clients/client_002.json` — salaried executive persona (heavy NBFC/financials, LRS holdings — contrast case)
  - `data/portfolios/` — broker CSV, PMS/AIF statement `.txt`, manual JSON entries for unlisted shares and real estate
  - `data/market/returns.csv` — synthetic return series for 10–15 securities, enough for correlation and stress testing
  - `data/kb/policy/*.md` — 3–4 synthetic SEBI/RBI/Budget circular summaries
  - `data/kb/market/*.md` — 3–4 synthetic sector and macro outlook briefs
  - `data/products/alternatives.json` — dummy PMS/AIF/REIT/InvIT catalog with lock-ins and minimum tickets
  - `data/events/events.json` — scripted trigger events (rating downgrade, promoter pledge increase, policy change)
  - `rules/tax_rules_fy_demo.json` — illustrative LTCG/STCG rates, surcharge slabs, thresholds, harvesting rules
- **Design the data so conflicts emerge naturally:** large tax hit on concentration sale, a harvestable loss lot, AIF lock-in vs 2-year liquidity goal.
- Write `data/README.md` explaining each file.

**✅ Checkpoint:** Dummy data is internally consistent; client_001 portfolio files sum to the net-worth stated in the persona JSON.

### Iteration 4 — Shared Utilities

Build all code under `/shared`:

| File | Purpose |
|---|---|
| `shared/config.py` | Reads `.env`, exposes `WEALTHPILOT_MODE`, `LLM_API_KEY`, and constants. |
| `shared/trace.py` | `TraceLogger` class — appends plan/act/observe rows to the `wealthpilot-trace` Apify dataset. Validates each row against `TraceEntry.schema.json`. |
| `shared/storage.py` | Thin wrappers around Apify named KV store (`wealthpilot-state`) and datasets. `read_state(key)`, `write_state(key, value)`, `append_trace(entry)`, `append_report(report)`. |
| `shared/llm.py` | `get_llm_response(prompt, system=None, schema=None)` — reads API key from config, supports structured JSON output via schema, retry with exponential backoff, token budget enforcement. |
| `shared/tools.py` | `@tool` decorator / base class. Auto-logs every call (args + result summary) to the trace. Provides the `dummy_read(path)` function that loads from `/data` when mode is `dummy`. |
| `shared/__init__.py` | Re-exports key utilities for clean imports. |

- Write `tests/test_shared.py` — smoke tests for config loading, schema validation, trace logging, and the tool decorator.

**✅ Checkpoint:** `python -m pytest tests/test_shared.py` passes.

### Phase 1 — Definition of Done
- [x] Repo structure matches README §10
- [x] All 7 schemas exist and validate sample dummy data
- [x] All dummy data files created with intentional conflict scenarios
- [x] Shared utilities importable and tested
- [x] Every actor folder has valid Apify stubs

---

## Phase 2 — Core Actors: Data & Compliance Layer (Owner: Member B)

**Goal:** Build the three Actors that gather and gate information — `wp-client-context`, `wp-research-policy`, and `wp-tax-compliance`. By the end of this phase, each runs standalone with its own dummy-data tools, logs to the trace, and produces schema-valid output. These are the actors every decision actor in Phase 3 will depend on.

### Iteration 1 — `wp-client-context` Actor

Build `actors/wp-client-context/src/main.py`:

- **Agent loop:** Implement the Plan → Act → Observe → Reflect cycle (use LangGraph or a plain `while` loop with step limits).
- **Tools to register:**
  - `read_broker_csv(path)` — parses broker CSV holdings
  - `read_pms_statement(path)` — extracts holdings from PMS/AIF text statements via LLM
  - `read_manual_entries(path)` — loads manually entered unlisted shares, real estate, gold
  - `convert_currency(amount, from, to)` — static rate table in dummy mode
  - `read_client_memory(clientId)` — fetches past profile/decisions from KV store
  - `write_client_memory(clientId, data)` — persists profile updates with reasons
- **Core logic:**
  - Reconcile holdings from multiple sources, deduplicate, normalize to INR.
  - Compute exposure breakdowns: by asset class, by sector, by issuer, top-issuer %.
  - Build the risk profile and goals from client JSON.
  - Run a consistency check (e.g., "stated moderate risk vs 38% single-issuer exposure") and populate `profileConsistencyFlags`.
  - Flag stale or missing data in `dataQualityFlags` (e.g., "AIF_X NAV is 45 days old").
- **Output:** A fully validated `ClientContext` JSON (schema from Phase 1).
- Update `INPUT_SCHEMA.json` with: `clientId`, `sources[]`, optional `refreshProfile`.

**✅ Checkpoint:** Run the actor locally with `apify run` for client_001 — produces valid `ClientContext` with the 38% concentration flag and the stale-NAV flag.

### Iteration 2 — `wp-research-policy` Actor

Build `actors/wp-research-policy/src/main.py`:

- **Agent loop:** Same Plan → Act → Observe → Reflect cycle with step limits.
- **Tools to register:**
  - `search_policy_kb(query)` — keyword/semantic search over `data/kb/policy/*.md`
  - `search_market_kb(query)` — keyword/semantic search over `data/kb/market/*.md`
  - `summarize_finding(text, context)` — LLM summarizer that produces a structured `ResearchFinding`
- **Core logic:**
  - Read `ClientContext.exposure` and **plan which topics to investigate** based on the client's actual holdings (this is the agentic part — not a fixed list of queries).
  - For client_001 (38% in one mid-cap): prioritize that sector's outlook + capital-gains policy.
  - For client_002 (heavy NBFC + LRS): prioritize RBI rate policy + LRS/TCS rule changes.
  - Rate each finding by relevance and confidence.
  - Flag findings that affect `tax` or `strategy` domains so the Orchestrator knows to re-consult those actors.
- **Output:** List of `ResearchFinding` objects, schema-validated.
- Update `INPUT_SCHEMA.json` with: `exposure`, `goalSummary`, `lookbackDays`, `maxTopics`.

**✅ Checkpoint:** Run for both client_001 and client_002 — they produce **different** research topics from the same KB. This is the key agentic demo for this actor.

### Iteration 3 — `wp-tax-compliance` Actor

Build `actors/wp-tax-compliance/src/main.py`:

- **Deterministic calculators** (pure functions, no LLM) in a separate `tax_calculator.py`:
  - `calc_ltcg(sale_amount, cost_basis, asset_class, holding_period, fy)` → tax amount
  - `calc_stcg(sale_amount, cost_basis, asset_class, fy)` → tax amount
  - `calc_surcharge(total_income, base_tax)` → surcharge + cess
  - `find_harvestable_lots(holdings, current_prices)` → list of loss-making lots with potential offset
  - `check_lrs_limit(amount_usd, already_remitted)` → compliant / exceeds
  - `check_suitability(proposal, risk_profile, product_rules)` → pass / fail with reasons
  - All calculators read rates and thresholds from `rules/tax_rules_fy_demo.json` — **never hardcoded**.
- **Agent loop:** LLM decides *which* calculations to run for a given proposal (e.g., "this is a large sale, check surcharge band impact" or "there are loss lots, compute harvesting offset"). The LLM **plans**; the code **computes**.
- **Veto logic:** If the tax cost exceeds a threshold or suitability fails, return `verdict: "VETO"` with machine-readable `constraints[]` that Strategy can use to regenerate.
- **Output:** `TaxVerdict` JSON, schema-validated.
- Update `INPUT_SCHEMA.json` with: `proposal`, `ClientContext`, `researchFindings[]`, `financialYear`.

**✅ Checkpoint:** Unit tests pass for all deterministic calculators (`tests/test_tax_calculator.py`). Actor run on a "sell 60% of PROMOTER_CO" proposal returns a VETO with the constraint "max ₹2.0 Cr sale this FY".

### Iteration 4 — Phase 2 Tests & Contract Validation

- Write `tests/test_tax_calculator.py` — unit tests for every deterministic function:
  - LTCG/STCG computation with known inputs
  - Surcharge band edge cases
  - Harvesting offset calculation
  - LRS limit check
  - Suitability check pass/fail cases
- Write `tests/test_contracts.py` — for each of the three actors built in this phase:
  - Load their actual output (from a saved test run or a fixture) and validate against the schema.
  - Verify required fields like `confidence` and `reasoningSummary` are present.
  - Verify trace entries were written for every tool call.
- Ensure all three actors can be run back-to-back locally without conflicts (shared KV store keys don't collide).

**✅ Checkpoint:** `python -m pytest tests/test_tax_calculator.py tests/test_contracts.py` — all pass.

### Phase 2 — Definition of Done
- [x] `wp-client-context` produces valid `ClientContext` with consistency and quality flags
- [x] `wp-research-policy` produces exposure-driven findings (different per client)
- [x] `wp-tax-compliance` vetoes an over-limit sale with actionable constraints
- [x] All deterministic tax calculators are unit-tested
- [x] All actor outputs validate against their schemas
- [x] Every tool call is logged to the trace dataset

---

## Phase 3 — Decision & Control Actors (Owner: Member C)

**Goal:** Build the remaining four Actors — `wp-strategy`, `wp-evaluator`, `wp-orchestrator`, and `wp-execution-monitor`. By the end of this phase every actor exists, runs standalone, and the Orchestrator can call the others in sequence to execute the full scenario 001 task graph.

### Iteration 1 — `wp-strategy` Actor

Build `actors/wp-strategy/src/main.py`:

- **Tools to register:**
  - `get_product_catalog()` — loads `data/products/alternatives.json` (PMS, AIF, REIT, InvIT with lock-ins and minimums)
  - `calc_portfolio_weights(holdings, changes)` — recomputes allocation after proposed actions
  - `calc_correlation(assets, returns_csv)` — pairwise correlation from `data/market/returns.csv`
  - `run_stress_scenario(portfolio, scenario)` — applies a simple shock (rate hike, INR depreciation, equity drawdown) and returns estimated loss
- **Core logic:**
  - Read `ClientContext` + `ResearchFindings` as inputs.
  - Generate 3–5 **distinct** candidate strategies (e.g., aggressive sell-now, staged exit over 2 FYs, hedge-and-hold, partial sale + alternative rotation).
  - For each candidate: compute target allocation, top-issuer % after, stress-loss estimate.
  - On receiving `constraints[]` from a previous Tax veto → **regenerate** within those constraints (not just trim the old plan).
- **Output:** List of `CandidateStrategy` objects, schema-validated.
- Update `INPUT_SCHEMA.json`: `ClientContext`, `researchFindings[]`, optional `constraints[]`, `numCandidates`.

**✅ Checkpoint:** Actor produces 3+ distinct strategies for client_001. When re-run with constraint `"max ₹2.0 Cr sale this FY"`, it produces revised candidates that respect the cap.

### Iteration 2 — `wp-evaluator` Actor

Build `actors/wp-evaluator/src/main.py`:

- **Tools to register:**
  - `score_candidate(candidate, criteria_weights)` — deterministic multi-criteria scoring function
  - `derive_weights(goals, risk_profile)` — LLM-assisted: maps client goals to criterion weights (e.g., liquidity-needing client → high liquidity weight)
- **Core logic:**
  - Evaluate each candidate on: post-tax return, liquidity fit, concentration reduction, correlation improvement, stress resilience, compliance risk, execution complexity.
  - Weights are **derived from the client's goals**, not a generic scorecard.
  - Produce per-criterion scores + a written justification for each candidate.
  - Reject candidates that fail minimum thresholds (e.g., tax cost exceeds client's stated tolerance) with a reason.
  - Rank the remaining candidates.
- **Output:** `EvaluationResult` JSON with `ranking[]` and `rejected[]`, schema-validated.
- Update `INPUT_SCHEMA.json`: `candidates[]`, `ClientContext`, `taxVerdicts[]`.

**✅ Checkpoint:** Actor ranks strategies for client_001, rejects the aggressive sell-now (S1) due to tax cost, and provides per-criterion justifications.

### Iteration 3 — `wp-orchestrator` Actor

Build `actors/wp-orchestrator/src/main.py`:

- **Core logic (this is the most complex actor):**
  - **Task graph planner:** LLM decomposes the user goal into an ordered task graph (e.g., context → research → strategy → tax gate → evaluate).
  - **Actor router:** Calls each actor via `Actor.call()` (or local function calls for testing), passing outputs from one as inputs to the next.
  - **Replan detection:** After each actor returns, check if the output invalidates the current plan. Examples:
    - Tax returns a VETO → replan: re-invoke Strategy with constraints.
    - Tax discovers a harvesting opportunity → replan: send it to Strategy for revised candidates.
  - **Arbitration:** When actor outputs conflict (e.g., Evaluator ranks S4' highest but its AIF lock-in conflicts with the 2-year liquidity goal), the Orchestrator logs the conflict, applies a decision rule, and records the reasoning.
  - **Loop limits:** Max 3 strategy revision rounds. If still unresolved, escalate to human.
  - **Final report:** Assemble ranked options + explanation + what was rejected and why + tax impact summary.
- **Output:** `FinalReport` JSON, `task_graph` with all replans, `arbitration_log`.
- Update `INPUT_SCHEMA.json`: `clientId`, `goal`, `mode`, `maxRevisionRounds`.

**✅ Checkpoint:** Orchestrator runs scenario 001 end-to-end — calls Client Context → Research → Strategy → Tax (veto) → Strategy again (with constraints) → Tax (approve + harvesting) → Strategy (revised) → Evaluator → produces final report. At least 1 replan and 1 arbitration logged.

### Iteration 4 — `wp-execution-monitor` Actor

Build `actors/wp-execution-monitor/src/main.py`:

- **Tools to register:**
  - `submit_order(order)` — sends to a mock broker (local simulator that returns fills, partial fills, or rejections)
  - `check_portfolio_drift(current, target, tolerance)` — compares live holdings against approved plan
  - `read_event_feed()` — reads from `data/events/events.json` (scripted trigger events)
  - `assess_materiality(event, portfolio)` — LLM judges if an event warrants re-engaging the Orchestrator
- **Core logic:**
  - **Execution (simulated):** Sequence trades sensibly (liquidity before purchase, settlement timing). Handle partial fills by replanning remaining steps.
  - **Human gate:** Refuse to execute without `approved: true` in the input.
  - **Monitoring:** Compare portfolio against the approved plan, detect drift beyond tolerance.
  - **Trigger events:** Process events from the dummy feed (rating downgrade, promoter pledge increase). Use LLM to judge materiality. If material, send a `reengageRequest` to the Orchestrator.
- **Output:** `executionLog`, `driftReport`, optional `reengageRequest`.
- Update `INPUT_SCHEMA.json`: `approvedPlan`, `approved` (boolean), `monitoringConfig`.

**✅ Checkpoint:** Actor executes a staged trade plan, detects a simulated promoter-pledge-increase event, and flags it as material for Orchestrator re-engagement.

### Phase 3 — Definition of Done
- [x] `wp-strategy` generates distinct candidates and regenerates on constraints
- [x] `wp-evaluator` ranks with per-criterion scores and rejects below-threshold candidates
- [x] `wp-orchestrator` runs scenario 001 with at least 1 replan and 1 arbitration
- [x] `wp-execution-monitor` simulates trades and detects trigger events
- [x] All four actors produce schema-valid outputs with trace logging

---

## Phase 4 — Multi-Agent Integration & Scenario Execution (Owner: Member D)

**Goal:** Wire everything together for the system pipeline, validate scenario 001 and scenario 002, and prepare foundational sample inputs.

### Iteration 1 — End-to-End Integration (Scenario 001)
- [x] Run full scenario 001 pipeline via Orchestrator
- [x] Verify multi-agent sequence: Client Context -> Research -> Strategy -> Tax Veto -> Replanning -> Evaluator -> Arbitration -> Final Report
- [x] Validate all intermediate outputs and FinalReport conform to JSON Schemas

### Iteration 2 — Second Client Scenario (Client 002)
- [x] Verify client 002 portfolio reconciliation (NBFC concentration + LRS holdings)
- [x] Ensure exposure-targeted research selects NBFC and RBI LRS topics
- [x] Ensure Strategy generates rotation and offshore expansion candidates
- [x] Ensure Tax gate verifies compliance without false-positive promoter vetoes

### Iteration 3 — Sample Input Payloads
- [x] Create standardized runner inputs under `data/sample_inputs/` for both scenarios

### Phase 4 — Definition of Done
- [x] Scenario 001 runs end-to-end with veto, replans, and arbitration
- [x] Scenario 002 demonstrates distinct agentic behavior for salaried executive persona
- [x] Standard sample inputs created for reproducible runs

---

## Phase 5 — System Hardening, Trace Generation, Resiliency & Comprehensive Test Suite

**Goal:** Harden the multi-agent system into an enterprise-ready, thoroughly tested advisory engine. Generate and persist validated benchmark trace artifacts, eliminate all scenario-specific hardcoded assumptions, enforce multi-round replanning resilience, and implement comprehensive test suites covering edge cases, tax boundaries, currency conversion, and event sentinels.

### Iteration 1 — Trace Generation & Benchmark Artifacts
- **Objective:** Generate complete, verifiable trace logs for both benchmark client scenarios and persist them as standard artifacts in `docs/trace_examples/`.
- **Tasks:**
  - Execute clean benchmark runs of `wp-orchestrator` for `CLIENT_001` and `CLIENT_002`.
  - Extract the complete sequence of `TraceEntry` objects from the execution trace dataset.
  - Enrich the trace payload with execution metadata, task graph summary, and final recommendations.
  - Persist to:
    - `docs/trace_examples/scenario_001_trace.json`
    - `docs/trace_examples/scenario_002_trace.json`
  - Validate that every entry in both trace files passes `TraceEntry.schema.json` validation.

### Iteration 2 — Core Engine Generalization & Dynamic Explanation
- **Objective:** Fix residual scenario-specific hardcoding across actors so explanations, constraints, and arbitrations adapt dynamically to any client profile.
- **Tasks:**
  - **Orchestrator Explanation Generalization:** Update `wp-orchestrator`'s explanation builder to dynamically synthesize tax notes based on the actual `TaxVerdict` (e.g., distinguishing between surcharge vetoes/harvesting for concentrated promoters vs. clean compliance approvals for diversified salaried executives).
  - **Dynamic Arbitration Reasoning:** Ensure arbitration logs describe conflicts specific to the client's actual goals and asset lock-in constraints.
  - **Robust Input Fallbacks:** Ensure actors gracefully handle partial or missing payloads (e.g. defaulting to storage or mock records safely).

### Iteration 3 — Scenario 002 Dedicated Test Suite (`tests/test_scenario_002.py`)
- **Objective:** Prove genuine goal-driven multi-agent behavior and generality through automated test assertions for `CLIENT_002`.
- **Test Specifications:**
  - `test_scenario_002_end_to_end()`: Full pipeline execution asserting:
    - Schema conformity of `FinalReport`
    - Absence of false-positive tax vetoes (clean `APPROVE` or `APPROVE_WITH_CONDITIONS`)
    - Absence of unnecessary replan cycles when initial strategies are compliant
    - High ranking for `S1_NBFC_ROTATION` and `S2_LRS_EXPANSION`
  - `test_scenario_002_research_differentiation()`: Verifies that `wp-research-policy` investigates NBFC headwinds, RBI LRS caps, and macro interest rates (contrasting with mid-cap tech and promoter surcharge for Client 001).
  - `test_scenario_002_strategy_generation()`: Verifies generation of NBFC rotation, global diversification, and balanced growth candidates.
  - `test_scenario_002_tax_compliance()`: Verifies LRS limit tracking and TCS implications.

### Iteration 4 — Comprehensive System Resilience & Edge-Case Test Suite (`tests/test_phase5_integration.py`)
- **Objective:** Stress-test the multi-agent system across edge cases, failure modes, tax cliff conditions, and execution sentinels.
- **Test Specifications:**
  - **Multi-Round Replan Bounding:** Verify that `wp-orchestrator` respects `maxRevisionRounds` and terminates gracefully if proposals cannot satisfy constraints within budget.
  - **Tax Calculator Boundary Conditions:**
    - Verify LTCG vs STCG holding period threshold (12 months boundary).
    - Verify Surcharge rate transitions across ₹50L, ₹1 Cr, and ₹2 Cr gain thresholds.
    - Verify equity gain surcharge cap (15% cap under Section 112A).
  - **Tax-Loss Harvesting Boundary Checks:** Verify behavior when no harvestable loss lots exist in the portfolio.
  - **Multi-Currency Normalization:** Verify foreign asset valuation (USD/EUR conversion to INR in ClientContext).
  - **Human Gate & Sentinel Re-engagement:** Verify `wp-execution-monitor` blocks execution when `approved=False` and generates an orchestrator re-engagement trigger upon sensing promoter pledge spikes.
  - **Contract Integrity Across Actors:** Verify seamless handoffs between actors without schema breakage.

### Iteration 5 — Environment Configuration & Developer Onboarding
- **Objective:** Finalize `.env` configuration and provide clear key management guidelines for dummy vs. live deployment.
- **Tasks:**
  - Verify `.env` file structure and safe defaults.
  - Document key requirements, sourcing links, and purpose for Apify, OpenRouter, OpenAI, Anthropic, and Gemini.

### Phase 5 — Definition of Done
- [x] `data/sample_inputs/` contains valid input payloads for Scenario 001 and Scenario 002
- [x] Validated traces saved to `docs/trace_examples/scenario_001_trace.json` and `scenario_002_trace.json`
- [x] `tests/test_scenario_002.py` implemented and passing (100% green)
- [x] `tests/test_phase5_integration.py` implemented covering edge cases and resilience (100% green)
- [x] All existing test suites continue to pass without regression
- [x] `.env` file generated and key procurement guide documented

---

## Phase 6 — UI & Frontend: Interactive Trace Viewer & Advisor Cockpit

**Goal:** Build a state-of-the-art, visually stunning advisor-facing single-page application (SPA) in a dedicated `frontend/` directory to demonstrate WealthPilot's multi-agent reasoning, replanning loops, and portfolio recommendations for academic presentations and client demos.

### Iteration 1 — Architecture & Design System
- Modern, responsive SPA using Vanilla HTML5, CSS3, and JavaScript located in `frontend/`.
- Premium design system: Dark-mode-first aesthetic, harmonious HSL color palette, typography via Inter and Outfit fonts, glassmorphism cards, and smooth micro-animations.
- Dual-mode architecture: Runs seamlessly offline (via direct `file://` opening with built-in verified snapshots) or connected live to the Python REST API server (`python frontend/server.py`).

### Iteration 2 — Multi-Agent Execution Graph & Flow Timeline
- Interactive DAG / timeline visualizer representing agent execution steps:
  - Actor nodes: Client Context, Research & Policy, Strategy, Tax Compliance, Evaluator, Orchestrator, Execution Monitor.
  - Dynamic visual markers:
    - 🔴 **Tax Vetoes**: Distinct alert badge showing reason, rejected candidate, and constraint feedback loop.
    - 🟠 **Replanning Cycles**: Branching marker illustrating iterative strategy regeneration.
    - 🔵 **Arbitration Decisions**: Highlighting conflict resolution (e.g. AIF lock-in vs. liquidity horizon).
    - 🟢 **Execution Sentinel**: Trigger events and human-in-the-loop approval gates.

### Iteration 3 — Step-by-Step Inspector (Plan → Act → Observe → Reflect)
- Expandable slide-over drawer inspecting any selected trace node:
  - Agent Persona & Role Description.
  - Cognitive state breakdown: Thought process, Tool called, Inputs/Parameters, Output Summary.
  - Raw JSON contract viewer with code formatting.

### Iteration 4 — Advisor Cockpit & Final Report Dashboard
- Executive Summary view displaying:
  - Client profile banner (Net worth, risk rating, stated liquidity goals).
  - Ranked Strategy Proposals with per-criterion bar breakdown (Post-tax return, Liquidity, Concentration reduction, Stress resilience, Compliance).
  - Tax & Harvesting Impact card (estimated capital gains tax, loss offsets, net savings).
  - Target Asset Allocation comparison (Current vs. Proposed).
  - Simulated Execution & Monitoring Terminal with live mock trade orders.

### Iteration 5 — Scenario Switcher, Local Trace Loader & Live Run Modal
- Pre-loaded instant selector between **Scenario 001 (Concentrated Promoter)** and **Scenario 002 (Salaried Executive)**.
- Drag-and-drop / file input loader to inspect any custom `TraceEntry` JSON file generated from live Apify runs.
- Interactive **Run Live Advisory** modal triggering end-to-end multi-agent execution via `/api/run`.

### Phase 6 — Definition of Done
- [x] `frontend/index.html`, `frontend/style.css`, and `frontend/app.js` implemented
- [x] `frontend/server.py` lightweight HTTP and REST API server implemented
- [x] Scenario 001 and Scenario 002 traces render seamlessly in the browser
- [x] Step-by-step inspector displays thoughts, tools, and observations clearly
- [x] Key agentic events (veto, replan, arbitration) are visually highlighted
- [x] Human-in-the-loop trade execution gate and Sentinel monitoring verified
- [x] UI is fully responsive and interactive with zero compilation errors

