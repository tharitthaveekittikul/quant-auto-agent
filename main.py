"""
Quant Auto-Agent — async entry point.

Currently configured for XAUUSD (Gold) paper trading using:
  - Market data : Yahoo Finance (yfinance, free, no API key needed)
  - Execution   : Paper simulation (no real orders placed)
  - Brain model : BRAIN_MODEL env var (default: gemini-2.0-flash)
  - Checkpoints : Redis Stack (AsyncRedisSaver)

Run:
    uv run main.py
"""

import asyncio
import os

import asyncpg
from dotenv import load_dotenv
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from loguru import logger

from adapters.yfinance_client import YFinanceClient
from core.constants import DEFAULT_REDIS_URL, PG_DATABASE, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER
from core.graph import create_graph
from shared.database import init_db, log_account_state
from utils.logger import setup_logger

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SYMBOLS = ["XAUUSD"]       # Focus on Gold for now
BROKER = "yfinance"        # Paper trading via Yahoo Finance
STARTING_CAPITAL = 100_000.0
RUN_INTERVAL_SECONDS = 300  # 5 minutes


def _build_initial_state(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "broker": BROKER,
        "account_id": None,
        "market_data": [],
        "signals": {},
        "portfolio": {},
        "decision": None,
        "is_risk_passed": False,
        "risk_reason": "",
        "order_result": None,
        "messages": [],
        "error": None,
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run_agent_cycle(graph, symbol: str, config: dict, broker_client) -> None:
    """Run one full graph invocation for a symbol."""
    logger.info(f"--- Agent cycle start: {symbol} ---")
    initial_state = _build_initial_state(symbol)
    try:
        result = await graph.ainvoke(initial_state, config)
        decision = result.get("decision") or {}
        risk_passed = result.get("is_risk_passed", False)
        logger.info(
            f"Cycle complete: {symbol} | action={decision.get('action', 'N/A')} | "
            f"confidence={decision.get('confidence', 0):.2f} | "
            f"risk_passed={risk_passed} | reason={result.get('risk_reason', '')}"
        )
        if decision.get("action") != "HOLD" and decision.get("reasoning"):
            logger.info(f"Brain reasoning: {decision['reasoning'][:200]}")
    except Exception as exc:
        logger.error(f"Agent cycle failed for {symbol}: {exc}", exc_info=True)
        return

    # Snapshot portfolio to SQLite after every cycle
    try:
        acct = await broker_client.get_account()
        log_account_state({
            "broker": BROKER,
            "account_id": symbol,
            "cash": acct["cash"],
            "equity": acct["equity"],
            "buying_power": acct["buying_power"],
            "daily_pnl": acct["daily_pnl"],
            "daily_pnl_pct": acct["daily_pnl_pct"],
            "drawdown_pct": acct["drawdown_pct"],
        })
    except Exception as exc:
        logger.warning(f"AccountState snapshot failed: {exc}")


async def main() -> None:
    load_dotenv()
    setup_logger(os.getenv("LOG_LEVEL", "INFO"))

    logger.info(f"Initialising trading agent | symbols={SYMBOLS} | broker={BROKER}")
    logger.info(f"Brain model: {os.getenv('BRAIN_MODEL', 'claude-opus-4-6')} (via BRAIN_MODEL env)")

    # SQLite
    init_db()

    # YFinance paper trading client (no credentials needed)
    client = YFinanceClient(starting_capital=STARTING_CAPITAL)
    await client.connect_market(SYMBOLS)

    # asyncpg pool → QuestDB (used as cache; yfinance broker bypasses it)
    redis_url = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
    try:
        db_pool = await asyncpg.create_pool(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD,
            database=PG_DATABASE,
            min_size=1,
            max_size=5,
        )
        logger.info(f"QuestDB pool connected ({PG_HOST}:{PG_PORT})")
    except Exception as exc:
        logger.warning(f"QuestDB unavailable ({exc}) — yfinance broker will use REST-only mode")
        db_pool = None

    async with AsyncRedisSaver.from_conn_string(redis_url) as checkpointer:
        await checkpointer.asetup()
        logger.info(f"Redis checkpointer ready ({redis_url})")

        graph = create_graph(checkpointer, db_pool, client)

        try:
            while True:
                for symbol in SYMBOLS:
                    config = {"configurable": {"thread_id": f"trading-{BROKER}-{symbol}"}}
                    await run_agent_cycle(graph, symbol, config, client)

                logger.info(f"Sleeping {RUN_INTERVAL_SECONDS}s until next cycle...")
                await asyncio.sleep(RUN_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("Shutdown requested.")
        finally:
            if db_pool:
                await db_pool.close()
            await client.disconnect()
            logger.info("Agent shut down cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
