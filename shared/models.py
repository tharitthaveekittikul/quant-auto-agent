from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class AccountState(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    broker: str
    account_id: str
    cash: float
    equity: float
    buying_power: float
    daily_pnl: float
    daily_pnl_pct: float
    drawdown_pct: float
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TradeOrder(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    broker: str
    symbol: str
    action: str  # BUY / SELL
    quantity: float
    order_type: str = "market"
    strategy_name: str = ""
    confidence: float = 0.0
    target_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    order_id: Optional[str] = None
    status: str = "submitted"
    reasoning: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TradeLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    broker: str
    symbol: str
    action: str
    quantity: float
    fill_price: Optional[float] = None
    pnl: Optional[float] = None
    strategy_name: str = ""
    order_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
