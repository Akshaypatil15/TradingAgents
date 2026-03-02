/* ============================================================
   Quantech Demo - Application Logic
   Separated JS for maintainability and modularity
   ============================================================ */

/* --- Application State --- */
const state = {
  isRunning: false,
  reports: {},
  dashboards: {},
  currentReportKey: "",
  timerInterval: null,
  timerSeconds: 0,
};

/* --- LLM Model Definitions --- */
const MODELS = {
  openai: ["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o"],
  anthropic: ["claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5"],
  google: [
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
  ],
  xai: ["grok-4", "grok-4-1-fast-reasoning"],
  openrouter: ["nvidia/nemotron-3-nano", "z-ai/glm-4.5-air"],
};

/* --- Initialization --- */
document.addEventListener("DOMContentLoaded", () => {
  const dateInput = document.getElementById("analysisDate");
  const today = new Date();

  // Set default value to today
  dateInput.valueAsDate = today;

  // Fix: Restrict date picker to max today or past dates
  const yyyy = today.getFullYear();
  const mm = String(today.getMonth() + 1).padStart(2, "0");
  const dd = String(today.getDate()).padStart(2, "0");
  dateInput.setAttribute("max", `${yyyy}-${mm}-${dd}`);

  updateModels();
  startClock();
});

/* --- Model Dropdown Population --- */
async function updateModels() {
  const provider = document.getElementById("llmProvider").value;
  const sel = document.getElementById("modelSelect");
  sel.innerHTML = "";

  if (provider === "ollama" || provider === "lmstudio") {
    const label = provider === "ollama" ? "Ollama" : "LM Studio";
    sel.add(new Option("Connecting to " + label + "...", ""));
    const endpoint =
      provider === "ollama"
        ? "http://localhost:8000/api/ollama_models"
        : "http://localhost:8000/api/lmstudio_models";
    try {
      const res = await fetch(endpoint);
      const data = await res.json();
      sel.innerHTML = "";
      if (data.models && data.models.length > 0) {
        data.models.forEach((m) => sel.add(new Option(m, m)));
      } else {
        sel.add(new Option("No models found", ""));
      }
    } catch (_) {
      sel.innerHTML = "";
      sel.add(new Option("Error fetching models", ""));
    }
  } else if (MODELS[provider]) {
    MODELS[provider].forEach((m) => sel.add(new Option(m, m)));
  }
}

/* --- Checkbox Toggle Fix --- */
function toggleCheckbox(el, event) {
  // 1. Get the internal checkbox
  const cb = el.querySelector('input[type="checkbox"]');

  // 2. If the user didn't click the checkbox directly, toggle it manually
  if (event.target !== cb) {
    cb.checked = !cb.checked;
  }

  // 3. Toggle the 'selected' class based on the checkbox state
  if (cb.checked) {
    el.classList.add("selected");
  } else {
    el.classList.remove("selected");
  }
}

/* --- Initialization --- */
document.addEventListener("DOMContentLoaded", () => {
  // Date Fix: Restrict to max today
  const dateInput = document.getElementById("analysisDate");
  const today = new Date();
  dateInput.valueAsDate = today;
  dateInput.setAttribute("max", today.toISOString().split("T")[0]);

  // Data Source Logic: Attach listeners to all cards
  document.querySelectorAll(".checkbox-card").forEach((card) => {
    // Ensure the visual state matches the 'checked' attribute on load
    const cb = card.querySelector("input");
    if (cb && cb.checked) card.classList.add("selected");

    card.addEventListener("click", (e) => toggleCheckbox(card, e));
  });

  // Keep existing model and clock init
  updateModels();
  startClock();
});

/* --- Agent Card Toggle --- */
function toggleAgentCard(el) {
  el.classList.toggle("selected-agent");
}

/* --- Advanced Section Toggle --- */
function toggleAdvanced() {
  const content = document.getElementById("advancedContent");
  content.classList.toggle("open");
  const arrow = document.querySelector(".advanced-toggle-arrow");
  if (arrow) {
    arrow.textContent = content.classList.contains("open")
      ? "\u25B2"
      : "\u25BC";
  }
}

