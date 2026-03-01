"""
TradingAgents Dynamic Dashboard Generator
Uses LM Studio LLM to dynamically generate matplotlib dashboard code
based on actual agent input/output data.
"""

import os
import sys
import json
import textwrap
import traceback
import tempfile
import subprocess
from pathlib import Path

# Output directory for generated PNGs
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# LM Studio connection (uses same config as server.py)
LM_STUDIO_URL = "http://127.0.0.1:1234/v1"


def _get_llm_client(config: dict):
    """Get LLM client using same config as server."""
    from tradingagents.llm_clients.factory import create_llm_client
    provider = config.get("llm_provider", "lmstudio")
    model = config.get("quick_think_llm", "")
    base_url = config.get("backend_url", LM_STUDIO_URL)
    if provider == "lmstudio":
        base_url = LM_STUDIO_URL
    client = create_llm_client(provider, model, base_url=base_url)
    return client.get_llm()


def extract_agent_data(state: dict, agent: str) -> tuple:
    """Extract (input_data, output_data) for a given agent from state."""
    ticker = state.get("company_of_interest") or state.get("ticker", "N/A")
    trade_date = state.get("trade_date", "N/A")
    inp, out = {}, {}

    if agent == "market":
        report = state.get("market_report") or ""
        inp = {"ticker": ticker, "trade_date": trade_date,
               "data_requested": "OHLCV + Technical Indicators"}
        out = {"report_length_chars": len(report),
               "report_preview": report[:600]}

    elif agent == "news":
        report = state.get("news_report") or ""
        inp = {"ticker": ticker, "trade_date": trade_date,
               "data_requested": "News Articles + Insider Transactions"}
        out = {"report_length_chars": len(report),
               "report_preview": report[:600]}

    elif agent == "social":
        report = state.get("sentiment_report") or ""
        inp = {"ticker": ticker, "trade_date": trade_date,
               "data_requested": "Social Media + Sentiment Signals"}
        out = {"report_length_chars": len(report),
               "report_preview": report[:600]}

    elif agent == "fundamentals":
        report = state.get("fundamentals_report") or ""
        inp = {"ticker": ticker, "trade_date": trade_date,
               "data_requested": "Balance Sheet + Income + Cashflow"}
        out = {"report_length_chars": len(report),
               "report_preview": report[:600]}

    elif agent in ("bull", "bear"):
        debate = state.get("investment_debate_state") or {}
        history_key = "bull_history" if agent == "bull" else "bear_history"
        history = debate.get(history_key) or []
        total_report_chars = sum([
            len(state.get("market_report") or ""),
            len(state.get("news_report") or ""),
            len(state.get("sentiment_report") or ""),
            len(state.get("fundamentals_report") or ""),
        ])
        inp = {"ticker": ticker,
               "total_analyst_report_chars": total_report_chars,
               "debate_rounds": len(history),
               "last_argument_length": len(history[-1]) if history else 0}
        out = {"current_stance_preview": (debate.get("current_response") or "")[:300],
               "total_argument_chars": sum(len(h) for h in history),
               "rounds_participated": len(history)}

    elif agent == "research":
        debate = state.get("investment_debate_state") or {}
        bull_hist = debate.get("bull_history") or []
        bear_hist = debate.get("bear_history") or []
        inp = {"ticker": ticker,
               "bull_rounds": len(bull_hist),
               "bear_rounds": len(bear_hist),
               "total_debate_chars": sum(len(h) for h in bull_hist + bear_hist)}
        decision = debate.get("judge_decision") or ""
        out = {"judge_decision_chars": len(decision),
               "decision_preview": decision[:400]}

    elif agent == "trader":
        debate = state.get("investment_debate_state") or {}
        plan = state.get("trader_investment_plan") or \
               state.get("trader_investment_decision") or ""
        inp = {"ticker": ticker,
               "research_decision_chars": len(debate.get("judge_decision") or ""),
               "investment_plan_chars": len(state.get("investment_plan") or "")}
        out = {"trader_plan_chars": len(plan),
               "plan_preview": plan[:400],
               "final_decision_chars": len(state.get("final_trade_decision") or "")}

    elif agent == "risk":
        risk = state.get("risk_debate_state") or {}
        agg = risk.get("aggressive_history") or []
        con = risk.get("conservative_history") or []
        neu = risk.get("neutral_history") or []
        trader_plan = state.get("trader_investment_plan") or \
                      state.get("trader_investment_decision") or ""
        inp = {"ticker": ticker,
               "trader_plan_chars": len(trader_plan),
               "aggressive_rounds": len(agg),
               "conservative_rounds": len(con),
               "neutral_rounds": len(neu)}
        decision = risk.get("judge_decision") or ""
        out = {"risk_decision_chars": len(decision),
               "final_trade_decision": (state.get("final_trade_decision") or "")[:400],
               "total_risk_debate_chars": sum(len(h) for h in agg + con + neu)}

    return inp, out


