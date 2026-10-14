# WealthPilot — Deployment & Production Guide

This guide provides end-to-end instructions for deploying the **WealthPilot Multi-Agent Institutional Wealth Advisory Platform**. It covers deploying the specialist actors to **Apify**, deploying the interactive **Frontend Portal**, and managing environment configurations across environments.

---

## 1. System Architecture Overview

The repository is structured as a modular monorepo:

```text
WealthPilot/
├── actors/                      # 7 Containerized Apify Actors
│   ├── wp-orchestrator/         # Supervisory Agent & Task Graph Planner
│   ├── wp-client-context/       # Portfolio & Mandate Ingestion
│   ├── wp-research-policy/      # SEBI / RBI Regulatory Research Engine
│   ├── wp-strategy/             # Multi-Goal Allocation & Rebalancing Generator
│   ├── wp-tax-compliance/       # Indian LTCG/STCG Tax & Loss Harvesting Auditor
│   ├── wp-evaluator/            # Multi-Criteria Institutional Scoring & Fit Engine
│   └── wp-execution-monitor/    # Trade Staging & Post-Execution Reconciliation
├── frontend/                    # Interactive Institutional Web Application
│   ├── index.html               # Semantic UI & Institutional Dashboard
│   ├── app.js                   # Client-side reactivity, GSAP animations & API client
│   ├── style.css                # Institutional glassmorphic design system
│   └── server.py                # Lightweight REST proxy & Actor dispatcher
├── data/                        # Client profiles & multi-asset holding datasets
├── schemas/                     # Strict JSON schemas & data validators
└── shared/                      # Logging, tracing, storage, and utility helpers
```

---

## 2. Deploying to Apify

### Frequently Asked Questions

#### Q1: Can I deploy the whole system on the Apify website directly from GitHub?
**Yes.** Apify supports linking directly to a GitHub repository. You can either deploy the complete workflow as a **Unified Orchestrator Actor**, or deploy each specialist actor as an **independent microservice**.

#### Q2: My frontend is in the same repository. Will that be a problem?
**No.** Apify allows you to specify the **Source code directory / Root directory** for each Actor in your GitHub repository (e.g. `actors/wp-orchestrator` or `actors/wp-client-context`). Apify only builds the Docker image from that folder and ignores the frontend folder.

---

### Deployment Approaches

| Approach | Description | Recommended For |
| :--- | :--- | :--- |
| **Option A: Unified Orchestrator Actor** | Deploy `wp-orchestrator` as a single Apify Actor containing all micro-actors. Routes tasks internally with zero network latency. | Hackathons, Demos, Quick Evaluations, Low-Cost Setup |
| **Option B: Distributed Micro-Actors** | Deploy all 7 actors as separate Apify Actors. Each has its own dedicated Apify URL, OpenAPI schema, and independent run queue. | Enterprise Production, Scalable Teams, Pay-Per-Actor Billing |

---

### Option A: Deploying the Unified Orchestrator Actor (Recommended)

This deploys the end-to-end multi-agent system onto Apify in a single container.

#### Files Configured at Repo Root:
1. **`.dockerignore`**: Excludes `.git`, `.venv`, `.env`, and `frontend/` from the build image.
2. **`.actor/actor.json`**: Actor metadata and specification.
3. **`.actor/input_schema.json`**: Apify input form specification (`clientId`, `goal`, `maxRevisionRounds`).
4. **`.actor/Dockerfile`**: Builds from repo root using `apify/actor-python:3.12`.
5. **`actor_main.py`**: Reads `await Actor.get_input()`, runs `load_orchestrator().run_orchestrator()`, validates against schema, and writes output via `await Actor.push_data(report)`.

