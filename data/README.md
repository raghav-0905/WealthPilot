# WealthPilot Dummy Data Guide

This directory contains synthetic data crafted specifically to demonstrate autonomous multi-agent wealth advisory behaviors without depending on live external APIs.

## Directory Structure

```
data/
├── clients/
│   ├── client_001.json           # Promoter-entrepreneur persona (₹12 Cr net worth, 38% concentration)
│   └── client_002.json           # Salaried executive persona (₹8 Cr net worth, NBFC + LRS exposure)
├── portfolios/
│   ├── client_001_broker.csv     # Broker CSV with listed holdings and harvestable loss lot
│   ├── client_001_pms.txt        # PMS & Cat-II AIF statements with 3-year lock-in terms
│   ├── client_001_manual.json    # Commercial property and unlisted equity holdings
│   ├── client_002_broker.csv     # Broker CSV with NBFC overweight and US ETF holdings
│   ├── client_002_pms.txt        # High-conviction equity PMS statement
│   └── client_002_manual.json    # Corporate fixed deposit holding
├── market/
│   └── returns.csv               # 36-month synthetic return series for correlation and stress tests
├── kb/
│   ├── policy/                   # Markdown regulatory briefs (SEBI circulars, RBI LRS, Budget tax rules)
│   └── market/                   # Markdown market briefs (Tech midcaps, NBFCs, Macro interest rate view)
├── products/
│   └── alternatives.json         # Dummy PMS, Cat-II AIF, REIT, InvIT catalog with lock-ins and minimums
└── events/
    └── events.json               # Scripted market/promoter events for post-execution drift monitoring
```

## Natural Conflict Scenarios Designed-In

1. **Promoter Concentration vs. Tax Surcharge (Client 001):**
   - Client holds 38% of net worth in `PROMOTER_CO`. An aggressive full sale triggers a huge tax bill (>₹50L) pushing taxable income into top surcharge brackets.
   - **Expected behavior:** `wp-tax-compliance` vetoes an all-at-once exit and issues a constraint: *"Limit sale of PROMOTER_CO to ₹2.0 Cr in FY; remainder next FY"*.
2. **Tax Loss Harvesting Opportunity:**
   - In `client_001_broker.csv`, `CLEANTECH_SOL` holds an unrealized capital loss of ₹12.5 Lakhs.
   - **Expected behavior:** `wp-tax-compliance` opportunistically flags this lot to offset gains, prompting an Orchestrator replan.
3. **Liquidity Need vs. AIF Lock-in:**
   - Client 001 has a ₹2 Cr liquidity goal within 2 years, but holds ₹1.2 Cr in `STELLAR_GROWTH_AIF_CAT2` with a mandatory 3-year lock-in.
   - **Expected behavior:** `wp-evaluator` and `wp-orchestrator` penalize or arbitrate against any strategy that assumes liquidity from locked-in AIF units.
4. **Different Exposures Drive Different Research Topics (Client 002):**
   - Client 002 has high NBFC exposure (30%) and US ETF holdings under LRS.
   - **Expected behavior:** `wp-research-policy` automatically investigates RBI NBFC guidelines and LRS/TCS rules instead of the tech mid-cap topics queried for Client 001.
