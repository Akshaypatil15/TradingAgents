// app.js - Real Backend Integration

const state = {
    isRunning: false,
    reports: {}, // Stores report content by title
    currentReportKey: "",
    chatHistory: []
};

// --- INITIALIZATION ---
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('analysisDate').valueAsDate = new Date();
    updateModels(); // From inline script logic
    setupEventListeners();
});

// --- EVENT LISTENERS ---
function setupEventListeners() {
    // 1. Agent Selection
    document.querySelectorAll('.agent-card').forEach(card => {
        card.addEventListener('click', function() {
            this.classList.toggle('selected-agent');
            const role = this.id.replace('agent-', '');
            // Map UI IDs to Checkbox Values
            let cbValue = role;
            if(role === 'bull' || role === 'bear') return; // Research agents aren't selectable directly in config
            if(role === 'trader' || role === 'risk') return; 
            
            const checkbox = document.querySelector(`input[value="${cbValue}"]`);
            if (checkbox) {
                checkbox.checked = this.classList.contains('selected-agent');
                checkbox.parentElement.classList.toggle('selected', checkbox.checked);
            }
        });
    });

    // 2. Report Dropdown
    const reportDropdown = document.querySelector('.panel-header .panel-dropdown');
    if(reportDropdown) {
        reportDropdown.addEventListener('change', (e) => {
            state.currentReportKey = e.target.value;
            updateReportView(e.target.value);
        });
    }

    // 3. Chat Input
    const reportInput = document.getElementById('reportInput');
    reportInput.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            const question = reportInput.value.trim();
            // If it's the last line, treat as question
            const lines = question.split('\n');
            const lastLine = lines[lines.length - 1];
            
            if (!lastLine) return;

            // Visual feedback
            reportInput.value += `\n\n> User: ${lastLine}\n> AI: Thinking...`;
            reportInput.scrollTop = reportInput.scrollHeight;

            await askQuestionToReport(lastLine);
        }
    });
}

// --- CORE: START ANALYSIS ---
async function startAnalysis() {
    if (state.isRunning) return;

    // 1. Get Config
    const config = {
        ticker: document.getElementById('ticker').value,
        date: document.getElementById('analysisDate').value,
        analysts: getSelectedAnalysts(),
        research_depth: parseInt(document.getElementById('researchDepth').value),
        provider: document.getElementById('llmProvider').value,
        model_deep: document.getElementById('deepModel').value,
        model_fast: document.getElementById('fastModel').value,
        reasoning_effort: document.getElementById('reasoningEffort').value
    };

    // 2. Reset UI
    state.isRunning = true;
    state.reports = {};
    document.getElementById('globalStatus').classList.add('active');
    document.getElementById('statusText').innerText = 'RUNNING';
    document.getElementById('dashboardInput').value = '';
    document.getElementById('reportInput').value = 'Waiting for reports...';
    
    // Reset Agents
    document.querySelectorAll('.agent-card').forEach(c => {
        c.classList.remove('completed');
        c.querySelector('.spinner').style.display = 'none';
        c.querySelector('.agent-status span').innerText = 'Pending';
        c.querySelector('.agent-status span').style.color = 'var(--text-dim)';
    });

    startSessionTimer();

    try {
        // 3. Send Start Command
        const res = await fetch('http://localhost:8000/api/start_analysis', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        if(!res.ok) throw new Error("Backend failed to start");

        // 4. Open Event Stream
        const evtSource = new EventSource('http://localhost:8000/api/stream_logs');

        evtSource.onmessage = (e) => {
            const data = JSON.parse(e.data);
            handleBackendEvent(data, evtSource);
        };

        evtSource.onerror = (e) => {
            console.error("Stream Error", e);
            evtSource.close();
            finishAnalysis();
        };

    } catch (e) {
        logToDashboard(`ERROR: ${e.message}`);
        finishAnalysis();
    }
}

// --- EVENT HANDLER ---
function handleBackendEvent(data, evtSource) {
    // 1. Logs
    if (data.type === 'log') {
        logToDashboard(data.content);
        if (data.stats) updateStats(data.stats);
    }
    
    // 2. Status Updates (Spinners)
    else if (data.type === 'status') {
        setAgentStatus(data.agent, data.status);
    }
    
    // 3. Reports
    else if (data.type === 'report') {
        const title = data.title;
        state.reports[title] = data.content;
        
        // Add to dropdown
        addReportToDropdown(title);
        
        // Auto-switch if it's the first one or important
        if (Object.keys(state.reports).length === 1 || title === "Final Portfolio Decision") {
            state.currentReportKey = title;
            updateReportView(title);
            // Select dropdown option
            const dd = document.querySelector('.panel-dropdown');
            dd.value = title;
        }
    }
    
    // 4. Completion
    else if (data.type === 'complete') {
        evtSource.close();
        finishAnalysis();
    }
}

// --- CHAT LOGIC ---
async function askQuestionToReport(question) {
    const context = state.reports[state.currentReportKey] || "";
    if (!context) return;

    try {
        const res = await fetch('http://localhost:8000/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: question,
                context: context,
                provider: document.getElementById('llmProvider').value
            })
        });
        
        const data = await res.json();
        
        // Replace "Thinking..." with answer
        const ta = document.getElementById('reportInput');
        const currentVal = ta.value;
        ta.value = currentVal.replace("> AI: Thinking...", `> AI: ${data.answer}\n\n`);
        ta.scrollTop = ta.scrollHeight;

    } catch (e) {
        const ta = document.getElementById('reportInput');
        ta.value += `\nError: ${e.message}\n`;
    }
}