#### Method 1: Web Console (Zero-Install, Recommended)
1. Go to [Apify Console](https://console.apify.com/) -> **Actors** -> **Create new**.
2. Click **Link Git repository** and paste: `https://github.com/raghav-0905/WealthPilot`.
3. Set **Source Directory**: Leave empty or `/` (Repo root).
4. Click **Save & Build**. Apify builds the container directly from GitHub.

#### Method 2: Apify CLI
```bash
npm install -g apify-cli
apify login
apify run          # Test locally in emulated Apify environment
apify push         # Build and push to Apify Cloud
```

#### Triggering via Apify API (Sync Endpoint)
To execute the actor and retrieve the full dataset result in a single HTTP call:

```bash
curl --request POST \
  --url "https://api.apify.com/v2/acts/<YOUR_USERNAME>~wealthpilot-orchestrator/run-sync-get-dataset-items" \
  --header "Authorization: Bearer <YOUR_APIFY_TOKEN>" \
  --header "Content-Type: application/json" \
  --data '{
    "clientId": "CLIENT_001",
    "goal": "Target liquidity ₹2.0 Cr over 2 years avoiding peak capital gains surcharge.",
    "maxRevisionRounds": 3
  }'
```

---

### Option B: Deploying 7 Specialist Micro-Actors on Apify

If you wish to deploy each specialist actor independently:

#### Method 1: Using the Apify Web Console (GitHub Integration)
1. Go to [Apify Console](https://console.apify.com/) -> **Actors** -> **Create new**.
2. Select **Link to GitHub repository**.
3. Select your repository: `raghav-0905/WealthPilot`.
4. In **Source Directory / Root Directory**, specify the subfolder for each actor:
   - Actor 1: `actors/wp-client-context`
   - Actor 2: `actors/wp-research-policy`
   - Actor 3: `actors/wp-strategy`
   - Actor 4: `actors/wp-tax-compliance`
   - Actor 5: `actors/wp-evaluator`
   - Actor 6: `actors/wp-execution-monitor`
   - Actor 7: `actors/wp-orchestrator`
5. Repeat for each actor you wish to publish as a standalone tool in the Apify Store or private catalog.

#### Method 2: Using Apify CLI Subfolder Push
Navigate into each actor's directory and push individually:

```bash
cd actors/wp-client-context
apify push

cd ../wp-research-policy
apify push

# Repeat for remaining specialist actors
```

---

## 3. Environment Variables Configuration

Set these environment variables in your **Apify Actor Settings** or `.env` file:

| Variable | Description | Example / Default |
| :--- | :--- | :--- |
| `WEALTHPILOT_MODE` | Runtime execution engine | `live` (Apify + LLM) or `dummy` (Deterministic) |
| `APIFY_TOKEN` | Your Apify API Token | `apify_api_xxxxxxxxxxxxxxxx` |
| `APIFY_USERNAME` | Your Apify Account Username | `your-username` |
| `LLM_PROVIDER` | Model inference provider | `apify-openrouter` or `gemini` or `openai` |
| `LLM_API_KEY` | API Key for LLM provider | Same as `APIFY_TOKEN` if using Apify OpenRouter |
| `LLM_MODEL` | Foundation model name | `openai/gpt-4o-mini` or `anthropic/claude-3-5-sonnet` |
| `PORT` | Web server listening port | `8000` |

---

## 4. Deploying the Frontend Portal

The frontend consists of static client files (`index.html`, `style.css`, `app.js`) backed by `frontend/server.py` to route API requests to local or remote Apify actors.

### Option A: Deploy on Render / Railway / Fly.io (Single Container)
Render or Railway provides the easiest deployment because it runs `server.py` directly.

#### 1. Add `render.yaml` or Dockerfile for Web Service
```yaml
services:
  - type: web
    name: wealthpilot-portal
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: python frontend/server.py $PORT
    envVars:
      - key: WEALTHPILOT_MODE
        value: live
      - key: APIFY_TOKEN
        sync: false
      - key: LLM_API_KEY
        sync: false
```

#### 2. Deploy via Render Console
1. Connect your GitHub repository `raghav-0905/WealthPilot` on [Render.com](https://render.com).
2. Set **Start Command**: `python frontend/server.py 10000` (or `$PORT`).
3. Add environment variables (`APIFY_TOKEN`, `LLM_API_KEY`).
4. Click **Deploy**. Your institutional frontend will be live on a public HTTPS URL (e.g. `https://wealthpilot-portal.onrender.com`).

---

### Option B: Deploy Static Frontend on Vercel / Netlify
If you want to host the UI as a static site:
1. In `frontend/app.js`, set the API endpoint to point to your deployed backend or Apify webhook URL:
   ```javascript
   const API_BASE_URL = "https://your-backend-api.onrender.com";
   ```
2. In Vercel or Netlify:
   - **Root Directory**: `frontend`
   - **Build Command**: Leave empty (Pure HTML/CSS/JS)
   - **Publish Directory**: `.`
3. Deploy!

---

## 5. Pre-Deployment Verification Checklist

Before pushing to production, run the following verification steps:

- [x] **Local Multi-Agent Execution**:
  ```bash
  python run.py --scenario 1
  ```
- [x] **JavaScript Syntax & Integrity**:
  ```bash
  node -c frontend/app.js
  ```
- [x] **Local Frontend Server Verification**:
  ```bash
  python frontend/server.py 8000
  ```
- [x] **Schema Validation**:
  ```bash
  python -c "from schemas.validate import validate_data; print('Schemas OK')"
  ```
- [x] **Git Clean State**: Confirm all local changes are staged and pushed to `main`.
