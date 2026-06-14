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

# 設定網頁標題與排版 (寬螢幕模式)
st.set_page_config(page_title="個人投資組合與技術分析儀表板", layout="wide")

# ==========================================
# 0. 輔助函式：安全轉換數字
# ==========================================
def safe_float(val):
    """安全地將資料轉換為浮點數，遇到空白或非數字則回傳 0.0"""
    try:
        return float(val) if pd.notna(val) and str(val).strip() != '' else 0.0
    except:
        return 0.0

# ==========================================
# 1. 資料庫與清單設定 (Google Sheets 雙分頁連線)
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

# 讀取台股
try:
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0)
    df_tw = df_tw.dropna(subset=['Ticker'])
    # 自動補齊台股所需欄位
    if 'Shares' not in df_tw.columns: df_tw['Shares'] = 0.0
    if '出借' not in df_tw.columns: df_tw['出借'] = 0.0
    if '類別' not in df_tw.columns: df_tw['類別'] = '台股'
    PORTFOLIO_TW = df_tw.to_dict('records')
except Exception as e:
    st.error(f"⚠️ 無法讀取台股資料，請確認試算表內有『TW_Portfolio』工作表。錯誤: {e}")
    PORTFOLIO_TW = []
    df_tw = pd.DataFrame(columns=["Ticker", "Shares", "出借", "類別"])

# 讀取美股
try:
    df_us = conn.read(worksheet="US_Portfolio", ttl=0)
    df_us = df_us.dropna(subset=['Ticker'])
    # 自動補齊美股所需欄位
    if 'Shares' not in df_us.columns: df_us['Shares'] = 0.0
    if '複委託' not in df_us.columns: df_us['複委託'] = 0.0
    if '類別' not in df_us.columns: df_us['類別'] = '美股'
    PORTFOLIO_US = df_us.to_dict('records')
except Exception as e:
    st.warning(f"⚠️ 無法讀取美股資料，請確認試算表內有『US_Portfolio』工作表。錯誤: {e}")
    PORTFOLIO_US = []
    df_us = pd.DataFrame(columns=["Ticker", "Shares", "複委託", "類別"])

# 技術分析觀察清單
TW_CORE = [
    {'symbol': '2330.TW', 'name': '台積電'}, {'symbol': '2317.TW', 'name': '鴻海'},
    {'symbol': '2454.TW', 'name': '聯發科'}, {'symbol': '2308.TW', 'name': '台達電'},
    {'symbol': '3008.TW', 'name': '大立光'}, {'symbol': '0050.TW', 'name': '元大台灣50'},
    {'symbol': '006208.TW', 'name': '富邦台50'},
    {'symbol': '00878.TW', 'name': '國泰永續高股息'}, {'symbol': '00713.TW', 'name': '元大台灣高息低波'},
    {'symbol': '00919.TW', 'name': '群益台灣精選高息'}, {'symbol': '009812.TW', 'name': '野村日本東證ETF'},
    {'symbol': '00922.TW', 'name': '國泰台灣領袖50'}, {'symbol': '00923.TW', 'name': '群益台灣ESG低碳'},
    {'symbol': '00830.TW', 'name': '國泰費城半導體'}, {'symbol': '00981A.TW', 'name': '主動統一台股增長'},
    {'symbol': '00988A.TW', 'name': '主動統一全球創新'}, {'symbol': '009815.TW', 'name': '大華美國MAG7+'}
]

US_WATCH = [
    {'symbol': 'NVDA', 'name': '輝達 Nvidia'}, {'symbol': 'MSFT', 'name': '微軟 Microsoft'},
    {'symbol': 'GOOGL', 'name': '谷歌 Google'}, {'symbol': 'VOO', 'name': '標普500 VOO'},
    {'symbol': 'QQQ', 'name': '納斯達克 QQQ'}, {'symbol': 'VT', 'name': '領航全球股票 VT'},
    {'symbol': 'VWRA.L', 'name': '富時全球全指 VWRA'}
]

# ==========================================
# 2. 核心抓取與計算邏輯
# ==========================================
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip()
    return f"{ticker}.TWO" if re.match(r'^\d+B$', ticker) else f"{ticker}.TW"

@st.cache_data(ttl=900)
def get_basic_data(ticker):
    for _ in range(3):
        try:
            time.sleep(0.3)
            hist = yf.Ticker(ticker).history(period="1y")
            if not hist.empty:
                price = float(hist['Close'].dropna().iloc[-1])
                div_2026 = float(hist['Dividends'][hist.index.year == 2026].sum()) if 'Dividends' in hist.columns else 0.0
                return price, div_2026
        except:
            time.sleep(1)
    return 0.0, 0.0

@st.cache_data(ttl=900)
def get_usdtwd():
    for _ in range(3):
        try:
            time.sleep(0.3)
            hist = yf.Ticker("TWD=X").history(period="5d")
            if not hist.empty:
                return float(hist['Close'].dropna().iloc[-1])
        except:
            time.sleep(1)
    return 32.5

