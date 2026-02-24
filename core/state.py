from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from typing_extensions import TypedDict


class TradingDecision(BaseModel):
    """Structured output schema for the brain node LLM call."""

    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float  # 0.0 – 1.0
    target_price: float
    stop_loss: float
    take_profit: float
    quantity: float  # shares / contracts to trade
    strategy_name: str
    reasoning: str


class AgentState(TypedDict):
    # --- Identity ---
    symbol: str
    broker: Literal["alpaca", "projectx"]
    account_id: int | None  # required for projectx, None for alpaca

    # --- market_reader output ---
    market_data: list[dict]   # raw OHLCV bars [{t, o, h, l, c, v}]
    signals: dict             # {sma_20, sma_50, ema_12, ema_26, rsi_14,
                              #  macd_line, macd_signal, macd_histogram,
                              #  bb_upper, bb_middle, bb_lower,
                              #  current_price, spread, volume_24h}
    portfolio: dict           # {cash, equity, buying_power, daily_pnl,
                              #  daily_pnl_pct, drawdown_pct, positions}

    # --- brain output ---
    decision: dict | None  # TradingDecision.model_dump() or None

    # --- guardrail output ---
    is_risk_passed: bool
    risk_reason: str

    # --- execution output ---
    order_result: dict | None

    # --- LLM conversation history (appended, never replaced) ---
    messages: Annotated[list[AnyMessage], add_messages]

    # --- Error state ---
    error: str | None