def _ask_llm_for_dashboard_code(llm, dashboard_type: str, agent: str,
                                  ticker: str, date: str,
                                  data: dict, output_path: str) -> str:
    numeric = {k: v for k, v in data.items() if isinstance(v, (int, float))}
    text_fields = {k: str(v)[:120] for k, v in data.items() if isinstance(v, str)}

    prompt = f"""Write Python matplotlib code to create a dashboard image. 

CRITICAL RULES - violations will cause errors:
1. Figure size: fig, axes = plt.subplots(nrows=2, ncols=1, figsize=(8, 4), facecolor='#09090b')
   OR: fig = plt.figure(figsize=(8, 4), facecolor='#09090b')
   NEVER use any other figsize.
2. Save with: plt.savefig(OUTPUT_PATH, dpi=72, bbox_inches='tight', facecolor='#09090b')
   The variable OUTPUT_PATH is already defined for you - do NOT hardcode any file path.
3. plt.close(fig) after saving. Never plt.show().
4. No emoji or unicode - ASCII only in all strings.
5. Axes facecolor: '#18181b'. Text color: '#e4e4e7'. Title color: '#00e599'.
6. When iterating over dict items use: for i, (k, v) in enumerate(mydict.items())
   Never use the key as a number index.
7. All division must be safe: use max(denominator, 1) to avoid ZeroDivisionError.
8. Do not import anything - matplotlib and numpy are already imported as plt and np.
9. Only write executable code - no comments, no explanations, no markdown.

DASHBOARD: {dashboard_type.upper()} | Agent: {agent.upper()} | {ticker} | {date}

NUMERIC DATA (plot as bar chart in top subplot):
{json.dumps(numeric)}

TEXT DATA (show as text in bottom subplot):
{json.dumps(text_fields)}

LAYOUT:
- Top subplot (ax1): bar chart of numeric data. 
  Use: labels=[k[:12] for k in numeric.keys()], values=list(numeric.values())
  Color '#3b82f6' for input dashboards, '#00e599' for output, '#a855f7' for relationship.
  Add value labels above bars. Rotate x labels 30 degrees.
  If no numeric data, write: ax1.text(0.5, 0.5, 'No numeric data', transform=ax1.transAxes, ha='center', color='#a1a1aa')
  ax1.axis('off') only if no numeric data.
- Bottom subplot (ax2): text panel.
  ax2.set_facecolor('#18181b')
  ax2.axis('off')
  Write a 2-sentence interpretation of what this {dashboard_type} data means for the {agent} agent.
  Then list up to 3 key data points.
  Use ax2.text() with transform=ax2.transAxes, fontsize=8, color='#e4e4e7', va='top', wrap=True
- Add overall title: fig.suptitle('{dashboard_type.upper()} | {agent.upper()} | {ticker}', color='#00e599', fontsize=10, fontweight='bold')
- plt.tight_layout()

Write ONLY the Python code starting with fig, axes = ... or fig = ..."""

    response = llm.invoke([("user", prompt)])
    code = response.content.strip()
    # Strip markdown if present
    if "```" in code:
        lines = code.split("\n")
        code_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```"):
                in_block = not in_block
                continue
            if in_block or not line.strip().startswith("```"):
                code_lines.append(line)
        code = "\n".join(code_lines)
    return code


def _execute_code_safely(code: str, agent: str, dashboard_type: str,
                          output_path: str) -> bool:
    """Execute LLM-generated code safely, injecting OUTPUT_PATH as a variable."""
    # Inject imports and OUTPUT_PATH at the top — LLM never sees the path string
    preamble = (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "import numpy as np\n"
        f"OUTPUT_PATH = r'{output_path}'\n"  # raw string handles Windows backslashes
    )
    full_code = preamble + "\n" + code

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py',
                                      delete=False, encoding='utf-8') as f:
        f.write(full_code)
        temp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, temp_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"  Dashboard code error [{agent}/{dashboard_type}]:\n{result.stderr[-600:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"  Dashboard timed out [{agent}/{dashboard_type}]")
        return False
    except Exception as e:
        print(f"  Dashboard execution error: {e}")
        return False
    finally:
        try:
            os.unlink(temp_path)
        except:
            pass


