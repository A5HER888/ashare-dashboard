# pages/backtest_page.py — 策略回测页面

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.fetcher import get_stock_history, search_stock
from analysis.indicators import add_all_indicators
from analysis.backtest import backtest_strategy, STRATEGIES


def render():
    st.title("策略回测")
    st.caption("基于历史数据的简单规则回测，不代表未来收益，不构成投资建议")

    # -----------------------------------------------------------------------
    # Stock selector
    # -----------------------------------------------------------------------
    st.subheader("选择股票")
    query = st.text_input("搜索股票（代码或名称）", placeholder="例如: 000001", key="bt_search")

    symbol, stock_name = None, ""
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
            chosen = st.selectbox("选择股票", options, key="bt_select")
            symbol = chosen.split()[0]
            stock_name = chosen.split()[1] if len(chosen.split()) > 1 else ""

    if not symbol:
        st.info("请搜索并选择股票")
        return

    # -----------------------------------------------------------------------
    # Strategy and parameter selectors
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("策略设置")

    strategy_name = st.selectbox("选择策略", list(STRATEGIES.keys()), key="bt_strategy")

    # Strategy-specific parameter UI
    strategy_params = {}

    if strategy_name == "MA均线金叉策略":
        col1, col2 = st.columns(2)
        with col1:
            fast = st.selectbox("快线周期", [5, 10], index=0, key="bt_ma_fast")
        with col2:
            slow = st.selectbox("慢线周期", [20, 60], index=0, key="bt_ma_slow")
        strategy_params = {"fast": fast, "slow": slow}

    elif strategy_name == "RSI超卖反弹策略":
        col1, col2, col3 = st.columns(3)
        with col1:
            rsi_period = st.slider("RSI周期", 7, 21, 14, key="bt_rsi_period")
        with col2:
            oversold = st.slider("超卖线", 20, 40, 30, key="bt_rsi_os")
        with col3:
            overbought = st.slider("超买线", 60, 80, 70, key="bt_rsi_ob")
        strategy_params = {"period": rsi_period, "oversold": oversold, "overbought": overbought}

    elif strategy_name == "量比突破策略":
        col1, col2 = st.columns(2)
        with col1:
            vr_thresh = st.slider("量比阈值", 1.5, 5.0, 2.0, step=0.1, key="bt_vr_thresh")
        with col2:
            hold_days = st.slider("持有天数", 3, 20, 5, key="bt_hold_days")
        strategy_params = {"vr_threshold": vr_thresh, "hold_days": hold_days}

    # History period
    period_map = {"近半年": 190, "近1年": 380, "近2年": 760, "近3年": 1100}
    period_label = st.radio("回测周期", list(period_map.keys()), horizontal=True, key="bt_period")
    days = period_map[period_label]

    # -----------------------------------------------------------------------
    # Run backtest
    # -----------------------------------------------------------------------
    st.markdown("---")
    if not st.button("运行回测", key="bt_run"):
        st.info("设置完成后点击「运行回测」")
        return

    with st.spinner("运行回测中..."):
        raw_df = get_stock_history(symbol, days=days)
        if raw_df.empty:
            st.error("无法获取数据")
            return
        raw_df = add_all_indicators(raw_df)

        try:
            result_df, trades, metrics = backtest_strategy(raw_df, strategy_name, **strategy_params)
        except Exception as e:
            st.error(f"回测失败: {e}")
            return

    # -----------------------------------------------------------------------
    # Metrics summary
    # -----------------------------------------------------------------------
    st.subheader(f"{stock_name}（{symbol}）— {strategy_name} 回测结果")

    m_cols = st.columns(len(metrics))
    for col, (k, v) in zip(m_cols, metrics.items()):
        col.metric(k, v)

    # -----------------------------------------------------------------------
    # Cumulative return chart
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("策略净值曲线 vs 买入持有")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=result_df["date"],
        y=result_df["cumulative_strategy"],
        mode="lines",
        name="策略净值",
        line=dict(color="#FFD700", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=result_df["date"],
        y=result_df["cumulative_bah"],
        mode="lines",
        name="买入持有",
        line=dict(color="#888888", width=1.5, dash="dash"),
    ))
    fig.add_hline(y=1.0, line_color="#444444", line_dash="dot")
    fig.update_layout(
        height=380,
        margin=dict(l=0, r=0, t=10, b=0),
        plot_bgcolor="#0F0F0F",
        paper_bgcolor="#0F0F0F",
        font_color="#CCCCCC",
        xaxis=dict(gridcolor="#1E1E1E"),
        yaxis=dict(gridcolor="#1E1E1E", title="净值"),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    # -----------------------------------------------------------------------
    # Trade list
    # -----------------------------------------------------------------------
    if trades:
        st.markdown("---")
        with st.expander(f"交易记录（共 {len(trades)} 笔）"):
            trade_rows = []
            for t in trades:
                ret = t["return"]
                trade_rows.append({
                    "平仓日期": t["date_exit"].strftime("%Y-%m-%d") if hasattr(t["date_exit"], "strftime") else str(t["date_exit"]),
                    "买入价": round(t["entry"], 2),
                    "卖出价": round(t["exit"], 2),
                    "收益率": f"{ret:+.2%}",
                    "盈亏": "盈利" if ret > 0 else "亏损",
                })
            trade_df = pd.DataFrame(trade_rows)

            def color_profit(val):
                if "盈利" in str(val):
                    return "color: #E94560"
                elif "亏损" in str(val):
                    return "color: #00B07C"
                return ""

            styled_trades = trade_df.style.applymap(color_profit, subset=["盈亏"])
            st.dataframe(styled_trades, use_container_width=True, hide_index=True)
    else:
        st.info("回测期间未产生任何交易")

    # -----------------------------------------------------------------------
    # Disclaimer
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.caption(
        "⚠️ 回测结果仅供学习研究，历史表现不代表未来收益。"
        "本系统不提供任何投资建议，据此操作风险自担。"
    )
