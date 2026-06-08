import streamlit as st
import yfinance as yf
import pandas as pd
import time
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="投資組合儀表板", layout="wide")
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=3600)
def load_data():
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0)
    df_us = conn.read(worksheet="US_Portfolio", ttl=0)
    # 將所有數值欄位強制轉換為 float，確保沒有 NaN
    for col in ['Shares', '出借', '複委託']:
        if col in df_tw.columns: df_tw[col] = pd.to_numeric(df_tw[col], errors='coerce').fillna(0)
        if col in df_us.columns: df_us[col] = pd.to_numeric(df_us[col], errors='coerce').fillna(0)
    return df_tw, df_us

df_tw, df_us = load_data()

st.title("📊 個人投資組合儀表板")
if st.button("🔄 強制刷新"):
    st.cache_data.clear()
    st.rerun()

# 獲取匯率
try:
    usdtwd = float(yf.Ticker("TWD=X").history(period="1d")['Close'].iloc[-1])
except:
    usdtwd = 32.5

total_val = 0

# 分開處理台股與美股，並加上 time.sleep 避免被擋
st.write("正在讀取股價...")
progress_bar = st.progress(0)
total_count = len(df_tw) + len(df_us)
current = 0

for _, row in df_tw.iterrows():
    try:
        # 單檔查詢 + 延遲
        time.sleep(0.6) 
        price = float(yf.Ticker(f"{row['Ticker']}.TW").history(period="1d")['Close'].iloc[-1])
        total_val += price * (float(row['Shares']) + float(row['出借']))
    except: pass
    current += 1
    progress_bar.progress(current / total_count)

for _, row in df_us.iterrows():
    try:
        time.sleep(0.6)
        price = float(yf.Ticker(row['Ticker']).history(period="1d")['Close'].iloc[-1])
        total_val += price * (float(row['Shares']) + float(row['複委託'])) * usdtwd
    except: pass
    current += 1
    progress_bar.progress(current / total_count)

st.metric("總市值 (TWD)", f"${total_val:,.0f}")

# 編輯區
col1, col2 = st.columns(2)
with col1:
    edited_tw = st.data_editor(df_tw, num_rows="dynamic")
    if st.button("💾 儲存台股"):
        conn.update(worksheet="TW_Portfolio", data=edited_tw)
        st.rerun()
with col2:
    edited_us = st.data_editor(df_us, num_rows="dynamic")
    if st.button("💾 儲存美股"):
        conn.update(worksheet="US_Portfolio", data=edited_us)
        st.rerun()
