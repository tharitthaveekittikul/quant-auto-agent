from dataclasses import dataclass
from enum import Enum


class Environment(str, Enum):
    PAPER = "paper"
    LIVE = "live"


@dataclass(frozen=True)
class AlpacaConfig:
    name: str
    paper: bool
    # "iex" = free tier (30 symbols max), "sip" = paid SIP feed, "test" = sandbox
    data_feed: str


ALPACA_CONFIGS: dict[Environment, AlpacaConfig] = {
    Environment.PAPER: AlpacaConfig(
        name="Alpaca Paper",
        paper=True,
        data_feed="iex",
    ),
    Environment.LIVE: AlpacaConfig(
        name="Alpaca Live",
        paper=False,
        data_feed="sip",
    ),
}
