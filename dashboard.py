import streamlit as st
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import re
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

# 設定網頁標題與排版
st.set_page_config(page_title="個人投資組合儀表板", layout="wide")

# --- 1. 投資組合資料 ---
PORTFOLIO_TW = [
    {'Ticker': '0050', 'Shares': 4332},
    {'Ticker': '0056', 'Shares': 8000},
    {'Ticker': '006208', 'Shares': 6000},
    {'Ticker': '00646', 'Shares': 149 + 11000},
    {'Ticker': '00662', 'Shares': 600 + 2000},
    {'Ticker': '00679B', 'Shares': 10000},
    {'Ticker': '00687B', 'Shares': 3438},
    {'Ticker': '00692', 'Shares': 2000 + 15000},
    {'Ticker': '00697B', 'Shares': 2262},
    {'Ticker': '00712', 'Shares': 2918 + 7000},
    {'Ticker': '00713', 'Shares': 1853 + 13000},
    {'Ticker': '00719B', 'Shares': 7042},
    {'Ticker': '00757', 'Shares': 324 + 3000},
    {'Ticker': '00772B', 'Shares': 100 + 18000},
    {'Ticker': '00830', 'Shares': 695 + 7000},
    {'Ticker': '00878', 'Shares': 4108 + 46000},
    {'Ticker': '00919', 'Shares': 4116+29000},
    {'Ticker': '00922', 'Shares': 22000+0},
    {'Ticker': '00923', 'Shares': 23000+5000},
    {'Ticker': '00937B', 'Shares': 3665 + 19000},
    {'Ticker': '009800', 'Shares': 14000 + 1000},
    {'Ticker': '009812', 'Shares': 6273 + 18000},
    {'Ticker': '009813', 'Shares': 2710 + 39000},
    {'Ticker': '009815', 'Shares': 0+15000},
    {'Ticker': '009816', 'Shares': 1000},
    {'Ticker': '00981A', 'Shares': 7000+2000},
    {'Ticker': '00988A', 'Shares': 2417 + 9000},
    {'Ticker': '1216', 'Shares': 2000},
    {'Ticker': '2317', 'Shares': 154},
    {'Ticker': '2330', 'Shares': 38},
    {'Ticker': '2412', 'Shares': 9000},
    {'Ticker': '2454', 'Shares': 1},
]

PORTFOLIO_US = [
    {'Ticker': 'AOR', 'Shares': 0.19},
    {'Ticker': 'BNDW', 'Shares': 37.6},
    {'Ticker': 'META', 'Shares': 2.0},
    {'Ticker': 'NVDA', 'Shares': 1.0},
    {'Ticker': 'QQQ', 'Shares': 17.8 + 2.6},
    {'Ticker': 'VNQ', 'Shares': 8.0 + 27.62 + 19.39},
    {'Ticker': 'VOO', 'Shares': 10.0 + 5.31},
    {'Ticker': 'VT', 'Shares': 202.49 + 86.19 + 76.78 + 105.63},
    {'Ticker': 'VWRA.L', 'Shares': 194.0},
    {'Ticker': 'CSPX.L', 'Shares': 9.0},
    {'Ticker': 'VXUS', 'Shares': 24.0},
]

# --- 2. 輔助函式 (加入暫存機制 ttl=3600秒，避免頻繁請求 yfinance) ---
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip()
    if re.match(r'^\d+B$', ticker):
        return f"{ticker}.TWO"
    return f"{ticker}.TW"

def classify_asset(ticker, market):
    ticker = str(ticker).strip().upper()
    if ticker in ['VT', 'VWRA.L', '009812', '009812.TW']: return '全球ETF'
    if market == 'TW':
        if ticker.endswith('B'): return '債券ETF'
        if ticker.startswith('00'):
            overseas = ['00646', '00757', '00662', '00830', '009811', '00712', '00717', '009800', '009813','009815', '00988A']
            if ticker in overseas: return '美股ETF與個股'
            market_cap = ['0050', '006208', '00692', '00922', '00923']
            if ticker in market_cap: return '台股市值型ETF'
            high_div = ['0056', '00878', '00919', '00713']
            if ticker in high_div: return '台股高股息型ETF'
            return '台股其他ETF'
        return '台股個股'
    elif market == 'US':
        if ticker in ['BND', 'BNDW', 'BNDX', 'IEF', 'TLT', 'SHY']: return '債券ETF'
        return '美股ETF與個股'
    return '其他'

@st.cache_data(ttl=3600)
def get_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        price = 0.0
        if not hist.empty:
            valid_closes = hist['Close'].dropna()
            if not valid_closes.empty:
                price = float(valid_closes.iloc[-1])
        
        div_2026 = 0.0
        if not hist.empty and 'Dividends' in hist.columns:
            divs = hist['Dividends']
            divs_2026 = divs[divs.index.year == 2026]
            div_sum = divs_2026.sum()
            if not pd.isna(div_sum): 
                div_2026 = float(div_sum)
                
        return price, div_2026
    except Exception:
        return 0.0, 0.0