/* --- Session Timer / Clock --- */
function startClock() {
  function tick() {
    const el = document.getElementById("sessionTimer");
    if (el) el.textContent = new Date().toLocaleTimeString("en-GB");
  }
  tick();
  setInterval(tick, 1000);
}

function startSessionTimer() {
  state.timerSeconds = 0;
  clearInterval(state.timerInterval);
  state.timerInterval = setInterval(() => {
    state.timerSeconds++;
    const h = String(Math.floor(state.timerSeconds / 3600)).padStart(2, "0");
    const m = String(Math.floor((state.timerSeconds % 3600) / 60)).padStart(
      2,
      "0",
    );
    const s = String(state.timerSeconds % 60).padStart(2, "0");
    const el = document.getElementById("sessionTimer");
    if (el) el.textContent = h + ":" + m + ":" + s;
  }, 1000);
}

function stopSessionTimer() {
  clearInterval(state.timerInterval);
}

/* --- Collect Config from UI --- */
function getConfig() {
  const selectedAnalysts = [];
  document
    .querySelectorAll(".checkbox-card.selected input")
    .forEach((i) => selectedAnalysts.push(i.value));

  const selectedAgents = [];
  const agentMap = {
    "agent-bull": "bull",
    "agent-bear": "bear",
    "agent-trader": "trader",
    "agent-risk": "risk",
  };
  document.querySelectorAll(".agent-card.selected-agent").forEach((card) => {
    if (agentMap[card.id]) selectedAgents.push(agentMap[card.id]);
  });

  return {
    ticker: document.getElementById("ticker").value,
    date: document.getElementById("analysisDate").value,
    analysts: selectedAnalysts,
    selected_agents: selectedAgents,
    provider: document.getElementById("llmProvider").value,
    model_deep: document.getElementById("modelSelect").value,
    model_fast: document.getElementById("modelSelect").value,
    reasoning_effort: "medium",
    max_debate_rounds: parseInt(
      document.getElementById("debateRounds").value,
      10,
    ),
    max_risk_rounds: parseInt(document.getElementById("riskRounds").value, 10),
    max_recur_limit: parseInt(document.getElementById("recurLimit").value, 10),
    results_dir: document.getElementById("resultsDir").value,
    vendors: {
      core_stock_apis: document.getElementById("vendorStock").value,
      news_data: document.getElementById("vendorNews").value,
      fundamental_data: document.getElementById("vendorFund").value,
      technical_indicators: document.getElementById("vendorTech").value,
    },
  };
}

