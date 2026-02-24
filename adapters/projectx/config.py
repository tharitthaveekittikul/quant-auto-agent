from dataclasses import dataclass
from enum import Enum


class Environment(str, Enum):
    DEMO = "demo"
    TOPSTEP = "topstep"


@dataclass(frozen=True)
class EnvironmentConfig:
    name: str
    api_url: str
    market_hub_url: str
    user_hub_url: str


ENVIRONMENT_CONFIGS: dict[Environment, EnvironmentConfig] = {
    Environment.DEMO: EnvironmentConfig(
        name="Demo",
        api_url="https://gateway-api-demo.s2f.projectx.com",
        market_hub_url="https://gateway-rtc-demo.s2f.projectx.com/hubs/market",
        user_hub_url="https://gateway-rtc-demo.s2f.projectx.com/hubs/user",
    ),
    Environment.TOPSTEP: EnvironmentConfig(
        name="TopstepX",
        api_url="https://api.topstepx.com",
        market_hub_url="https://rtc.topstepx.com/hubs/market",
        user_hub_url="https://rtc.topstepx.com/hubs/user",
    ),
}
