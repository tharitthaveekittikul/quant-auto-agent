import os

# --- Indicator Parameters ---
SMA_SHORT = 20
SMA_LONG = 50
EMA_FAST = 12
EMA_SLOW = 26
RSI_PERIOD = 14
MACD_SIGNAL = 9
BB_PERIOD = 20
BB_STD = 2.0
MIN_BARS_REQUIRED = 60

# --- QuestDB (Postgres Wire Protocol) ---
OHLCV_SAMPLE_INTERVAL = "5m"
OHLCV_LOOKBACK_HOURS = 24

PG_HOST = os.getenv("QUESTDB_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("QUESTDB_PG_PORT", "8812"))
PG_USER = os.getenv("QUESTDB_USER", "admin")
PG_PASSWORD = os.getenv("QUESTDB_PASSWORD", "quest")
PG_DATABASE = os.getenv("QUESTDB_DATABASE", "qdb")

# --- Risk Limits ---
MAX_DRAWDOWN_PCT = 0.05       # 5% max drawdown
DAILY_LOSS_LIMIT_PCT = 0.02   # 2% daily loss limit
MIN_CONFIDENCE = 0.65          # minimum decision confidence
MAX_POSITION_PCT = 0.10        # max 10% of equity per position
MAX_PRICE_DEVIATION_PCT = 0.02 # max 2% deviation from current price

# --- LLM ---
BRAIN_MODEL_ENV = "BRAIN_MODEL"
DEFAULT_BRAIN_MODEL = "claude-opus-4-6"

# --- Redis ---
DEFAULT_REDIS_URL = "redis://localhost:6379"
