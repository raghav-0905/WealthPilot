/**
 * WealthPilot Advisor Cockpit & Cognitive Trace Explorer
 * ======================================================
 * Interactive frontend logic supporting both live backend API execution
 * (http://localhost:8000) and offline standalone mode (file://).
 */

// Application State
const state = {
  currentScenario: "scenario_001",
  data: null,
  selectedStrategyId: null,
  activeStepIndex: null,
  isApproved: false,
  apiAvailable: false
};

// DOM Element References
const els = {
  btnScenario1: document.getElementById("btnScenario1"),
  btnScenario2: document.getElementById("btnScenario2"),
  btnUploadFile: document.getElementById("btnUploadFile"),
  fileInput: document.getElementById("fileInput"),
  btnExportReport: document.getElementById("btnExportReport"),
  btnOpenRunModal: document.getElementById("btnOpenRunModal"),
  btnCloseRunModal: document.getElementById("btnCloseRunModal"),
  btnCancelRun: document.getElementById("btnCancelRun"),
  btnSubmitRun: document.getElementById("btnSubmitRun"),
  runModalOverlay: document.getElementById("runModalOverlay"),
  inputClientId: document.getElementById("inputClientId"),
  inputGoal: document.getElementById("inputGoal"),
  inputMaxRounds: document.getElementById("inputMaxRounds"),

  // Hero & KPIs
  clientName: document.getElementById("clientName"),
  clientPersona: document.getElementById("clientPersona"),
  kpiNetWorth: document.getElementById("kpiNetWorth"),
  kpiTopIssuer: document.getElementById("kpiTopIssuer"),
  kpiTopIssuerName: document.getElementById("kpiTopIssuerName"),
  kpiLiquidityGoal: document.getElementById("kpiLiquidityGoal"),
  kpiHorizon: document.getElementById("kpiHorizon"),
  kpiSystemMode: document.getElementById("kpiSystemMode"),

  // Graph & Timeline
  badgeStepCount: document.getElementById("badgeStepCount"),
  badgeVeto: document.getElementById("badgeVeto"),
  badgeReplan: document.getElementById("badgeReplan"),
  badgeArbitration: document.getElementById("badgeArbitration"),
  dagNodes: document.querySelectorAll(".agent-node"),
  timelineList: document.getElementById("timelineList"),

  // Right Panel: Decision Cockpit
  explanationText: document.getElementById("explanationText"),
  strategyGrid: document.getElementById("strategyGrid"),
  selectedStrategyTitle: document.getElementById("selectedStrategyTitle"),
  criteriaList: document.getElementById("criteriaList"),
  taxEstimatedAmount: document.getElementById("taxEstimatedAmount"),
  taxLossHarvested: document.getElementById("taxLossHarvested"),
  taxNotes: document.getElementById("taxNotes"),
  targetAllocationList: document.getElementById("targetAllocationList"),
  btnToggleApproval: document.getElementById("btnToggleApproval"),
  tradeTableBody: document.getElementById("tradeTableBody"),

  // Inspector Drawer
  inspectorDrawer: document.getElementById("inspectorDrawer"),
  btnCloseDrawer: document.getElementById("btnCloseDrawer"),
  drawerActorTitle: document.getElementById("drawerActorTitle"),
  drawerStepTitle: document.getElementById("drawerStepTitle"),
  drawerThought: document.getElementById("drawerThought"),
  drawerToolName: document.getElementById("drawerToolName"),
  drawerArgs: document.getElementById("drawerArgs"),
  drawerResult: document.getElementById("drawerResult")
};

// ==============================================================================
// 1. DATA INITIALIZATION & BENCHMARK FALLBACKS
// ==============================================================================

async function checkApiHealth() {
  try {
    const res = await fetch("/api/health");
    if (res.ok) {
      const data = await res.json();
      state.apiAvailable = true;
      els.kpiSystemMode.textContent = "Live API (Mode: " + data.mode + ")";
      els.kpiSystemMode.className = "kpi-value text-emerald";
    }
  } catch (e) {
    state.apiAvailable = false;
    els.kpiSystemMode.textContent = "Offline Simulator";
    els.kpiSystemMode.className = "kpi-value text-cyan";
  }
}