def _get_dashboard_purpose(dashboard_type: str, agent: str,
                             numeric: dict, text: dict, ticker: str) -> str:
    purposes = {
        ("input", "news"):         f"Show what data the News Analyst received for {ticker}: ticker, date, and what data sources were requested",
        ("input", "market"):       f"Show what market data inputs the Market Analyst received for {ticker}",
        ("input", "social"):       f"Show social/sentiment data inputs received for {ticker}",
        ("input", "fundamentals"): f"Show fundamental financial data inputs received for {ticker}",
        ("input", "bull"):         f"Show the research inputs the Bull Researcher received: analyst report sizes and debate round counts",
        ("input", "bear"):         f"Show the research inputs the Bear Researcher received: analyst report sizes and debate round counts",
        ("input", "research"):     f"Show the debate inputs the Research Manager evaluated: bull vs bear round counts and total debate size",
        ("input", "trader"):       f"Show what the Trader received: research decision size and investment plan size",
        ("input", "risk"):         f"Show risk debate inputs: trader plan size and rounds per analyst (aggressive/conservative/neutral)",
        ("output", "news"):        f"Show the News Analysis output for {ticker}: report size and preview of findings",
        ("output", "market"):      f"Show Market Analysis output for {ticker}: report size and preview",
        ("output", "social"):      f"Show Social Sentiment output for {ticker}: report size and sentiment preview",
        ("output", "fundamentals"): f"Show Fundamentals output for {ticker}: report size and financial findings preview",
        ("output", "bull"):        f"Show Bull Researcher output: argument size, rounds participated, current bullish stance",
        ("output", "bear"):        f"Show Bear Researcher output: argument size, rounds participated, current bearish stance",
        ("output", "research"):    f"Show Research Manager decision output: decision size and ruling preview",
        ("output", "trader"):      f"Show Trader output: execution plan size and final decision preview",
        ("output", "risk"):        f"Show Risk Manager output: final decision size, total debate size, and decision preview",
        ("relationship", "news"):  f"Show how news volume and complexity relates to report output size for {ticker}",
        ("relationship", "bull"):  f"Show relationship between debate rounds and argument quality for Bull Researcher",
        ("relationship", "bear"):  f"Show relationship between debate rounds and argument quality for Bear Researcher",
        ("relationship", "risk"):  f"Show balance between aggressive/conservative/neutral risk views and final decision",
    }
    key = (dashboard_type, agent)
    return purposes.get(key,
        f"Visualize the {dashboard_type} data for the {agent} agent analyzing {ticker}")


def _get_layout_hint(dashboard_type: str, numeric: dict, text: dict) -> str:
    n_numeric = len(numeric)
    n_text = len(text)
    if dashboard_type == "input":
        if n_numeric > 0 and n_text > 0:
            return "top subplot for numeric bar chart, bottom subplot for text info panel"
        elif n_numeric > 0:
            return "single bar chart showing all numeric values"
        else:
            return "text panel showing all input fields"
    elif dashboard_type == "output":
        if n_numeric > 0 and n_text > 0:
            return "left side bar chart for numeric metrics, right side text panel for report preview"
        elif n_numeric > 0:
            return "bar chart or gauge for numeric output"
        else:
            return "text panel with output preview"
    else:  # relationship
        return "top: 2-3 sentence narrative text, middle: comparison chart, bottom: key insight"


def _execute_code_safely(code: str, agent: str, dashboard_type: str,
                          output_path: str) -> bool:
    """Execute LLM-generated code safely, injecting OUTPUT_PATH as a variable."""
    # Inject imports and OUTPUT_PATH at the top — LLM never sees the path string
    preamble = (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "import numpy as np\n"
        f"OUTPUT_PATH = r'{output_path}'\n"  # raw string handles Windows backslashes
    )
    full_code = preamble + "\n" + code

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py',
                                      delete=False, encoding='utf-8') as f:
        f.write(full_code)
        temp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, temp_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"  Dashboard code error [{agent}/{dashboard_type}]:\n{result.stderr[-600:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"  Dashboard timed out [{agent}/{dashboard_type}]")
        return False
    except Exception as e:
        print(f"  Dashboard execution error: {e}")
        return False
    finally:
        try:
            os.unlink(temp_path)
        except:
            pass

