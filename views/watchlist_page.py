# pages/watchlist_page.py — 自选股页面

import streamlit as st
import pandas as pd
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.fetcher import get_batch_realtime, search_stock
from data.watchlist_store import load_watchlist, add_stock, remove_stock
from config import VOLUME_RATIO_MODERATE, VOLUME_RATIO_HIGH


def _color_change(val):
    """Return CSS color string for a percentage change value."""
    try:
        v = float(val)
        if v > 0:
            return "color: #E94560; font-weight: bold"
        elif v < 0:
            return "color: #00B07C; font-weight: bold"
    except Exception:
        pass
    return ""


def _color_vr(val):
    """Highlight unusual volume ratio."""
    try:
        v = float(val)
        if v >= VOLUME_RATIO_HIGH:
            return "background-color: rgba(233,69,96,0.25); font-weight: bold"
        elif v >= VOLUME_RATIO_MODERATE:
            return "background-color: rgba(255,165,0,0.20)"
    except Exception:
        pass
    return ""


def render():
    st.title("自选股")

    watchlist = load_watchlist()
    codes = [s["code"] for s in watchlist]

    # -----------------------------------------------------------------------
    # Add stock panel
    # -----------------------------------------------------------------------
    with st.expander("添加股票到自选股", expanded=len(watchlist) == 0):
        query = st.text_input("搜索股票（代码或名称）", key="wl_search")
        if query:
            results = search_stock(query)
            if results.empty:
                st.warning("未找到匹配股票")
            else:
                for _, row in results.iterrows():
                    c1, c2 = st.columns([4, 1])
                    c1.write(f"{row['code']}  {row['name']}")
                    if c2.button("添加", key=f"add_{row['code']}"):
                        add_stock(row["code"], row["name"])
                        st.success(f"已添加 {row['name']}")
                        st.rerun()

    st.markdown("---")

    if not watchlist:
        st.info("自选股为空，请先添加股票")
        return

    # -----------------------------------------------------------------------
    # Fetch real-time quotes for all watchlist stocks
    # -----------------------------------------------------------------------
    with st.spinner("获取行情数据..."):
        quotes_df = get_batch_realtime(codes)

    # -----------------------------------------------------------------------
    # Build display table
    # -----------------------------------------------------------------------
    rows = []
    for stock in watchlist:
        code = stock["code"]
        name = stock["name"]
        if not quotes_df.empty and code in quotes_df.index:
            q = quotes_df.loc[code]
            price    = q.get("price")
            change   = q.get("change_pct")
            volume   = q.get("volume")
            vr       = q.get("volume_ratio")
            turnover = q.get("turnover")
            name     = q.get("name", name) or name
        else:
            price = change = volume = vr = turnover = None

        rows.append({
            "代码":   code,
            "名称":   name,
            "最新价": round(price, 2) if pd.notna(price) and price is not None else "—",
            "涨跌幅%": round(change, 2) if pd.notna(change) and change is not None else "—",
            "成交量(万)": f"{volume/10000:.1f}" if volume and pd.notna(volume) else "—",
            "量比":   round(vr, 2) if vr and pd.notna(vr) else "—",
            "换手率%": round(turnover, 2) if turnover and pd.notna(turnover) else "—",
        })

    display_df = pd.DataFrame(rows)

    # -----------------------------------------------------------------------
    # Alert banner for unusual activity
    # -----------------------------------------------------------------------
    alerts = []
    for row in rows:
        code, name = row["代码"], row["名称"]
        change = row["涨跌幅%"]
        vr     = row["量比"]
        try:
            if abs(float(change)) >= 5:
                direction = "大涨" if float(change) > 0 else "大跌"
                alerts.append(f"**{name}({code})** 今日{direction} {change}%")
        except Exception:
            pass
        try:
            if float(vr) >= VOLUME_RATIO_HIGH:
                alerts.append(f"**{name}({code})** 量比 {vr}x — 显著放量")
        except Exception:
            pass

    if alerts:
        with st.container():
            st.warning("异动提示")
            for a in alerts:
                st.markdown(f"- {a}")
        st.markdown("---")

    # -----------------------------------------------------------------------
    # Table with styling
    # -----------------------------------------------------------------------
    st.subheader(f"持仓自选（{len(watchlist)} 只）")

    styled = (
        display_df.style
        .applymap(_color_change, subset=["涨跌幅%"])
        .applymap(_color_vr, subset=["量比"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # -----------------------------------------------------------------------
    # Remove stocks
    # -----------------------------------------------------------------------
    st.markdown("---")
    st.subheader("移除股票")
    remove_options = [f"{s['code']}  {s['name']}" for s in watchlist]
    to_remove = st.multiselect("选择要移除的股票", remove_options, key="wl_remove")
    if st.button("确认移除", key="wl_confirm_remove") and to_remove:
        for item in to_remove:
            code = item.split()[0]
            remove_stock(code)
        st.success(f"已移除 {len(to_remove)} 只股票")
        st.rerun()

    # Refresh
    st.markdown("---")
    if st.button("刷新行情", key="wl_refresh"):
        st.cache_data.clear()
        st.rerun()