async function loadScenarioData(scenarioId) {
  state.currentScenario = scenarioId;
  state.isApproved = false;
  resetApprovalButton();

  // Try API first if available
  if (state.apiAvailable || window.location.protocol.startsWith("http")) {
    try {
      const res = await fetch(`/api/trace/${scenarioId}`);
      if (res.ok) {
        state.data = await res.json();
        renderCompleteUI();
        return;
      }
    } catch (e) {
      console.warn("API trace fetch failed, attempting direct relative file read...", e);
    }
  }

  // Fallback: Fetch directly from relative path docs/trace_examples/
  try {
    const relativePath = `../docs/trace_examples/${scenarioId}_trace.json`;
    const res = await fetch(relativePath);
    if (res.ok) {
      state.data = await res.json();
      renderCompleteUI();
      return;
    }
  } catch (e) {
    console.warn("Relative path fetch failed, using built-in verified snapshot...", e);
  }

  // Built-in verified snapshot fallback for direct file:// browser viewing
  state.data = getBuiltinSnapshot(scenarioId);
  renderCompleteUI();
}

// ==============================================================================
// 2. RENDERING ENGINE
// ==============================================================================

function renderCompleteUI() {
  if (!state.data) return;

  const report = state.data.finalReport || {};
  const taskGraph = report.taskGraph || {};
  const steps = taskGraph.executedSteps || [];
  const replans = taskGraph.replans || [];
  const arbitrations = report.arbitrationLog || [];
  const ranked = report.rankedOptions || [];

  // 1. Update Hero Banner
  const isScenario1 = state.currentScenario.includes("001") || report.clientId === "CLIENT_001";
  if (isScenario1) {
    els.clientName.textContent = "Rajesh Singhania";
    els.clientPersona.textContent = "Founder & Promoter | 38% Equity in PROMOTER_CO";
    els.kpiNetWorth.textContent = "₹12.00 Cr";
    els.kpiTopIssuer.textContent = "38.0%";
    els.kpiTopIssuerName.textContent = "PROMOTER_CO (Mid-Cap IT)";
    els.kpiLiquidityGoal.textContent = "₹2.00 Cr";
    els.kpiHorizon.textContent = "Target: 2 Years Horizon";

    els.badgeVeto.style.display = "block";
    els.badgeReplan.style.display = replans.length > 0 ? "block" : "none";
    els.badgeArbitration.style.display = arbitrations.length > 0 ? "block" : "none";
  } else {
    els.clientName.textContent = "Ananya Sen";
    els.clientPersona.textContent = "Senior Corporate Executive | 30% NBFC Concentration";
    els.kpiNetWorth.textContent = "₹8.00 Cr";
    els.kpiTopIssuer.textContent = "20.0%";
    els.kpiTopIssuerName.textContent = "BAJAJ_FINANCE (NBFC)";
    els.kpiLiquidityGoal.textContent = "₹4.00 Cr";
    els.kpiHorizon.textContent = "Target: 7 Years Horizon";

    els.badgeVeto.style.display = "none";
    els.badgeReplan.style.display = "none";
    els.badgeArbitration.style.display = "none";
  }

  // 2. Update Narrative
  els.explanationText.textContent = report.explanation || "No explanation provided.";

  // 3. Update Step Count
  els.badgeStepCount.textContent = `${steps.length} Steps Executed`;

  // 4. Render Step-by-Step Timeline
  renderTimeline(steps);

  // 5. Render Ranked Strategies
  renderStrategyGrid(ranked);

  // Default select Rank 1
  if (ranked.length > 0) {
    selectStrategy(ranked[0].id);
  }

  // 6. Render Allocations & Tax Impact
  renderTaxAndAllocations(report);

  // 7. Render Simulated Trade Orders
  renderTradeOrders();

  // 8. GSAP Spatial Staggered Entrances (antigravity-design-expert)
  if (window.gsap) {
    window.gsap.from(".agent-node", {
      y: 16,
      opacity: 0,
      stagger: 0.05,
      duration: 0.45,
      ease: "power2.out"
    });
    window.gsap.from(".timeline-item", {
      x: -14,
      opacity: 0,
      stagger: 0.04,
      duration: 0.4,
      ease: "power2.out"
    });
    window.gsap.from(".strategy-card", {
      y: 12,
      opacity: 0,
      stagger: 0.06,
      duration: 0.45,
      ease: "back.out(1.2)"
    });
  }
}

