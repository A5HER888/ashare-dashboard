# views/market_overview.py — Market overview page.

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.fetcher import get_index_spot, get_index_history, get_sector_performance
from config import MAJOR_INDICES


def render():
    st.title("市场总览")
    st.caption("数据来源：AKShare  |  每 5 分钟自动刷新缓存")

    # -----------------------------------------------------------------------
    # 1. Major index tiles
    # -----------------------------------------------------------------------
    st.subheader("主要指数")

    spot_df = get_index_spot()

    index_order = list(MAJOR_INDICES.items())  # [(name, code), ...]
    cols = st.columns(len(index_order))

    for col, (name, code) in zip(cols, index_order):
        with col:
            if not spot_df.empty:
                row = spot_df[spot_df["code"] == code]
                if not row.empty:
                    r = row.iloc[0]
                    price = r.get("price", None)
                    change = r.get("change_pct", None)
                    color = "normal" if change is None else ("off" if change < 0 else "normal")
                    delta_str = f"{change:+.2f}%" if pd.notna(change) else "—"
                    st.metric(
                        label=name,
                        value=f"{price:.2f}" if pd.notna(price) else "—",
                        delta=delta_str,
                        delta_color="inverse" if (change is not None and change < 0) else "normal",
                    )
                else:
                    st.metric(label=name, value="—")
            else:
                st.metric(label=name, value="获取失败")

    st.markdown("---")

    # -----------------------------------------------------------------------
    # 2. Index charts (past 60 days)
    # -----------------------------------------------------------------------
    st.subheader("指数走势（近60日）")

    selected_index_name = st.selectbox(
        "选择指数", list(MAJOR_INDICES.keys()), key="overview_index_select"
    )
    selected_code = MAJOR_INDICES[selected_index_name]

    hist_df = get_index_history(selected_code, days=90)

    if not hist_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=hist_df["date"],
            y=hist_df["close"],
            mode="lines",
            name=selected_index_name,
            line=dict(color="#E94560", width=2),
            fill="tozeroy",
            fillcolor="rgba(233,69,96,0.08)",
        ))
        fig.update_layout(
            height=320,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis_title="",
            yaxis_title="点位",
            plot_bgcolor="#0F0F0F",
            paper_bgcolor="#0F0F0F",
            font_color="#CCCCCC",
            xaxis=dict(gridcolor="#222222"),
            yaxis=dict(gridcolor="#222222"),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无指数历史数据")

    st.markdown("---")

    # -----------------------------------------------------------------------
    # 3. Sector performance
    # -----------------------------------------------------------------------
    st.subheader("板块涨跌排行")

    sector_df = get_sector_performance()

    if not sector_df.empty and "change_pct" in sector_df.columns and "name" in sector_df.columns:
        col_top, col_bot = st.columns(2)

        top5 = sector_df.head(5)[["name", "change_pct"]].copy()
        bot5 = sector_df.tail(5)[["name", "change_pct"]].copy()

        with col_top:
            st.markdown("**涨幅前5板块**")
            for _, row in top5.iterrows():
                pct = row["change_pct"]
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between'>"
                    f"<span>{row['name']}</span>"
                    f"<span style='color:#E94560;font-weight:bold'>+{pct:.2f}%</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        with col_bot:
            st.markdown("**跌幅前5板块**")
            for _, row in bot5.iterrows():
                pct = row["change_pct"]
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between'>"
                    f"<span>{row['name']}</span>"
                    f"<span style='color:#00B07C;font-weight:bold'>{pct:.2f}%</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        st.markdown("---")

        # Full sector bar chart
        with st.expander("查看全部板块涨跌幅"):
            plot_df = sector_df[["name", "change_pct"]].dropna().sort_values("change_pct")
            colors = ["#E94560" if x >= 0 else "#00B07C" for x in plot_df["change_pct"]]
            fig2 = go.Figure(go.Bar(
                x=plot_df["change_pct"],
                y=plot_df["name"],
                orientation="h",
                marker_color=colors,
                text=[f"{v:+.2f}%" for v in plot_df["change_pct"]],
                textposition="outside",
            ))
            fig2.update_layout(
                height=max(400, len(plot_df) * 22),
                margin=dict(l=0, r=60, t=10, b=0),
                plot_bgcolor="#0F0F0F",
                paper_bgcolor="#0F0F0F",
                font_color="#CCCCCC",
                xaxis=dict(gridcolor="#222222"),
                yaxis=dict(gridcolor="#222222"),
            )
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("暂无板块数据，或今日尚未开盘")

    # -----------------------------------------------------------------------
    # 4. Refresh button
    # -----------------------------------------------------------------------
    st.markdown("---")
    if st.button("刷新数据", key="overview_refresh"):
        st.cache_data.clear()
        st.rerun()
