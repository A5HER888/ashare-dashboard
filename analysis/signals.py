# analysis/signals.py — Rule-based signal detection engine.
# All detectors take a DataFrame that already has indicators added (add_all_indicators).
# Each returns a list of signal dicts: {type, date, value, description}

import pandas as pd
import numpy as np
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    RSI_OVERSOLD, RSI_OVERBOUGHT,
    VOLUME_RATIO_HIGH, VOLUME_RATIO_MODERATE,
    BREAKOUT_LOOKBACK
)


# ---------------------------------------------------------------------------
# Individual signal detectors
# ---------------------------------------------------------------------------

def detect_ma_crossover(df: pd.DataFrame, fast: int = 5, slow: int = 20) -> list:
    """
    Golden cross: fast MA crosses above slow MA (bullish).
    Death cross:  fast MA crosses below slow MA (bearish).
    Looks at the last 5 trading days to catch recent events.
    """
    signals = []
    fast_col = f"ma{fast}"
    slow_col = f"ma{slow}"
    if fast_col not in df.columns or slow_col not in df.columns:
        return signals

    recent = df.tail(10).reset_index(drop=True)
    for i in range(1, len(recent)):
        prev_fast = recent.loc[i - 1, fast_col]
        prev_slow = recent.loc[i - 1, slow_col]
        curr_fast = recent.loc[i, fast_col]
        curr_slow = recent.loc[i, slow_col]
        date = recent.loc[i, "date"]

        if pd.isna(prev_fast) or pd.isna(prev_slow):
            continue

        if prev_fast <= prev_slow and curr_fast > curr_slow:
            signals.append({
                "type": "MA金叉",
                "direction": "bullish",
                "date": date,
                "value": round(curr_fast, 2),
                "description": f"MA{fast} 上穿 MA{slow}（金叉）",
            })
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            signals.append({
                "type": "MA死叉",
                "direction": "bearish",
                "date": date,
                "value": round(curr_fast, 2),
                "description": f"MA{fast} 下穿 MA{slow}（死叉）",
            })
    return signals


def detect_rsi_signals(df: pd.DataFrame) -> list:
    """Detect RSI entering oversold (<30) or overbought (>70) zones."""
    signals = []
    if "rsi" not in df.columns or df["rsi"].isna().all():
        return signals

    recent = df.tail(10).reset_index(drop=True)
    for i in range(1, len(recent)):
        rsi_prev = recent.loc[i - 1, "rsi"]
        rsi_curr = recent.loc[i, "rsi"]
        date = recent.loc[i, "date"]
        if pd.isna(rsi_curr) or pd.isna(rsi_prev):
            continue

        # Entered oversold
        if rsi_prev >= RSI_OVERSOLD and rsi_curr < RSI_OVERSOLD:
            signals.append({
                "type": "RSI超卖",
                "direction": "bullish",
                "date": date,
                "value": round(rsi_curr, 1),
                "description": f"RSI 跌入超卖区（{rsi_curr:.1f} < {RSI_OVERSOLD}）",
            })
        # Exited oversold (reversal hint)
        elif rsi_prev < RSI_OVERSOLD and rsi_curr >= RSI_OVERSOLD:
            signals.append({
                "type": "RSI超卖反弹",
                "direction": "bullish",
                "date": date,
                "value": round(rsi_curr, 1),
                "description": f"RSI 从超卖区回升（{rsi_curr:.1f}）",
            })
        # Entered overbought
        elif rsi_prev <= RSI_OVERBOUGHT and rsi_curr > RSI_OVERBOUGHT:
            signals.append({
                "type": "RSI超买",
                "direction": "bearish",
                "date": date,
                "value": round(rsi_curr, 1),
                "description": f"RSI 进入超买区（{rsi_curr:.1f} > {RSI_OVERBOUGHT}）",
            })
    return signals


