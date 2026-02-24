"""
guardrail node — pure Python risk enforcement, no LLM calls.
"""

from __future__ import annotations

from loguru import logger

from core.constants import (
    DAILY_LOSS_LIMIT_PCT,
    MAX_DRAWDOWN_PCT,
    MAX_POSITION_PCT,
    MAX_PRICE_DEVIATION_PCT,
    MIN_CONFIDENCE,
)


def guardrail(state: dict) -> dict:
    """
    LangGraph node: validates the brain decision against risk rules.
    Returns is_risk_passed (bool) and risk_reason (str).
    """
    decision: dict | None = state.get("decision")
    portfolio: dict = state.get("portfolio", {})
    signals: dict = state.get("signals", {})

    # Rule 1: decision must exist
    if not decision:
        reason = "No decision produced by brain node."
        logger.warning(f"[guardrail] FAIL — {reason}")
        return {"is_risk_passed": False, "risk_reason": reason}

    action = decision.get("action", "HOLD")
    confidence = float(decision.get("confidence", 0))
    target_price = float(decision.get("target_price", 0))
    quantity = float(decision.get("quantity", 0))

    current_price = float(signals.get("current_price", target_price) or target_price)
    equity = float(portfolio.get("equity", 0) or 0)
    daily_pnl_pct = float(portfolio.get("daily_pnl_pct", 0) or 0)
    drawdown_pct = float(portfolio.get("drawdown_pct", 0) or 0)

    # Rule 2: confidence threshold
    if confidence < MIN_CONFIDENCE:
        reason = f"Confidence {confidence:.2f} below minimum {MIN_CONFIDENCE}."
        logger.info(f"[guardrail] FAIL — {reason}")
        return {"is_risk_passed": False, "risk_reason": reason}

    # Rule 3: daily loss limit
    if daily_pnl_pct < -DAILY_LOSS_LIMIT_PCT:
        reason = f"Daily loss {daily_pnl_pct*100:.2f}% exceeds limit {DAILY_LOSS_LIMIT_PCT*100:.0f}%."
        logger.warning(f"[guardrail] FAIL — {reason}")
        return {"is_risk_passed": False, "risk_reason": reason}

    # Rule 4: drawdown limit
    if drawdown_pct > MAX_DRAWDOWN_PCT:
        reason = f"Drawdown {drawdown_pct*100:.2f}% exceeds max {MAX_DRAWDOWN_PCT*100:.0f}%."
        logger.warning(f"[guardrail] FAIL — {reason}")
        return {"is_risk_passed": False, "risk_reason": reason}

    # Rule 5: price deviation check (only for actionable decisions)
    if action in ("BUY", "SELL") and current_price > 0 and target_price > 0:
        deviation = abs(target_price - current_price) / current_price
        if deviation > MAX_PRICE_DEVIATION_PCT:
            reason = (
                f"Target price {target_price:.2f} deviates {deviation*100:.2f}% "
                f"from current {current_price:.2f} (max {MAX_PRICE_DEVIATION_PCT*100:.0f}%)."
            )
            logger.warning(f"[guardrail] FAIL — {reason}")
            return {"is_risk_passed": False, "risk_reason": reason}

    # Rule 6: position size check
    if action in ("BUY", "SELL") and equity > 0 and current_price > 0:
        estimated_value = quantity * current_price
        max_value = equity * MAX_POSITION_PCT
        if estimated_value > max_value:
            reason = (
                f"Position size ${estimated_value:.2f} exceeds max "
                f"{MAX_POSITION_PCT*100:.0f}% of equity (${max_value:.2f})."
            )
            logger.warning(f"[guardrail] FAIL — {reason}")
            return {"is_risk_passed": False, "risk_reason": reason}

    logger.info(f"[guardrail] PASS — action={action}, confidence={confidence:.2f}")
    return {"is_risk_passed": True, "risk_reason": "All risk checks passed."}
