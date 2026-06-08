import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_gsheets import GSheetsConnection
from datetime import datetime

st.set_page_config(page_title="投資組合儀表板", layout="wide")
conn = st.connection("gsheets", type=GSheetsConnection)

# --- 資料讀取與處理 ---
@st.cache_data(ttl=0) # 設為0確保即時更新
def get_portfolio():
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0)
    df_us = conn.read(worksheet="US_Portfolio", ttl=0)
    for col in ['Shares', '出借']: df_tw[col] = pd.to_numeric(df_tw[col], errors='coerce').fillna(0)
    for col in ['Shares', '複委託']: df_us[col] = pd.to_numeric(df_us[col], errors='coerce').fillna(0)
    return df_tw, df_us

df_tw, df_us = get_portfolio()

# --- 資料抓取 ---
tw_symbols = [f"{s}.TW" for s in df_tw['Ticker'].dropna().astype(str)]
us_symbols = [s for s in df_us['Ticker'].dropna().astype(str)]
all_symbols = list(set(tw_symbols + us_symbols + ["TWD=X"]))

with st.spinner("正在下載最新報價..."):
    data = yf.download(all_symbols, period="1d", group_by='ticker', progress=False)
    usdtwd = float(data['TWD=X']['Close'].iloc[-1]) if 'TWD=X' in data else 32.5

# --- 頁面顯示 ---
st.title("📊 個人投資組合儀表板")
if st.button("🔄 強制重新整理所有數據"):
    st.cache_data.clear()
    st.rerun()

st.caption(f"數據最後更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# 計算市值
total_val = 0
for _, row in df_tw.iterrows():
    price = float(data[f"{row['Ticker']}.TW"]['Close'].iloc[-1]) if f"{row['Ticker']}.TW" in data else 0
    total_val += price * (row['Shares'] + row['出借'])

for _, row in df_us.iterrows():
    price = float(data[row['Ticker']]['Close'].iloc[-1]) if row['Ticker'] in data else 0
    total_val += price * (row['Shares'] + row['複委託']) * usdtwd

st.metric("總市值 (TWD)", f"${total_val:,.0f}")

# --- 技術分析繪圖 ---
st.divider()
st.subheader("📈 技術指標分析")
selected = st.selectbox("選擇標的:", df_tw['Ticker'].tolist() + df_us['Ticker'].tolist())
if selected:
    sym = f"{selected}.TW" if selected in df_tw['Ticker'].values else selected
    df_tech = yf.download(sym, period="1y", progress=False)
    if not df_tech.empty:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
        fig.add_trace(go.Candlestick(x=df_tech.index, open=df_tech['Open'], high=df_tech['High'], low=df_tech['Low'], close=df_tech['Close']), row=1, col=1)
        st.plotly_chart(fig, use_container_width=True)

# --- 側邊欄 ---
with st.sidebar:
    st.header("📝 持股管理")
    edited_tw = st.data_editor(df_tw, num_rows="dynamic")
    if st.button("💾 儲存台股"):
        conn.update(worksheet="TW_Portfolio", data=edited_tw)
        st.rerun()
    edited_us = st.data_editor(df_us, num_rows="dynamic")
    if st.button("💾 儲存美股"):
        conn.update(worksheet="US_Portfolio", data=edited_us)
        st.rerun()
