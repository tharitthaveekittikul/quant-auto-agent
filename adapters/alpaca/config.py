from dataclasses import dataclass
from enum import Enum

from alpaca.data.enums import DataFeed


class Environment(str, Enum):
    PAPER = "paper"
    LIVE = "live"


@dataclass(frozen=True)
class AlpacaConfig:
    name: str
    paper: bool
    # IEX = free tier (30 symbols max), SIP = paid SIP feed
    data_feed: DataFeed


ALPACA_CONFIGS: dict[Environment, AlpacaConfig] = {
    Environment.PAPER: AlpacaConfig(
        name="Alpaca Paper",
        paper=True,
        data_feed=DataFeed.IEX,
    ),
    Environment.LIVE: AlpacaConfig(
        name="Alpaca Live",
        paper=False,
        data_feed=DataFeed.SIP,
    ),
}
