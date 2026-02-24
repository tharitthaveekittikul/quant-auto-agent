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
    Initialize the database by creating tables
    """
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
    """Example function Agent for logging trade to SQLite"""
    from .models import TradeOrder # Prevent Circular Import
    with Session(engine) as session:
        new_order = TradeOrder(**order_data)
        session.add(new_order)
        session.commit()
        session.refresh(new_order)
        logger.info(f"Trade logged to SQLite: {new_order}")
        return new_order