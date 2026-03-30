# data/fetcher.py — All market data fetching lives here.
# Pages never import akshare or yfinance directly; they use this module only.
#
# Data source routing (controlled by config.DATA_SOURCE):
#   "yfinance"  → Yahoo Finance via the yfinance library.
#                 Reliable from the US. A-shares use .SS / .SZ suffixes.
#   "akshare"   → Scrapes Chinese financial sites. Use inside China or on VPN.
#
# Resilience layers (in order):
#   1. DEV_MODE = True  → synthetic mock data, no network calls at all.
#   2. Live fetch       → retried up to RETRY_COUNT times with back-off.
#   3. All retries fail → friendly Chinese warning + mock data fallback.

import time
import logging
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timedelta
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    MAJOR_INDICES, CACHE_TTL, DEFAULT_HISTORY_DAYS,
    DEV_MODE, DATA_SOURCE, RETRY_COUNT, RETRY_DELAY,
)
import data.mock_data as mock

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Yahoo Finance ticker helpers
# ---------------------------------------------------------------------------

# Shanghai prefixes: 600xxx 601xxx 603xxx 605xxx 688xxx (STAR) 900xxx 510xxx 515xxx
_SHANGHAI_STARTS = ("60", "68", "90", "51", "56")

def _yfcode(symbol: str) -> str:
    """
    Convert a 6-digit A-share code to its Yahoo Finance ticker.
      600519 → 600519.SS  (Shanghai)
      000001 → 000001.SZ  (Shenzhen)
    """
    s = symbol.strip().zfill(6)
    if s[:2] in _SHANGHAI_STARTS:
        return f"{s}.SS"
    return f"{s}.SZ"

# Index symbol → Yahoo Finance ticker
_INDEX_YF = {
    "000001": "000001.SS",   # 上证指数
    "399001": "399001.SZ",   # 深证成指
    "000300": "000300.SS",   # 沪深300
    "399006": "399006.SZ",   # 创业板指
}

# Compact built-in stock list — used for name-based search when yfinance
# is the source (yfinance has no search-by-name API).
# Add more entries here as needed; code is 6-digit string.
_BUILTIN_STOCK_LIST = {
    "000001": "平安银行",   "000002": "万科A",      "000333": "美的集团",
    "000651": "格力电器",   "000725": "京东方A",     "000858": "五粮液",
    "000895": "双汇发展",   "001979": "招商蛇口",    "002001": "新和成",
    "002027": "分众传媒",   "002230": "科大讯飞",    "002304": "洋河股份",
    "002415": "海康威视",   "002594": "比亚迪",      "300015": "爱尔眼科",
    "300059": "东方财富",   "300122": "智飞生物",    "300274": "阳光电源",
    "300750": "宁德时代",   "300760": "迈瑞医疗",    "600000": "浦发银行",
    "600009": "上海机场",   "600016": "民生银行",    "600019": "宝钢股份",
    "600028": "中国石化",   "600029": "南方航空",    "600030": "中信证券",
    "600031": "三一重工",   "600036": "招商银行",    "600048": "保利发展",
    "600050": "中国联通",   "600104": "上汽集团",    "600111": "北方稀土",
    "600276": "恒瑞医药",   "600309": "万华化学",    "600346": "恒力石化",
    "600406": "国电南瑞",   "600436": "片仔癀",      "600519": "贵州茅台",
    "600585": "海螺水泥",   "600690": "海尔智家",    "600703": "三安光电",
    "600745": "闻泰科技",   "600809": "山西汾酒",    "600887": "伊利股份",
    "600900": "长江电力",   "600905": "三峰环境",    "601012": "隆基绿能",
    "601066": "中信建投",   "601088": "中国神华",    "601166": "兴业银行",
    "601216": "君正集团",   "601288": "农业银行",    "601318": "中国平安",
    "601336": "新华保险",   "601398": "工商银行",    "601601": "中国太保",
    "601668": "中国建筑",   "601688": "华泰证券",    "601728": "中国电信",
    "601857": "中国石油",   "601888": "中国中免",    "601899": "紫金矿业",
    "601919": "中远海控",   "601939": "建设银行",    "601988": "中国银行",
    "603259": "药明康德",   "603288": "海天味业",    "603501": "韦尔股份",
    "603986": "兆易创新",   "688041": "海光信息",    "688111": "金山办公",
    "688599": "天合光能",   "688981": "中芯国际",
}


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

