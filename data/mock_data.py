# data/mock_data.py — Synthetic fallback data for offline / dev mode.
#
# All functions mirror the return shape of their fetcher.py counterparts so
# pages can consume mock data without any special-casing.
# Data is generated with a seeded random walk so charts look realistic.

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _trading_days(days: int) -> pd.DatetimeIndex:
    """Return the last `days` business days ending today."""
    end = datetime.today()
    return pd.bdate_range(end=end, periods=days)


def _random_walk_ohlcv(
    seed: int,
    days: int,
    start_price: float,
    volatility: float = 0.015,
    trend: float = 0.0001,
    base_volume: float = 5e7,
) -> pd.DataFrame:
    """
    Generate realistic-looking OHLCV data using a seeded random walk.
    Suitable for stocks (start_price ~10-200) and indices (start_price ~3000+).
    """
    rng = np.random.default_rng(seed)
    dates = _trading_days(days)
    n = len(dates)

    # Close prices via log-normal random walk
    log_returns = rng.normal(trend, volatility, n)
    closes = start_price * np.exp(np.cumsum(log_returns))

    # Open = previous close ± small gap
    opens = np.empty(n)
    opens[0] = start_price
    opens[1:] = closes[:-1] * (1 + rng.normal(0, 0.003, n - 1))

    # High/Low bracket the open–close range
    hi_extra = abs(rng.normal(0, volatility * 0.6, n))
    lo_extra = abs(rng.normal(0, volatility * 0.6, n))
    highs = np.maximum(opens, closes) * (1 + hi_extra)
    lows  = np.minimum(opens, closes) * (1 - lo_extra)

    # Volume: log-normal around base_volume, with occasional spikes
    volumes = rng.lognormal(np.log(base_volume), 0.5, n).astype(np.int64)
    spike_mask = rng.random(n) > 0.92
    volumes[spike_mask] = (volumes[spike_mask] * rng.uniform(2, 4, spike_mask.sum())).astype(np.int64)

    amount   = volumes * closes
    change_pct = pd.Series(closes).pct_change().fillna(0).values * 100
    turnover   = rng.uniform(0.3, 4.0, n).round(2)

    df = pd.DataFrame({
        "date":       dates,
        "open":       np.round(opens, 2),
        "close":      np.round(closes, 2),
        "high":       np.round(highs, 2),
        "low":        np.round(lows, 2),
        "volume":     volumes,
        "amount":     np.round(amount, 0),
        "change_pct": np.round(change_pct, 2),
        "turnover":   turnover,
    })
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Index mock data
# ---------------------------------------------------------------------------

# Fixed seeds per index so the generated data is stable across app restarts
_INDEX_SEEDS = {
    "000001": (1001, 3200.0, 0.010),   # 上证指数 — lower vol
    "399001": (1002, 10800.0, 0.012),  # 深证成指
    "000300": (1003, 3900.0, 0.011),   # 沪深300
    "399006": (1004, 2200.0, 0.018),   # 创业板指 — higher vol
}

def mock_index_spot() -> pd.DataFrame:
    """Fake real-time snapshot for the four major indices."""
    rows = []
    for name, code in [("上证指数","000001"),("深证成指","399001"),
                       ("沪深300","000300"),("创业板指","399006")]:
        seed, start, vol = _INDEX_SEEDS[code]
        df = _random_walk_ohlcv(seed, 3, start, volatility=vol)
        last = df.iloc[-1]
        prev = df.iloc[-2]
        change_pct = round((last["close"] - prev["close"]) / prev["close"] * 100, 2)
        rows.append({
            "code": code, "name": name,
            "price": last["close"],
            "change_pct": change_pct,
            "change_amt": round(last["close"] - prev["close"], 2),
            "volume": last["volume"],
            "amount": last["amount"],
            "amplitude": round((last["high"] - last["low"]) / prev["close"] * 100, 2),
            "high": last["high"], "low": last["low"],
            "open": last["open"], "prev_close": prev["close"],
            "volume_ratio": round(1.0 + np.random.default_rng(seed + 99).uniform(-0.3, 0.8), 2),
        })
    return pd.DataFrame(rows)


def mock_index_history(symbol: str, days: int = 180) -> pd.DataFrame:
    """Fake daily OHLCV for an index."""
    seed, start, vol = _INDEX_SEEDS.get(symbol, (9999, 3000.0, 0.012))
    return _random_walk_ohlcv(seed, days, start, volatility=vol, base_volume=int(3e10))


# ---------------------------------------------------------------------------
# Stock mock data
# ---------------------------------------------------------------------------

