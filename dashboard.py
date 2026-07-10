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
    try:
        return float(val) if pd.notna(val) and str(val).strip() != '' else 0.0
    except:
        return 0.0

# ==========================================
# 1. 資料庫與清單設定 (Google Sheets 雙分頁連線)
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0)
    df_tw = df_tw.dropna(subset=['Ticker'])
    if '名稱' not in df_tw.columns: df_tw['名稱'] = ''
    if 'Shares' not in df_tw.columns: df_tw['Shares'] = 0.0
    if '出借' not in df_tw.columns: df_tw['出借'] = 0.0
    if '類別' not in df_tw.columns: df_tw['類別'] = '台股'
    PORTFOLIO_TW = df_tw.to_dict('records')
except Exception as e:
    st.error(f"⚠️ 無法讀取台股資料，請確認試算表內有『TW_Portfolio』工作表。錯誤: {e}")
    PORTFOLIO_TW = []
    df_tw = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "出借", "類別"])

try:
    df_us = conn.read(worksheet="US_Portfolio", ttl=0)
    df_us = df_us.dropna(subset=['Ticker'])
    if '名稱' not in df_us.columns: df_us['名稱'] = ''
    if 'Shares' not in df_us.columns: df_us['Shares'] = 0.0
    if '複委託' not in df_us.columns: df_us['複委託'] = 0.0
    if '類別' not in df_us.columns: df_us['類別'] = '美股'
    PORTFOLIO_US = df_us.to_dict('records')
except Exception as e:
    st.warning(f"⚠️ 無法讀取美股資料，請確認試算表內有『US_Portfolio』工作表。錯誤: {e}")
    PORTFOLIO_US = []
    df_us = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "複委託", "類別"])

# ==========================================
# 2. 核心抓取與計算邏輯 (🌟 終極修復：導正 6 位數台股代碼分流)
# ==========================================
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip()
    # 只有明確帶字母 'B' 的債券、或含有其他字母的櫃買權證才走 .TWO
    if re.match(r'^\d+B$', ticker) or (not ticker.isdigit() and '.' not in ticker):
        return f"{ticker}.TWO"
    # 所有的 4 位數、6 位數純數字股票/ETF (0050, 006208, 009815 等) 一律回歸標準的 .TW
    return f"{ticker}.TW"

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

@st.cache_data(ttl=3600)
def get_benchmark_returns():
    benchmarks = {'台股': 0.0, '美股': 0.0}
    try:
        tw_hist = yf.Ticker("^TWII").history(period="1y").dropna(subset=['Close'])
        if len(tw_hist) > 252:
            benchmarks['台股'] = ((tw_hist['Close'].iloc[-1] - tw_hist['Close'].iloc[-252]) / tw_hist['Close'].iloc[-252]) * 100
        elif not tw_hist.empty:
            benchmarks['台股'] = ((tw_hist['Close'].iloc[-1] - tw_hist['Close'].iloc[0]) / tw_hist['Close'].iloc[0]) * 100
    except: pass
    try:
        us_hist = yf.Ticker("^GSPC").history(period="1y").dropna(subset=['Close'])
        if len(us_hist) > 252:
            benchmarks['美股'] = ((us_hist['Close'].iloc[-1] - us_hist['Close'].iloc[-252]) / us_hist['Close'].iloc[-252]) * 100
        elif not us_hist.empty:
            benchmarks['美股'] = ((us_hist['Close'].iloc[-1] - us_hist['Close'].iloc[0]) / us_hist['Close'].iloc[0]) * 100
    except: pass
    return benchmarks

@st.cache_data(ttl=3600)
def get_fundamental_info(sym):
    try:
        time.sleep(0.2)
        info = yf.Ticker(sym).info
        return {
            'quoteType': info.get('quoteType'),
            'beta': info.get('beta'),
            'grossMargins': info.get('grossMargins'),
            'operatingMargins': info.get('operatingMargins'),
            'profitMargins': info.get('profitMargins'),
            'returnOnEquity': info.get('returnOnEquity')
        }
    except:
        return {}

