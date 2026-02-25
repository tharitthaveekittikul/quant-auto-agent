"""
Telegram notification adapter for the quant trading agent.

Uses python-telegram-bot v20+ async Bot.send_message() — no polling/webhook needed.
The bot pushes notifications; it does not listen for commands.

Message types sent:
  - Trade executed  : BUY/SELL went through (action + price + reasoning)
  - Trade blocked   : guardrail rejected the trade
  - Cycle summary   : periodic market + portfolio snapshot (optional)
  - Error alert     : agent cycle crashed

Setup (see README or CLAUDE.md):
  TELEGRAM_BOT_TOKEN  — from @BotFather
  TELEGRAM_CHAT_ID    — your personal chat ID or a channel ID (e.g. -1001234567890)
"""

from __future__ import annotations

import os

from loguru import logger
from telegram import Bot
from telegram.error import TelegramError


class TelegramNotifier:
    """Async Telegram push-notification client."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._bot = Bot(token=token)
        self._chat_id = chat_id

    @classmethod
    def from_env(cls) -> "TelegramNotifier | None":
        """
        Create from environment variables.
        Returns None if TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set.
        """
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            logger.info("[Telegram] Disabled — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable")
            return None
        notifier = cls(token, chat_id)
        logger.info(f"[Telegram] Notifier ready (chat_id={chat_id})")
        return notifier

    # --- Public notification methods ---

    async def send_trade(
        self,
        symbol: str,
        action: str,
        qty: float,
        price: float,
        confidence: float,
        strategy: str,
        reasoning: str,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
    ) -> None:
        emoji = "🟢" if action == "BUY" else "🔴"
        text = (
            f"{emoji} <b>{action} {symbol}</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"Strategy: <code>{strategy}</code>\n"
            f"Confidence: <b>{confidence * 100:.0f}%</b>\n"
            f"Entry price: <b>${price:,.4f}</b>\n"
            f"Qty: {qty} unit(s)\n"
        )
        if stop_loss:
            text += f"Stop loss: ${stop_loss:,.4f}\n"
        if take_profit:
            text += f"Take profit: ${take_profit:,.4f}\n"
        if reasoning:
            text += f"\n💬 {reasoning[:300]}"

        await self._send(text)

    async def send_risk_blocked(
        self,
        symbol: str,
        action: str,
        confidence: float,
        reason: str,
    ) -> None:
        text = (
            f"⛔ <b>TRADE BLOCKED — {symbol}</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"Action: {action} (confidence {confidence * 100:.0f}%)\n"
            f"Reason: {reason}"
        )
        await self._send(text)

    async def send_cycle_summary(
        self,
        symbol: str,
        signals: dict,
        portfolio: dict,
        action: str,
    ) -> None:
        price = signals.get("current_price", 0)
        rsi = signals.get("rsi_14", 0)
        macd = signals.get("macd_line", 0)
        equity = portfolio.get("equity", 0)
        daily_pnl = portfolio.get("daily_pnl", 0)
        daily_pnl_pct = portfolio.get("daily_pnl_pct", 0) * 100
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"

        text = (
            f"📊 <b>{symbol}</b> cycle summary\n"
            f"━━━━━━━━━━━━━━\n"
            f"Price: <b>${price:,.4f}</b>\n"
            f"RSI(14): {rsi:.1f} | MACD: {macd:+.4f}\n"
            f"Decision: <b>{action}</b>\n"
            f"\n{pnl_emoji} Equity: ${equity:,.2f} | "
            f"P&L today: ${daily_pnl:+,.2f} ({daily_pnl_pct:+.2f}%)"
        )
        await self._send(text)

    async def send_error(self, symbol: str, error: str) -> None:
        text = (
            f"🚨 <b>AGENT ERROR — {symbol}</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"<code>{error[:500]}</code>"
        )
        await self._send(text)

    async def send_startup(self, broker: str, symbols: list[str]) -> None:
        text = (
            f"🤖 <b>Trading agent started</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"Broker: <code>{broker}</code>\n"
            f"Symbols: <code>{', '.join(symbols)}</code>"
        )
        await self._send(text)

    # --- Internal ---

    async def _send(self, text: str) -> None:
        try:
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode="HTML",
            )
        except TelegramError as exc:
            logger.warning(f"[Telegram] Failed to send message: {exc}")