def _fallback_dashboard(dashboard_type: str, agent: str, ticker: str,
                         date: str, data: dict, output_path: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    numeric = {k: v for k, v in data.items() if isinstance(v, (int, float))}
    text_fields = {k: str(v)[:150] for k, v in data.items() if isinstance(v, str)}

    color_map = {"input": "#3b82f6", "output": "#00e599", "relationship": "#a855f7"}
    bar_color = color_map.get(dashboard_type, "#3b82f6")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 4), facecolor="#09090b")
    fig.suptitle(f"{dashboard_type.upper()} | {agent.upper()} | {ticker}",
                 color="#00e599", fontsize=10, fontweight="bold")

    ax1.set_facecolor("#18181b")
    if numeric:
        labels = [k[:12] for k in numeric.keys()]
        values = list(numeric.values())
        bars = ax1.bar(labels, values, color=bar_color, edgecolor="#3f3f46")
        for bar, val in zip(bars, values):
            ax1.text(bar.get_x() + bar.get_width()/2,
                     bar.get_height() + max(values)*0.01,
                     f"{val:,.0f}", ha="center", va="bottom",
                     fontsize=7, color="#a1a1aa")
        ax1.set_facecolor("#18181b")
        ax1.tick_params(colors="#a1a1aa", labelsize=7)
        ax1.spines[:].set_color("#3f3f46")
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=30, ha="right")
    else:
        ax1.text(0.5, 0.5, "No numeric data", transform=ax1.transAxes,
                 ha="center", color="#a1a1aa", fontsize=9)
        ax1.axis("off")

    ax2.set_facecolor("#18181b")
    ax2.axis("off")
    lines = [f"{k}: {v}" for k, v in list(text_fields.items())[:4]]
    body = "\n".join(lines) if lines else "No text data."
    ax2.text(0.02, 0.95, body, transform=ax2.transAxes,
             fontsize=7, color="#e4e4e7", va="top",
             fontfamily="monospace", linespacing=1.7)

    plt.tight_layout()
    plt.savefig(output_path, dpi=72, bbox_inches="tight", facecolor="#09090b")
    plt.close(fig)

def generate_dashboards(agent: str, ticker: str, date: str,
                         results_dir: str = "./results",
                         config: dict = None) -> dict:
    """
    Generate all 3 dashboards for a given agent using LLM-generated code.
    Returns dict of {dashboard_type: file_path}.
    """
    print(f"\n{'='*60}")
    print(f"  TradingAgents Dashboard Generator")
    print(f"  Agent: {agent.upper()} | Ticker: {ticker} | Date: {date}")
    print(f"{'='*60}")

    # Load state
    state = _load_state(results_dir, ticker, date)
    inp, out = extract_agent_data(state, agent)

    print(f"  Input fields:  {list(inp.keys())}")
    print(f"  Output fields: {list(out.keys())}")

    # Get LLM
    llm = None
    if config:
        try:
            llm = _get_llm_client(config)
            print(f"  LLM: Connected to {config.get('llm_provider')} / {config.get('quick_think_llm')}")
        except Exception as e:
            print(f"  LLM: Could not connect ({e}), using fallback")

    paths = {}
    datasets = {
        "input": inp,
        "output": out,
        "relationship": {**inp, **{f"out_{k}": v for k, v in out.items()}}
    }

    for dashboard_type, data in datasets.items():
        output_path = str(OUTPUT_DIR / f"{ticker}_{agent}_{dashboard_type}_{date}.png")
        success = False

       
        if llm:
            try:
                print(f"  Generating {dashboard_type} dashboard via LLM...")
                code = _ask_llm_for_dashboard_code(
                    llm, dashboard_type, agent, ticker, date, data, output_path
                )
                success = _execute_code_safely(code, agent, dashboard_type, output_path)  # add output_path
                if success:
                    print(f"  LLM dashboard saved -> {output_path}")
            except Exception as e:
                print(f"  LLM generation failed: {e}")
                success = False

        if not success:
            print(f"  Using fallback for {dashboard_type}...")
            _fallback_dashboard(dashboard_type, agent, ticker, date, data, output_path)

        paths[dashboard_type] = Path(output_path)

    print(f"\n  All dashboards saved to: {OUTPUT_DIR.resolve()}\n")
    return paths


def _load_state(results_dir: str, ticker: str, date: str) -> dict:
    """Load state JSON."""
    path = Path(results_dir) / ticker / "logs" / f"full_states_log_{date}.json"
    if not path.exists():
        path = Path("eval_results") / ticker / \
               "TradingAgentsStrategy_logs" / f"full_states_log_{date}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"State file not found.\nTried: {path}"
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return list(data.values())[0] if data else {}