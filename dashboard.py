import streamlit as st
import yfinance as yf
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime

st.set_page_config(page_title="投資組合儀表板", layout="wide")
conn = st.connection("gsheets", type=GSheetsConnection)

# 確保數據處理不會崩潰
@st.cache_data(ttl=0)
def load_data():
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0)
    df_us = conn.read(worksheet="US_Portfolio", ttl=0)
    for df in [df_tw, df_us]:
        for col in ['Shares', '出借', '複委託']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df_tw, df_us

df_tw, df_us = load_data()

st.title("📊 個人投資組合儀表板")
if st.button("🔄 強制重新整理"):
    st.cache_data.clear()
    st.rerun()

# 初始化總計
total_tw = 0
total_us = 0
usdtwd = 32.5 # 預設值，避免抓不到時崩潰

# 嘗試抓匯率
try:
    fx = yf.Ticker("TWD=X").history(period="1d")
    if not fx.empty: usdtwd = fx['Close'].iloc[-1]
except: pass

# 顯示總市值看板 (使用 try-except 保護)
try:
    # 計算台股
    for _, row in df_tw.iterrows():
        ticker = f"{row['Ticker']}.TW"
        hist = yf.Ticker(ticker).history(period="1d")
        if not hist.empty:
            price = hist['Close'].iloc[-1]
            total_tw += price * (row['Shares'] + row['出借'])

    # 計算美股
    for _, row in df_us.iterrows():
        ticker = str(row['Ticker'])
        hist = yf.Ticker(ticker).history(period="1d")
        if not hist.empty:
            price = hist['Close'].iloc[-1]
            total_us += price * (row['Shares'] + row['複委託']) * usdtwd
            
    st.metric("總市值 (TWD)", f"${(total_tw + total_us):,.0f}")
except Exception as e:
    st.error(f"計算市值時發生錯誤，請檢查代號：{e}")

# 顯示編輯區
st.divider()
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
