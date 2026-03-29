# pages/signals_page.py — 信号检测页面

import streamlit as st
import pandas as pd
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.fetcher import get_stock_history, search_stock
from data.watchlist_store import load_watchlist
from analysis.indicators import add_all_indicators
from analysis.signals import detect_all_signals, signals_to_dataframe


DIRECTION_BADGE = {
    "看多": "🔴 看多",
    "看空": "🟢 看空",
    "中性": "⚪ 中性",
}

DIRECTION_COLOR = {
    "看多": "#E94560",
    "看空": "#00B07C",
    "中性": "#888888",
}


def _render_signals_for(symbol: str, name: str):
    """Fetch data, run signal detection, and display results for one stock."""
    df = get_stock_history(symbol, days=120)
    if df.empty:
        st.warning(f"{symbol} 数据获取失败")
        return

    df = add_all_indicators(df)
    signals = detect_all_signals(df)
    sig_df = signals_to_dataframe(signals)

    st.subheader(f"{name}（{symbol}）")

    if sig_df.empty:
        st.info("近期无明显信号")
        return

    # Display each signal as a colour-coded card row
    for _, row in sig_df.iterrows():
        direction = row["方向"]
        color = DIRECTION_COLOR.get(direction, "#888888")
        st.markdown(
            f"<div style='border-left: 4px solid {color}; padding: 6px 12px; "
            f"margin-bottom: 6px; background: rgba(255,255,255,0.04); border-radius: 4px;'>"
            f"<span style='color:{color};font-weight:bold'>{row['信号类型']}</span>"
            f"&nbsp;&nbsp;<span style='color:#888;font-size:0.85em'>{row['日期']}</span>"
            f"<br><span style='font-size:0.9em'>{row['描述']}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )


def render():
    st.title("信号检测")
    st.caption("基于规则的技术面信号，不构成投资建议")

    # -----------------------------------------------------------------------
    # Source selector: scan watchlist or search single stock
    # -----------------------------------------------------------------------
    scan_mode = st.radio(
        "检测范围",
        ["扫描自选股", "指定单只股票"],
        horizontal=True,
        key="signal_mode",
    )

    # -----------------------------------------------------------------------
    # Scan watchlist
    # -----------------------------------------------------------------------
    if scan_mode == "扫描自选股":
        watchlist = load_watchlist()
        if not watchlist:
            st.info("自选股为空，请先在「自选股」页面添加股票")
            return

        st.info(f"将扫描 {len(watchlist)} 只自选股，可能需要约 {len(watchlist) * 2} 秒")

        if st.button("开始扫描", key="scan_btn"):
            progress = st.progress(0, text="扫描中...")
            results = {}
            for i, stock in enumerate(watchlist):
                symbol = stock["code"]
                name   = stock["name"]
                df = get_stock_history(symbol, days=120)
                if not df.empty:
                    df = add_all_indicators(df)
                    sigs = detect_all_signals(df)
                    if sigs:
                        results[symbol] = (name, sigs)
                progress.progress((i + 1) / len(watchlist), text=f"正在处理 {name}...")

            progress.empty()

            if not results:
                st.success("未检测到明显信号")
                return

            st.success(f"共发现 {sum(len(v[1]) for v in results.values())} 个信号，涉及 {len(results)} 只股票")
            st.markdown("---")

            for symbol, (name, sigs) in results.items():
                sig_df = signals_to_dataframe(sigs)
                _render_signals_for_preloaded(symbol, name, sig_df)
                st.markdown("---")

    # -----------------------------------------------------------------------
    # Single stock
    # -----------------------------------------------------------------------
    else:
        query = st.text_input("搜索股票", placeholder="代码或名称", key="sig_search")
        if not query:
            st.info("请输入股票代码或名称")
            return

        results = search_stock(query)
        if results.empty:
            st.warning("未找到匹配股票")
            return

        if len(results) == 1:
            symbol = results.iloc[0]["code"]
            name   = results.iloc[0]["name"]
        else:
            options = [f"{r['code']}  {r['name']}" for _, r in results.iterrows()]
            chosen  = st.selectbox("选择股票", options, key="sig_select")
            symbol  = chosen.split()[0]
            name    = chosen.split()[1] if len(chosen.split()) > 1 else ""

        with st.spinner("检测信号中..."):
            _render_signals_for(symbol, name)

    # -----------------------------------------------------------------------
    # Signal legend
    # -----------------------------------------------------------------------
    with st.expander("信号说明"):
        st.markdown("""
| 信号名称 | 方向 | 含义 |
|---------|------|------|
| MA金叉 | 看多 | 短期均线上穿长期均线 |
| MA死叉 | 看空 | 短期均线下穿长期均线 |
| RSI超卖 | 看多 | RSI < 30，股价可能超卖 |
| RSI超买 | 看空 | RSI > 70，股价可能超买 |
| RSI超卖反弹 | 看多 | RSI从超卖区回升 |
| MACD金叉 | 看多 | MACD线上穿信号线，柱由绿转红 |
| MACD死叉 | 看空 | MACD线下穿信号线，柱由红转绿 |
| 放量异动 | 中性 | 量比 ≥ 2x，成交量显著放大 |
| 温和放量 | 中性 | 量比 ≥ 1.5x |
| 突破新高 | 看多 | 收盘价突破近20日最高价 |

> **注意：** 所有信号均为技术面参考，实际操作需结合基本面及市场环境综合判断。
        """)


def _render_signals_for_preloaded(symbol: str, name: str, sig_df: pd.DataFrame):
    """Render signal cards from a pre-built DataFrame (used in batch scan)."""
    st.subheader(f"{name}（{symbol}）")
    for _, row in sig_df.iterrows():
        direction = row["方向"]
        color = DIRECTION_COLOR.get(direction, "#888888")
        st.markdown(
            f"<div style='border-left: 4px solid {color}; padding: 6px 12px; "
            f"margin-bottom: 6px; background: rgba(255,255,255,0.04); border-radius: 4px;'>"
            f"<span style='color:{color};font-weight:bold'>{row['信号类型']}</span>"
            f"&nbsp;&nbsp;<span style='color:#888;font-size:0.85em'>{row['日期']}</span>"
            f"<br><span style='font-size:0.9em'>{row['描述']}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