// --- HELPERS ---
function logToDashboard(msg) {
    const db = document.getElementById('dashboardInput');
    const time = new Date().toLocaleTimeString();
    db.value += `[${time}] ${msg}\n`;
    db.scrollTop = db.scrollHeight;
}

function updateStats(stats) {
    document.getElementById('statLLM').innerText = stats.llm_calls;
    document.getElementById('statTool').innerText = stats.tool_calls;
    document.getElementById('statTokens').innerText = stats.tokens;
}

function setAgentStatus(agentKey, status) {
    // Map backend keys to UI IDs
    let id = "";
    if(agentKey.includes("market")) id = "agent-market";
    else if(agentKey.includes("news")) id = "agent-news";
    else if(agentKey.includes("social")) id = "agent-news"; // Share card
    else if(agentKey.includes("fund")) id = "agent-market"; // Share card
    else if(agentKey.includes("bull")) id = "agent-bull";
    else if(agentKey.includes("bear")) id = "agent-bear";
    else if(agentKey.includes("trader")) id = "agent-trader";
    else if(agentKey.includes("risk")) id = "agent-risk";
    
    const card = document.getElementById(id);
    if(!card) return;

    const spinner = card.querySelector('.spinner');
    const txt = card.querySelector('.agent-status span');

    if(status === 'thinking') {
        spinner.style.display = 'block';
        txt.innerText = 'Thinking...';
        txt.style.color = 'var(--primary)';
    } else if (status === 'completed') {
        spinner.style.display = 'none';
        txt.innerText = 'Completed';
        txt.style.color = '#fff';
        card.classList.add('completed');
        card.style.borderColor = 'var(--primary)';
    }
}

function addReportToDropdown(title) {
    const dd = document.querySelector('.panel-dropdown');
    // Check duplicates
    for(let i=0; i<dd.options.length; i++) {
        if(dd.options[i].value === title) return;
    }
    const opt = document.createElement('option');
    opt.text = title;
    opt.value = title;
    dd.add(opt);
}

function updateReportView(key) {
    const ta = document.getElementById('reportInput');
    ta.value = state.reports[key] || "No report data.";
}

function getSelectedAnalysts() {
    const arr = [];
    document.querySelectorAll('.checkbox-card.selected input').forEach(i => arr.push(i.value));
    return arr;
}

let timerInt;
function startSessionTimer() {
    let sec = 0;
    clearInterval(timerInt);
    timerInt = setInterval(() => {
        sec++;
        const date = new Date(0);
        date.setSeconds(sec);
        document.getElementById('sessionTimer').innerText = date.toISOString().substr(11, 8);
    }, 1000);
}

function finishAnalysis() {
    state.isRunning = false;
    document.getElementById('globalStatus').classList.remove('active');
    document.getElementById('statusText').innerText = 'DONE';
    clearInterval(timerInt);
}