def detect_macd_crossover(df: pd.DataFrame) -> list:
    """MACD line crosses signal line (golden/death cross on MACD histogram)."""
    signals = []
    if "macd_line" not in df.columns or "macd_signal" not in df.columns:
        return signals

    recent = df.tail(10).reset_index(drop=True)
    for i in range(1, len(recent)):
        prev_hist = recent.loc[i - 1, "macd_hist"]
        curr_hist = recent.loc[i, "macd_hist"]
        date = recent.loc[i, "date"]
        if pd.isna(prev_hist) or pd.isna(curr_hist):
            continue

        if prev_hist <= 0 and curr_hist > 0:
            signals.append({
                "type": "MACD金叉",
                "direction": "bullish",
                "date": date,
                "value": round(curr_hist, 4),
                "description": "MACD 柱翻红（MACD线上穿信号线）",
            })
        elif prev_hist >= 0 and curr_hist < 0:
            signals.append({
                "type": "MACD死叉",
                "direction": "bearish",
                "date": date,
                "value": round(curr_hist, 4),
                "description": "MACD 柱翻绿（MACD线下穿信号线）",
            })
    return signals


def detect_volume_spike(df: pd.DataFrame) -> list:
    """Detect days where volume ratio exceeds the high threshold."""
    signals = []
    if "volume_ratio" not in df.columns:
        return signals

    recent = df.tail(5)
    for _, row in recent.iterrows():
        vr = row.get("volume_ratio")
        if pd.isna(vr):
            continue
        if vr >= VOLUME_RATIO_HIGH:
            signals.append({
                "type": "放量异动",
                "direction": "neutral",
                "date": row["date"],
                "value": round(vr, 2),
                "description": f"量比 {vr:.2f}x — 显著放量",
            })
        elif vr >= VOLUME_RATIO_MODERATE:
            signals.append({
                "type": "温和放量",
                "direction": "neutral",
                "date": row["date"],
                "value": round(vr, 2),
                "description": f"量比 {vr:.2f}x — 温和放量",
            })
    return signals


def detect_breakout(df: pd.DataFrame, lookback: int = BREAKOUT_LOOKBACK) -> list:
    """Price breaks above the highest close in the previous N trading days."""
    signals = []
    if len(df) < lookback + 1:
        return signals

    # Look at the last 5 bars for recent breakouts
    check_window = df.tail(5 + lookback)
    for i in range(lookback, len(check_window)):
        segment = check_window.iloc[i - lookback: i]
        prev_high = segment["close"].max()
        curr_close = check_window.iloc[i]["close"]
        date = check_window.iloc[i]["date"]
        if pd.isna(prev_high) or pd.isna(curr_close):
            continue
        if curr_close > prev_high:
            signals.append({
                "type": "突破新高",
                "direction": "bullish",
                "date": date,
                "value": round(curr_close, 2),
                "description": f"收盘价 {curr_close} 突破近 {lookback} 日最高 {prev_high:.2f}",
            })
    return signals


# ---------------------------------------------------------------------------
# Main entry: run all detectors
# ---------------------------------------------------------------------------

def detect_all_signals(df: pd.DataFrame) -> list:
    """
    Run all signal detectors and return a combined, deduplicated list.
    Input df must already have indicators added (add_all_indicators).
    """
    if df.empty:
        return []

    all_signals = []
    all_signals += detect_ma_crossover(df, fast=5, slow=20)
    all_signals += detect_ma_crossover(df, fast=10, slow=60)
    all_signals += detect_rsi_signals(df)
    all_signals += detect_macd_crossover(df)
    all_signals += detect_volume_spike(df)
    all_signals += detect_breakout(df)

    # Sort by date descending so newest signals appear first
    all_signals.sort(key=lambda s: s["date"], reverse=True)
    return all_signals


def signals_to_dataframe(signals: list) -> pd.DataFrame:
    """Convert signal list to a display-ready DataFrame."""
    if not signals:
        return pd.DataFrame(columns=["日期", "信号类型", "方向", "数值", "描述"])
    rows = []
    for s in signals:
        direction_label = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}.get(
            s.get("direction", "neutral"), "中性"
        )
        rows.append({
            "日期": s["date"].strftime("%Y-%m-%d") if hasattr(s["date"], "strftime") else str(s["date"]),
            "信号类型": s["type"],
            "方向": direction_label,
            "数值": s["value"],
            "描述": s["description"],
        })
    return pd.DataFrame(rows)