def _friendly_error(exc: Exception) -> str:
    msg = str(exc)
    name = type(exc).__name__
    if "RemoteDisconnected" in msg or "RemoteDisconnected" in name:
        return "远端服务器主动断开连接"
    if "ConnectionError" in name or "ConnectionAbortedError" in name:
        return "网络连接失败，请检查网络是否正常"
    if "Timeout" in name or "timeout" in msg.lower():
        return "请求超时，服务器响应过慢"
    if "HTTPError" in name:
        return f"HTTP 错误：{msg[:80]}"
    if "JSONDecodeError" in name:
        return "数据格式解析失败"
    if "SSLError" in name:
        return "SSL 证书验证失败"
    return f"未知错误：{msg[:100]}"


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------

def _with_retry(fn, *args, label: str = "请求", **kwargs):
    """
    Call fn(*args, **kwargs) up to RETRY_COUNT times.
    Waits RETRY_DELAY * 2^attempt seconds between attempts (capped at 10s).
    Returns (result, None) on success, (None, error_str) on final failure.
    """
    last_exc = None
    for attempt in range(RETRY_COUNT):
        try:
            return fn(*args, **kwargs), None
        except Exception as exc:
            last_exc = exc
            wait = min(RETRY_DELAY * (2 ** attempt), 10.0)
            logger.warning(
                "【%s】第 %d/%d 次失败：%s — %.0fs 后重试",
                label, attempt + 1, RETRY_COUNT, _friendly_error(exc), wait,
            )
            if attempt < RETRY_COUNT - 1:
                time.sleep(wait)
    return None, _friendly_error(last_exc)


# ---------------------------------------------------------------------------
# Column normalisation (shared by akshare and yfinance paths)
# ---------------------------------------------------------------------------

def _today() -> str:
    return datetime.today().strftime("%Y%m%d")

def _start_date(days: int) -> str:
    return (datetime.today() - timedelta(days=days)).strftime("%Y%m%d")

_AK_COL_MAP = {
    "日期": "date", "开盘": "open", "收盘": "close",
    "最高": "high", "最低": "low", "成交量": "volume",
    "成交额": "amount", "振幅": "amplitude",
    "涨跌幅": "change_pct", "涨跌额": "change_amt", "换手率": "turnover",
}

