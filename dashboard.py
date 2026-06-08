import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import warnings
from streamlit_gsheets import GSheetsConnection
from datetime import datetime

warnings.filterwarnings('ignore')
st.set_page_config(page_title="投資組合儀表板", layout="wide")

# --- 輔助函式 ---
def safe_float(val):
    try: return float(val) if pd.notna(val) and str(val).strip() != '' else 0.0
    except: return 0.0

# --- 初始化 Google Sheets 連線 ---
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=3600)
def load_data():
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0)
    df_us = conn.read(worksheet="US_Portfolio", ttl=0)
    # 補全必要欄位
    for col in ['Shares', '出借']: if col not in df_tw.columns: df_tw[col] = 0.0
    for col in ['Shares', '複委託']: if col not in df_us.columns: df_us[col] = 0.0
    return df_tw, df_us

df_tw, df_us = load_data()

# --- 主程式 ---
st.title("📊 個人投資組合儀表板")
if st.button("🔄 強制重新整理所有數據"):
    st.cache_data.clear()
    st.rerun()

# 準備批次查詢清單
tw_symbols = [f"{s}.TW" for s in df_tw['Ticker'].astype(str)]
us_symbols = [s for s in df_us['Ticker'].astype(str)]
all_symbols = list(set(tw_symbols + us_symbols + ["TWD=X"]))

# 批次下載數據
with st.spinner("正在同步即時報價..."):
    data = yf.download(all_symbols, period="1d", group_by='ticker', progress=False)
    usdtwd = safe_float(data['TWD=X']['Close'].iloc[-1]) if 'TWD=X' in data else 32.5

# 計算總市值
total_val = 0
for _, row in df_tw.iterrows():
    sym = f"{row['Ticker']}.TW"
    price = safe_float(data[sym]['Close'].iloc[-1]) if sym in data else 0
    total_val += price * (safe_float(row['Shares']) + safe_float(row['出借']))

for _, row in df_us.iterrows():
    sym = row['Ticker']
    price = safe_float(data[sym]['Close'].iloc[-1]) if sym in data else 0
    total_val += price * (safe_float(row['Shares']) + safe_float(row['複委託'])) * usdtwd

st.metric("總市值 (TWD)", f"${total_val:,.0f}")

# --- 側邊欄管理 (新增/刪除功能) ---
with st.sidebar:
    st.header("📝 持股雲端管理")
    
    st.subheader("台股")
    edited_tw = st.data_editor(df_tw, num_rows="dynamic")
    if st.button("💾 儲存台股"):
        conn.update(worksheet="TW_Portfolio", data=edited_tw)
        st.rerun()
    
    st.divider()
    
    st.subheader("美股")
    edited_us = st.data_editor(df_us, num_rows="dynamic")
    if st.button("💾 儲存美股"):
        conn.update(worksheet="US_Portfolio", data=edited_us)
        st.rerun()
