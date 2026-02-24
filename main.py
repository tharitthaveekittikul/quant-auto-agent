"""
Quant Auto-Agent — async entry point.

Starts the Alpaca market stream and runs the LangGraph trading agent
on a periodic schedule with Redis-backed state persistence.
"""

import asyncio
import os

import asyncpg
from dotenv import load_dotenv
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from loguru import logger

from adapters.alpaca.client import AlpacaClient
from core.constants import DEFAULT_REDIS_URL, PG_DATABASE, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER
from core.graph import create_graph
from shared.database import init_db
from utils.logger import setup_logger

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SYMBOLS = ["AAPL", "SPY"]
BROKER = "alpaca"
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

async def run_agent_cycle(graph, symbol: str, config: dict) -> None:
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
    except Exception as exc:
        logger.error(f"Agent cycle failed for {symbol}: {exc}")


async def main() -> None:
    load_dotenv()
    setup_logger(os.getenv("LOG_LEVEL", "INFO"))

    logger.info("Initialising trading agent...")

    # SQLite
    init_db()

    # Alpaca client
    client = await AlpacaClient.from_env()

    # Start market stream (feeds QuestDB)
    await client.connect_market(SYMBOLS)
    logger.info(f"Market stream started for {SYMBOLS}")

    # Give stream a moment to warm up
    await asyncio.sleep(2)

    # asyncpg pool → QuestDB Postgres wire protocol
    redis_url = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
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

    async with AsyncRedisSaver.from_conn_string(redis_url) as checkpointer:
        await checkpointer.asetup()
        logger.info(f"Redis checkpointer ready ({redis_url})")

        graph = create_graph(checkpointer, db_pool, client)

        try:
            while True:
                for symbol in SYMBOLS:
                    config = {"configurable": {"thread_id": f"trading-{BROKER}-{symbol}"}}
                    await run_agent_cycle(graph, symbol, config)

                logger.info(f"Sleeping {RUN_INTERVAL_SECONDS}s until next cycle...")
                await asyncio.sleep(RUN_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("Shutdown requested.")
        finally:
            await db_pool.close()
            await client.disconnect()
            logger.info("Agent shut down cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
