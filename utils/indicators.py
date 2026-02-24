import numpy as np

from core.constants import (
    BB_PERIOD,
    BB_STD,
    EMA_FAST,
    EMA_SLOW,
    MACD_SIGNAL,
    RSI_PERIOD,
    SMA_LONG,
    SMA_SHORT,
)


def sma(prices: list[float], period: int) -> float:
    """Simple moving average of the last `period` prices."""
    if len(prices) < period:
        return float("nan")
    return float(np.mean(prices[-period:]))


def ema(prices: list[float], period: int) -> float:
    """
    Exponential moving average using Wilder's smoothing.
    Seeds from SMA of the first `period` values.
    """
    if len(prices) < period:
        return float("nan")
    arr = np.array(prices, dtype=float)
    k = 2.0 / (period + 1)
    result = np.mean(arr[:period])
    for price in arr[period:]:
        result = price * k + result * (1 - k)
    return float(result)


def rsi(prices: list[float], period: int = 14) -> float:
    """
    Relative Strength Index using Wilder's smoothing.
    Returns a value in [0, 100].
    """
    if len(prices) < period + 1:
        return float("nan")
    arr = np.array(prices, dtype=float)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))


def macd(
    prices: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict:
    """
    MACD indicator: line, signal, histogram.
    Returns dict with keys: macd_line, macd_signal, macd_histogram.
    """
    nan_result = {"macd_line": float("nan"), "macd_signal": float("nan"), "macd_histogram": float("nan")}
    if len(prices) < slow + signal:
        return nan_result

    arr = np.array(prices, dtype=float)

    def _ema_series(data: np.ndarray, period: int) -> np.ndarray:
        k = 2.0 / (period + 1)
        result = [float(np.mean(data[:period]))]
        for p in data[period:]:
            result.append(p * k + result[-1] * (1 - k))
        return np.array(result)

    ema_fast = _ema_series(arr, fast)
    ema_slow = _ema_series(arr, slow)

    # Align: ema_fast is longer; trim to match ema_slow length
    offset = slow - fast
    ema_fast_trimmed = ema_fast[offset:]

    macd_line_series = ema_fast_trimmed - ema_slow
    signal_series = _ema_series(macd_line_series, signal)

    line = float(macd_line_series[-1])
    sig = float(signal_series[-1])
    return {
        "macd_line": line,
        "macd_signal": sig,
        "macd_histogram": line - sig,
    }


def bollinger_bands(
    prices: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> dict:
    """
    Bollinger Bands: upper, middle (SMA), lower.
    """
    nan_result = {"bb_upper": float("nan"), "bb_middle": float("nan"), "bb_lower": float("nan")}
    if len(prices) < period:
        return nan_result
    window = np.array(prices[-period:], dtype=float)
    middle = float(np.mean(window))
    std = float(np.std(window, ddof=1))
    return {
        "bb_upper": middle + num_std * std,
        "bb_middle": middle,
        "bb_lower": middle - num_std * std,
    }


def compute_all(bars: list[dict]) -> dict:
    """
    Convenience wrapper called by market_reader.
    Expects bars as list of dicts with at least 'c' (close), 'v' (volume),
    'b' (bid), 'a' (ask) keys.
    Returns flattened signals dict.
    """
    if not bars:
        return {}

    closes = [float(b.get("c", b.get("close", 0))) for b in bars]
    volumes = [float(b.get("v", b.get("volume", 0))) for b in bars]
    last_bar = bars[-1]
    bid = float(last_bar.get("b", last_bar.get("bid", 0)))
    ask = float(last_bar.get("a", last_bar.get("ask", 0)))
    current_price = closes[-1] if closes else 0.0

    signals: dict = {
        "current_price": current_price,
        "spread": round(ask - bid, 6) if ask and bid else 0.0,
        "volume_24h": sum(volumes),
        "sma_20": sma(closes, SMA_SHORT),
        "sma_50": sma(closes, SMA_LONG),
        "ema_12": ema(closes, EMA_FAST),
        "ema_26": ema(closes, EMA_SLOW),
        "rsi_14": rsi(closes, RSI_PERIOD),
    }
    signals.update(macd(closes, EMA_FAST, EMA_SLOW, MACD_SIGNAL))
    signals.update(bollinger_bands(closes, BB_PERIOD, BB_STD))
    return signals
