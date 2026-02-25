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
# Start QuestDB and Redis Stack
docker-compose up -d

# Stop
docker-compose down
```

## Architecture

This is a **quantitative trading AI agent** built on LangGraph. It streams real-time market data from Alpaca (or ProjectX/TopstepX), computes technical indicators, and runs a stateful AI decision-making loop that can place trades automatically.

### Data Flow

```
                    ┌─ adapters/projectx/market_hub.py (SignalR) ─┐
                    │                                              │
                    └─ adapters/alpaca/market_stream.py (WSS) ────┴──→ QuestDB (ILP, port 9009)
                                                                               ↓
                                                            agents/nodes/market_reader.py
                                                            (QuestDB OHLCV query + REST fallback
                                                             + utils/indicators.py signals
                                                             + broker portfolio fetch)
                                                                               ↓
                                                            agents/nodes/brain.py ←→ LLM (Claude/GPT/Gemini)
                                                            (structured TradingDecision output)
                                                                               ↓
                                                            agents/nodes/guardrail.py
                                                            (pure Python risk rules, no LLM)
                                                                               ↓
                                          ┌──────────────── route_after_guardrail() ───────────────┐
                                          │ is_risk_passed=True, action∈{BUY,SELL}                 │ HOLD or fail
                                          ↓                                                        ↓
                            agents/nodes/execution.py                                             END
                            (broker order + SQLite log)
                                          ↓
              adapters/alpaca/client.py  ←── order result
              adapters/projectx/client.py
                                          ↓
                                   shared/database.py → SQLite (TradeOrder log)
```

### Key Directories

- **`main.py`** — Async entry point. Starts market stream, asyncpg pool, Redis checkpointer, runs the LangGraph cycle every 5 minutes.
- **`core/`** — `graph.py` (LangGraph factory), `state.py` (`AgentState` TypedDict + `TradingDecision` Pydantic), `constants.py` (all thresholds and env var names).
- **`agents/nodes/`** — Four LangGraph nodes: `market_reader.py`, `brain.py`, `guardrail.py`, `execution.py`.
- **`adapters/projectx/`** — ProjectX Gateway API client (SignalR + REST). For demo (s2f) and production TopstepX.
- **`adapters/alpaca/`** — Alpaca Markets paper trading client (WebSocket + REST via alpaca-py SDK).
- **`shared/`** — `database.py` (SQLite + QuestDB ILP helpers), `models.py` (`AccountState`, `TradeOrder`, `TradeLog` SQLModel tables).
- **`utils/`** — `logger.py` (Loguru setup), `llm.py` (`get_llm()` multi-provider factory), `indicators.py` (SMA/EMA/RSI/MACD/BB + `compute_all()`).
- **`research_lab/experiments/`** — Scratch space for strategy experimentation.

### LangGraph State Machine

Graph defined in `core/graph.py` via `create_graph(checkpointer, db_pool, broker_client)`.

```
START → market_reader → brain → guardrail
guardrail --[risk_passed + BUY/SELL]--> execution → END
guardrail --[HOLD or risk fail]---------> END
```

**State** (`core/state.py` `AgentState`):

| Field | Set by | Type |
|-------|--------|------|
| `symbol`, `broker`, `account_id` | caller (initial state) | identity |
| `market_data`, `signals`, `portfolio` | `market_reader` | market context |
| `decision` | `brain` | `TradingDecision.model_dump()` |
| `is_risk_passed`, `risk_reason` | `guardrail` | risk verdict |
| `order_result` | `execution` | broker response |
| `messages` | `brain` + `execution` | LangChain message history (auto-appended) |
| `error` | `market_reader` | error string or None |

State is **persisted in Redis** via `AsyncRedisSaver` — the graph resumes from the last checkpoint on restart using `thread_id = "trading-{broker}-{symbol}"`.

### Agent Nodes

| Node | File | Key function | LLM? |
|------|------|-------------|------|
| `market_reader` | `agents/nodes/market_reader.py` | `market_reader(state, *, db_pool, broker_client)` | No |
| `brain` | `agents/nodes/brain.py` | `brain(state)` | Yes |
| `guardrail` | `agents/nodes/guardrail.py` | `guardrail(state)` | No |
| `execution` | `agents/nodes/execution.py` | `execution(state, *, broker_client)` | No |

**market_reader** queries QuestDB via asyncpg (Postgres wire port 8812):
```sql
SELECT timestamp, first(last) o, max(last) h, min(last) l, last(last) c,
       sum(volume) v, last(bid) bid, last(ask) ask