@st.cache_data(ttl=900)
def get_stock_data(sym):
    is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
    for _ in range(3):
        try:
            time.sleep(0.3)
            # 🌟 100% 回歸原點：使用最初運作最穩定、無衝突的 yf.download 引擎
            df = yf.download(sym, period="3y", progress=False)
            if not df.empty and len(df) >= 2:
                if isinstance(df.columns, pd.MultiIndex): 
                    df.columns = df.columns.get_level_values(0)
                
                if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
                    df.index = df.index.tz_convert(None)
                    
                df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
                
                df['MA10'] = df['Close'].rolling(10, min_periods=1).mean()
                df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
                
                if is_tw:
                    df['季線'] = df['Close'].rolling(60, min_periods=1).mean()
                    df['半年線'] = df['Close'].rolling(120, min_periods=1).mean()
                    df['年線'] = df['Close'].rolling(240, min_periods=1).mean()
                else:
                    df['季線'] = df['Close'].rolling(50, min_periods=1).mean()
                    df['半年線'] = df['Close'].rolling(100, min_periods=1).mean()
                    df['年線'] = df['Close'].rolling(200, min_periods=1).mean()
                
                low_min = df['Low'].rolling(9, min_periods=1).min()
                high_max = df['High'].rolling(9, min_periods=1).max()
                
                rsv = (df['Close'] - low_min) / (high_max - low_min + 1e-9) * 100
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
def get_perf_div_data(sym, display_ticker, market, bench_returns):
    for _ in range(3):
        try:
            time.sleep(0.3)
            tk = yf.Ticker(sym)
            hist = tk.history(period="3y") 
            if not hist.empty:
                valid_hist = hist['Close'].dropna()
                if valid_hist.empty: return None
                
                curr_p = float(valid_hist.iloc[-1])
                
                def calc_ret(days_back):
                    if len(valid_hist) > days_back:
                        past_p = float(valid_hist.iloc[-days_back])
                        return ((curr_p - past_p) / past_p) * 100 if past_p > 0 else None
                    return None

                ret_1q = calc_ret(63)
                ret_6m = calc_ret(126)
                
                is_new_stock = False
                if len(valid_hist) > 252:
                    ret_1y = ((curr_p - float(valid_hist.iloc[-252])) / float(valid_hist.iloc[-252])) * 100
                else:
                    ret_1y = ((curr_p - float(valid_hist.iloc[0])) / float(valid_hist.iloc[0])) * 100
                    is_new_stock = True

                bench_ret = bench_returns.get(market, 0.0)
                if ret_1y is not None:
                    rel_val = ret_1y - bench_ret
                    emoji = "🟢" if rel_val >= 0 else "🔴"
                    sign = "+" if rel_val > 0 else ""
                    suffix = " (上市至今)" if is_new_stock else ""
                    rel_str_display = f"{emoji} {sign}{rel_val:.2f} %{suffix}"
                else:
                    rel_str_display = "暫無資料"

                f_info = get_fundamental_info(sym)
                quote_type = str(f_info.get('quoteType', '')).upper()
                is_etf = 'ETF' in quote_type or 'MUTUALFUND' in quote_type
                
                def fmt_pct(val):
                    if is_etf: return "ETF/不適用"
                    return f"{val * 100:.1f} %" if val is not None and pd.notna(val) else "暫無資料"

                gross_m = fmt_pct(f_info.get('grossMargins'))
                op_m = fmt_pct(f_info.get('operatingMargins'))
                prof_m = fmt_pct(f_info.get('profitMargins'))
                roe = fmt_pct(f_info.get('returnOnEquity'))

                div_records = []
                tot_div = 0.0
                if 'Dividends' in hist.columns:
                    divs = hist['Dividends']
                    divs = divs[divs > 0]
                    divs_desc = divs.sort_index(ascending=False)
                    for date, val in divs_desc.items():
                        date_str = date.strftime('%Y-%m-%d')
                        div_records.append(f"{date_str}: ${val:.2f}")
                        tot_div += float(val)

                div_history_str = " / ".join(div_records) if div_records else "無配息紀錄"
                yield_1y = (tot_div / curr_p) * 100 if curr_p > 0 and tot_div > 0 else 0.0

                return {
                    "市場": market,
                    "標的": display_ticker,
                    "最新收盤價": curr_p,
                    "近一季報酬": ret_1q,
                    "近半年報酬": ret_6m,
                    "近一年報酬": ret_1y,
                    "相對大盤(1年)": rel_str_display,
                    "近一年殖利率": yield_1y,
                    "總配息金額": tot_div,
                    "近一年配息明細": div_history_str,
                    "毛利率": gross_m,
                    "營益率": op_m,
                    "淨利率": prof_m,
                    "ROE": roe
                }
        except:
            time.sleep(1)
    return None

@st.cache_data(ttl=900)
def process_technical_analysis(sym, name):
    try:
        df = get_stock_data(sym)
        if df is None or df.empty:
            raise ValueError("歷史 K 線載入失敗")
            
        is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
        market = '台股' if is_tw else '美股'
        
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        has_enough_weekly = len(df_w) >= 2
        
        if has_enough_weekly:
            low_min_w = df_w['Low'].rolling(9, min_periods=1).min()
            high_max_w = df_w['High'].rolling(9, min_periods=1).max()
            rsv_w = (df_w['Close'] - low_min_w) / (high_max_w - low_min_w + 1e-9) * 100
            df_w['K_w'] = rsv_w.ewm(com=2, adjust=False).mean()
            df_w['D_w'] = df_w['K_w'].ewm(com=2, adjust=False).mean()
            df_w['EMA12'] = df_w['Close'].ewm(span=12, adjust=False).mean()
            df_w['EMA26'] = df_w['Close'].ewm(span=26, adjust=False).mean()
            df_w['MACD'] = df_w['EMA12'] - df_w['EMA26']
            df_w['MACD_Signal'] = df_w['MACD'].ewm(span=9, adjust=False).mean()
        
        last_p = float(df['Close'].iloc[-1]) if len(df) > 0 else 0
        ma10 = float(df['MA10'].iloc[-1]) if len(df) > 0 and pd.notna(df['MA10'].iloc[-1]) else 0
        ma20 = float(df['MA20'].iloc[-1]) if len(df) > 0 and pd.notna(df['MA20'].iloc[-1]) else 0
        ma_season = float(df['季線'].iloc[-1]) if len(df) > 0 and pd.notna(df['季線'].iloc[-1]) else 0
        ma_half = float(df['半年線'].iloc[-1]) if len(df) > 0 and pd.notna(df['半年線'].iloc[-1]) else 0
        ma_year = float(df['年線'].iloc[-1]) if len(df) > 0 and pd.notna(df['年線'].iloc[-1]) else 0
        
        high_52w = df['High'].tail(252).max() if len(df) > 0 else 0
        low_52w = df['Low'].tail(252).min() if len(df) > 0 else 0
        pos_52w = ((last_p - low_52w) / (high_52w - low_52w + 1