/* --- Start Analysis --- */
async function startAnalysis() {
  if (state.isRunning) return;

  const config = getConfig();

  // Reset state
  state.isRunning = true;
  state.reports = {};
  state.dashboards = {};

  // Update UI status
  const statusBadge = document.getElementById("globalStatus");
  statusBadge.className = "status-badge active";
  document.getElementById("statusText").textContent = "RUNNING";

  // Update ticker display
  const tickerEl = document.getElementById("tickerDisplay");
  if (tickerEl) tickerEl.textContent = config.ticker;

  // Clear outputs
  document.getElementById("logOutput").value = "";
  document.getElementById("reportOutput").value = "Waiting for reports...";

  // Clear dropdowns
  clearDropdown("dashboardDropdown");
  clearDropdown("reportDropdown");

  // Reset agent cards
  document.querySelectorAll(".agent-card").forEach((c) => {
    c.classList.remove("completed", "running");
    const spinner = c.querySelector(".spinner");
    const check = c.querySelector(".check-icon");
    const txt = c.querySelector(".agent-status-text");
    if (spinner) spinner.style.display = "none";
    if (check) check.style.display = "none";
    if (txt) {
      txt.textContent = "Pending";
      txt.style.color = "";
    }
  });

  // Disable start button
  const startBtn = document.getElementById("startBtn");
  if (startBtn) startBtn.disabled = true;

  // Log config
  logMessage("=== ANALYSIS CONFIG ===");
  logMessage("Ticker: " + config.ticker + " | Date: " + config.date);
  logMessage("Analysts: " + config.analysts.join(", "));
  logMessage("Provider: " + config.provider + " | Model: " + config.model_deep);
  logMessage(
    "Debate Rounds: " +
      config.max_debate_rounds +
      " | Risk Rounds: " +
      config.max_risk_rounds,
  );
  logMessage("=== CONNECTING TO BACKEND ===");

  startSessionTimer();

  try {
    const res = await fetch("http://localhost:8000/api/start_analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });

    if (!res.ok) throw new Error("Backend returned " + res.status);

    const evtSource = new EventSource("http://localhost:8000/api/stream_logs");

    evtSource.onmessage = (e) => {
      const data = JSON.parse(e.data);
      handleEvent(data, evtSource);
    };

    evtSource.onerror = () => {
      evtSource.close();
      finishAnalysis();
    };
  } catch (e) {
    logMessage("ERROR: " + e.message);
    logMessage("Make sure the backend is running on localhost:8000");
    finishAnalysis();
  }
}

/* --- Stop Analysis --- */
function stopAnalysis() {
  fetch("http://localhost:8000/api/stop_analysis", { method: "POST" }).catch(
    () => {},
  );
  finishAnalysis();
  logMessage("Analysis stopped by user.");
}

/* --- Event Handler --- */
function handleEvent(data, evtSource) {
  if (data.type === "log") {
    logMessage(data.content);
    if (data.stats) updateStats(data.stats);
  } else if (data.type === "status") {
    setAgentStatus(data.agent, data.status);
  } else if (data.type === "report") {
    state.reports[data.title] = data.content;
    addToDropdown("reportDropdown", data.title);
    if (
      Object.keys(state.reports).length === 1 ||
      data.title === "Final Portfolio Decision"
    ) {
      state.currentReportKey = data.title;
      updateReportView(data.title);
      document.getElementById("reportDropdown").value = data.title;
    }
  } else if (data.type === "dashboard") {
    state.dashboards[data.title] = data.data;
    addToDropdown("dashboardDropdown", data.title);
    if (Object.keys(state.dashboards).length === 1) {
      document.getElementById("dashboardDropdown").value = data.title;
      onDashboardSelect(data.title);
    }
  } else if (data.type === "complete") {
    evtSource.close();
    finishAnalysis();
  }
}

/* --- Finish Analysis --- */
function finishAnalysis() {
  state.isRunning = false;
  stopSessionTimer();

  const statusBadge = document.getElementById("globalStatus");
  statusBadge.className = "status-badge done";
  document.getElementById("statusText").textContent = "DONE";

  const startBtn = document.getElementById("startBtn");
  if (startBtn) startBtn.disabled = false;
}

/* --- Log Messages --- */
function logMessage(msg) {
  const el = document.getElementById("logOutput");
  const time = new Date().toLocaleTimeString("en-GB");
  el.value += "[" + time + "] " + msg + "\n";
  el.scrollTop = el.scrollHeight;
}

/* --- Stats --- */
function updateStats(stats) {
  const llm = document.getElementById("statLLM");
  const tool = document.getElementById("statTool");
  const tokens = document.getElementById("statTokens");
  if (llm) llm.textContent = stats.llm_calls;
  if (tool) tool.textContent = stats.tool_calls;
  if (tokens) tokens.textContent = stats.tokens;
}

/* --- Agent Status --- */
function setAgentStatus(agentKey, status) {
  const map = {
    market: "agent-market",
    news: "agent-news",
    social: "agent-social",
    fundamentals: "agent-fundamentals",
    fund: "agent-fundamentals",
    bull: "agent-bull",
    bear: "agent-bear",
    trader: "agent-trader",
    risk: "agent-risk",
  };

  let id = "";
  for (const [key, val] of Object.entries(map)) {
    if (agentKey.includes(key)) {
      id = val;
      break;
    }
  }

  const card = document.getElementById(id);
  if (!card) return;

  const spinner = card.querySelector(".spinner");
  const check = card.querySelector(".check-icon");
  const txt = card.querySelector(".agent-status-text");

  if (status === "thinking") {
    card.classList.add("running");
    card.classList.remove("completed");
    if (spinner) spinner.style.display = "block";
    if (check) check.style.display = "none";
    if (txt) {
      txt.textContent = "Thinking...";
      txt.style.color = "var(--primary)";
    }
  } else if (status === "completed") {
    card.classList.remove("running");
    card.classList.add("completed");
    if (spinner) spinner.style.display = "none";
    if (check) check.style.display = "inline-flex";
    if (txt) {
      txt.textContent = "Completed";
      txt.style.color = "var(--primary)";
    }
  }
}

/* --- Dropdown Helpers --- */
function addToDropdown(id, title) {
  const dd = document.getElementById(id);
  for (let i = 0; i < dd.options.length; i++) {
    if (dd.options[i].value === title) return;
  }
  dd.add(new Option(title, title));
}

function clearDropdown(id) {
  const dd = document.getElementById(id);
  dd.innerHTML = "";
  dd.add(new Option("-- select --", ""));
}

/* --- Report View --- */
function onReportSelect(key) {
  if (!key) return;
  state.currentReportKey = key;
  updateReportView(key);
}

function updateReportView(key) {
  const el = document.getElementById("reportOutput");
  el.value = state.reports[key] || "No report data.";
  const dd = document.getElementById("reportDropdown");
  if (dd.value !== key) dd.value = key;
}

/* --- Dashboard View --- */
function onDashboardSelect(value) {
  if (!value) return;
  const box = document.getElementById("dashboardImageBox");
  const data = state.dashboards[value];
  if (!data) {
    box.innerHTML =
      '<div class="empty-state"><div class="empty-state-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="m9 9 6 6m0-6-6 6"/></svg></div><p class="empty-state-text">No dashboard data available yet.</p></div>';
    return;
  }
  let html = '<div style="display:flex;flex-direction:column;gap:16px;">';
  if (data.input) {
    html +=
      '<div class="dashboard-image-label">INPUT</div><img src="data:image/png;base64,' +
      data.input +
      '" alt="Input visualization">';
  }
  if (data.output) {
    html +=
      '<div class="dashboard-image-label">OUTPUT</div><img src="data:image/png;base64,' +
      data.output +
      '" alt="Output visualization">';
  }
  if (data.relationship) {
    html +=
      '<div class="dashboard-image-label">RELATIONSHIP</div><img src="data:image/png;base64,' +
      data.relationship +
      '" alt="Relationship visualization">';
  }
  html += "</div>";
  box.innerHTML = html;
}

/* --- Report Chat --- */
async function askQuestionToReport(question) {
  const context = state.reports[state.currentReportKey] || "";
  if (!context) return;
  try {
    const res = await fetch("http://localhost:8000/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: question,
        context: context,
        provider: document.getElementById("llmProvider").value,
      }),
    });
    const data = await res.json();
    const ta = document.getElementById("reportOutput");
    ta.value = ta.value.replace(
      "> AI: Thinking...",
      "> AI: " + data.answer + "\n\n",
    );
    ta.scrollTop = ta.scrollHeight;
  } catch (e) {
    const ta = document.getElementById("reportOutput");
    ta.value += "\nError: " + e.message + "\n";
  }
}

