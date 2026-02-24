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
ProjectX SignalR → adapters/projectx/market_hub.py → QuestDB (port 9009, ILP)
                                                    ↓
                                             agents/nodes/market_reader.py
                                                    ↓
                                             agents/nodes/brain.py  ←→  LLM (Claude/OpenAI)
                                                    ↓
                                             agents/nodes/guardrail.py
                                                    ↓
                 adapters/projectx/user_hub.py ← TradeOrder → SQLite (shared/database.py)
                          (order/position events)            ↓
                                                    adapters/telegram_bot.py → Telegram
```

### Key Directories

- **`adapters/projectx/`** — Full ProjectX Gateway API client (demo + production). See below.
- **`agents/nodes/`** — LangGraph agent nodes: `brain.py` (LLM decision making), `guardrail.py` (risk enforcement), `market_reader.py` (data preprocessing).
- **`core/`** — LangGraph graph definition (`graph.py`), shared agent state schema (`state.py`), and system-wide constants (`constants.py`).
- **`shared/`** — Database layer. `database.py` manages SQLite (SQLModel ORM) and QuestDB (InfluxDB Line Protocol). `models.py` defines `AccountState`, `TradeOrder`, `TradeLog` SQLModel tables and the schema-less `MarketTick` (QuestDB).
- **`utils/`** — `logger.py` (Loguru), `indicators.py` (technical indicators with numpy/pandas).
- **`research_lab/experiments/`** — Scratch space for strategy experimentation.

### adapters/projectx/ — ProjectX Client

| File | Purpose |
|------|---------|
| `config.py` | `Environment` enum (DEMO/TOPSTEP) and base URLs for each env |
| `auth.py` | `AuthSession` — login via API key, token refresh (token valid 24h) |
| `rest_client.py` | `RestClient` — async httpx wrapper for all REST endpoints |
| `market_hub.py` | `MarketHub` — SignalR client for real-time quotes/trades/depth |
| `user_hub.py` | `UserHub` — SignalR client for order/position/account/trade events |
| `client.py` | `ProjectXClient` — unified facade combining all of the above |

**Environment URLs:**

| | REST API | Market Hub | User Hub |
|---|---|---|---|
| Demo | `gateway-api-demo.s2f.projectx.com` | `gateway-rtc-demo.s2f.projectx.com/hubs/market` | `…/hubs/user` |
| TopstepX | `api.topstepx.com` | `rtc.topstepx.com/hubs/market` | `rtc.topstepx.com/hubs/user` |

**Auth flow:** POST `/api/Auth/loginKey` → JWT token → pass as `Bearer` on REST + `access_token_factory` for SignalR. Call `/api/Auth/validate` every 23h to refresh.

**SignalR** uses `signalrcore` (thread-based). Callbacks run in the SignalR thread; use `asyncio.run_coroutine_threadsafe(coro, loop)` to bridge into the main async event loop.

**Quick start:**
```python
client = await ProjectXClient.from_env()           # reads PROJECTX_ENV/USERNAME/API_KEY
accounts = await client.rest.search_accounts()
await client.connect_market(["CON.F.US.MES.M25"])  # streams quotes → QuestDB
await client.connect_user(account_id, on_order=handler)
```

### Databases

| Database | Purpose | Access |
|----------|---------|--------|
| SQLite (`data/trading.db`) | Trade orders, account state, audit logs | SQLModel ORM via `shared/database.py` |
| QuestDB | Time-series market tick data | InfluxDB Line Protocol port 9009; web console port 9000; Postgres port 8812 |
| Redis | LangGraph agent state persistence | `aioredis` async client |

### Agent Framework

**LangGraph** for graph orchestration, **LangChain** for LLM calls (both `langchain-anthropic` and `langchain-openai` available). Graph defined in `core/graph.py`, state schema in `core/state.py`, Redis for cross-restart state persistence.

### Environment Variables

Configure in `.env` (gitignored):

```
PROJECTX_ENV=demo          # "demo" or "topstep"
PROJECTX_USERNAME=
PROJECTX_API_KEY=
QUESTDB_HOST=127.0.0.1
QUESTDB_PORT=9009
REDIS_URL=redis://localhost:6379
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
TELEGRAM_BOT_TOKEN=
```