FROM market_data WHERE symbol=$1 AND last>0
AND timestamp >= dateadd('h', -24, now())
SAMPLE BY 5m ALIGN TO CALENDAR ORDER BY timestamp ASC LIMIT 100
```
Falls back to broker REST bars if QuestDB has < 60 bars.

**brain** calls `get_llm("BRAIN_MODEL", "claude-opus-4-6")` with structured output (`TradingDecision`). Supports Claude, GPT, Gemini — detected by model name prefix.

**guardrail** checks (first failure wins):
1. Decision exists
2. Confidence ≥ 0.65
3. Daily P&L ≥ −2% of equity
4. Drawdown ≤ 5%
5. Target price within 2% of current price
6. Position size ≤ 10% of equity

### Utils

**`utils/llm.py` — `get_llm(env_var, default)`**
- `claude-*` → `ChatAnthropic`
- `gpt-*` / `o1-*` / `o3-*` / `o4-*` → `ChatOpenAI`
- `gemini-*` → `ChatGoogleGenerativeAI`
- All instantiated with `temperature=0.0`

**`utils/indicators.py` — `compute_all(bars) → dict`**
Returns: `sma_20`, `sma_50`, `ema_12`, `ema_26`, `rsi_14`, `macd_line`, `macd_signal`, `macd_histogram`, `bb_upper`, `bb_middle`, `bb_lower`, `current_price`, `spread`, `volume_24h`

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
| `config.py` | `Environment` enum (PAPER/LIVE); `data_feed: DataFeed` (IEX=free/SIP=paid) |
| `rest_client.py` | `RestClient` — async wrapper around alpaca-py `TradingClient` (orders, positions, account) |
| `market_stream.py` | `MarketStream` — WebSocket quotes + trades → QuestDB; wraps `StockDataStream` |
| `trade_stream.py` | `TradeStream` — order fill events; wraps `TradingStream` |
| `client.py` | `AlpacaClient` — unified facade |

**Note:** `data_feed` must be `alpaca.data.enums.DataFeed` enum (not a plain string) — `StockDataStream` calls `.value` on it internally.

**Quick start:**
```python
client = await AlpacaClient.from_env()             # reads ALPACA_ENV/API_KEY/SECRET_KEY
account = await client.rest.get_account()          # $100k simulated paper cash
await client.connect_market(["AAPL", "SPY"])       # streams quotes + trades → QuestDB
await client.connect_user(on_order=handler)        # order fill events
await client.buy("SPY", qty=1)                     # market order
await client.rest.place_limit_order("AAPL", qty=5, side="sell", limit_price=200.0)
```

### adapters/oanda/ — OANDA v20 Forex/Metals Client

Supports forex pairs (EUR_USD, GBP_JPY) and metals (XAU_USD gold, XAG_USD silver) on OANDA's fxpractice or live environment.

| File | Purpose |
|------|---------|
| `config.py` | `Environment` enum (PRACTICE/LIVE); `OandaConfig` frozen dataclass; `OANDA_CONFIGS` dict |
| `rest_client.py` | `RestClient` — async `httpx.AsyncClient` wrapper for all v20 REST endpoints |
| `market_stream.py` | `MarketStream` — chunked HTTP pricing stream → QuestDB; runs as asyncio.Task |
| `trade_stream.py` | `TradeStream` — chunked HTTP transaction stream; fires `on_order` callback |
| `client.py` | `OandaClient` — unified facade mirroring AlpacaClient interface |

**Auth:** Personal Access Token (Bearer) — no login/refresh flow.

**Streaming transport:** `httpx` async chunked HTTP (not WebSocket/SignalR). Auto-reconnects with exponential backoff.

**Units convention:** Positive string = buy, negative = sell (e.g. `"100"` or `"-100"`). All price/units in request bodies are strings per OANDA spec.

**Quick start:**
```python
client = await OandaClient.from_env()              # reads OANDA_ENV/API_KEY/ACCOUNT_ID
account = await client.rest.get_account(client.account_id)
await client.connect_market(["XAU_USD", "EUR_USD"])  # streams prices → QuestDB
await client.connect_user(on_order=handler)          # order fill events
await client.buy("XAU_USD", qty=1)                   # market order (1 unit)
await client.sell("EUR_USD", qty=10000)              # market order
```

**Environment variables:**
```
OANDA_ENV=practice           # "practice" or "live"
OANDA_API_KEY=               # Personal Access Token from OANDA AMP
OANDA_ACCOUNT_ID=            # optional; auto-fetched from /v3/accounts if absent
```

### Databases

| Database | Purpose | Access |
|----------|---------|--------|
| SQLite (`data/trading.db`) | `TradeOrder`, `TradeLog`, `AccountState` | SQLModel ORM via `shared/database.py` |
| QuestDB | Time-series tick data (`market_data` table) | ILP port 9009 (write); Postgres port 8812 (query); web console port 9000 |
| Redis Stack | LangGraph checkpoint state (requires RedisJSON module) | `AsyncRedisSaver` via `langgraph-checkpoint-redis` |

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
QUESTDB_PORT=9009          # ILP write port
QUESTDB_PG_PORT=8812       # Postgres query port (used by asyncpg)
REDIS_URL=redis://localhost:6379
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=
BRAIN_MODEL=claude-opus-4-6   # or gpt-4o or gemini-2.0-flash
TELEGRAM_BOT_TOKEN=
OANDA_ENV=practice           # "practice" or "live"
OANDA_API_KEY=               # Personal Access Token from OANDA AMP
OANDA_ACCOUNT_ID=            # optional; auto-fetched from /v3/accounts if absent
```

### Known Behaviours

- **Zero bars on startup**: Normal when market is closed or QuestDB is empty. The stream feeds QuestDB over time; the REST fallback only returns data during US market hours (9:30 AM–4 PM ET) on the IEX free feed.
- **Redis requires redis-stack**: `langgraph-checkpoint-redis` uses the RedisJSON module. Use `redis/redis-stack:latest` in docker-compose, not `redis:alpine`.
- **Alpaca `data_feed` must be `DataFeed` enum**: Not a plain string — `StockDataStream` calls `.value` on it.
- **Thread bridging**: Both Alpaca streams and ProjectX SignalR run in background threads. Use `asyncio.run_coroutine_threadsafe(coro, main_loop)` to bridge callbacks to the async main loop.
