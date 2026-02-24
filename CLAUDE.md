# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Package manager**: `uv` (Python 3.13)

```bash
# Install dependencies
uv sync

# Run the project
uv run main.py

# Run a specific script
uv run python -m <module>

# Add a dependency
uv add <package>
```

**Infrastructure** (requires Docker):
```bash
# Start QuestDB and Redis
docker-compose up -d

# Stop
docker-compose down
```

## Architecture

This is a **quantitative trading AI agent** that connects to the Topstep/ProjectX broker, processes real-time market data, and makes AI-driven trading decisions.

### Data Flow

```
TopstepX WebSocket → adapters/topstep_client.py → QuestDB (port 9009, ILP)
                                                  ↓
                                           agents/nodes/market_reader.py
                                                  ↓
                                           agents/nodes/brain.py  ←→  LLM (Claude/OpenAI)
                                                  ↓
                                           agents/nodes/guardrail.py
                                                  ↓
                                           TradeOrder → SQLite (via shared/database.py)
                                                  ↓
                                           adapters/telegram_bot.py → Telegram notifications
```

### Key Directories

- **`adapters/`** — External service connectors. `topstep_client.py` is a WebSocket client for real-time market data from ProjectX API (`wss://api.projectx.topstep.com/v1/realtime`). `telegram_bot.py` is for user notifications and control.
- **`agents/nodes/`** — LangGraph agent nodes. `brain.py` is the main decision node (LLM reasoning), `guardrail.py` enforces risk rules, `market_reader.py` fetches/preprocesses market data.
- **`core/`** — LangGraph graph definition (`graph.py`), shared agent state schema (`state.py`), and system-wide constants (`constants.py`).
- **`shared/`** — Database layer. `database.py` manages both SQLite (via SQLModel/SQLAlchemy) and QuestDB (via InfluxDB Line Protocol on port 9009). `models.py` defines `AccountState`, `TradeOrder`, and `TradeLog` SQLModel tables, plus `MarketTick` (schema-less, stored in QuestDB).
- **`utils/`** — `logger.py` (Loguru setup), `indicators.py` (technical indicators using numpy/pandas).
- **`research_lab/experiments/`** — Scratch space for strategy experimentation.

### Databases

| Database | Purpose | Access |
|----------|---------|--------|
| SQLite (`data/trading.db`) | Trade orders, account state, audit logs | SQLModel ORM via `shared/database.py` |
| QuestDB | Time-series market tick data (bid/ask/last/volume) | InfluxDB Line Protocol (port 9009), Postgres wire (port 8812), Web Console (port 9000) |
| Redis | LangGraph agent state persistence | `aioredis` async client |

### Agent Framework

The system uses **LangGraph** for orchestration with **LangChain** for LLM integrations (both `langchain-anthropic` and `langchain-openai` are available). The agent graph is defined in `core/graph.py` with state managed by `core/state.py`. Agent state can be persisted to Redis for durability across restarts.

### Environment Variables

Configure in `.env` (gitignored):
- `QUESTDB_HOST` / `QUESTDB_PORT` — defaults to `127.0.0.1:9009`
- TopstepX API key (used in `TopstepWebSocketClient`)
- LLM API keys (Anthropic / OpenAI)
- Telegram bot token
