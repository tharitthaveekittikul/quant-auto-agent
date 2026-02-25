"""
brain node — calls the LLM with structured output to produce a TradingDecision.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from core.constants import BRAIN_MODEL_ENV, DEFAULT_BRAIN_MODEL
from core.state import TradingDecision
from utils.llm import get_llm

# Context injected into the prompt so the LLM knows units and instrument type
_SYMBOL_CONTEXT: dict[str, str] = {
    "XAUUSD": (
        "Gold (XAU/USD) futures — priced in USD per troy ounce (see current_price in signals). "
        "Quantity = troy ounces. "
        "Example: at $5000/oz, buying 1 oz costs $5000; 0.1 oz costs $500. "
        "Scale quantity so position value stays within 10% of equity."
    ),
    "XAGUSD": (
        "Silver (XAG) priced in USD per troy ounce. "
        "Quantity = troy ounces."
    ),
    "AUDUSD": (
        "Australian Dollar / US Dollar forex pair. "
        "Quantity = AUD units (not full lots). Use small quantities e.g. 100–1000 AUD."
    ),
    "EURUSD": (
        "Euro / US Dollar forex pair. "
        "Quantity = EUR units. Use small quantities e.g. 100–1000 EUR."
    ),
    "GBPJPY": (
        "British Pound / Japanese Yen forex pair. "
        "Quantity = GBP units. Use small quantities e.g. 100–1000 GBP."
    ),
}

_SYSTEM_PROMPT = """You are an expert quantitative trading AI with a risk-first philosophy.
Your role is to analyze technical signals and portfolio state to produce precise trading decisions.

## Decision Guidelines

**BUY** when:
- RSI < 40 (oversold) AND price above SMA_20 (uptrend)
- MACD line crosses above signal line with positive histogram
- Price near or below Bollinger lower band with bullish momentum
- Confidence must reflect signal alignment strength

**SELL** when:
- RSI > 65 (overbought) AND price below SMA_20 (downtrend)
- MACD line crosses below signal line
- Price near or above Bollinger upper band with bearish momentum
- Active long position exists that should be closed

**HOLD** when:
- Signals are mixed or unclear
- Confidence would be below 0.65
- Near daily loss limits or in high-drawdown state

## Confidence Calibration
- 0.90–1.00: All signals strongly aligned, high conviction
- 0.75–0.89: Most signals aligned, moderate conviction
- 0.65–0.74: Marginally aligned, minimum actionable threshold
- < 0.65: Insufficient signal — output HOLD

## Risk Rules
- target_price, stop_loss, take_profit must be realistic relative to current_price
- quantity should be proportional to conviction and portfolio size
- Always provide clear, concise reasoning
"""


async def brain(state: dict) -> dict:
    """LangGraph node: calls LLM for a structured TradingDecision."""
    symbol: str = state["symbol"]
    signals: dict = state.get("signals", {})
    portfolio: dict = state.get("portfolio", {})
    messages: list = state.get("messages", [])

    if not signals:
        logger.warning("[brain] No signals available, returning HOLD")
        decision = TradingDecision(
            action="HOLD",
            confidence=0.0,
            target_price=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            quantity=0.0,
            strategy_name="no_data",
            reasoning="No market data available.",
        )
        return {"decision": decision.model_dump(), "messages": []}

    # Build human prompt
    signals_str = json.dumps(
        {k: round(v, 4) if isinstance(v, float) else v for k, v in signals.items()},
        indent=2,
    )
    portfolio_summary = (
        f"equity=${portfolio.get('equity', 0):.2f}, "
        f"cash=${portfolio.get('cash', 0):.2f}, "
        f"buying_power=${portfolio.get('buying_power', 0):.2f}, "
        f"daily_pnl={portfolio.get('daily_pnl_pct', 0)*100:.2f}%, "
        f"drawdown={portfolio.get('drawdown_pct', 0)*100:.2f}%, "
        f"positions={len(portfolio.get('positions', []))}"
    )

    recent_msgs = []
    for m in messages[-5:]:
        if hasattr(m, "content"):
            role = type(m).__name__.replace("Message", "").lower()
            recent_msgs.append(f"{role}: {m.content}")

    instrument_ctx = _SYMBOL_CONTEXT.get(symbol.upper(), f"Symbol: {symbol}")

    human_content = f"""Instrument: {symbol}
Instrument context: {instrument_ctx}

Technical Signals:
{signals_str}

Portfolio: {portfolio_summary}

{"Recent context:" + chr(10) + chr(10).join(recent_msgs) if recent_msgs else ""}

Based on the signals above, provide a trading decision for {symbol}. Pay attention to the instrument context when choosing quantity."""

    llm = get_llm(BRAIN_MODEL_ENV, DEFAULT_BRAIN_MODEL)
    structured_llm = llm.with_structured_output(TradingDecision, method="json_schema")

    prompt_messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]

    try:
        decision: TradingDecision = await structured_llm.ainvoke(prompt_messages)
        logger.info(
            f"[brain] Decision: {decision.action} | confidence={decision.confidence:.2f} | "
            f"strategy={decision.strategy_name}"
        )
    except Exception as exc:
        logger.error(f"[brain] LLM call failed: {exc}")
        decision = TradingDecision(
            action="HOLD",
            confidence=0.0,
            target_price=signals.get("current_price", 0.0),
            stop_loss=0.0,
            take_profit=0.0,
            quantity=0.0,
            strategy_name="error",
            reasoning=f"LLM error: {exc}",
        )

    from langchain_core.messages import AIMessage

    ai_msg = AIMessage(
        content=f"Decision: {decision.action} | confidence={decision.confidence:.2f} | {decision.reasoning}"
    )
    return {"decision": decision.model_dump(), "messages": [ai_msg]}
