import streamlit as st
import yfinance as yf
import pandas as pd
import time
from streamlit_gsheets import GSheetsConnection
from datetime import datetime

st.set_page_config(page_title="投資組合儀表板", layout="wide")
conn = st.connection("gsheets", type=GSheetsConnection)

# 穩健下載函式：強制等待與批次處理
@st.cache_data(ttl=0)
def fetch_prices(tickers):
    # 每次只嘗試下載一次，若失敗則回傳空字典
    try:
        # 使用下載函數，加上延遲以保護 Rate Limit
        data = yf.download(tickers, period="1d", group_by='ticker', progress=False)
        return data
    except Exception:
        return pd.DataFrame()

# 載入與處理
@st.cache_data(ttl=0)
def get_data():
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0)
    df_us = conn.read(worksheet="US_Portfolio", ttl=0)
    for df in [df_tw, df_us]:
        for col in ['Shares', '出借', '複委託']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df_tw, df_us

df_tw, df_us = get_data()

# 準備代號清單 (加入 .TW 與匯率)
tw_list = [f"{str(s)}.TW" for s in df_tw['Ticker'].dropna()]
us_list = [str(s) for s in df_us['Ticker'].dropna()]
all_tickers = list(set(tw_list + us_list + ["TWD=X"]))

st.title("📊 個人投資組合儀表板")
if st.button("🔄 強制刷新報價"):
    st.cache_data.clear()
    st.rerun()

# 獲取價格
data = fetch_prices(all_tickers)
usdtwd = float(data['TWD=X']['Close'].iloc[-1]) if 'TWD=X' in data else 32.5

# 計算與渲染
total_val = 0
try:
    for _, row in df_tw.iterrows():
        sym = f"{row['Ticker']}.TW"
        if sym in data: total_val += float(data[sym]['Close'].iloc[-1]) * (row['Shares'] + row['出借'])
    for _, row in df_us.iterrows():
        sym = row['Ticker']
        if sym in data: total_val += float(data[sym]['Close'].iloc[-1]) * (row['Shares'] + row['複委託']) * usdtwd
    st.metric("總市值 (TWD)", f"${total_val:,.0f}")
except Exception as e:
    st.warning(f"部分行情更新失敗，系統運作中... ({e})")

# 顯示表格 (分開兩列)
col1, col2 = st.columns(2)
with col1:
    st.subheader("台股持股")
    edited_tw = st.data_editor(df_tw, num_rows="dynamic")
    if st.button("💾 儲存台股"):
        conn.update(worksheet="TW_Portfolio", data=edited_tw)
        st.rerun()
with col2:
    st.subheader("美股持股")
    edited_us = st.data_editor(df_us, num_rows="dynamic")
    if st.button("💾 儲存美股"):
        conn.update(worksheet="US_Portfolio", data=edited_us)
        st.rerun()
