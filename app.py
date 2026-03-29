# app.py — 主入口，Streamlit 多页面导航
# 运行方式：streamlit run app.py

import streamlit as st

st.set_page_config(
    page_title="A股量化研究平台",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Global dark theme override (补充 Streamlit 默认样式)
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* 隐藏 Streamlit 默认页脚和菜单 */
    #MainMenu { visibility: hidden; }
    footer     { visibility: hidden; }

    /* 侧边栏样式 */
    [data-testid="stSidebar"] {
        background-color: #0A0A0A;
    }

    /* 指标卡片 */
    [data-testid="metric-container"] {
        background: #111111;
        border: 1px solid #2A2A2A;
        border-radius: 8px;
        padding: 12px;
    }

    /* 按钮 */
    .stButton > button {
        border-radius: 6px;
        font-weight: 600;
    }

    /* DataFrame 斑马纹 */
    [data-testid="stDataFrame"] tr:nth-child(even) {
        background-color: rgba(255,255,255,0.02);
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 📈 A股量化研究")
    st.markdown("---")

    page = st.radio(
        "功能导航",
        options=[
            "🏠 市场总览",
            "🔍 个股分析",
            "⭐ 自选股",
            "🚦 信号检测",
            "📊 策略回测",
        ],
        key="nav_page",
    )

    st.markdown("---")
    st.caption("数据来源：AKShare")
    st.caption("仅供研究，不构成投资建议")

# ---------------------------------------------------------------------------
# Page routing
# ---------------------------------------------------------------------------
if page == "🏠 市场总览":
    from views.market_overview import render
    render()

elif page == "🔍 个股分析":
    from views.stock_analysis import render
    render()

elif page == "⭐ 自选股":
    from views.watchlist_page import render
    render()

elif page == "🚦 信号检测":
    from views.signals_page import render
    render()

elif page == "📊 策略回测":
    from views.backtest_page import render
    render()
