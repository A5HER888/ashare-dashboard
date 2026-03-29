# pages/stock_analysis.py — Individual stock analysis page.

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.fetcher import get_stock_history, get_stock_info, get_stock_realtime_quote, search_stock
from data.watchlist_store import add_stock, is_in_watchlist
from analysis.indicators import add_all_indicators
from config import VOLUME_RATIO_MODERATE, VOLUME_RATIO_HIGH


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------

def build_stock_chart(df: pd.DataFrame, symbol: str) -> go.Figure:
    """
    Build a 4-panel Plotly figure:
    Panel 1 (tall):  Candlestick + MA lines
    Panel 2 (medium): Volume bars + volume ratio line
    Panel 3 (small):  RSI
    Panel 4 (small):  MACD
    """
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        row_heights=[0.50, 0.20, 0.15, 0.15],
        vertical_spacing=0.03,
        subplot_titles=("K线 + 均线", "成交量 / 量比", "RSI", "MACD"),
    )

    # --- Panel 1: Candlestick ---
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        increasing_line_color="#E94560",
        decreasing_line_color="#00B07C",
        name="K线",
    ), row=1, col=1)

    ma_colors = {5: "#FFD700", 10: "#FFA500", 20: "#00BFFF", 60: "#EE82EE"}
    for period, color in ma_colors.items():
        col_name = f"ma{period}"
        if col_name in df.columns:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df[col_name],
                mode="lines", name=f"MA{period}",
                line=dict(color=color, width=1.2),
            ), row=1, col=1)

    # --- Panel 2: Volume bars + volume ratio ---
    # Color volume bars by price direction
    bar_colors = ["#E94560" if c >= o else "#00B07C"
                  for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df["date"], y=df["volume"],
        marker_color=bar_colors,
        name="成交量", showlegend=False,
        opacity=0.8,
    ), row=2, col=1)

    if "volume_ratio" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["volume_ratio"],
            mode="lines", name="量比",
            line=dict(color="#FFFFFF", width=1.5, dash="dot"),
            yaxis="y5",  # secondary axis on panel 2
        ), row=2, col=1)
        # Draw threshold lines
        fig.add_hline(y=VOLUME_RATIO_MODERATE, line_dash="dash",
                      line_color="orange", row=2, col=1,
                      annotation_text=f"量比{VOLUME_RATIO_MODERATE}x",
                      annotation_font_color="orange")
        fig.add_hline(y=VOLUME_RATIO_HIGH, line_dash="dash",
                      line_color="red", row=2, col=1,
                      annotation_text=f"量比{VOLUME_RATIO_HIGH}x",
                      annotation_font_color="red")

    # --- Panel 3: RSI ---
    if "rsi" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["rsi"],
            mode="lines", name="RSI",
            line=dict(color="#9B59B6", width=1.5),
        ), row=3, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="#E94560", row=3, col=1,
                      annotation_text="超买70", annotation_font_color="#E94560")
        fig.add_hline(y=30, line_dash="dash", line_color="#00B07C", row=3, col=1,
                      annotation_text="超卖30", annotation_font_color="#00B07C")

    # --- Panel 4: MACD ---
    if "macd_hist" in df.columns:
        hist_colors = ["#E94560" if v >= 0 else "#00B07C" for v in df["macd_hist"]]
        fig.add_trace(go.Bar(
            x=df["date"], y=df["macd_hist"],
            marker_color=hist_colors,
            name="MACD柱", showlegend=False,
        ), row=4, col=1)
    if "macd_line" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["macd_line"],
            mode="lines", name="MACD",
            line=dict(color="#FFD700", width=1.2),
        ), row=4, col=1)
    if "macd_signal" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["macd_signal"],
            mode="lines", name="Signal",
            line=dict(color="#FF6B6B", width=1.2),
        ), row=4, col=1)

    fig.update_layout(
        height=820,
        margin=dict(l=0, r=0, t=30, b=0),
        plot_bgcolor="#0F0F0F",
        paper_bgcolor="#0F0F0F",
        font_color="#CCCCCC",
        legend=dict(
            orientation="h", y=1.02, x=0,
            bgcolor="rgba(0,0,0,0)",
            font_size=11,
        ),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )
    for axis in ["xaxis", "xaxis2", "xaxis3", "xaxis4",
                 "yaxis", "yaxis2", "yaxis3", "yaxis4"]:
        fig.update_layout(**{axis: dict(gridcolor="#1E1E1E")})

    return fig


# ---------------------------------------------------------------------------
# Page render
# ---------------------------------------------------------------------------

