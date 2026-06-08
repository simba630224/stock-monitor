import streamlit as st
import yfinance as yf
import pandas as pd
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="投資組合儀表板", layout="wide")
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=0)
def load_data():
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0)
    df_us = conn.read(worksheet="US_Portfolio", ttl=0)
    # 確保數值轉為 float，NaN 變 0
    for col in ['Shares', '出借', '複委託']:
        if col in df_tw.columns: df_tw[col] = pd.to_numeric(df_tw[col], errors='coerce').fillna(0)
        if col in df_us.columns: df_us[col] = pd.to_numeric(df_us[col], errors='coerce').fillna(0)
    return df_tw, df_us

df_tw, df_us = load_data()

# 改用個別查詢且加上極致容錯，避免 nan
def get_price(ticker):
    try:
        # 使用快速查詢，若失敗直接回傳 0
        p = yf.Ticker(ticker).fast_info['last_price']
        return float(p) if p else 0.0
    except:
        return 0.0

# 獲取匯率
usdtwd = get_price("TWD=X")
if usdtwd == 0: usdtwd = 32.5

st.title("📊 個人投資組合儀表板")

# 計算市值
total_tw = sum([get_price(f"{row['Ticker']}.TW") * (row['Shares'] + row['出借']) for _, row in df_tw.iterrows()])
total_us = sum([get_price(row['Ticker']) * (row['Shares'] + row['複委託']) * usdtwd for _, row in df_us.iterrows()])

st.metric("總市值 (TWD)", f"${(total_tw + total_us):,.0f}")

# 顯示編輯區
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
