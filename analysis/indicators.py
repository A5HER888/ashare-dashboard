# analysis/indicators.py — Pure pandas technical indicator calculations.
# All functions take a DataFrame (output of fetcher.get_stock_history) and return
# a new DataFrame with extra columns added. No side effects, no Streamlit calls.

import pandas as pd
import numpy as np
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import MA_PERIODS, RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL, VOLUME_AVG_PERIOD


# ---------------------------------------------------------------------------
# Moving Averages
# ---------------------------------------------------------------------------

def add_moving_averages(df: pd.DataFrame, periods: list = MA_PERIODS) -> pd.DataFrame:
    """Add MA columns: ma5, ma10, ma20, ma60 (or whatever periods are given)."""
    df = df.copy()
    for p in periods:
        df[f"ma{p}"] = df["close"].rolling(window=p, min_periods=1).mean().round(4)
    return df


# ---------------------------------------------------------------------------
# RSI (Relative Strength Index)
# ---------------------------------------------------------------------------

def add_rsi(df: pd.DataFrame, period: int = RSI_PERIOD) -> pd.DataFrame:
    """
    Add RSI column using Wilder's smoothing (EWM with alpha = 1/period).
    Values range 0-100. Below 30 = oversold, above 70 = overbought.
    """
    df = df.copy()
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Wilder smoothing (equivalent to EMA with alpha=1/period)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = (100 - 100 / (1 + rs)).round(2)
    return df


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def add_macd(
    df: pd.DataFrame,
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL
) -> pd.DataFrame:
    """
    Add MACD columns:
      macd_line  = EMA(fast) - EMA(slow)
      macd_signal = EMA(macd_line, signal)
      macd_hist  = macd_line - macd_signal  (the histogram / bar)
    """
    df = df.copy()
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["macd_line"]   = (ema_fast - ema_slow).round(4)
    df["macd_signal"] = df["macd_line"].ewm(span=signal, adjust=False).mean().round(4)
    df["macd_hist"]   = (df["macd_line"] - df["macd_signal"]).round(4)
    return df


# ---------------------------------------------------------------------------
# Volume Ratio (量比)
# ---------------------------------------------------------------------------

def add_volume_ratio(df: pd.DataFrame, avg_period: int = VOLUME_AVG_PERIOD) -> pd.DataFrame:
    """
    Volume ratio = today's volume / average volume over the past N days (excluding today).

    A ratio > 1 means today's volume is above the recent average.
    Ratio > 1.5 = moderately elevated; > 2.0 = significant spike.

    Note: if akshare already provides a volume_ratio column in real-time data,
    that value is more accurate intraday. This calculation is for historical bars.
    """
    df = df.copy()
    # Rolling mean of the PREVIOUS N days (shift by 1 so we don't include today)
    avg_vol = df["volume"].shift(1).rolling(window=avg_period, min_periods=1).mean()
    df["volume_ratio"] = (df["volume"] / avg_vol.replace(0, np.nan)).round(2)
    return df


# ---------------------------------------------------------------------------
# Bollinger Bands (bonus — useful for breakout detection)
# ---------------------------------------------------------------------------

def add_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """Add upper/lower Bollinger Bands around the 20-day MA."""
    df = df.copy()
    mid = df["close"].rolling(window=period, min_periods=1).mean()
    std = df["close"].rolling(window=period, min_periods=1).std()
    df["bb_mid"]   = mid.round(4)
    df["bb_upper"] = (mid + std_dev * std).round(4)
    df["bb_lower"] = (mid - std_dev * std).round(4)
    return df


# ---------------------------------------------------------------------------
# Convenience: add all indicators at once
# ---------------------------------------------------------------------------

def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply all indicators in one call.
    Input: raw OHLCV DataFrame from fetcher.
    Output: same DataFrame with MA, RSI, MACD, volume_ratio, Bollinger columns added.
    """
    if df.empty:
        return df
    df = add_moving_averages(df)
    df = add_rsi(df)
    df = add_macd(df)
    df = add_volume_ratio(df)
    df = add_bollinger_bands(df)
    return df
