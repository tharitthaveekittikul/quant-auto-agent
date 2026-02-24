from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, DateTime, String, Float, JSON
from sqlmodel import SQLModel, Field

class AccountState(SQLModel, table=True):
    """Store Account State in every minute or hour"""
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    balance: float
    equity: float
    current_drawdown: float
    daily_pnl: float
    is_active: bool = True


class TradeOrder(SQLModel, table=True):
    """Store Trade Order"""
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)

    # Details
    symbol: str = Field(index=True)
    order_type: str
    entry_price: float
    exit_price: Optional[float] = None
    quantity: float

    # Topstep Specific
    order_id_topstep: str = Field(unique=True) # ID from ProjectX
    status: str # FILLED, CANCELLED, REJECTED, CLOSED

    # AI Reasoning
    strategy_name: str
    confidence_score: float
    reasoning: str = Field(sa_column=Column(String))
    setup_image_url: Optional[str] = None


class TradeLog(SQLModel, table=True):
    """Store every trade log for doing Audit Trail"""
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    agent_name: str
    level: str
    message: str
    metadata: Optional[dict] = Field(default_factory=dict, sa_column=Column(JSON))

# --- QuestDB Model Concepts (Schema-less/ILP) ---

class MarketTick:
    """
    Model for QuestDB refer time-series via InfluxDB Line Protocol (ILP)
    """
    table_name = "market_data"
    # Columns:
    # timestamp: Timestamp (Designated)
    # symbol: Symbol (Symbol Type - Optimized for Query)
    # bid: Float
    # ask: Float
    # last: Float
    # volume: Float