function renderTimeline(steps) {
  els.timelineList.innerHTML = "";

  steps.forEach((step, idx) => {
    const item = document.createElement("div");
    item.className = "timeline-item";
    
    const isVeto = step.verdict === "VETO" || (step.summary && step.summary.includes("VETO"));
    const isReplan = step.actor.includes("replanned");

    if (isVeto) item.classList.add("veto");
    if (isReplan) item.classList.add("replan");

    let pillHtml = `<span class="timeline-pill success">DONE</span>`;
    if (isVeto) pillHtml = `<span class="timeline-pill veto">HARD VETO</span>`;
    else if (isReplan) pillHtml = `<span class="timeline-pill" style="color: var(--brand-amber); border-color: var(--brand-amber);">REPLANNED</span>`;

    item.innerHTML = `
      <div class="step-marker">${step.step}</div>
      <div class="timeline-content">
        <div class="timeline-header">
          <span class="timeline-actor">${step.actor}</span>
          ${pillHtml}
        </div>
        <p class="timeline-thought">${step.summary || "Step completed successfully."}</p>
      </div>
    `;

    item.addEventListener("click", () => {
      document.querySelectorAll(".timeline-item").forEach(el => el.classList.remove("active"));
      item.classList.add("active");
      highlightDagNode(step.actor);
      openStepInspector(step, idx);
    });

    els.timelineList.appendChild(item);
  });
}

function highlightDagNode(actorName) {
  els.dagNodes.forEach(node => {
    const nodeActor = node.getAttribute("data-actor");
    if (actorName.includes(nodeActor)) {
      node.classList.add("active");
    } else {
      node.classList.remove("active");
    }
  });
}

function renderStrategyGrid(strategies) {
  els.strategyGrid.innerHTML = "";

  strategies.forEach((strat, idx) => {
    const card = document.createElement("div");
    card.className = "strategy-card" + (idx === 0 ? " selected" : "");
    card.id = `strat_card_${strat.id}`;

    card.innerHTML = `
      <div class="rank-tag">RANK #${strat.rank}</div>
      <div class="strategy-name">Strategy ${strat.id}</div>
      <div class="score-row">
        <span style="font-size: 11px; color: var(--text-muted);">Overall Fit</span>
        <span class="score-number">${(strat.totalScore * 100).toFixed(0)}%</span>
      </div>
    `;

    card.addEventListener("click", () => {
      document.querySelectorAll(".strategy-card").forEach(c => c.classList.remove("selected"));
      card.classList.add("selected");
      selectStrategy(strat.id);
    });

    els.strategyGrid.appendChild(card);
  });
}

function selectStrategy(strategyId) {
  state.selectedStrategyId = strategyId;
  const strat = (state.data?.finalReport?.rankedOptions || []).find(s => s.id === strategyId);
  if (!strat) return;

  els.selectedStrategyTitle.textContent = `Strategy ${strat.id} (Rank #${strat.rank} • ${(strat.totalScore * 100).toFixed(0)}% Score)`;

  // Render Criteria Bars
  const crit = strat.criteria || {};
  const criteriaLabels = {
    postTaxReturn: "Post-Tax Return",
    liquidity: "Liquidity Alignment",
    concentration: "Concentration Cut",
    stress: "Stress Resilience",
    compliance: "Statutory Compliance"
  };

  els.criteriaList.innerHTML = "";
  for (const [key, label] of Object.entries(criteriaLabels)) {
    const val = crit[key] || 0.8;
    const pct = Math.round(val * 100);

    const row = document.createElement("div");
    row.className = "criteria-row";
    row.innerHTML = `
      <span style="color: var(--text-secondary); font-weight: 500;">${label}</span>
      <div class="bar-bg">
        <div class="bar-fill" style="width: ${pct}%;"></div>
      </div>
      <span style="font-family: var(--font-mono); font-size: 12px; font-weight: 600; text-align: right;">${pct}%</span>
    `;
    els.criteriaList.appendChild(row);
  }

  // Animate Criteria Bars with GSAP
  if (window.gsap) {
    window.gsap.from(".bar-fill", {
      width: 0,
      stagger: 0.05,
      duration: 0.5,
      ease: "power2.out"
    });
  }
}

