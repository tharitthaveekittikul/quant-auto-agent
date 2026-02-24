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
                    ┌─ adapters/projectx/market_hub.py (SignalR) ─┐
                    │                                              │
                    └─ adapters/alpaca/market_stream.py (WSS) ────┴──→ QuestDB (ILP, port 9009)
                                                                               ↓
                                                                  agents/nodes/market_reader.py
                                                                               ↓
                                                                  agents/nodes/brain.py ←→ LLM
                                                                               ↓
                                                                  agents/nodes/guardrail.py
                                                                               ↓
              adapters/projectx/user_hub.py  ←── order/fill events ──── SQLite (shared/database.py)
              adapters/alpaca/trade_stream.py                                  ↓
                                                                  adapters/telegram_bot.py → Telegram
```

### Key Directories

- **`adapters/projectx/`** — ProjectX Gateway API client (SignalR + REST). For demo (s2f) and production TopstepX.
- **`adapters/alpaca/`** — Alpaca Markets paper trading client (WebSocket + REST via alpaca-py SDK). Free alternative for testing without a paid account.
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

**SignalR** uses `signalrcore` (thread-based). Callbacks run in the SignalR thread; bridge to async with `asyncio.run_coroutine_threadsafe(coro, main_loop)`.

**Quick start:**
```python
client = await ProjectXClient.from_env()           # reads PROJECTX_ENV/USERNAME/API_KEY
accounts = await client.rest.search_accounts()
await client.connect_market(["CON.F.US.MES.M25"])  # streams quotes → QuestDB
await client.connect_user(account_id, on_order=handler)
```

### adapters/alpaca/ — Alpaca Paper Trading Client

Free alternative using Alpaca Markets paper trading ($100k simulated cash, no account fee).

| File | Purpose |
|------|---------|
| `config.py` | `Environment` enum (PAPER/LIVE) and feed config (`iex`=free/`sip`=paid) |
| `rest_client.py` | `RestClient` — async wrapper around alpaca-py `TradingClient` (orders, positions, account) |
| `market_stream.py` | `MarketStream` — WebSocket quotes + trades → QuestDB; wraps `StockDataStream` |
| `trade_stream.py` | `TradeStream` — order fill events; wraps `TradingStream` |
| `client.py` | `AlpacaClient` — unified facade |

**Environment URLs:**

| | REST API | Market Data Stream |
|---|---|---|
| Paper | `paper-api.alpaca.markets` | `stream.data.alpaca.markets/v2/iex` (free, 30 symbol limit) |
| Live | `api.alpaca.markets` | `stream.data.alpaca.markets/v2/sip` (paid) |

**Auth:** `APCA-API-KEY-ID` + `APCA-API-SECRET-KEY` headers. Paper and live accounts have **separate** credentials.

**Streams** use alpaca-py which runs its own asyncio event loop in a background thread. Bridge callbacks to the main loop with `asyncio.run_coroutine_threadsafe(coro, main_loop)`.

**Quick start:**
```python
client = await AlpacaClient.from_env()             # reads ALPACA_ENV/API_KEY/SECRET_KEY
account = await client.rest.get_account()          # $100k simulated paper cash
await client.connect_market(["AAPL", "SPY"])       # streams quotes + trades → QuestDB
await client.connect_user(on_order=handler)        # order fill events
await client.buy("SPY", qty=1)                     # market order
await client.rest.place_limit_order("AAPL", qty=5, side="sell", limit_price=200.0)
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
ALPACA_ENV=paper           # "paper" or "live"
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
QUESTDB_HOST=127.0.0.1
QUESTDB_PORT=9009
REDIS_URL=redis://localhost:6379
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
TELEGRAM_BOT_TOKEN=
```
