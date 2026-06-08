import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
from datetime import datetime

# 基礎設定
st.set_page_config(page_title="投資組合儀表板", layout="wide")
conn = st.connection("gsheets", type=GSheetsConnection)

# 強制清除快取函式
def clear_all_cache():
    st.cache_data.clear()
    st.rerun()

# 讀取資料
@st.cache_data(ttl=0)
def load_data():
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0)
    df_us = conn.read(worksheet="US_Portfolio", ttl=0)
    # 確保數值格式
    for col in ['Shares', '出借']: df_tw[col] = pd.to_numeric(df_tw[col], errors='coerce').fillna(0)
    for col in ['Shares', '複委託']: df_us[col] = pd.to_numeric(df_us[col], errors='coerce').fillna(0)
    return df_tw, df_us

df_tw, df_us = load_data()

# 取得匯率
@st.cache_data(ttl=3600)
def get_fx():
    try: return yf.Ticker("TWD=X").history(period="1d")['Close'].iloc[-1]
    except: return 32.5

usdtwd = get_fx()

st.title("📊 個人投資組合儀表板")
if st.button("🔄 強制重新整理"): clear_all_cache()

# 計算台股市值
total_tw = 0
for _, row in df_tw.iterrows():
    try:
        ticker = f"{row['Ticker']}.TW"
        price = yf.Ticker(ticker).history(period="1d")['Close'].iloc[-1]
        total_tw += price * (row['Shares'] + row['出借'])
    except: continue

# 計算美股市值
total_us = 0
for _, row in df_us.iterrows():
    try:
        price = yf.Ticker(row['Ticker']).history(period="1d")['Close'].iloc[-1]
        total_us += price * (row['Shares'] + row['複委託']) * usdtwd
    except: continue

# 顯示看板
col1, col2 = st.columns(2)
col1.metric("總市值 (TWD)", f"${(total_tw + total_us):,.0f}")
col2.metric("更新時間", datetime.now().strftime("%H:%M:%S"))

# 側邊欄編輯
with st.sidebar:
    st.subheader("台股編輯")
    edited_tw = st.data_editor(df_tw, num_rows="dynamic")
    if st.button("💾 儲存台股"):
        conn.update(worksheet="TW_Portfolio", data=edited_tw)
        clear_all_cache()
    
    st.subheader("美股編輯")
    edited_us = st.data_editor(df_us, num_rows="dynamic")
    if st.button("💾 儲存美股"):
        conn.update(worksheet="US_Portfolio", data=edited_us)
        clear_all_cache()
