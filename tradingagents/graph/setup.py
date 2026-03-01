# TradingAgents/graph/setup.py

from typing import Dict, Any, List, Optional
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.agent_utils import create_msg_delete

from .conditional_logic import ConditionalLogic


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: ChatOpenAI,
        deep_thinking_llm: ChatOpenAI,
        tool_nodes: Dict[str, ToolNode],
        bull_memory,
        bear_memory,
        trader_memory,
        invest_judge_memory,
        risk_manager_memory,
        conditional_logic: ConditionalLogic,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.bull_memory = bull_memory
        self.bear_memory = bear_memory
        self.trader_memory = trader_memory
        self.invest_judge_memory = invest_judge_memory
        self.risk_manager_memory = risk_manager_memory
        self.conditional_logic = conditional_logic

    def setup_graph(
        self,
        selected_analysts=["market", "social", "news", "fundamentals"],
        selected_agents=None,
    ):
        """Set up and compile the agent workflow graph.
        
        Args:
            selected_analysts: List of analyst types to include (market, social, news, fundamentals)
            selected_agents: List of downstream agents to include (bull, bear, trader, risk).
                             If None, all downstream agents are enabled.
        """

        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        # --- AGENT FILTERING ---
        # Default: all agents enabled if nothing specified
        if selected_agents is None:
            enable_bull = True
            enable_bear = True
            enable_trader = True
            enable_risk = True
        else:
            enable_bull = "bull" in selected_agents
            enable_bear = "bear" in selected_agents
            enable_trader = "trader" in selected_agents
            enable_risk = "risk" in selected_agents

        # Validate at least one downstream agent is enabled
        if not any([enable_bull, enable_bear, enable_trader, enable_risk]):
            raise ValueError(
                "Trading Agents Graph Setup Error: at least one downstream agent (bull, bear, trader, risk) must be selected!"
            )

        # --- ANALYST NODES ---
        analyst_nodes = {}
        delete_nodes = {}
        tool_nodes = {}

        if "market" in selected_analysts:
            analyst_nodes["market"] = create_market_analyst(self.quick_thinking_llm)
            delete_nodes["market"] = create_msg_delete()
            tool_nodes["market"] = self.tool_nodes["market"]

        if "social" in selected_analysts:
            analyst_nodes["social"] = create_social_media_analyst(self.quick_thinking_llm)
            delete_nodes["social"] = create_msg_delete()
            tool_nodes["social"] = self.tool_nodes["social"]

        if "news" in selected_analysts:
            analyst_nodes["news"] = create_news_analyst(self.quick_thinking_llm)
            delete_nodes["news"] = create_msg_delete()
            tool_nodes["news"] = self.tool_nodes["news"]

        if "fundamentals" in selected_analysts:
            analyst_nodes["fundamentals"] = create_fundamentals_analyst(self.quick_thinking_llm)
            delete_nodes["fundamentals"] = create_msg_delete()
            tool_nodes["fundamentals"] = self.tool_nodes["fundamentals"]

        # --- DOWNSTREAM AGENT NODES (conditional) ---
        if enable_bull:
            bull_researcher_node = create_bull_researcher(
                self.quick_thinking_llm, self.bull_memory
            )
        if enable_bear:
            bear_researcher_node = create_bear_researcher(
                self.quick_thinking_llm, self.bear_memory
            )
        if enable_bull or enable_bear:
            research_manager_node = create_research_manager(
                self.deep_thinking_llm, self.invest_judge_memory
            )
        if enable_trader:
            trader_node = create_trader(self.quick_thinking_llm, self.trader_memory)
        if enable_risk:
            aggressive_analyst = create_aggressive_debator(self.quick_thinking_llm)
            neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
            conservative_analyst = create_conservative_debator(self.quick_thinking_llm)
            risk_manager_node = create_risk_manager(
                self.deep_thinking_llm, self.risk_manager_memory
            )

        # --- BUILD WORKFLOW ---
        workflow = StateGraph(AgentState)

        # Add analyst nodes
        for analyst_type, node in analyst_nodes.items():
            workflow.add_node(f"{analyst_type.capitalize()} Analyst", node)
            workflow.add_node(
                f"Msg Clear {analyst_type.capitalize()}", delete_nodes[analyst_type]
            )
            workflow.add_node(f"tools_{analyst_type}", tool_nodes[analyst_type])

        # Add downstream agent nodes conditionally
        if enable_bull:
            workflow.add_node("Bull Researcher", bull_researcher_node)
        if enable_bear:
            workflow.add_node("Bear Researcher", bear_researcher_node)
        if enable_bull or enable_bear:
            workflow.add_node("Research Manager", research_manager_node)
        if enable_trader:
            workflow.add_node("Trader", trader_node)
        if enable_risk:
            workflow.add_node("Aggressive Analyst", aggressive_analyst)
            workflow.add_node("Neutral Analyst", neutral_analyst)
            workflow.add_node("Conservative Analyst", conservative_analyst)
            workflow.add_node("Risk Judge", risk_manager_node)

        # --- ANALYST EDGES ---
        # Start → first analyst
        first_analyst = selected_analysts[0]
        workflow.add_edge(START, f"{first_analyst.capitalize()} Analyst")

        # Connect analysts in sequence
        for i, analyst_type in enumerate(selected_analysts):
            current_analyst = f"{analyst_type.capitalize()} Analyst"
            current_tools = f"tools_{analyst_type}"
            current_clear = f"Msg Clear {analyst_type.capitalize()}"

            workflow.add_conditional_edges(
                current_analyst,
                getattr(self.conditional_logic, f"should_continue_{analyst_type}"),
                [current_tools, current_clear],
            )
            workflow.add_edge(current_tools, current_analyst)

            if i < len(selected_analysts) - 1:
                # Connect to next analyst
                next_analyst = f"{selected_analysts[i + 1].capitalize()} Analyst"
                workflow.add_edge(current_clear, next_analyst)
            else:
                # Last analyst → connect to first available downstream agent
                if enable_bull:
                    workflow.add_edge(current_clear, "Bull Researcher")
                elif enable_bear:
                    workflow.add_edge(current_clear, "Bear Researcher")
                elif enable_trader:
                    workflow.add_edge(current_clear, "Trader")
                elif enable_risk:
                    workflow.add_edge(current_clear, "Aggressive Analyst")
                else:
                    workflow.add_edge(current_clear, END)

        # --- DOWNSTREAM AGENT EDGES ---

        # Bull / Bear debate
        if enable_bull and enable_bear:
            # Both enabled — full debate loop
            workflow.add_conditional_edges(
                "Bull Researcher",
                self.conditional_logic.should_continue_debate,
                {
                    "Bear Researcher": "Bear Researcher",
                    "Research Manager": "Research Manager",
                },
            )
            workflow.add_conditional_edges(
                "Bear Researcher",
                self.conditional_logic.should_continue_debate,
                {
                    "Bull Researcher": "Bull Researcher",
                    "Research Manager": "Research Manager",
                },
            )
        elif enable_bull:
            # Only Bull — skip debate, go straight to Research Manager or next
            if enable_trader:
                workflow.add_edge("Bull Researcher", "Research Manager")
            elif enable_risk:
                workflow.add_edge("Bull Researcher", "Research Manager")
            else:
                workflow.add_edge("Bull Researcher", END)
        elif enable_bear:
            # Only Bear — skip debate, go straight to Research Manager or next
            if enable_trader:
                workflow.add_edge("Bear Researcher", "Research Manager")
            elif enable_risk:
                workflow.add_edge("Bear Researcher", "Research Manager")
            else:
                workflow.add_edge("Bear Researcher", END)

        # Research Manager → next stage
        if enable_bull or enable_bear:
            if enable_trader:
                workflow.add_edge("Research Manager", "Trader")
            elif enable_risk:
                workflow.add_edge("Research Manager", "Aggressive Analyst")
            else:
                workflow.add_edge("Research Manager", END)

        # Trader → next stage
        if enable_trader:
            if enable_risk:
                workflow.add_edge("Trader", "Aggressive Analyst")
            else:
                workflow.add_edge("Trader", END)

        # Risk debate loop
        if enable_risk:
            workflow.add_conditional_edges(
                "Aggressive Analyst",
                self.conditional_logic.should_continue_risk_analysis,
                {
                    "Conservative Analyst": "Conservative Analyst",
                    "Risk Judge": "Risk Judge",
                },
            )
            workflow.add_conditional_edges(
                "Conservative Analyst",
                self.conditional_logic.should_continue_risk_analysis,
                {
                    "Neutral Analyst": "Neutral Analyst",
                    "Risk Judge": "Risk Judge",
                },
            )
            workflow.add_conditional_edges(
                "Neutral Analyst",
                self.conditional_logic.should_continue_risk_analysis,
                {
                    "Aggressive Analyst": "Aggressive Analyst",
                    "Risk Judge": "Risk Judge",
                },
            )
            workflow.add_edge("Risk Judge", END)

        return workflow.compile()