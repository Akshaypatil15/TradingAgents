import asyncio
import json
import os
import traceback
import subprocess
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from typing import List, Optional, Dict
import logging
from collections import deque
from dynamic_dashboards.dashboard_generator import generate_dashboards
import base64

# Capture tradingagents logs into a queue for streaming to UI
log_records = deque(maxlen=500)


class UILogHandler(logging.Handler):
    def emit(self, record):
        log_records.append({"level": record.levelname, "message": self.format(record), "time": record.created})


ui_handler = UILogHandler()
ui_handler.setFormatter(logging.Formatter("%(asctime)s | %(name)s | %(message)s", datefmt="%H:%M:%S"))
logging.getLogger("tradingagents").addHandler(ui_handler)
logging.getLogger("tradingagents").setLevel(logging.DEBUG)

# --- IMPORT TRADING AGENTS ---
try:
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG
    from cli.stats_handler import StatsCallbackHandler
    from tradingagents.llm_clients.factory import create_llm_client

    # Import the connection manager to close it properly
    from tradingagents.llm_clients.lm_studio_api_management.connection_manager import lm_studio_manager
except ImportError as e:
    print("Error: Could not import TradingAgents modules.")
    raise e


# --- LIFESPAN MANAGER (FIXES THE HANGING) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    print("INFO:    TradingAgents Engine Starting...")
    yield
    # Shutdown logic (Runs when you press Ctrl+C)
    print("INFO:    Shutting down... Closing connections.")
    lm_studio_manager.close()  # <--- Force close the persistent connection
    print("INFO:    Connections closed. RAM released.")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- DATA MODELS ---
class AnalysisConfig(BaseModel):
    ticker: str
    date: str
    analysts: List[str]
    selected_agents: Optional[List[str]] = None  # bull, bear, trader, risk
    provider: str
    model_deep: str
    model_fast: str
    reasoning_effort: str
    max_debate_rounds: int = 1
    max_risk_rounds: int = 1
    max_recur_limit: int = 100
    results_dir: str = "./results"
    vendors: Optional[Dict[str, str]] = None


class ChatRequest(BaseModel):
    question: str
    context: str
    provider: str


class DashboardRequest(BaseModel):
    agent: str
    ticker: str
    date: str
    results_dir: str = "./results"


# --- GLOBAL STATE ---
analysis_queue = asyncio.Queue()

# --- ROUTES ---

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/ollama_models")
async def get_ollama_models():
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, shell=True)
        if result.returncode != 0:
            return {"models": [], "error": "Ollama command failed"}
        lines = result.stdout.strip().split("\n")
        models = [line.split()[0] for line in lines[1:] if line.split()]
        return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}