/* --- Report Input Key Handler --- */
document.addEventListener("DOMContentLoaded", () => {
  const reportOutput = document.getElementById("reportOutput");
  if (reportOutput) {
    reportOutput.addEventListener("keydown", async (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const lines = e.target.value.trim().split("\n");
        const question = lines[lines.length - 1];
        if (!question) return;
        e.target.value += "\n\n> User: " + question + "\n> AI: Thinking...";
        e.target.scrollTop = e.target.scrollHeight;
        await askQuestionToReport(question);
      }
    });
  }
});

/* --- Copy Log Output --- */
function copyLogs() {
  const el = document.getElementById("logOutput");
  if (el) {
    navigator.clipboard.writeText(el.value).catch(() => {});
  }
}

/* --- Clear Log Output --- */
function clearLogs() {
  const el = document.getElementById("logOutput");
  if (el) el.value = "";
}

/* --- Open Logs in Popup Window --- */
function openLogsWindow() {
  const raw = document.getElementById("logOutput").value || "No logs yet.";
  const win = window.open(
    "",
    "_blank",
    "width=900,height=650,top=100,left=100",
  );
  if (!win) return;
  win.document.write(
    "<!DOCTYPE html><html><head><title>Quantech Demo // Logs</title>" +
      "<style>body{background:#06080a;color:#e1e4ea;font-family:'JetBrains Mono',monospace;font-size:12px;padding:20px;margin:0}" +
      "h3{color:#00d992;margin-bottom:12px}.toolbar{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap}" +
      "button{background:#23272f;border:1px solid #2a2e37;color:#e1e4ea;padding:5px 10px;border-radius:4px;cursor:pointer;font-family:monospace;font-size:11px}" +
      "button.active{border-color:#00d992;color:#00d992}#logContainer{background:#000;padding:12px;border-radius:6px;border:1px solid #2a2e37;max-height:520px;overflow-y:auto}" +
      "pre{white-space:pre-wrap;word-break:break-word;line-height:1.6;margin:0}" +
      ".line-INFO{color:#e1e4ea}.line-DEBUG{color:#8b919e}.line-WARNING{color:#f59e0b}.line-ERROR{color:#ef4444}" +
      ".line-CONFIG{color:#3b82f6}.line-SYSTEM{color:#00d992}.line-GRAPH{color:#8b5cf6}.line-AGENT{color:#ec4899}" +
      "</style></head><body>" +
      "<h3>Quantech Demo - Log Output</h3>" +
      '<div class="toolbar">' +
      '<button onclick="window.close()">Close</button>' +
      "<button onclick=\"navigator.clipboard.writeText(document.getElementById('logContainer').innerText)\">Copy All</button>" +
      '<button class="active" onclick="filterLogs(\'ALL\',this)">ALL</button>' +
      "<button onclick=\"filterLogs('INFO',this)\">INFO</button>" +
      "<button onclick=\"filterLogs('ERROR',this)\">ERROR</button>" +
      "<button onclick=\"filterLogs('WARNING',this)\">WARNING</button>" +
      "</div>" +
      '<div id="logContainer"><pre id="logPre"></pre></div>' +
      "<script>" +
      "var raw=" +
      JSON.stringify(raw) +
      ";" +
      "var lines=raw.split('\\n').filter(function(l){return l.trim()});" +
      "function getLineClass(l){if(l.indexOf('[ERROR]')===0||l.indexOf('ERROR:')===0)return'line-ERROR';if(l.indexOf('[WARNING]')===0)return'line-WARNING';if(l.indexOf('[DEBUG]')===0)return'line-DEBUG';if(l.indexOf('CONFIG:')===0)return'line-CONFIG';if(l.indexOf('SYSTEM:')===0)return'line-SYSTEM';if(l.indexOf('GRAPH:')===0)return'line-GRAPH';if(l.indexOf('AGENT:')===0||l.indexOf('MANAGER:')===0||l.indexOf('RESEARCH:')===0)return'line-AGENT';return'line-INFO'}" +
      "function filterLogs(level,btn){document.querySelectorAll('button').forEach(function(b){b.classList.remove('active')});btn.classList.add('active');var pre=document.getElementById('logPre');pre.innerHTML='';lines.forEach(function(line){var show=level==='ALL'||(level==='INFO'?getLineClass(line)==='line-INFO':line.indexOf('['+level+']')===0||line.indexOf(level+':')===0);if(show){var span=document.createElement('span');span.className=getLineClass(line);span.textContent=line+'\\n';pre.appendChild(span)}})}" +
      "filterLogs('ALL',document.querySelector('button.active'));" +
      "</" +
      "script></body></html>",
  );
  win.document.close();
}