def _stock_seed(symbol: str) -> int:
    """Derive a stable seed from the stock code string."""
    return sum(ord(c) * (i + 1) for i, c in enumerate(symbol)) % 99999


def mock_stock_history(symbol: str, days: int = 180) -> pd.DataFrame:
    """Fake daily OHLCV for a stock (前复权)."""
    seed = _stock_seed(symbol)
    rng = np.random.default_rng(seed)
    start_price = round(rng.uniform(5.0, 120.0), 2)
    vol         = rng.uniform(0.012, 0.025)
    return _random_walk_ohlcv(seed, days, start_price, volatility=vol, base_volume=2e7)


def mock_stock_info(symbol: str) -> dict:
    """Fake basic stock info."""
    seed = _stock_seed(symbol)
    rng = np.random.default_rng(seed)
    industries = ["银行", "白酒", "新能源", "医药生物", "半导体", "房地产", "消费电子", "化工"]
    markets    = ["上海主板", "深圳主板", "创业板", "科创板"]
    return {
        "股票代码": symbol,
        "股票简称": f"模拟股票{symbol[-3:]}",
        "所属行业": rng.choice(industries),
        "上市市场": rng.choice(markets),
        "总市值":   f"{rng.integers(10, 5000)}亿",
        "流通市值": f"{rng.integers(8, 3000)}亿",
        "市盈率(动态)": round(rng.uniform(8, 80), 1),
        "市净率":   round(rng.uniform(0.8, 8.0), 2),
        "ROE":      f"{round(rng.uniform(3, 25), 1)}%",
        "数据说明": "【模拟数据 — 仅供开发调试，非真实行情】",
    }


def mock_stock_realtime_quote(symbol: str) -> dict:
    """Fake real-time quote for a stock."""
    df = mock_stock_history(symbol, days=3)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    change_pct = round((last["close"] - prev["close"]) / prev["close"] * 100, 2)
    seed = _stock_seed(symbol)
    vr = round(np.random.default_rng(seed + 7).uniform(0.5, 3.5), 2)
    return {
        "code": symbol,
        "name": f"模拟{symbol[-3:]}",
        "price": last["close"],
        "change_pct": change_pct,
        "change_amt": round(last["close"] - prev["close"], 2),
        "volume": int(last["volume"]),
        "amount": float(last["amount"]),
        "amplitude": round((last["high"] - last["low"]) / prev["close"] * 100, 2),
        "high": last["high"], "low": last["low"],
        "open": last["open"], "prev_close": prev["close"],
        "volume_ratio": vr,
        "turnover": last["turnover"],
        "pe_ratio": round(np.random.default_rng(seed + 3).uniform(8, 60), 1),
        "market_cap": None,
    }


def mock_search_stock(query: str) -> pd.DataFrame:
    """Return a small fake search result list."""
    samples = [
        ("000001", "平安银行"), ("600519", "贵州茅台"), ("000858", "五粮液"),
        ("300750", "宁德时代"), ("601318", "中国平安"), ("000333", "美的集团"),
        ("600036", "招商银行"), ("002594", "比亚迪"),   ("688981", "中芯国际"),
        ("600900", "长江电力"),
    ]
    q = query.strip().lower()
    results = [(c, n) for c, n in samples if q in c or q in n]
    if not results:
        results = samples[:5]  # return some samples so the UI isn't empty
    return pd.DataFrame(results, columns=["code", "name"])


# ---------------------------------------------------------------------------
# Sector mock data
# ---------------------------------------------------------------------------

_SECTORS = [
    "银行", "保险", "证券", "白酒", "食品饮料", "医药生物", "医疗器械",
    "新能源", "光伏设备", "储能", "半导体", "消费电子", "软件开发",
    "房地产", "建筑材料", "钢铁", "化工", "有色金属", "煤炭", "石油石化",
    "汽车", "电力设备", "军工", "农业", "航空",
]

def mock_sector_performance() -> pd.DataFrame:
    """Fake sector performance table sorted by change_pct descending."""
    rng = np.random.default_rng(42)
    change_pcts = rng.normal(0, 1.5, len(_SECTORS)).round(2)
    df = pd.DataFrame({
        "name":       _SECTORS,
        "change_pct": change_pcts,
        "amount":     rng.integers(50, 2000, len(_SECTORS)) * 1e8,
        "leader":     [f"模拟龙头{i:02d}" for i in range(len(_SECTORS))],
    })
    return df.sort_values("change_pct", ascending=False).reset_index(drop=True)


def mock_batch_realtime(symbols: list) -> pd.DataFrame:
    """Fake batch quotes indexed by code."""
    rows = []
    for sym in symbols:
        q = mock_stock_realtime_quote(sym)
        rows.append(q)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("code")
    return df