@st.cache_data(ttl=3600)
def get_usdtwd():
    try:
        hist = yf.Ticker("TWD=X").history(period="5d")
        if not hist.empty:
            valid_closes = hist['Close'].dropna()
            if not valid_closes.empty:
                return float(valid_closes.iloc[-1])
        return 32.5
    except: 
        return 32.5

@st.cache_data(ttl=3600)
def get_fx_data(fx_ticker="TWD=X"):
    data = yf.Ticker(fx_ticker).history(period="1y")
    data = data.dropna(subset=['Close'])
    data['MA20'] = data['Close'].rolling(window=20).mean()
    data['MA60'] = data['Close'].rolling(window=60).mean()
    return data

# --- 3. 網頁渲染邏輯 ---
st.title("📈 個人投資組合儀表板")
st.text(f"更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

with st.spinner("正在同步即時報價資料..."):
    usdtwd = get_usdtwd()
    total_market_value = 0
    total_dividends_2026 = 0
    asset_allocation = {}

    # 處理台股與美股
    for item in PORTFOLIO_TW:
        yf_ticker = get_yf_ticker_tw(item['Ticker'])
        asset_type = classify_asset(item['Ticker'], 'TW')
        price, div = get_data(yf_ticker)
        value = price * item['Shares']
        div_total = div * item['Shares']
        
        if pd.notna(value): 
            total_market_value += value
            asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + value
        if pd.notna(div_total): 
            total_dividends_2026 += div_total

    for item in PORTFOLIO_US:
        asset_type = classify_asset(item['Ticker'], 'US')
        price, div = get_data(item['Ticker'])
        value = price * item['Shares'] * usdtwd
        div_total = div * item['Shares'] * usdtwd
        
        if pd.notna(value):
            total_market_value += value
            asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + value
        if pd.notna(div_total):
            total_dividends_2026 += div_total

# --- 頂端指標 ---
col1, col2, col3 = st.columns(3)
col1.metric("💰 總市值 (TWD)", f"{total_market_value:,.0f}")
col2.metric("💵 2026 累計股息 (TWD)", f"{total_dividends_2026:,.0f}")
col3.metric("💱 目前匯率 (USD/TWD)", f"{usdtwd:.3f}")

st.divider()

# --- 資產配置與圖表 ---
st.subheader("📊 資產配置")
col_chart, col_table = st.columns([2, 1])

# 準備配置資料表
df_allocation = pd.DataFrame(list(asset_allocation.items()), columns=['資產類別', '市值 (TWD)'])
df_allocation = df_allocation.sort_values(by='市值 (TWD)', ascending=False)
df_allocation['佔比 (%)'] = (df_allocation['市值 (TWD)'] / total_market_value * 100).round(1)

with col_chart:
    fig_pie, ax_pie = plt.subplots(figsize=(8, 5))
    ax_pie.pie(df_allocation['市值 (TWD)'], labels=df_allocation['資產類別'], autopct='%1.1f%%', startangle=140)
    ax_pie.axis('equal')
    st.pyplot(fig_pie)

with col_table:
    st.dataframe(df_allocation, hide_index=True, use_container_width=True)

st.divider()

# --- 匯率走勢圖 ---
st.subheader("💱 USD/TWD 匯率走勢 (1年)")
fx_data = get_fx_data()
if not fx_data.empty:
    fig_fx, ax_fx = plt.subplots(figsize=(12, 5))
    ax_fx.plot(fx_data.index, fx_data['Close'], label='USD/TWD', color='black', linewidth=1.5)
    ax_fx.plot(fx_data.index, fx_data['MA20'], label='MA20 (月線)', color='blue', linestyle='--')
    ax_fx.plot(fx_data.index, fx_data['MA60'], label='MA60 (季線)', color='red', linestyle='-.')
    
    ax_fx.grid(True, linestyle=':', alpha=0.6)
    ax_fx.legend(loc='upper left')
    st.pyplot(fig_fx)
    
    # 匯率狀態判定
    curr_price = fx_data['Close'].iloc[-1]
    ma20_val = fx_data['MA20'].iloc[-1]
    ma60_val = fx_data['MA60'].iloc[-1]
    status = []
    status.append("站上月線" if curr_price > ma20_val else "跌破月線")
    status.append("站上季線" if curr_price > ma60_val else "跌破季線")
    st.info(f"現價: **{curr_price:.3f}** | MA20: {ma20_val:.3f} | MA60: {ma60_val:.3f} | 狀態: {' / '.join(status)}")
