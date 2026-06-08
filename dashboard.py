import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
from datetime import datetime
import warnings
from streamlit_gsheets import GSheetsConnection

warnings.filterwarnings('ignore')

st.set_page_config(page_title="個人投資組合與技術分析儀表板", layout="wide")

# ==========================================
# 輔助函式
# ==========================================
def safe_float(val):
    try: return float(val) if pd.notna(val) and str(val).strip() != '' else 0.0
    except: return 0.0

# ==========================================
# 1. 資料庫連線 (使用 ttl=0 強制更新)
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0)
    df_tw = df_tw.dropna(subset=['Ticker'])
    if 'Shares' not in df_tw.columns: df_tw['Shares'] = 0.0
    if '出借' not in df_tw.columns: df_tw['出借'] = 0.0
    PORTFOLIO_TW = df_tw.to_dict('records')
except:
    PORTFOLIO_TW = []
    df_tw = pd.DataFrame(columns=["Ticker", "Shares", "出借"])

try:
    df_us = conn.read(worksheet="US_Portfolio", ttl=0)
    df_us = df_us.dropna(subset=['Ticker'])
    if 'Shares' not in df_us.columns: df_us['Shares'] = 0.0
    if '複委託' not in df_us.columns: df_us['複委託'] = 0.0
    PORTFOLIO_US = df_us.to_dict('records')
except:
    PORTFOLIO_US = []
    df_us = pd.DataFrame(columns=["Ticker", "Shares", "複委託"])

# ==========================================
# 2. 技術分析計算邏輯 (ttl=0)
# ==========================================
@st.cache_data(ttl=0)
def get_stock_data(sym):
    df = yf.download(sym, period="3y", progress=False)
    if df.empty or len(df) < 252: return None
    df.index = df.index.tz_localize(None)
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
    
    df['MA10'] = df['Close'].rolling(10).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()
    
    # KD & MACD
    rsv = (df['Close'] - df['Low'].rolling(9).min()) / (df['High'].rolling(9).max() - df['Low'].rolling(9).min()) * 100
    df['K_d'] = rsv.ewm(com=2, adjust=False).mean()
    df['D_d'] = df['K_d'].ewm(com=2, adjust=False).mean()
    
    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    return df

# ==========================================
# 3. 網頁 UI
# ==========================================
st.title("📊 個人投資組合與技術分析儀表板")
if st.button("🔄 強制更新數據"):
    st.cache_data.clear()
    st.rerun()

st.caption(f"數據更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

tab1, tab2 = st.tabs(["💰 投資組合總覽", "📈 技術分析掃描"])

with tab1:
    usdtwd = float(yf.Ticker("TWD=X").history(period="1d")['Close'].iloc[-1])
    total_val = 0
    ind_holdings = []

    # 計算總市值 (台股+美股)
    for item in PORTFOLIO_TW:
        price = safe_float(yf.Ticker(f"{item['Ticker']}.TW").history(period="1d")['Close'].iloc[-1])
        val = price * (safe_float(item['Shares']) + safe_float(item['出借']))
        total_val += val
        ind_holdings.append({'標的': item['Ticker'], '市值': val, '類別': '台股'})
        
    for item in PORTFOLIO_US:
        price = safe_float(yf.Ticker(item['Ticker']).history(period="1d")['Close'].iloc[-1])
        val = price * (safe_float(item['Shares']) + safe_float(item['複委託'])) * usdtwd
        total_val += val
        ind_holdings.append({'標的': item['Ticker'], '市值': val, '類別': '美股'})

    st.metric("總市值 (TWD)", f"${total_val:,.0f}")
    
    # 這裡加入圖表與表格... (請保持先前版本圖表邏輯)

with tab2:
    st.subheader("📈 技術指標繪圖")
    all_tickers = [item['Ticker'] for item in PORTFOLIO_TW] + [item['Ticker'] for item in PORTFOLIO_US]
    selected = st.selectbox("選擇標的:", all_tickers)
    
    if selected:
        sym = f"{selected}.TW" if selected in [item['Ticker'] for item in PORTFOLIO_TW] else selected
        df_plot = get_stock_data(sym)
        if df_plot is not None:
            df_plot = df_plot.tail(150)
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.5, 0.25, 0.25])
            fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close']), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['K_d'], name='K'), row=2, col=1)
            fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['MACD_Hist'], name='MACD'), row=3, col=1)
            st.plotly_chart(fig, use_container_width=True)

# ==========================================
# 4. 側邊欄管理 (新增/刪除功能已透過 data_editor 內建)
# ==========================================
with st.sidebar:
    st.header("📝 持股雲端管理")
    edited_tw = st.data_editor(df_tw, num_rows="dynamic", key="tw")
    if st.button("💾 儲存台股"):
        conn.update(worksheet="TW_Portfolio", data=edited_tw)
        st.rerun()
    
    st.divider()
    edited_us = st.data_editor(df_us, num_rows="dynamic", key="us")
    if st.button("💾 儲存美股"):
        conn.update(worksheet="US_Portfolio", data=edited_us)
        st.rerun()
