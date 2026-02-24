"""
LangGraph state machine definition for the trading agent.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any, Literal

from langgraph.graph import END, START, StateGraph

from agents.nodes.brain import brain
from agents.nodes.execution import execution
from agents.nodes.guardrail import guardrail
from agents.nodes.market_reader import market_reader
from core.state import AgentState

if TYPE_CHECKING:
    import asyncpg
    from langgraph.checkpoint.base import BaseCheckpointSaver


def route_after_guardrail(state: AgentState) -> Literal["execution", "__end__"]:
    """Route to execution if risk passed and action is BUY/SELL, else END."""
    if not state.get("is_risk_passed"):
        return END
    decision = state.get("decision") or {}
    if decision.get("action") in ("BUY", "SELL"):
        return "execution"
    return END


def create_graph(
    checkpointer: "BaseCheckpointSaver",
    db_pool: "asyncpg.Pool",
    broker_client: Any,
):
    """
    Factory that builds and compiles the trading agent graph.

    Nodes receive db_pool and broker_client via functools.partial closures
    so LangGraph's node signature (state -> update) is preserved.
    """
    builder = StateGraph(AgentState)

    # Bind dependencies into async node functions
    market_reader_node = partial(market_reader, db_pool=db_pool, broker_client=broker_client)
    execution_node = partial(execution, broker_client=broker_client)

    builder.add_node("market_reader", market_reader_node)
    builder.add_node("brain", brain)
    builder.add_node("guardrail", guardrail)
    builder.add_node("execution", execution_node)

    # Edges
    builder.add_edge(START, "market_reader")
    builder.add_edge("market_reader", "brain")
    builder.add_edge("brain", "guardrail")
    builder.add_conditional_edges(
        "guardrail",
        route_after_guardrail,
        {"execution": "execution", END: END},
    )
    builder.add_edge("execution", END)

    return builder.compile(checkpointer=checkpointer)