function renderTaxAndAllocations(report) {
  const isScenario1 = state.currentScenario.includes("001") || report.clientId === "CLIENT_001";
  
  if (isScenario1) {
    els.taxEstimatedAmount.textContent = "₹40.71 L";
    els.taxLossHarvested.textContent = "₹12.50 L";
    els.taxNotes.textContent = "Section 112A equity LTCG surcharge capped at 15%. Remainder staged into FY27-28 to avoid upper 25% surcharge slab.";
    
    els.targetAllocationList.innerHTML = `
      <div style="display: flex; justify-content: space-between; font-size: 12px;">
        <span style="color: var(--text-secondary);">Listed Equity</span>
        <span style="font-weight: 600;">21.3% (Cut from 38%)</span>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 12px;">
        <span style="color: var(--text-secondary);">Govt Bonds (Liquid)</span>
        <span style="font-weight: 600; color: var(--brand-emerald);">20.3% (+₹2.0 Cr)</span>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 12px;">
        <span style="color: var(--text-secondary);">Mutual Funds</span>
        <span style="font-weight: 600;">20.8%</span>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 12px;">
        <span style="color: var(--text-secondary);">PMS & AIF</span>
        <span style="font-weight: 600;">25.0%</span>
      </div>
    `;
  } else {
    els.taxEstimatedAmount.textContent = "₹17.56 L";
    els.taxLossHarvested.textContent = "₹0.00 L";
    els.taxNotes.textContent = "Compliant with standard LTCG rates. Remittance within $250k LRS cap with 20% TCS on excess above ₹7L.";

    els.targetAllocationList.innerHTML = `
      <div style="display: flex; justify-content: space-between; font-size: 12px;">
        <span style="color: var(--text-secondary);">NBFC Equity</span>
        <span style="font-weight: 600;">12.5% (Cut from 30%)</span>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 12px;">
        <span style="color: var(--text-secondary);">Offshore USD Equities</span>
        <span style="font-weight: 600; color: var(--brand-cyan);">15.5% (+₹60 Lakh)</span>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 12px;">
        <span style="color: var(--text-secondary);">Domestic Mutual Funds</span>
        <span style="font-weight: 600;">22.0%</span>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 12px;">
        <span style="color: var(--text-secondary);">Sovereign Bonds</span>
        <span style="font-weight: 600;">22.5%</span>
      </div>
    `;
  }
}

function renderTradeOrders() {
  els.tradeTableBody.innerHTML = "";

  if (!state.isApproved) {
    els.tradeTableBody.innerHTML = `
      <tr>
        <td colspan="5" style="text-align: center; color: var(--text-muted); padding: 24px;">
          Human-in-the-Loop Gate: Awaiting Advisor Authorization.<br>
          Click <strong>'Approve & Simulate Trades'</strong> to route orders to broker sandbox.
        </td>
      </tr>
    `;
    return;
  }

  const isScenario1 = state.currentScenario.includes("001");
  const orders = isScenario1 ? [
    { id: "ORD_77102", action: "SELL", asset: "PROMOTER_CO", amount: "₹20,000,000", status: "FILLED" },
    { id: "ORD_77103", action: "SELL", asset: "CLEANTECH_SOL", amount: "₹2,000,000", status: "FILLED (Harvested)" },
    { id: "ORD_77104", action: "BUY", asset: "GOI_BONDS_7_18", amount: "₹10,000,000", status: "FILLED" },
    { id: "ORD_77105", action: "BUY", asset: "HDFC_LARGE_CAP", amount: "₹12,000,000", status: "FILLED" }
  ] : [
    { id: "ORD_88201", action: "SELL", asset: "BAJAJ_FINANCE", amount: "₹8,000,000", status: "FILLED" },
    { id: "ORD_88202", action: "SELL", asset: "CHOLAMANDALAM", amount: "₹4,000,000", status: "FILLED" },
    { id: "ORD_88203", action: "BUY", asset: "GOI_BONDS_7_18", amount: "₹6,000,000", status: "FILLED" },
    { id: "ORD_88204", action: "BUY", asset: "VANGUARD_USD_ETF", amount: "₹6,000,000", status: "FILLED" }
  ];

  orders.forEach(o => {
    const tr = document.createElement("tr");
    const isSell = o.action === "SELL";
    tr.innerHTML = `
      <td style="font-family: var(--font-mono); font-weight: 600;">${o.id}</td>
      <td><span class="timeline-pill ${isSell ? 'veto' : 'success'}">${o.action}</span></td>
      <td style="font-weight: 500;">${o.asset}</td>
      <td style="font-family: var(--font-mono);">${o.amount}</td>
      <td><span class="timeline-pill success">${o.status}</span></td>
    `;
    els.tradeTableBody.appendChild(tr);
  });
}

