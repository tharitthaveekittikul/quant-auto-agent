import os
from sqlmodel import SQLModel, create_engine, Session
from loguru import logger
import socket

# --- Configuration --- 
SQLITE_FILE_NAME = "data/trading.db"
SQLITE_URL = f"sqlite:///{SQLITE_FILE_NAME}"

# QuestDB
QUESTDB_HOST = os.getenv("QUESTDB_HOST", "127.0.0.1")
QUESTDB_PORT = int(os.getenv("QUESTDB_PORT", "9009"))

# --- SQLite Setup ---
# echo=False to reduce log noise
engine = create_engine(SQLITE_URL, echo=False)


def init_db():
    """
    Initialize the database by creating tables.
    All models must be imported before create_all so SQLModel sees them.
    """
    from .models import AccountState, TradeLog, TradeOrder  # noqa: F401

    os.makedirs("data", exist_ok=True)
    logger.info(f"Initializing database at {SQLITE_URL}")
    SQLModel.metadata.create_all(engine)
    logger.success("SQLite database initialized successfully")

def get_session():
    """
    Generate a new database session
    """
    with Session(engine) as session:
        yield session

# --- QuestDB Setup (Time-series Database) --- 

def send_to_questdb(symbol: str, bid: float, ask: float, last: float, volume: float):
    """
    Send market data to QuestDB via port 9009 (InfluxDB Line Protocol)
    """
    try:
        # Format: table_name,tag_set field_set timestamp
        # QuestDB will create table market_data automatically
        # tag_set: symbol
        # field_set: bid, ask, last, volume
        # timestamp: current time
        line = f"market_data,symbol={symbol} bid={bid},ask={ask},last={last},volume={volume}\n"

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1) # Prevent crash when DB down
            s.connect((QUESTDB_HOST, QUESTDB_PORT))
            s.sendall(line.encode())
    
    except Exception as e:
        logger.error(f"Failed to send data to QuestDB: {e}")

# --- Heloper Function for AI Agent --- 

def log_trade_to_db(order_data: dict):
    """Log a trade decision (intent) to TradeOrder table."""
    from .models import TradeOrder
    with Session(engine) as session:
        new_order = TradeOrder(**order_data)
        session.add(new_order)
        session.commit()
        session.refresh(new_order)
        logger.info(f"TradeOrder logged: {new_order.action} {new_order.quantity} {new_order.symbol} @ {new_order.target_price}")
        return new_order


def log_trade_log_to_db(log_data: dict):
    """Log an execution result (fill + P&L) to TradeLog table."""
    from .models import TradeLog
    with Session(engine) as session:
        entry = TradeLog(**log_data)
        session.add(entry)
        session.commit()
        session.refresh(entry)
        pnl_str = f" | pnl=${entry.pnl:+.2f}" if entry.pnl is not None else ""
        logger.info(f"TradeLog logged: {entry.action} {entry.quantity} {entry.symbol} @ {entry.fill_price}{pnl_str}")
        return entry


def log_account_state(state_data: dict):
    """Snapshot current portfolio equity to AccountState table."""
    from .models import AccountState
    with Session(engine) as session:
        snap = AccountState(**state_data)
        session.add(snap)
        session.commit()
        session.refresh(snap)
        logger.debug(f"AccountState snapshot: equity=${snap.equity:.2f} | daily_pnl={snap.daily_pnl_pct*100:.2f}%")
        return snap