@app.get("/api/lmstudio_models")
async def get_lmstudio_models():
    lm_url = "http://127.0.0.1:1234/v1/models"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(lm_url, timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                return {"models": models}
            else:
                return {"models": [], "error": f"LM Studio returned status {resp.status_code}"}
    except Exception as e:
        return {"models": [], "error": "Could not connect to LM Studio"}


@app.post("/api/start_analysis")
async def start_analysis(config: AnalysisConfig):
    while not analysis_queue.empty():
        try:
            analysis_queue.get_nowait()
        except:
            pass
    await analysis_queue.put(config)
    return {"status": "queued"}


# In server.py, replace run_dashboard with this version
# that passes graph_config so the same LLM/model is used


async def run_dashboard(agent: str, ticker: str, date: str, results_dir: str, config: dict) -> dict:
    """Run dashboard generator using same LLM config as the analysis."""
    try:
        import asyncio
        from dynamic_dashboards.dashboard_generator import generate_dashboards
        import base64

        agent = agent.lower()
        valid = ["market", "news", "social", "fundamentals", "bull", "bear", "research", "trader", "risk"]
        if agent not in valid:
            print(f"Dashboard: unknown agent '{agent}', skipping")
            return {}

        # Pass config so generator uses same LM Studio model
        paths = await asyncio.get_event_loop().run_in_executor(
            None, lambda: generate_dashboards(agent, ticker, date, results_dir, config=config)
        )

        result = {}
        for dtype, path in paths.items():
            with open(path, "rb") as f:
                result[dtype] = base64.b64encode(f.read()).decode("utf-8")
        return result

    except Exception as e:
        print(f"Dashboard error for {agent}: {e}")
        traceback.print_exc()
        return {}


@app.get("/api/stream_logs")
async def stream_logs(request: Request):
    async def event_generator():
        # Step 1: Confirm connection
        yield json.dumps({"type": "log", "content": "STREAM: Connected to server"})

        # Step 2: Get config from queue ONCE
        try:
            config_data = await asyncio.wait_for(analysis_queue.get(), timeout=10.0)
        except asyncio.TimeoutError:
            yield json.dumps({"type": "log", "content": "ERROR: Timeout waiting for config."})
            return

        yield json.dumps({"type": "log", "content": f"STREAM: Config received for {config_data.ticker}"})

        if await request.is_disconnected():
            return

        yield json.dumps({"type": "log", "content": f"SYSTEM: Initializing {config_data.ticker} analysis..."})

        # Step 3: Prepare directory
        base_path = config_data.results_dir.strip() if config_data.results_dir else ""
        if not base_path:
            base_path = os.path.join(os.getcwd(), "results")

        try:
            os.makedirs(base_path, exist_ok=True)
            yield json.dumps({"type": "log", "content": f"FILESYSTEM: Saving results to {base_path}"})
        except Exception as e:
            yield json.dumps({"type": "log", "content": f"ERROR: Could not create directory. Using default."})
            base_path = os.path.join(os.getcwd(), "results")

        # Step 4: Build config
        graph_config = DEFAULT_CONFIG.copy()
        graph_config["llm_provider"] = config_data.provider
        graph_config["deep_think_llm"] = config_data.model_deep
        graph_config["quick_think_llm"] = config_data.model_fast

        if config_data.provider == "openai":
            graph_config["openai_reasoning_effort"] = config_data.reasoning_effort
        elif config_data.provider == "lmstudio":
            graph_config["backend_url"] = "http://127.0.0.1:1234/v1"

        graph_config["max_debate_rounds"] = config_data.max_debate_rounds
        graph_config["max_risk_discuss_rounds"] = config_data.max_risk_rounds
        graph_config["max_recur_limit"] = config_data.max_recur_limit
        graph_config["results_dir"] = base_path

        if config_data.vendors:
            graph_config["data_vendors"] = {
                "core_stock_apis": config_data.vendors.get(
                    "core_stock_apis", DEFAULT_CONFIG["data_vendors"]["core_stock_apis"]
                ),
                "technical_indicators": config_data.vendors.get(
                    "technical_indicators", DEFAULT_CONFIG["data_vendors"]["technical_indicators"]
                ),
                "fundamental_data": config_data.vendors.get(
                    "fundamental_data", DEFAULT_CONFIG["data_vendors"]["fundamental_data"]
                ),
                "news_data": config_data.vendors.get("news_data", DEFAULT_CONFIG["data_vendors"]["news_data"]),
            }

        selected_analysts = config_data.analysts if config_data.analysts else ["market"]

        selected_agents = config_data.selected_agents
        if not selected_agents:
            enable_bull = enable_bear = enable_trader = enable_risk = True
        else:
            enable_bull = "bull" in selected_agents
            enable_bear = "bear" in selected_agents
            enable_trader = "trader" in selected_agents
            enable_risk = "risk" in selected_agents

        graph_config["enable_bull_researcher"] = enable_bull
        graph_config["enable_bear_researcher"] = enable_bear
        graph_config["enable_trader"] = enable_trader
        graph_config["enable_risk_manager"] = enable_risk

        # Step 5: Log final config
        yield json.dumps({"type": "log", "content": f"CONFIG: Analysts={selected_analysts}"})
        yield json.dumps({"type": "log", "content": f"CONFIG: Agents={selected_agents or 'all'}"})
        yield json.dumps(
            {"type": "log", "content": f"CONFIG: Provider={config_data.provider} | Model={config_data.model_deep}"}
        )
        yield json.dumps(
            {
                "type": "log",
                "content": f"CONFIG: Debate={graph_config['max_debate_rounds']} | Risk={graph_config['max_risk_discuss_rounds']} | Recur={graph_config['max_recur_limit']}",
            }
        )
        yield json.dumps({"type": "log", "content": f"CONFIG: Vendors={graph_config['data_vendors']}"})
        yield json.dumps({"type": "log", "content": f"CONFIG: Results Dir={base_path}"})

        # Step 6: Build and run graph ONCE
        try:
            stats_handler = StatsCallbackHandler()
            yield json.dumps({"type": "log", "content": "GRAPH: Initializing TradingAgentsGraph..."})

            graph = TradingAgentsGraph(
                selected_analysts=selected_analysts,
                selected_agents=selected_agents if selected_agents else None,
                config=graph_config,
                callbacks=[stats_handler],
            )
            yield json.dumps({"type": "log", "content": "GRAPH: Graph built successfully"})

            init_state = graph.propagator.create_initial_state(config_data.ticker, config_data.date)
            yield json.dumps({"type": "log", "content": "GRAPH: Initial state created, starting stream..."})

            # Seed final_state with initial values so ticker/date are always available
            final_state = {
                "company_of_interest": config_data.ticker,
                "trade_date": config_data.date,
            }

            # Single loop only
            async for chunk in graph.graph.astream(init_state):
                while log_records:
                    rec = log_records.popleft()
                    yield json.dumps(
                        {"type": "log", "content": f"[{rec['level']}] {rec['message']}", "level": rec["level"]}
                    )
                if await request.is_disconnected():
                    print("Client disconnected. Stopping.")
                    break

                stats = stats_handler.get_stats()
                current_stats = {
                    "llm_calls": stats["llm_calls"],
                    "tool_calls": stats["tool_calls"],
                    "tokens": stats["tokens_in"] + stats["tokens_out"],
                }
                chunk_key = list(chunk.keys())[0] if chunk else ""
                yield json.dumps(
                    {"type": "log", "content": f"GRAPH: Chunk keys={list(chunk.keys())}", "stats": current_stats}
                )
                # Get the actual state values from inside the chunk
                chunk_data = chunk.get(chunk_key, {})
                for k, v in chunk_data.items():
                    if v is not None and v != "" and v != [] and v != {}:
                        final_state[k] = v

                if "market_report" in chunk_data and chunk_data["market_report"]:
                    yield json.dumps({"type": "status", "agent": "market", "status": "completed"})
                    yield json.dumps(
                        {"type": "report", "title": "Market Analysis", "content": chunk_data["market_report"]}
                    )
                    yield json.dumps(
                        {"type": "log", "content": "AGENT: Market Analyst finished.", "stats": current_stats}
                    )

                if "news_report" in chunk_data and chunk_data["news_report"]:
                    yield json.dumps({"type": "status", "agent": "news", "status": "completed"})
                    yield json.dumps({"type": "report", "title": "News Analysis", "content": chunk_data["news_report"]})
                    yield json.dumps(
                        {"type": "log", "content": "AGENT: News Analyst finished.", "stats": current_stats}
                    )

                if "sentiment_report" in chunk_data and chunk_data["sentiment_report"]:
                    yield json.dumps({"type": "status", "agent": "social", "status": "completed"})
                    yield json.dumps(
                        {"type": "report", "title": "Social Sentiment", "content": chunk_data["sentiment_report"]}
                    )
                    yield json.dumps(
                        {"type": "log", "content": "AGENT: Social Analyst finished.", "stats": current_stats}
                    )

                if "fundamentals_report" in chunk_data and chunk_data["fundamentals_report"]:
                    yield json.dumps({"type": "status", "agent": "fundamentals", "status": "completed"})
                    yield json.dumps(
                        {
                            "type": "report",
                            "title": "Fundamental Analysis",
                            "content": chunk_data["fundamentals_report"],
                        }
                    )
                    yield json.dumps(
                        {"type": "log", "content": "AGENT: Fundamentals Analyst finished.", "stats": current_stats}
                    )

                if "investment_debate_state" in chunk_data:
                    debate = chunk_data["investment_debate_state"]
                    if debate.get("current_response", "").startswith("Bull"):
                        yield json.dumps({"type": "status", "agent": "bull", "status": "completed"})
                        yield json.dumps(
                            {"type": "log", "content": "RESEARCH: Bull argument presented.", "stats": current_stats}
                        )
                    elif debate.get("current_response", "").startswith("Bear"):
                        yield json.dumps({"type": "status", "agent": "bear", "status": "completed"})
                        yield json.dumps(
                            {"type": "log", "content": "RESEARCH: Bear argument presented.", "stats": current_stats}
                        )
                    if debate.get("judge_decision"):
                        yield json.dumps(
                            {"type": "report", "title": "Research Decision", "content": debate["judge_decision"]}
                        )
                        yield json.dumps(
                            {"type": "log", "content": "MANAGER: Research decision made.", "stats": current_stats}
                        )

                if "trader_investment_plan" in chunk_data and chunk_data["trader_investment_plan"]:
                    yield json.dumps({"type": "status", "agent": "trader", "status": "completed"})
                    yield json.dumps(
                        {"type": "report", "title": "Execution Plan", "content": chunk_data["trader_investment_plan"]}
                    )
                    yield json.dumps(
                        {"type": "log", "content": "EXECUTION: Trader plan generated.", "stats": current_stats}
                    )

                if "risk_debate_state" in chunk_data:
                    risk = chunk_data["risk_debate_state"]
                    if risk.get("judge_decision"):
                        yield json.dumps({"type": "status", "agent": "risk", "status": "completed"})
                        yield json.dumps(
                            {"type": "report", "title": "Final Portfolio Decision", "content": risk["judge_decision"]}
                        )
                        yield json.dumps(
                            {"type": "log", "content": "MANAGER: Risk final decision.", "stats": current_stats}
                        )

                final_state.update(chunk_data)

                await asyncio.sleep(0.01)

            # Generate dashboards for all completed agents
            yield json.dumps({"type": "log", "content": "DASHBOARD: Generating visualizations..."})

            completed_agents = []
            if final_state.get("news_report"):
                completed_agents.append("news")
            if final_state.get("market_report"):
                completed_agents.append("market")
            if final_state.get("sentiment_report"):
                completed_agents.append("social")
            if final_state.get("fundamentals_report"):
                completed_agents.append("fundamentals")
            debate = final_state.get("investment_debate_state") or {}
            if debate.get("bull_history"):
                completed_agents.append("bull")
            if debate.get("bear_history"):
                completed_agents.append("bear")
            if debate.get("judge_decision"):
                completed_agents.append("research")
            if final_state.get("trader_investment_plan"):
                completed_agents.append("trader")
            risk = final_state.get("risk_debate_state") or {}
            if risk.get("judge_decision"):
                completed_agents.append("risk")

            # Save final state to JSON so dashboard generator can read it
            # Save state JSON first
            # try:
            #     from pathlib import Path
            #     save_dir = Path(base_path) / config_data.ticker / "logs"
            #     save_dir.mkdir(parents=True, exist_ok=True)
            #     save_path = save_dir / f"full_states_log_{config_data.date}.json"
            #     with open(save_path, "w") as f:
            #         import json as json_lib
            #         json_lib.dump({config_data.date: final_state}, f, indent=4, default=str)
            #     yield json.dumps({"type": "log", "content": f"FILESYSTEM: State saved → {save_path}"})
            # except Exception as e:
            #     yield json.dumps({"type": "log", "content": f"WARNING: State save failed: {e}"})

            # yield json.dumps({"type": "log", "content": f"DASHBOARD: Generating for agents: {completed_agents}"})

            # # Generate dashboard for each completed agent
            # for agent_name in completed_agents:
            #     yield json.dumps({"type": "log", "content": f"DASHBOARD: Generating {agent_name}..."})
            #     dash = await run_dashboard(
            #         agent_name,
            #         config_data.ticker,
            #         config_data.date,
            #         base_path,
            #         graph_config
            #     )
            #     if dash:
            #         yield json.dumps({
            #             "type": "dashboard",
            #             "title": f"{agent_name.capitalize()} Dashboard",
            #             "data": dash
            #         })
            #         yield json.dumps({"type": "log", "content": f"DASHBOARD: {agent_name} done."})
            #     else:
            #         yield json.dumps({"type": "log", "content": f"DASHBOARD: ✗ {agent_name} failed."})

            # yield json.dumps({"type": "log", "content": "SYSTEM: Analysis Complete."})
            # yield json.dumps({"type": "complete"})

        except Exception as e:
            print(traceback.format_exc())
            yield json.dumps({"type": "log", "content": f"ERROR: {str(e)}"})
            yield json.dumps({"type": "complete"})

    return EventSourceResponse(event_generator())


@app.post("/api/chat")
async def chat_with_report(req: ChatRequest):
    from tradingagents.llm_clients.factory import create_llm_client

    try:
        base_url = "http://127.0.0.1:1234/v1" if req.provider == "lmstudio" else None
        client = create_llm_client(req.provider, "default", base_url=base_url)
        llm = client.get_llm()
        prompt = [
            ("system", "Answer based ONLY on the context."),
            ("human", f"CONTEXT:\n{req.context}\n\nQUESTION: {req.question}"),
        ]
        response = llm.invoke(prompt)
        return {"answer": response.content}
    except Exception as e:
        return {"answer": f"Error: {str(e)}"}


@app.post("/api/generate_dashboard")
async def generate_dashboard(req: DashboardRequest):
    """Generate input/output/relationship dashboards for a given agent."""
    try:
        from dynamic_dashboards.dashboard_generator import generate_dashboards
        import base64

        paths = generate_dashboards(agent=req.agent, ticker=req.ticker, date=req.date, results_dir=req.results_dir)

        # Read each PNG and return as base64 so the UI can display inline
        result = {}
        for dashboard_type, path in paths.items():
            with open(path, "rb") as f:
                result[dashboard_type] = base64.b64encode(f.read()).decode("utf-8")

        return {"status": "ok", "dashboards": result}

    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        import traceback

        print(traceback.format_exc())
        return {"status": "error", "message": str(e)}


@app.get("/api/list_reports")
async def list_reports(results_dir: str = "./results"):
    """List all result files available in the results directory."""
    try:
        from pathlib import Path

        base = Path(results_dir)
        files = []
        if base.exists():
            for f in base.rglob("*.json"):
                files.append(str(f.relative_to(base)))
            for f in base.rglob("*.txt"):
                files.append(str(f.relative_to(base)))
        return {"files": sorted(files)}
    except Exception as e:
        return {"files": [], "error": str(e)}


if __name__ == "__main__":
    import uvicorn

    print("Starting TradingAgents Server...")
    # Force exit on Ctrl+C by using the lifespan manager
    uvicorn.run(app, host="0.0.0.0", port=8000)