@st.cache_data(ttl=3600)
def get_fx_data():
    for _ in range(3):
        try:
            time.sleep(0.3)
            data = yf.Ticker("TWD=X").history(period="1y").dropna(subset=['Close'])
            if not data.empty:
                data['MA20'] = data['Close'].rolling(window=20).mean()
                data['MA60'] = data['Close'].rolling(window=60).mean()
                return data
        except:
            time.sleep(1)
    return pd.DataFrame()

@st.cache_data(ttl=900)
def get_stock_data(sym):
    is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
    for _ in range(3):
        try:
            time.sleep(0.3)
            df = yf.download(sym, period="3y", progress=False)
            if not df.empty and len(df) >= 252:
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                df.index = df.index.tz_localize(None)
                df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
                
                df['MA10'] = df['Close'].rolling(10).mean()
                df['MA20'] = df['Close'].rolling(20).mean()
                
                if is_tw:
                    df['季線'] = df['Close'].rolling(60).mean()
                    df['半年線'] = df['Close'].rolling(120).mean()
                    df['年線'] = df['Close'].rolling(240).mean()
                else:
                    df['季線'] = df['Close'].rolling(50).mean()
                    df['半年線'] = df['Close'].rolling(100).mean()
                    df['年線'] = df['Close'].rolling(200).mean()
                
                low_min = df['Low'].rolling(9).min()
                high_max = df['High'].rolling(9).max()
                rsv = (df['Close'] - low_min) / (high_max - low_min) * 100
                df['K_d'] = rsv.ewm(com=2, adjust=False).mean()
                df['D_d'] = df['K_d'].ewm(com=2, adjust=False).mean()
                
                df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
                df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
                df['MACD'] = df['EMA12'] - df['EMA26']
                df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
                df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
                
                return df
        except:
            time.sleep(1)
    return None

@st.cache_data(ttl=900)
def process_technical_analysis(sym, name):
    try:
        df = get_stock_data(sym)
        if df is None: return None
        is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
        market = '台股' if is_tw else '美股'
        
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        df_w['K_w'] = ((df_w['Close'] - df_w['Low'].rolling(9).min()) / (df_w['High'].rolling(9).max() - df_w['Low'].rolling(9).min()) * 100).ewm(com=2, adjust=False).mean()
        df_w['D_w'] = df_w['K_w'].ewm(com=2, adjust=False).mean()
        
        df_w['EMA12'] = df_w['Close'].ewm(span=12, adjust=False).mean()
        df_w['EMA26'] = df_w['Close'].ewm(span=26, adjust=False).mean()
        df_w['MACD'] = df_w['EMA12'] - df_w['EMA26']
        df_w['MACD_Signal'] = df_w['MACD'].ewm(span=9, adjust=False).mean()
        
        last_p = float(df['Close'].iloc[-1])
        ma20 = float(df['MA20'].iloc[-1]) if pd.notna(df['MA20'].iloc[-1]) else 0
        ma_season = float(df['季線'].iloc[-1]) if pd.notna(df['季線'].iloc[-1]) else 0
        ma_half = float(df['半年線'].iloc[-1]) if pd.notna(df['半年線'].iloc[-1]) else 0
        ma_year = float(df['年線'].iloc[-1]) if pd.notna(df['年線'].iloc[-1]) else 0
        high_52w = df['High'].tail(252).max()
        
        k_d, d_d = float(df['K_d'].iloc[-1]), float(df['D_d'].iloc[-1])
        pk_d, pd_d = float(df['K_d'].iloc[-2]), float(df['D_d'].iloc[-2])
        k_w, d_w = float(df_w['K_w'].iloc[-1]), float(df_w['D_w'].iloc[-1])
        pk_w, pd_w = float(df_w['K_w'].iloc[-2]), float(df_w['D_w'].iloc[-2])
        
        kd_d_status = "🟢 金叉轉強" if (k_d > d_d and pk_d <= pd_d) else ("🔴 死亡交叉" if (k_d < d_d and pk_d >= pd_d) else "趨勢延續")
        kd_w_status = "🟢 金叉轉強" if (k_w > d_w and pk_w <= pd_w) else ("🔴 死亡交叉" if (k_w < d_w and pk_w >= pd_w) else "趨勢延續")

        macd_d, macds_d = float(df['MACD'].iloc[-1]), float(df['MACD_Signal'].iloc[-1])
        pmacd_d, pmacds_d = float(df['MACD'].iloc[-2]), float(df['MACD_Signal'].iloc[-2])
        macd_w, macds_w = float(df_w['MACD'].iloc[-1]), float(df_w['MACD_Signal'].iloc[-1])
        pmacd_w, pmacds_w = float(df_w['MACD'].iloc[-2]), float(df_w['MACD_Signal'].iloc[-2])
        
        macd_d_status = "🟢 金叉" if (macd_d > macds_d and pmacd_d <= pmacds_d) else ("🔴 死叉" if (macd_d < macds_d and pmacd_d >= pmacds_d) else "趨勢延續")
        macd_w_status = "🟢 金叉" if (macd_w > macds_w and pmacd_w <= pmacds_w) else ("🔴 死叉" if (macd_w < macds_w and pmacd_w >= pmacds_w) else "趨勢延續")
        
        alerts = []
        if last_p < ma20: alerts.append("跌破MA20")
        if high_52w > 0 and (high_52w - last_p) / high_52w >= 0
