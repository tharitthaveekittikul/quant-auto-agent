"""
execution node — places broker orders and logs to SQLite.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from loguru import logger

from shared.database import log_trade_to_db


async def execution(state: dict, *, broker_client: Any) -> dict:
    """
    LangGraph node: executes the approved trading decision via the broker.
    Only called when is_risk_passed=True and action in {BUY, SELL}.
    """
    decision: dict = state["decision"]
    symbol: str = state["symbol"]
    broker: str = state["broker"]
    account_id = state.get("account_id")

    action = decision["action"]
    quantity = float(decision.get("quantity", 1))

    logger.info(f"[execution] Placing {action} order: {quantity} {symbol} via {broker}")

    order_result: dict = {}

    try:
        if broker == "alpaca":
            if action == "BUY":
                order_result = await broker_client.buy(symbol, qty=quantity, order_type="market")
            else:
                order_result = await broker_client.sell(symbol, qty=quantity, order_type="market")

        elif broker == "projectx":
            # ProjectX: side 0=Buy, 1=Sell; type 2=Market
            side = 0 if action == "BUY" else 1
            order_result = await broker_client.rest.place_order(
                account_id=account_id,
                contract_id=symbol,
                order_type=2,
                side=side,
                size=int(quantity),
            )

        logger.success(f"[execution] Order placed: {order_result.get('id', order_result)}")

    except Exception as exc:
        logger.error(f"[execution] Order placement failed: {exc}")
        return {
            "order_result": {"error": str(exc)},
            "messages": [AIMessage(content=f"Order failed: {exc}")],
        }

    # Log to SQLite
    try:
        order_id = str(order_result.get("id", ""))
        log_trade_to_db(
            {
                "broker": broker,
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "order_type": "market",
                "strategy_name": decision.get("strategy_name", ""),
                "confidence": float(decision.get("confidence", 0)),
                "target_price": float(decision.get("target_price", 0)),
                "stop_loss": float(decision.get("stop_loss", 0)),
                "take_profit": float(decision.get("take_profit", 0)),
                "order_id": order_id,
                "status": "submitted",
                "reasoning": decision.get("reasoning", ""),
            }
        )
    except Exception as exc:
        logger.error(f"[execution] SQLite log failed: {exc}")

    msg = AIMessage(
        content=(
            f"Order executed: {action} {quantity} {symbol} | "
            f"strategy={decision.get('strategy_name')} | "
            f"order_id={order_result.get('id', 'N/A')}"
        )
    )
    return {"order_result": order_result, "messages": [msg]}
