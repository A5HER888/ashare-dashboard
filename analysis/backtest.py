# analysis/backtest.py — Simple event-driven backtesting framework.
# Strategies generate buy/sell signals; the engine simulates holding one position at a time.
# No leverage, no short selling. All positions are full-capital (100% in or 100% out).

import pandas as pd
import numpy as np
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RSI_OVERSOLD, RSI_OVERBOUGHT


# ---------------------------------------------------------------------------
# Core backtest engine
# ---------------------------------------------------------------------------

def run_backtest(df: pd.DataFrame, signals: pd.Series) -> pd.DataFrame:
    """
    Given a signal series (1 = buy, -1 = sell, 0 = hold), simulate a long-only strategy.
    Returns a DataFrame with columns: date, close, position, daily_return, strategy_return, cumulative.

    Rules:
    - Buy at next day's open after a buy signal.
    - Sell at next day's open after a sell signal.
    - No simultaneous positions. No short selling.
    """
    df = df.copy().reset_index(drop=True)
    df["signal"] = signals.values if hasattr(signals, "values") else signals

    position = 0          # 0 = out of market, 1 = holding
    entry_price = 0.0
    trades = []
    position_series = []

    for i in range(len(df)):
        row = df.iloc[i]

        # Execute yesterday's signal at today's open
        if i > 0:
            prev_signal = df.iloc[i - 1]["signal"]
            if prev_signal == 1 and position == 0:
                position = 1
                entry_price = row["open"] if not pd.isna(row["open"]) else row["close"]
            elif prev_signal == -1 and position == 1:
                exit_price = row["open"] if not pd.isna(row["open"]) else row["close"]
                trades.append({
                    "entry": entry_price,
                    "exit": exit_price,
                    "return": (exit_price - entry_price) / entry_price,
                    "date_exit": row["date"],
                })
                position = 0
                entry_price = 0.0

        position_series.append(position)

    df["position"] = position_series

    # Daily returns
    df["close_return"] = df["close"].pct_change()
    # Strategy earns the daily return only when in position (shifted: buy at open means we earn from open-to-close of entry day onwards)
    df["strategy_return"] = df["close_return"] * df["position"].shift(1).fillna(0)

    # Cumulative returns (start at 1.0)
    df["cumulative_strategy"] = (1 + df["strategy_return"]).cumprod()
    df["cumulative_bah"]       = (1 + df["close_return"]).cumprod()   # buy-and-hold benchmark

    return df, trades


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------

def calculate_metrics(df: pd.DataFrame, trades: list) -> dict:
    """
    Compute key backtest metrics from the result DataFrame and trade list.
    """
    strat_returns = df["strategy_return"].dropna()
    cum_strat = df["cumulative_strategy"].dropna()

    total_return = cum_strat.iloc[-1] - 1 if len(cum_strat) > 0 else 0
    bah_return   = df["cumulative_bah"].iloc[-1] - 1 if len(df) > 0 else 0

    # Max drawdown
    rolling_max = cum_strat.cummax()
    drawdown = (cum_strat - rolling_max) / rolling_max
    max_drawdown = drawdown.min()

    # Win rate
    if trades:
        wins = sum(1 for t in trades if t["return"] > 0)
        win_rate = wins / len(trades)
    else:
        win_rate = 0.0

    # Annualised Sharpe (rough — assumes 252 trading days)
    if strat_returns.std() > 0:
        sharpe = (strat_returns.mean() / strat_returns.std()) * np.sqrt(252)
    else:
        sharpe = 0.0

    return {
        "总收益率":     f"{total_return:.2%}",
        "买入持有收益": f"{bah_return:.2%}",
        "最大回撤":     f"{max_drawdown:.2%}",
        "胜率":         f"{win_rate:.2%}",
        "交易次数":     len(trades),
        "夏普比率":     f"{sharpe:.2f}",
    }


# ---------------------------------------------------------------------------
# Strategy: MA Crossover
# ---------------------------------------------------------------------------

def strategy_ma_crossover(df: pd.DataFrame, fast: int = 5, slow: int = 20) -> pd.Series:
    """
    Buy when fast MA crosses above slow MA.
    Sell when fast MA crosses below slow MA.
    Returns signal Series (1 = buy, -1 = sell, 0 = hold).
    """
    fast_ma = df["close"].rolling(fast, min_periods=1).mean()
    slow_ma  = df["close"].rolling(slow, min_periods=1).mean()

    signal = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        if fast_ma.iloc[i - 1] <= slow_ma.iloc[i - 1] and fast_ma.iloc[i] > slow_ma.iloc[i]:
            signal.iloc[i] = 1   # golden cross → buy
        elif fast_ma.iloc[i - 1] >= slow_ma.iloc[i - 1] and fast_ma.iloc[i] < slow_ma.iloc[i]:
            signal.iloc[i] = -1  # death cross → sell
    return signal


# ---------------------------------------------------------------------------
# Strategy: RSI
# ---------------------------------------------------------------------------

def strategy_rsi(
    df: pd.DataFrame,
    period: int = 14,
    oversold: int = RSI_OVERSOLD,
    overbought: int = RSI_OVERBOUGHT
) -> pd.Series:
    """
    Buy when RSI crosses above oversold level.
    Sell when RSI crosses above overbought level.
    """
    from analysis.indicators import add_rsi
    df = add_rsi(df.copy(), period=period)
    rsi = df["rsi"]

    signal = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        r_prev, r_curr = rsi.iloc[i - 1], rsi.iloc[i]
        if pd.isna(r_prev) or pd.isna(r_curr):
            continue
        if r_prev < oversold and r_curr >= oversold:
            signal.iloc[i] = 1   # exiting oversold → buy
        elif r_prev < overbought and r_curr >= overbought:
            signal.iloc[i] = -1  # entering overbought → sell
    return signal


# ---------------------------------------------------------------------------
# Strategy: Volume Ratio Breakout
# ---------------------------------------------------------------------------

def strategy_volume_ratio(
    df: pd.DataFrame,
    vr_threshold: float = 2.0,
    hold_days: int = 5
) -> pd.Series:
    """
    Buy when volume ratio exceeds threshold AND price closes up on that day.
    Sell after holding for hold_days trading days.
    """
    from analysis.indicators import add_volume_ratio
    df = add_volume_ratio(df.copy())

    signal = pd.Series(0, index=df.index)
    sell_on = -1  # index to sell at

    for i in range(1, len(df)):
        if i == sell_on:
            signal.iloc[i] = -1
            sell_on = -1
            continue

        vr = df["volume_ratio"].iloc[i]
        price_up = df["close"].iloc[i] > df["close"].iloc[i - 1]

        if pd.notna(vr) and vr >= vr_threshold and price_up and sell_on == -1:
            signal.iloc[i] = 1
            sell_on = min(i + hold_days, len(df) - 1)

    return signal


# ---------------------------------------------------------------------------
# Convenience: run a named strategy
# ---------------------------------------------------------------------------

STRATEGIES = {
    "MA均线金叉策略": strategy_ma_crossover,
    "RSI超卖反弹策略": strategy_rsi,
    "量比突破策略": strategy_volume_ratio,
}

def backtest_strategy(df: pd.DataFrame, strategy_name: str, **kwargs) -> tuple:
    """
    Run a named strategy. Returns (result_df, trades, metrics).
    kwargs are forwarded to the strategy function.
    """
    if strategy_name not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    strategy_fn = STRATEGIES[strategy_name]
    signals = strategy_fn(df, **kwargs)
    result_df, trades = run_backtest(df, signals)
    metrics = calculate_metrics(result_df, trades)
    return result_df, trades, metrics