def _normalise_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=_AK_COL_MAP)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
    for col in ["open", "close", "high", "low", "volume", "change_pct", "turnover"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# yfinance fetch helpers
# ---------------------------------------------------------------------------

def _yf_history(yf_ticker_str: str, days: int, shares: float = None) -> pd.DataFrame:
    """
    Download OHLCV history from Yahoo Finance and normalise to our schema.
    `shares` (float) is used to compute turnover rate if provided.
    """
    import yfinance as yf

    start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    end   = (datetime.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    ticker = yf.Ticker(yf_ticker_str)
    # auto_adjust=True ≈ 前复权 (accounts for splits & dividends)
    raw = ticker.history(start=start, end=end, auto_adjust=True)

    if raw.empty:
        return pd.DataFrame()

    df = raw.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["date", "open", "high", "low", "close", "volume"]
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df["change_pct"] = df["close"].pct_change().mul(100).round(2)
    df["amount"]     = (df["volume"] * df["close"]).round(0)

    if shares and shares > 0:
        df["turnover"] = (df["volume"] / shares * 100).round(2)
    else:
        df["turnover"] = np.nan

    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].round(3)

    return df.dropna(subset=["close"]).reset_index(drop=True)


def _yf_fast_info(yf_ticker_str: str) -> dict:
    """Return fast_info attributes as a plain dict; empty dict on failure."""
    import yfinance as yf
    try:
        fi = yf.Ticker(yf_ticker_str).fast_info
        return {
            "price":       fi.last_price,
            "open":        fi.open,
            "high":        fi.day_high,
            "low":         fi.day_low,
            "prev_close":  fi.previous_close,
            "volume":      fi.last_volume,
            "market_cap":  getattr(fi, "market_cap", None),
            "shares":      getattr(fi, "shares", None),
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Public API — Index data
# ---------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL)
def get_index_spot() -> pd.DataFrame:
    """
    Real-time snapshot for all major indices.
    Columns: code, name, price, change_pct, change_amt, volume,
             high, low, open, prev_close
    """
    if DEV_MODE:
        _toast_dev("指数实时行情")
        return mock.mock_index_spot()

    if DATA_SOURCE == "yfinance":
        return _get_index_spot_yf()
    else:
        return _get_index_spot_ak()


def _get_index_spot_yf() -> pd.DataFrame:
    import yfinance as yf
    rows = []
    for name, symbol in MAJOR_INDICES.items():
        yf_code = _INDEX_YF.get(symbol, _yfcode(symbol))
        result, err = _with_retry(_yf_fast_info, yf_code, label=f"指数行情({name})")
        if err or not result:
            st.warning(f"⚠️ {name} 行情获取失败，使用模拟数据。原因：{err}")
            mock_row = mock.mock_index_spot()
            mock_row = mock_row[mock_row["code"] == symbol]
            rows.append(mock_row.iloc[0].to_dict() if not mock_row.empty else {})
            continue
        fi = result
        price      = fi.get("price") or 0.0
        prev_close = fi.get("prev_close") or price
        change_amt = round(price - prev_close, 2) if prev_close else 0.0
        change_pct = round(change_amt / prev_close * 100, 2) if prev_close else 0.0
        rows.append({
            "code":       symbol,
            "name":       name,
            "price":      round(price, 2),
            "change_pct": change_pct,
            "change_amt": change_amt,
            "volume":     fi.get("volume"),
            "high":       round(fi.get("high") or price, 2),
            "low":        round(fi.get("low") or price, 2),
            "open":       round(fi.get("open") or price, 2),
            "prev_close": round(prev_close, 2),
        })
    return pd.DataFrame(rows)


def _get_index_spot_ak() -> pd.DataFrame:
    import akshare as ak
    result, err = _with_retry(ak.stock_zh_index_spot_em, label="指数实时行情")
    if err:
        st.warning(f"⚠️ 指数行情获取失败，已切换为模拟数据。原因：{err}")
        return mock.mock_index_spot()
    try:
        df = result
        # Map by Chinese column name — safe across akshare versions that add/remove columns
        col_map = {
            "代码": "code",   "名称": "name",     "最新价": "price",
            "涨跌幅": "change_pct", "涨跌额": "change_amt",
            "成交量": "volume", "成交额": "amount", "振幅": "amplitude",
            "最高": "high",   "最低": "low",      "今开": "open",
            "昨收": "prev_close", "量比": "volume_ratio",
        }
        df = df.rename(columns=col_map)
        target = set(MAJOR_INDICES.values())
        df = df[df["code"].isin(target)].copy()
        df["change_pct"] = pd.to_numeric(df["change_pct"], errors="coerce")
        df["price"]      = pd.to_numeric(df["price"],      errors="coerce")
        return df.reset_index(drop=True)
    except Exception as exc:
        st.warning(f"⚠️ 指数数据解析失败，已切换为模拟数据。原因：{_friendly_error(exc)}")
        return mock.mock_index_spot()


@st.cache_data(ttl=CACHE_TTL)
def get_index_history(symbol: str, days: int = DEFAULT_HISTORY_DAYS) -> pd.DataFrame:
    """Daily OHLCV history for an index (e.g. symbol='000001')."""
    if DEV_MODE:
        _toast_dev(f"指数历史 {symbol}")
        return mock.mock_index_history(symbol, days)

    if DATA_SOURCE == "yfinance":
        yf_code = _INDEX_YF.get(symbol, _yfcode(symbol))
        result, err = _with_retry(_yf_history, yf_code, days, label=f"指数历史({symbol})")
        if err or (result is not None and result.empty):
            st.warning(f"⚠️ 指数 {symbol} 历史数据获取失败，已切换为模拟数据。原因：{err or '数据为空'}")
            return mock.mock_index_history(symbol, days)
        return result if result is not None else mock.mock_index_history(symbol, days)
    else:
        return _get_index_history_ak(symbol, days)


def _get_index_history_ak(symbol: str, days: int) -> pd.DataFrame:
    import akshare as ak
    result, err = _with_retry(
        ak.index_zh_a_hist,
        symbol=symbol, period="daily",
        start_date=_start_date(days), end_date=_today(),
        label=f"指数历史({symbol})",
    )
    if err:
        st.warning(f"⚠️ 指数 {symbol} 历史数据获取失败，已切换为模拟数据。原因：{err}")
        return mock.mock_index_history(symbol, days)
    try:
        return _normalise_ohlcv(result)
    except Exception as exc:
        st.warning(f"⚠️ 指数历史解析失败。原因：{_friendly_error(exc)}")
        return mock.mock_index_history(symbol, days)


# ---------------------------------------------------------------------------
# Public API — Individual stock data
# ---------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL)
def get_stock_history(symbol: str, days: int = DEFAULT_HISTORY_DAYS) -> pd.DataFrame:
    """
    Daily OHLCV for a stock, forward-adjusted (前复权).
    symbol: 6-digit code, e.g. '000001', '600519'
    """
    if DEV_MODE:
        _toast_dev(f"个股历史 {symbol}")
        return mock.mock_stock_history(symbol, days)

    if DATA_SOURCE == "yfinance":
        yf_code = _yfcode(symbol)
        # Pre-fetch shares outstanding so we can compute turnover
        fi = _yf_fast_info(yf_code)
        shares = fi.get("shares")
        result, err = _with_retry(_yf_history, yf_code, days, shares, label=f"个股历史({symbol})")
        if err or result is None or result.empty:
            st.warning(f"⚠️ 股票 {symbol} 历史数据获取失败，已切换为模拟数据。原因：{err or '数据为空'}")
            return mock.mock_stock_history(symbol, days)
        return result
    else:
        return _get_stock_history_ak(symbol, days)


def _get_stock_history_ak(symbol: str, days: int) -> pd.DataFrame:
    import akshare as ak
    result, err = _with_retry(
        ak.stock_zh_a_hist,
        symbol=symbol, period="daily",
        start_date=_start_date(days), end_date=_today(),
        adjust="qfq",
        label=f"个股历史({symbol})",
    )
    if err:
        st.warning(f"⚠️ 股票 {symbol} 历史数据获取失败，已切换为模拟数据。原因：{err}")
        return mock.mock_stock_history(symbol, days)
    try:
        return _normalise_ohlcv(result)
    except Exception as exc:
        st.warning(f"⚠️ 历史数据解析失败。原因：{_friendly_error(exc)}")
        return mock.mock_stock_history(symbol, days)


@st.cache_data(ttl=CACHE_TTL)
def get_stock_info(symbol: str) -> dict:
    """Basic stock info: name, sector, PE, market cap, etc."""
    if DEV_MODE:
        return mock.mock_stock_info(symbol)

    if DATA_SOURCE == "yfinance":
        return _get_stock_info_yf(symbol)
    else:
        return _get_stock_info_ak(symbol)


def _get_stock_info_yf(symbol: str) -> dict:
    import yfinance as yf
    def _fetch():
        return yf.Ticker(_yfcode(symbol)).info

    result, err = _with_retry(_fetch, label=f"个股信息({symbol})")
    if err or not result:
        return mock.mock_stock_info(symbol)
    # Map Yahoo Finance keys to display-friendly Chinese labels
    return {
        "股票代码":    symbol,
        "股票简称":    result.get("shortName") or result.get("longName") or symbol,
        "所属行业":    result.get("industry") or result.get("sector") or "—",
        "上市市场":    result.get("exchange") or "—",
        "总市值":      _fmt_cap(result.get("marketCap")),
        "市盈率(动态)": result.get("trailingPE") or result.get("forwardPE") or "—",
        "市净率":      result.get("priceToBook") or "—",
        "ROE":         _fmt_pct(result.get("returnOnEquity")),
        "52周最高":    result.get("fiftyTwoWeekHigh") or "—",
        "52周最低":    result.get("fiftyTwoWeekLow") or "—",
        "数据来源":    "Yahoo Finance",
    }


def _get_stock_info_ak(symbol: str) -> dict:
    import akshare as ak
    result, err = _with_retry(
        ak.stock_individual_info_em, symbol=symbol, label=f"个股信息({symbol})"
    )
    if err or result is None:
        return mock.mock_stock_info(symbol)
    try:
        return dict(zip(result.iloc[:, 0], result.iloc[:, 1]))
    except Exception:
        return mock.mock_stock_info(symbol)


@st.cache_data(ttl=CACHE_TTL)
def get_stock_realtime_quote(symbol: str) -> dict:
    """Real-time (or delayed) quote for a single stock."""
    if DEV_MODE:
        return mock.mock_stock_realtime_quote(symbol)

    if DATA_SOURCE == "yfinance":
        yf_code = _yfcode(symbol)
        result, err = _with_retry(_yf_fast_info, yf_code, label=f"实时行情({symbol})")
        if err or not result:
            return mock.mock_stock_realtime_quote(symbol)
        fi = result
        price      = fi.get("price") or 0.0
        prev_close = fi.get("prev_close") or price
        change_amt = round(price - prev_close, 3) if prev_close else 0.0
        change_pct = round(change_amt / prev_close * 100, 2) if prev_close else 0.0
        shares     = fi.get("shares")
        volume     = fi.get("volume") or 0
        turnover   = round(volume / shares * 100, 2) if (shares and shares > 0) else None
        return {
            "code":         symbol,
            "name":         _BUILTIN_STOCK_LIST.get(symbol, symbol),
            "price":        round(price, 3),
            "change_pct":   change_pct,
            "change_amt":   change_amt,
            "volume":       volume,
            "amount":       round(volume * price, 0) if volume else None,
            "high":         round(fi.get("high") or price, 3),
            "low":          round(fi.get("low") or price, 3),
            "open":         round(fi.get("open") or price, 3),
            "prev_close":   round(prev_close, 3),
            "volume_ratio": None,   # calculated by indicators.py from history
            "turnover":     turnover,
            "pe_ratio":     None,
            "market_cap":   fi.get("market_cap"),
        }
    else:
        return _get_realtime_ak(symbol)


def _get_realtime_ak(symbol: str) -> dict:
    """
    Derive real-time quote from the last 2 days of history.
    Avoids downloading all 5000+ stocks via stock_zh_a_spot_em (very slow).
    """
    import akshare as ak
    result, err = _with_retry(
        ak.stock_zh_a_hist,
        symbol=symbol, period="daily",
        start_date=_start_date(10), end_date=_today(),
        adjust="",          # unadjusted for most accurate latest price
        label=f"实时行情({symbol})",
    )
    if err or result is None or result.empty:
        return mock.mock_stock_realtime_quote(symbol)
    try:
        df = _normalise_ohlcv(result)
        if len(df) < 1:
            return mock.mock_stock_realtime_quote(symbol)
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last
        price      = float(last["close"])
        prev_close = float(prev["close"])
        return {
            "code":         symbol,
            "name":         _BUILTIN_STOCK_LIST.get(symbol, symbol),
            "price":        price,
            "change_pct":   float(last.get("change_pct") or 0),
            "change_amt":   round(price - prev_close, 3),
            "volume":       int(last["volume"]) if pd.notna(last["volume"]) else None,
            "amount":       float(last.get("amount") or 0),
            "high":         float(last["high"]),
            "low":          float(last["low"]),
            "open":         float(last["open"]),
            "prev_close":   prev_close,
            "volume_ratio": None,   # calculated by indicators.py
            "turnover":     float(last["turnover"]) if pd.notna(last.get("turnover")) else None,
            "pe_ratio":     None,
            "market_cap":   None,
        }
    except Exception:
        return mock.mock_stock_realtime_quote(symbol)


@st.cache_data(ttl=CACHE_TTL)
def search_stock(query: str) -> pd.DataFrame:
    """
    Search stocks by 6-digit code or name fragment.
    yfinance source: searches the built-in stock list (offline, instant).
    akshare source:  queries live spot data.
    """
    if DEV_MODE:
        return mock.mock_search_stock(query)

    q = query.strip()
    if DATA_SOURCE == "yfinance":
        # Search the built-in list — no network needed
        rows = [
            (code, name)
            for code, name in _BUILTIN_STOCK_LIST.items()
            if q in code or q in name
        ]
        if not rows:
            # Nothing found — show a hint rather than empty silence
            st.info(f"未在内置股票列表中找到「{q}」。请直接输入6位股票代码（如 600519）。")
            return pd.DataFrame(columns=["code", "name"])
        return pd.DataFrame(rows, columns=["code", "name"]).head(20)
    else:
        return _search_ak(query)


def _search_ak(query: str) -> pd.DataFrame:
    q = query.strip()

    # If query is a pure 6-digit code, return immediately — no network call needed.
    # Fetching all 5000+ stocks just to match one code is extremely slow.
    if q.isdigit() and len(q) == 6:
        name = _BUILTIN_STOCK_LIST.get(q, q)
        return pd.DataFrame([{"code": q, "name": name}])

    # Name search — must fetch full market list (slow on akshare from overseas)
    import akshare as ak
    result, err = _with_retry(ak.stock_zh_a_spot_em, label="股票搜索")
    if err or result is None:
        st.warning(f"⚠️ 股票搜索失败，显示内置列表。原因：{err}")
        return mock.mock_search_stock(query)
    try:
        df = result[["代码", "名称"]].rename(columns={"代码": "code", "名称": "name"})
        mask = (
            df["code"].str.contains(q, case=False, na=False) |
            df["name"].str.contains(q, case=False, na=False)
        )
        found = df[mask].head(20).reset_index(drop=True)
        return found if not found.empty else mock.mock_search_stock(query)
    except Exception as exc:
        st.warning(f"⚠️ 搜索解析失败。原因：{_friendly_error(exc)}")
        return mock.mock_search_stock(query)


# ---------------------------------------------------------------------------
# Public API — Sector / industry data
# ---------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL)
def get_sector_performance() -> pd.DataFrame:
    """
    Today's sector performance sorted by change_pct descending.
    NOTE: Sector data requires akshare. When DATA_SOURCE='yfinance',
    this returns mock data (Yahoo Finance has no A-share sector API).
    """
    if DEV_MODE:
        _toast_dev("板块行情")
        return mock.mock_sector_performance()

    if DATA_SOURCE == "yfinance":
        # Yahoo Finance has no sector-level A-share data.
        # Show a clear notice and return labeled mock data.
        st.info(
            "ℹ️ **板块行情**：Yahoo Finance 不提供 A 股板块数据。"
            "如需真实板块数据，请将 `config.py` 中的 `DATA_SOURCE` 改为 `\"akshare\"` "
            "并使用中国境内网络或 VPN。当前显示的是模拟数据。"
        )
        return mock.mock_sector_performance()

    # akshare path
    import akshare as ak
    result, err = _with_retry(ak.stock_board_industry_name_em, label="板块行情")
    if err or result is None:
        st.warning(f"⚠️ 板块数据获取失败，已切换为模拟数据。原因：{err}")
        return mock.mock_sector_performance()
    try:
        df = result
        # Use exact-name mapping to avoid matching "领涨股票-涨跌幅" as change_pct
        exact_map = {
            "板块名称": "name",   "名称": "name",
            "涨跌幅":   "change_pct",
            "成交额":   "amount",
            "领涨股票": "leader",  "领涨股票名称": "leader",
        }
        df = df.rename(columns=exact_map)

        # Drop duplicate columns that akshare sometimes produces (keep first)
        df = df.loc[:, ~df.columns.duplicated()]

        if "change_pct" in df.columns:
            col = df["change_pct"]
            # Guard: if rename still produced a 2-D slice, take first column
            if isinstance(col, pd.DataFrame):
                col = col.iloc[:, 0]
            df["change_pct"] = pd.to_numeric(col, errors="coerce")
            df = df.sort_values("change_pct", ascending=False).reset_index(drop=True)
        return df
    except Exception as exc:
        st.warning(f"⚠️ 板块数据解析失败，已切换为模拟数据。原因：{_friendly_error(exc)}")
        return mock.mock_sector_performance()


# ---------------------------------------------------------------------------
# Public API — Batch real-time quotes (watchlist)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL)
def get_batch_realtime(symbols: list) -> pd.DataFrame:
    """
    Real-time quotes for a list of stock codes.
    Returns a DataFrame indexed by code.
    """
    if not symbols:
        return pd.DataFrame()
    if DEV_MODE:
        _toast_dev("批量行情")
        return mock.mock_batch_realtime(symbols)

    if DATA_SOURCE == "yfinance":
        return _get_batch_yf(symbols)
    else:
        return _get_batch_ak(symbols)


def _get_batch_yf(symbols: list) -> pd.DataFrame:
    import yfinance as yf
    yf_codes = [_yfcode(s) for s in symbols]
    code_map  = {_yfcode(s): s for s in symbols}   # YF code → original 6-digit

    def _download():
        return yf.download(
            yf_codes, period="2d", auto_adjust=True,
            progress=False, group_by="ticker", threads=True,
        )

    result, err = _with_retry(_download, label="批量行情(yfinance)")

    if err or result is None or result.empty:
        st.warning(f"⚠️ 批量行情获取失败，已切换为模拟数据。原因：{err or '数据为空'}")
        return mock.mock_batch_realtime(symbols)

    rows = []
    for yf_code, orig_code in code_map.items():
        try:
            # yf.download with multiple tickers returns MultiIndex columns
            if len(yf_codes) == 1:
                sub = result
            else:
                sub = result[yf_code] if yf_code in result.columns.get_level_values(1) else pd.DataFrame()

            if sub.empty or len(sub) < 1:
                rows.append(mock.mock_stock_realtime_quote(orig_code))
                continue

            last = sub.iloc[-1]
            prev = sub.iloc[-2] if len(sub) >= 2 else last
            price      = float(last.get("Close", 0) or 0)
            prev_close = float(prev.get("Close", price) or price)
            chg_pct    = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0.0
            rows.append({
                "code":       orig_code,
                "name":       _BUILTIN_STOCK_LIST.get(orig_code, orig_code),
                "price":      round(price, 3),
                "change_pct": chg_pct,
                "change_amt": round(price - prev_close, 3),
                "volume":     int(last.get("Volume", 0) or 0),
                "amount":     None,
                "volume_ratio": None,
                "turnover":   None,
            })
        except Exception:
            rows.append(mock.mock_stock_realtime_quote(orig_code))

    if not rows:
        return mock.mock_batch_realtime(symbols)

    df = pd.DataFrame(rows)
    df = df.set_index("code")
    return df


def _get_batch_ak(symbols: list) -> pd.DataFrame:
    import akshare as ak
    result, err = _with_retry(ak.stock_zh_a_spot_em, label="批量行情")
    if err or result is None:
        st.warning(f"⚠️ 批量行情获取失败，已切换为模拟数据。原因：{err}")
        return mock.mock_batch_realtime(symbols)
    try:
        df = result[result["代码"].isin(symbols)].copy()
        df = df.rename(columns={
            "代码": "code",      "名称": "name",       "最新价": "price",
            "涨跌幅": "change_pct", "涨跌额": "change_amt",
            "成交量": "volume",  "成交额": "amount",
            "量比": "volume_ratio", "换手率": "turnover",
            "最高": "high",      "最低": "low",
            "今开": "open",      "昨收": "prev_close",
        })
        for col in ["price", "change_pct", "volume", "volume_ratio", "turnover"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.set_index("code")
    except Exception as exc:
        st.warning(f"⚠️ 批量行情解析失败，已切换为模拟数据。原因：{_friendly_error(exc)}")
        return mock.mock_batch_realtime(symbols)


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------

def _fmt_cap(val) -> str:
    if val is None:
        return "—"
    val = float(val)
    if val >= 1e12:
        return f"{val/1e12:.2f}万亿"
    if val >= 1e8:
        return f"{val/1e8:.1f}亿"
    return f"{val/1e4:.0f}万"

def _fmt_pct(val) -> str:
    if val is None:
        return "—"
    return f"{float(val)*100:.1f}%"

def _toast_dev(label: str):
    try:
        st.toast(f"🛠 开发模式：{label} 使用模拟数据", icon="🛠")
    except Exception:
        pass