def render():
    st.title("个股分析")

    # -----------------------------------------------------------------------
    # Search bar
    # -----------------------------------------------------------------------
    query = st.text_input(
        "搜索股票（输入代码或名称）",
        placeholder="例如: 000001  或  平安银行",
        key="stock_search_query",
    )

    symbol = None
    stock_name = ""

    if query:
        results = search_stock(query)
        if results.empty:
            st.warning("未找到匹配股票")
            return

        if len(results) == 1:
            symbol = results.iloc[0]["code"]
            stock_name = results.iloc[0]["name"]
        else:
            options = [f"{r['code']}  {r['name']}" for _, r in results.iterrows()]
            chosen = st.selectbox("选择股票", options, key="stock_select")
            symbol = chosen.split()[0]
            stock_name = chosen.split()[1] if len(chosen.split()) > 1 else ""

    if not symbol:
        st.info("请在上方搜索框输入股票代码或名称")
        return

    # -----------------------------------------------------------------------
    # Period selector
    # -----------------------------------------------------------------------
    period_map = {"近1月": 40, "近3月": 100, "近6月": 190, "近1年": 380}
    period_label = st.radio(
        "时间范围", list(period_map.keys()), horizontal=True, key="stock_period"
    )
    days = period_map[period_label]

    # -----------------------------------------------------------------------
    # Load data
    # -----------------------------------------------------------------------
    with st.spinner(f"加载 {symbol} 数据..."):
        df = get_stock_history(symbol, days=days)
        quote = get_stock_realtime_quote(symbol)
        info = get_stock_info(symbol)

    if df.empty:
        st.error("无法获取该股票数据，请检查代码是否正确")
        return

    df = add_all_indicators(df)

    # -----------------------------------------------------------------------
    # Header: real-time quote metrics
    # -----------------------------------------------------------------------
    name_display = quote.get("name", stock_name) or stock_name
    st.subheader(f"{name_display}（{symbol}）")

    price     = quote.get("price")
    change    = quote.get("change_pct")
    vr        = quote.get("volume_ratio")
    turnover  = quote.get("turnover")
    volume    = quote.get("volume")
    pe        = quote.get("pe_ratio")
    mktcap    = quote.get("market_cap")

    # If real-time quote unavailable, fall back to last row of history
    if price is None and not df.empty:
        last = df.iloc[-1]
        price    = last["close"]
        change   = last["change_pct"]
        turnover = last.get("turnover")
        vr       = last.get("volume_ratio")
        volume   = last.get("volume")

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        delta_str = f"{change:+.2f}%" if change is not None and pd.notna(change) else "—"
        st.metric("最新价", f"{price:.2f}" if price else "—", delta=delta_str,
                  delta_color="inverse" if (change and change < 0) else "normal")
    with m2:
        st.metric("量比", f"{vr:.2f}x" if vr and pd.notna(vr) else "—")
    with m3:
        st.metric("换手率", f"{turnover:.2f}%" if turnover and pd.notna(turnover) else "—")
    with m4:
        vol_str = f"{volume/10000:.1f}万" if volume and pd.notna(volume) else "—"
        st.metric("成交量", vol_str)
    with m5:
        st.metric("市盈率(动)", f"{pe:.1f}" if pe and pd.notna(pe) else "—")

    # Volume ratio colour badge
    if vr and pd.notna(vr):
        if vr >= VOLUME_RATIO_HIGH:
            st.error(f"量比 {vr:.2f}x — 显著放量，请注意异动")
        elif vr >= VOLUME_RATIO_MODERATE:
            st.warning(f"量比 {vr:.2f}x — 温和放量")

    # -----------------------------------------------------------------------
    # Watchlist button
    # -----------------------------------------------------------------------
    in_wl = is_in_watchlist(symbol)
    btn_label = "从自选股移除" if in_wl else "加入自选股"
    if st.button(btn_label, key="wl_toggle"):
        if in_wl:
            from data.watchlist_store import remove_stock
            remove_stock(symbol)
            st.success(f"已从自选股移除 {name_display}")
        else:
            add_stock(symbol, name_display)
            st.success(f"已加入自选股 {name_display}")
        st.rerun()

    # -----------------------------------------------------------------------
    # Chart
    # -----------------------------------------------------------------------
    st.markdown("---")
    fig = build_stock_chart(df, symbol)
    st.plotly_chart(fig, use_container_width=True)

    # -----------------------------------------------------------------------
    # Basic info
    # -----------------------------------------------------------------------
    if info:
        with st.expander("基本资料"):
            pairs = list(info.items())
            n = len(pairs)
            cols = st.columns(3)
            for idx, (k, v) in enumerate(pairs):
                cols[idx % 3].markdown(f"**{k}**: {v}")

    # -----------------------------------------------------------------------
    # Latest data table
    # -----------------------------------------------------------------------
    with st.expander("近期日线数据"):
        display_cols = ["date", "open", "close", "high", "low", "volume",
                        "change_pct", "turnover", "volume_ratio"]
        show_cols = [c for c in display_cols if c in df.columns]
        rename = {
            "date": "日期", "open": "开盘", "close": "收盘",
            "high": "最高", "low": "最低", "volume": "成交量",
            "change_pct": "涨跌幅%", "turnover": "换手率%", "volume_ratio": "量比"
        }
        disp = df[show_cols].tail(20).rename(columns=rename).copy()
        disp["日期"] = disp["日期"].dt.strftime("%Y-%m-%d")
        st.dataframe(disp[::-1].reset_index(drop=True), use_container_width=True)