function resetApprovalButton() {
  els.btnToggleApproval.className = "btn btn-emerald";
  els.btnToggleApproval.innerHTML = "<span>Approve & Simulate Trades</span>";
}

// ==============================================================================
// 3. STEP INSPECTOR DRAWER
// ==============================================================================

function openStepInspector(step, idx) {
  // Find associated trace entry if available
  const traces = state.data?.traceEntries || [];
  const matchedTrace = traces.find(t => t.actor === step.actor && (t.step === step.step || t.step === idx + 1)) || traces[idx] || {};

  els.drawerActorTitle.textContent = step.actor || "Specialist Agent";
  els.drawerStepTitle.textContent = `Step ${step.step}: ${step.verdict ? step.verdict + ' Decision' : 'Execution'}`;
  
  els.drawerThought.textContent = matchedTrace.thought || step.summary || "Autonomous cognitive execution completed.";
  els.drawerToolName.textContent = matchedTrace.tool || "Actor.call";
  els.drawerArgs.textContent = JSON.stringify(matchedTrace.args || {}, null, 2);
  els.drawerResult.textContent = matchedTrace.result_summary || step.summary || "Execution output received.";

  els.inspectorDrawer.classList.add("open");
}

function closeStepInspector() {
  els.inspectorDrawer.classList.remove("open");
}

// ==============================================================================
// 4. LIVE RUN MODAL & EVENTS
// ==============================================================================

function openRunModal() {
  const isScenario1 = state.currentScenario.includes("001");
  els.inputClientId.value = isScenario1 ? "CLIENT_001" : "CLIENT_002";
  els.inputGoal.value = isScenario1 
    ? "Reduce concentration in my own company stock tax-efficiently; need ₹2 Cr liquidity in 2 years."
    : "De-risk NBFC exposure and diversify globally via RBI LRS window while maintaining wealth compounding.";
  els.runModalOverlay.classList.add("open");
}

function closeRunModal() {
  els.runModalOverlay.classList.remove("open");
}

async function submitLiveRun() {
  const clientId = els.inputClientId.value;
  const goal = els.inputGoal.value;
  const maxRevisionRounds = parseInt(els.inputMaxRounds.value, 10) || 3;

  els.btnSubmitRun.disabled = true;
  els.btnSubmitRun.innerHTML = "<span>Running Multi-Agent Pipeline...</span>";

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clientId, goal, maxRevisionRounds })
    });

    if (res.ok) {
      state.data = await res.json();
      state.currentScenario = clientId.toLowerCase();
      renderCompleteUI();
      closeRunModal();
    } else {
      alert("Backend run returned error: " + res.statusText);
    }
  } catch (e) {
    alert("Live API call failed. Make sure 'python frontend/server.py' is running on port 8000.\n\nError: " + e.message);
  } finally {
    els.btnSubmitRun.disabled = false;
    els.btnSubmitRun.innerHTML = "<span>Launch Autonomous Pipeline</span>";
  }
}

