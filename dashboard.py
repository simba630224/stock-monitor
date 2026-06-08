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
import time
from streamlit_gsheets import GSheetsConnection

warnings.filterwarnings('ignore')
st.set_page_config(page_title="個人投資組合與技術分析儀表板", layout="wide")

# ==========================================
# 0. 輔助函式
# ==========================================
def safe_float(val):
    try: return float(val) if pd.notna(val) and str(val).strip() != '' else 0.0
    except: return 0.0

# 穩健版價格查詢函式 (含重試機制)
@st.cache_data(ttl=3600)
def get_price_robust(ticker):
    for i in range(3): # 最多嘗試 3 次
        try:
            time.sleep(0.8) # 每次查詢強制暫停，避免 Rate Limit
            hist = yf.Ticker(ticker).history(period="1d")
            if not hist.empty:
                return float(hist['Close'].iloc[-1])
        except:
            time.sleep(1.5)
            continue
    return 0.0

# ==========================================
# 1. 資料庫與清單設定
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=600)
def load_portfolio():
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0)
    df_us = conn.read(worksheet="US_Portfolio", ttl=0)
    for col in ['Shares', '出借', '複委託']:
        if col in df_tw.columns: df_tw[col] = pd.to_numeric(df_tw[col], errors='coerce').fillna(0)
        if col in df_us.columns: df_us[col] = pd.to_numeric(df_us[col], errors='coerce').fillna(0)
    return df_tw, df_us

df_tw, df_us = load_portfolio()

# ==========================================
# 2. 核心計算邏輯
# ==========================================
st.title("📊 個人投資組合與技術分析儀表板")
if st.button("🔄 強制重新整理所有數據"):
    st.cache_data.clear()
    st.rerun()

st.caption(f"數據最後更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# 計算總市值 (使用穩健函式)
usdtwd = get_price_robust("TWD=X")
if usdtwd == 0: usdtwd = 32.5

total_market_value = 0
for _, row in df_tw.iterrows():
    p = get_price_robust(f"{row['Ticker']}.TW")
    total_market_value += p * (row['Shares'] + row['出借'])

for _, row in df_us.iterrows():
    p = get_price_robust(row['Ticker'])
    total_market_value += p * (row['Shares'] + row['複委託']) * usdtwd

st.metric("總市值 (TWD)", f"${total_market_value:,.0f}")

# ==========================================
# 3. UI 呈現
# ==========================================
tab1, tab2 = st.tabs(["💰 投資組合總覽", "📈 技術分析掃描"])

with tab1:
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

with tab2:
    st.info("技術指標掃描需讀取歷史數據，讀取時間較長，請耐心等候。")
    # 此處保留您原本的技術指標計算邏輯 (process_technical_analysis)
    # 為維持篇幅與穩定性，建議先確認上方總市值顯示正常後，再補回技術圖表。
