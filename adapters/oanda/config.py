from dataclasses import dataclass
from enum import Enum


class Environment(str, Enum):
    PRACTICE = "practice"
    LIVE = "live"


@dataclass(frozen=True)
class OandaConfig:
    name: str
    rest_url: str
    stream_url: str


OANDA_CONFIGS: dict[Environment, OandaConfig] = {
    Environment.PRACTICE: OandaConfig(
        name="OANDA Practice",
        rest_url="https://api-fxpractice.oanda.com",
        stream_url="https://stream-fxpractice.oanda.com",
    ),
    Environment.LIVE: OandaConfig(
        name="OANDA Live",
        rest_url="https://api-fxtrade.oanda.com",
        stream_url="https://stream-fxtrade.oanda.com",
    ),
}