// Export JSON
function exportReportJson() {
  if (!state.data) return;
  const blob = new Blob([JSON.stringify(state.data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${state.currentScenario}_final_report.json`;
  a.click();
  URL.revokeObjectURL(url);
}

// Load Custom Trace File
function handleFileUpload(e) {
  const file = e.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (event) => {
    try {
      const parsed = JSON.parse(event.target.result);
      state.data = parsed;
      state.currentScenario = parsed.scenarioId || parsed.clientId || "custom_upload";
      renderCompleteUI();
    } catch (err) {
      alert("Invalid JSON trace file: " + err.message);
    }
  };
  reader.readAsText(file);
}

// ==============================================================================
// 5. EVENT LISTENERS SETUP
// ==============================================================================

function setupEventListeners() {
  // Scenario switcher
  els.btnScenario1.addEventListener("click", () => {
    els.btnScenario1.classList.add("active");
    els.btnScenario2.classList.remove("active");
    loadScenarioData("scenario_001");
  });

  els.btnScenario2.addEventListener("click", () => {
    els.btnScenario2.classList.add("active");
    els.btnScenario1.classList.remove("active");
    loadScenarioData("scenario_002");
  });

  // Drawer
  els.btnCloseDrawer.addEventListener("click", closeStepInspector);

  // Modal
  els.btnOpenRunModal.addEventListener("click", openRunModal);
  els.btnCloseRunModal.addEventListener("click", closeRunModal);
  els.btnCancelRun.addEventListener("click", closeRunModal);
  els.btnSubmitRun.addEventListener("click", submitLiveRun);

  // File upload & Export
  els.btnExportReport.addEventListener("click", exportReportJson);
  els.btnUploadFile.addEventListener("click", () => els.fileInput.click());
  els.fileInput.addEventListener("change", handleFileUpload);

  // Toggle Human Approval
  els.btnToggleApproval.addEventListener("click", () => {
    state.isApproved = !state.isApproved;
    if (state.isApproved) {
      els.btnToggleApproval.className = "btn btn-secondary";
      els.btnToggleApproval.innerHTML = "<span>Reset Execution</span>";
    } else {
      resetApprovalButton();
    }
    renderTradeOrders();
  });
}

// ==============================================================================
// 6. BUILT-IN VERIFIED SNAPSHOT (FALLBACK FOR FILE://)
// ==============================================================================

function getBuiltinSnapshot(scenarioId) {
  if (scenarioId.includes("002")) {
    return {
      scenarioId: "CLIENT_002",
      clientId: "CLIENT_002",
      finalReport: {
        clientId: "CLIENT_002",
        explanation: "WealthPilot autonomous advisory review completed for CLIENT_002. Primary Recommendation: Strategy S1_NBFC_ROTATION (Score 0.90: Post-tax return 0.84, Liquidity fit 0.92, Concentration score 0.95, Stress resilience 0.84.). Tax Optimization: Verified compliance with statutory LTCG/STCG limits and surcharge brackets (Estimated Tax: ₹1,756,625). Rejected Strategies: None.",
        rankedOptions: [
          { id: "S1_NBFC_ROTATION", rank: 1, totalScore: 0.90, criteria: { postTaxReturn: 0.84, liquidity: 0.92, concentration: 0.95, stress: 0.84, compliance: 0.95 }, justification: "Score 0.90: Post-tax return 0.84, Liquidity fit 0.92, Concentration score 0.95." },
          { id: "S2_LRS_EXPANSION", rank: 2, totalScore: 0.89, criteria: { postTaxReturn: 0.82, liquidity: 0.92, concentration: 0.95, stress: 0.84, compliance: 0.95 }, justification: "Score 0.89: Post-tax return 0.82, Liquidity fit 0.92, Concentration score 0.95." },
          { id: "S3_BALANCED_GROWTH", rank: 3, totalScore: 0.85, criteria: { postTaxReturn: 0.74, liquidity: 0.92, concentration: 0.86, stress: 0.84, compliance: 0.95 }, justification: "Score 0.85: Post-tax return 0.74, Liquidity fit 0.92." }
        ],
        taskGraph: {
          executedSteps: [
            { step: 1, actor: "wp-client-context", status: "COMPLETED", summary: "Reconciled 6 holdings. Top issuer: 25.0%. Flags: 1" },
            { step: 2, actor: "wp-research-policy", status: "COMPLETED", summary: "Retrieved 3 exposure-targeted regulatory and sector findings." },
            { step: 3, actor: "wp-strategy", status: "COMPLETED", summary: "Generated 3 candidate strategies: S1_NBFC_ROTATION, S2_LRS_EXPANSION, S3_BALANCED_GROWTH." },
            { step: 4, actor: "wp-tax-compliance", status: "COMPLETED", verdict: "APPROVE", summary: "Tax gate returned APPROVE on S1_NBFC_ROTATION. Estimated Tax: ₹1,756,625." },
            { step: 5, actor: "wp-evaluator", status: "COMPLETED", summary: "Ranked 3 options; rejected 0." }
          ],
          replans: []
        }
      }
    };
  }

  // Default Scenario 001 snapshot
  return {
    scenarioId: "CLIENT_001",
    clientId: "CLIENT_001",
    finalReport: {
      clientId: "CLIENT_001",
      explanation: "WealthPilot autonomous advisory review completed for CLIENT_001. Primary Recommendation: Strategy S2 (Score 0.90: Post-tax return 0.88, Liquidity fit 0.92, Concentration score 0.86, Stress resilience 0.84.). Tax Optimization: Enforced ₹2.0 Cr annual realization cap to avoid upper surcharge slabs and harvested loss offset in CLEANTECH_SOL. Rejected Strategies: S1 (Tax cost exceeds client's stated tolerance and breaches single-year sale threshold (Vetoed by Tax & Compliance)).",
      arbitrationLog: [
        {
          conflict: "Alternative growth rotation (S4) vs. Client 2-year liquidity requirement (₹2.0 Cr)",
          decision: "Prioritize Strategy S2 (Staged Exit + Loss Harvesting) as Primary recommendation; designate S4 as Secondary alternative with liquidity caveat.",
          reasoning: "While S4 achieves high return potential, Cat-II AIFs enforce a 3-year lock-in which directly jeopardizes the client's mandatory 2-year overseas business liquidity milestone. S2 delivers immediate ₹2.0 Cr liquid funds in FY26-27, captures ₹12.5L loss harvesting in CLEANTECH_SOL, and keeps realization below the punitive 25% surcharge slab."
        }
      ],
      rankedOptions: [
        { id: "S2", rank: 1, totalScore: 0.90, criteria: { postTaxReturn: 0.88, liquidity: 0.92, concentration: 0.86, stress: 0.84, compliance: 0.95 }, justification: "Score 0.90: Post-tax return 0.88, Liquidity fit 0.92, Concentration score 0.86, Stress resilience 0.84." },
        { id: "S4", rank: 2, totalScore: 0.88, criteria: { postTaxReturn: 0.84, liquidity: 0.92, concentration: 0.86, stress: 0.78, compliance: 0.95 }, justification: "Score 0.88: Post-tax return 0.84, Liquidity fit 0.92, Concentration score 0.86, Stress resilience 0.78." },
        { id: "S3", rank: 3, totalScore: 0.88, criteria: { postTaxReturn: 0.74, liquidity: 0.92, concentration: 0.76, stress: 0.90, compliance: 0.95 }, justification: "Score 0.88: Post-tax return 0.74, Liquidity fit 0.92, Concentration score 0.76, Stress resilience 0.9." }
      ],
      taskGraph: {
        executedSteps: [
          { step: 1, actor: "wp-client-context", status: "COMPLETED", summary: "Reconciled 8 holdings. Top issuer: 38.0%. Flags: 1" },
          { step: 2, actor: "wp-research-policy", status: "COMPLETED", summary: "Retrieved 3 exposure-targeted regulatory and sector findings." },
          { step: 3, actor: "wp-strategy", status: "COMPLETED", summary: "Generated 4 candidate strategies: ['S1', 'S2', 'S3', 'S4']." },
          { step: 4, actor: "wp-tax-compliance", status: "COMPLETED", verdict: "VETO", summary: "Tax gate returned VETO on S1. Estimated Tax: ₹4,071,632." },
          { step: 5, actor: "wp-strategy (replanned)", status: "COMPLETED", summary: "Regenerated 3 compliant candidates: ['S2', 'S4', 'S3']." },
          { step: 6, actor: "wp-tax-compliance (re-check)", status: "COMPLETED", verdict: "VETO", summary: "Tax gate returned VETO on S2." },
          { step: 7, actor: "wp-evaluator", status: "COMPLETED", summary: "Ranked 3 options; rejected 0." }
        ],
        replans: [
          {
            round: 1,
            trigger: "TAX_VETO_AND_HARVESTING",
            reason: "Tax gate VETO on proposal S1 due to punitive surcharge slab. Active constraints: ['Limit sale of PROMOTER_CO to ₹2.0 Cr in FY; remainder next FY']. Discovered harvesting opportunity in CLEANTECH_SOL.",
            action: "Re-invoke wp-strategy with constraints and loss harvesting instructions"
          }
        ]
      }
    }
  };
}

// ==============================================================================
// 7. BOOTSTRAP APPLICATION
// ==============================================================================

window.addEventListener("DOMContentLoaded", async () => {
  setupEventListeners();
  await checkApiHealth();
  await loadScenarioData("scenario_001");
});
