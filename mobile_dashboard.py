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
import traceback
import requests
import io
from streamlit_gsheets import GSheetsConnection

warnings.filterwarnings('ignore')

st.set_page_config(page_title="行動隨身投資儀表板", layout="wide")

# ==========================================
# 0. 輔助函式：強力防呆安全轉換與均線位階
# ==========================================
def safe_float(val):
    try:
        if isinstance(val, str):
            val = re.sub(r'[^\d.-]', '', val)
        return float(val) if pd.notna(val) and str(val).strip() != '' else 0.0
    except:
        return 0.0

def analyze_ma_relation(price, ma_s1, ma_s2, ma_l1, ma_l2):
    short_term_name = "月/季線" if pd.notna(ma_s1) and ma_s2 != ma_l1 else "短中線"
    status = ""
    if pd.notna(ma_s1) and pd.notna(ma_s2) and ma_s1 > 0 and ma_s2 > 0:
        if price > ma_s1 and price > ma_s2: status += f"🟢 站穩 {short_term_name}"
        elif price < ma_s1 and price < ma_s2: status += f"🔴 {short_term_name} 之下"
        elif price > ma_s2 and price < ma_s1: status += f"🟡 守季線，受月線壓"
        elif price > ma_s1 and price < ma_s2: status += f"🔵 站月線，臨季線壓"
    else:
        status += "均線不足"
        
    status += " | "
    if pd.notna(ma_l1) and pd.notna(ma_l2) and ma_l1 > 0 and ma_l2 > 0:
        if price > ma_l1 and price > ma_l2: status += f"🟢 長線多頭"
        elif price < ma_l1 and price < ma_l2: status += f"🔴 長線空頭"
        elif price > ma_l2 and price < ma_l1: status += f"🟡 守年線"
        elif price > ma_l1 and price < ma_l2: status += f"🔵 臨年線壓"
    else:
        status += "均線不足"
    return status

# ==========================================
# 1. 資料庫與清單設定 (Google Sheets 連線)
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

def load_and_standardize_portfolio(worksheet_name, default_category):
    try:
        df = conn.read(worksheet=worksheet_name, ttl=0)
        if df is None or df.empty:
            return pd.DataFrame()
            
        df.columns = [str(c).strip() for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]
        
        col_map = {}
        for c in df.columns:
            cl = c.lower()
            if cl in ['ticker', 'symbol', '代號', '股票代號', '標的代號']: col_map[c] = 'Ticker'
            elif cl in ['name', '名稱', '標的名稱', '股票名稱']: col_map[c] = '名稱'
            elif cl in ['shares', '股數', '持有股數', '庫存', '數量']: col_map[c] = 'Shares'
            elif cl in ['出借', '借券', '複委託']: col_map[c] = '出借' if default_category == '台股' else '複委託'
            elif cl in ['類別', 'category', '分類', '市場']: col_map[c] = '類別'
            
        df = df.rename(columns=col_map)
        
        if 'Ticker' not in df.columns and len(df.columns) > 0:
            df = df.rename(columns={df.columns[0]: 'Ticker'})
            
        if 'Ticker' in df.columns:
            df = df.dropna(subset=['Ticker'])
            df = df[df['Ticker'].astype(str).str.strip() != '']
        else:
            return pd.DataFrame()
            
        if '名稱' not in df.columns: df['名稱'] = ''
        if 'Shares' not in df.columns: df['Shares'] = 0.0
        
        if default_category == '台股' and '出借' not in df.columns: df['出借'] = 0.0
        elif default_category == '美股' and '複委託' not in df.columns: df['複委託'] = 0.0
        
        if '類別' not in df.columns: df['類別'] = default_category
        
        return df
    except Exception as e:
        return pd.DataFrame()

df_tw = load_and_standardize_portfolio("TW_Portfolio", "台股")
if not df_tw.empty:
    PORTFOLIO_TW = df_tw.to_dict('records')
else:
    PORTFOLIO_TW = []
    df_tw = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "出借", "類別"])

df_us = load_and_standardize_portfolio("US_Portfolio", "美股")
if not df_us.empty:
    PORTFOLIO_US = df_us.to_dict('records')
else:
    PORTFOLIO_US = []
    df_us = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "複委託", "類別"])

# ==========================================
# 2. 核心抓取與計算邏輯
# ==========================================
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip().upper()
    if ticker.endswith('.TW') or ticker.endswith('.TWO'): return ticker
    if ticker.endswith('B') or ticker.endswith('C') or ticker == '009815': return f"{ticker}.TWO"
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
                div_1y = float(hist['Dividends'].sum()) if 'Dividends' in hist.columns else 0.0
                return price, div_2026, div_1y
        except: time.sleep(1)
    return 0.0, 0.0, 0.0

@st.cache_data(ttl=900)
def get_usdtwd():
    for _ in range(3):
        try:
            time.sleep(0.3)
            hist = yf.Ticker("TWD=X").history(period="5d")
            if not hist.empty: return float(hist['Close'].dropna().iloc[-1])
        except: time.sleep(1)
    return 32.5

@st.cache_data(ttl=3600)
def get_fx_data():
    for _ in range(3):
        try:
            time.sleep(0.3)
            data = yf.Ticker("TWD=X").history(period="1y").dropna(subset=['Close'])
            if not data.empty:
                data['MA20'] = data['Close'].rolling(window=20, min_periods=1).mean()
                data['MA60'] = data['Close'].rolling(window=60, min_periods=1).mean()
                return data
        except: time.sleep(1)
    return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_benchmark_returns():
    benchmarks = {'台股': 0.0, '美股': 0.0}
    try:
        tw_hist = yf.Ticker("^TWII").history(period="1y").dropna(subset=['Close'])
        if len(tw_hist) > 252: benchmarks['台股'] = ((tw_hist['Close'].iloc[-1] - tw_hist['Close'].iloc[-252]) / tw_hist['Close'].iloc[-252]) * 100
        elif not tw_hist.empty: benchmarks['台股'] = ((tw_hist['Close'].iloc[-1] - tw_hist['Close'].iloc[0]) / tw_hist['Close'].iloc[0]) * 100
    except: pass
    try:
        us_hist = yf.Ticker("^GSPC").history(period="1y").dropna(subset=['Close'])
        if len(us_hist) > 252: benchmarks['美股'] = ((us_hist['Close'].iloc[-1] - us_hist['Close'].iloc[-252]) / us_hist['Close'].iloc[-252]) * 100
        elif not us_hist.empty: benchmarks['美股'] = ((us_hist['Close'].iloc[-1] - us_hist['Close'].iloc[0]) / us_hist['Close'].iloc[0]) * 100
    except: pass
    return benchmarks

@st.cache_data(ttl=3600)
def get_fundamental_info(sym):
    try:
        time.sleep(0.1)
        info = yf.Ticker(sym).info
        return {
            'quoteType': info.get('quoteType'),
            'beta': info.get('beta'),
            'grossMargins': info.get('grossMargins'),
            'operatingMargins': info.get('operatingMargins'),
            'profitMargins': info.get('profitMargins'),
            'returnOnEquity': info.get('returnOnEquity'),
            'trailingPE': info.get('trailingPE'),
            'forwardPE': info.get('forwardPE')
        }
    except: return {}

@st.cache_data(ttl=900)
def get_stock_data(sym):
    is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
    for _ in range(3):
        try:
            time.sleep(0.3)
            df = yf.download(sym, period="3y", progress=False, threads=False)
            if not df.empty and len(df) >= 2:
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None: df.index = df.index.tz_convert(None)
                    
                available_cols = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume'] if c in df.columns]
                df = df[available_cols].astype(float).dropna(subset=['Close'])
                if 'Close' not in df.columns: continue
                
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
                
                if 'High' in df.columns and 'Low' in df.columns:
                    low_min = df['Low'].rolling(9, min_periods=1).min()
                    high_max = df['High'].rolling(9, min_periods=1).max()
                    rsv = (df['Close'] - low_min) / (high_max - low_min + 1e-9) * 100
                    df['K_d'] = rsv.ewm(com=2, adjust=False).mean()
                    df['D_d'] = df['K_d'].ewm(com=2, adjust=False).mean()
                else:
                    df['K_d'] = 50.0; df['D_d'] = 50.0
                
                df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
                df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
                df['MACD'] = df['EMA12'] - df['EMA26']
                df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
                df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
                
                return df
        except: time.sleep(1)
    return None

@st.cache_data(ttl=900)
def get_perf_div_data(sym, display_ticker, market, bench_returns):
    for _ in range(3):
        try:
            time.sleep(0.3)
            tk = yf.Ticker(sym)
            hist = tk.history(period="2y", auto_adjust=True) 
            if not hist.empty:
                valid_hist = hist['Close'].dropna()
                if valid_hist.empty: return None
                
                curr_p = float(valid_hist.iloc[-1])
                
                def calc_ret(days_back):
                    if len(valid_hist) > days_back:
                        past_p = float(valid_hist.iloc[-days_back])
                        return ((curr_p - past_p) / past_p) * 100 if past_p > 0 else 0.0
                    elif len(valid_hist) > 0:
                        past_p = float(valid_hist.iloc[0])
                        return ((curr_p - past_p) / past_p) * 100 if past_p > 0 else 0.0
                    return 0.0

                ret_1q = calc_ret(63)
                ret_6m = calc_ret(126)
                
                if len(valid_hist) > 252:
                    ret_1y = ((curr_p - float(valid_hist.iloc[-252])) / float(valid_hist.iloc[-252])) * 100
                else:
                    ret_1y = ((curr_p - float(valid_hist.iloc[0])) / float(valid_hist.iloc[0])) * 100

                bench_ret = bench_returns.get(market, 0.0)
                rel_val = ret_1y - bench_ret

                f_info = get_fundamental_info(sym)
                is_etf = 'ETF' in str(f_info.get('quoteType', '')).upper() or 'MUTUALFUND' in str(f_info.get('quoteType', '')).upper()
                
                roe_raw = f_info.get('returnOnEquity')
                roe_val = None
                if roe_raw is not None and not is_etf:
                    try:
                        roe_val = float(roe_raw) * 100
                    except: pass

                div_records = []
                tot_div = 0.0
                if 'Dividends' in hist.columns:
                    divs = hist['Dividends'][hist['Dividends'] > 0]
                    for date, val in divs.sort_index(ascending=False).items():
                        div_records.append(f"{date.strftime('%Y-%m-%d')}: ${val:.2f}")
                        tot_div += float(val)

                div_history_str = " / ".join(div_records) if div_records else "無配息紀錄"
                yield_1y = (tot_div / curr_p) * 100 if curr_p > 0 and tot_div > 0 else 0.0

                return {
                    "市場": market, "代號": display_ticker, "最新收盤價": curr_p,
                    "近一季含息報酬": float(ret_1q), "近半年含息報酬": float(ret_6m), "近一年含息報酬": float(ret_1y),
                    "相對大盤": float(rel_val), "近一年殖利率": float(yield_1y), "總配息金額": float(tot_div),
                    "近一年配息明細": div_history_str, "ROE": roe_val
                }
        except: time.sleep(1)
    return None

# 🚀 終極重構：解除天數限制，單一真相來源，PC/手機 100% 同步
@st.cache_data(ttl=900)
def process_technical_analysis(sym, name, market):
    try:
        df = get_stock_data(sym)
        if df is None or df.empty or len(df) < 2: 
            return None
            
        has_enough_weekly = False
        k_w, d_w, macd_w, macds_w = 0.0, 0.0, 0.0, 0.0
        
        try:
            agg_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
            available_cols = [c for c in agg_dict.keys() if c in df.columns]
            agg_dict = {c: agg_dict[c] for c in available_cols}
            
            df_w = df.resample('W-FRI').agg(agg_dict).dropna(subset=['Close'])
            if len(df_w) >= 2: 
                has_enough_weekly = True
                if 'High' in df_w.columns and 'Low' in df_w.columns:
                    low_min_w = df_w['Low'].rolling(9, min_periods=1).min()
                    high_max_w = df_w['High'].rolling(9, min_periods=1).max()
                    rsv_w = (df_w['Close'] - low_min_w) / (high_max_w - low_min_w + 1e-9) * 100
                    df_w['K_w'] = rsv_w.ewm(com=2, adjust=False).mean()
                    df_w['D_w'] = df_w['K_w'].ewm(com=2, adjust=False).mean()
                else:
                    df_w['K_w'] = 50.0; df_w['D_w'] = 50.0
                    
                df_w['EMA12'] = df_w['Close'].ewm(span=12, adjust=False).mean()
                df_w['EMA26'] = df_w['Close'].ewm(span=26, adjust=False).mean()
                df_w['MACD'] = df_w['EMA12'] - df_w['EMA26']
                df_w['MACD_Signal'] = df_w['MACD'].ewm(span=9, adjust=False).mean()
                
                k_w = float(df_w['K_w'].iloc[-1]) if pd.notna(df_w['K_w'].iloc[-1]) else 50.0
                d_w = float(df_w['D_w'].iloc[-1]) if pd.notna(df_w['D_w'].iloc[-1]) else 50.0
                macd_w = float(df_w['MACD'].iloc[-1]) if pd.notna(df_w['MACD'].iloc[-1]) else 0.0
                macds_w = float(df_w['MACD_Signal'].iloc[-1]) if pd.notna(df_w['MACD_Signal'].iloc[-1]) else 0.0
        except: pass
        
        last_p = float(df['Close'].iloc[-1])
        prev_p = float(df['Close'].iloc[-2]) if len(df) > 1 else last_p
        
        ma10 = float(df['MA10'].iloc[-1]) if pd.notna(df['MA10'].iloc[-1]) else 0.0
        ma20 = float(df['MA20'].iloc[-1]) if pd.notna(df['MA20'].iloc[-1]) else 0.0
        ma_season = float(df['季線'].iloc[-1]) if pd.notna(df['季線'].iloc[-1]) else 0.0
        ma_half = float(df['半年線'].iloc[-1]) if pd.notna(df['半年線'].iloc[-1]) else 0.0
        ma_year = float(df['年線'].iloc[-1]) if pd.notna(df['年線'].iloc[-1]) else 0.0
        
        prev_ma20 = float(df['MA20'].iloc[-2]) if len(df) > 1 and pd.notna(df['MA20'].iloc[-2]) else 0.0
        prev_ma_season = float(df['季線'].iloc[-2]) if len(df) > 1 and pd.notna(df['季線'].iloc[-2]) else 0.0

        ma_status_str = analyze_ma_relation(last_p, ma20, ma_season, ma_half, ma_year)
        is_break_ma = (last_p < ma20 and prev_p >= prev_ma20) or (last_p < ma_season and prev_p >= prev_ma_season)

        ma20_up_5d, ma_s_up_5d = False, False
        ma20_dn_5d, ma_s_dn_5d = False, False
        above_ma20_5d, below_ma20_5d = False, False
        above_mas_5d, below_mas_5d = False, False

        if len(df) >= 6:
            if pd.notna(df['MA20'].iloc[-6]):
                ma20_up_5d = all(df['MA20'].iloc[i] > df['MA20'].iloc[i-1] for i in range(-1, -6, -1))
                ma20_dn_5d = all(df['MA20'].iloc[i] < df['MA20'].iloc[i-1] for i in range(-1, -6, -1))
                above_ma20_5d = all(df['Close'].iloc[i] > df['MA20'].iloc[i] for i in range(-5, 0))
                below_ma20_5d = all(df['Close'].iloc[i] < df['MA20'].iloc[i] for i in range(-5, 0))
            
            if pd.notna(df['季線'].iloc[-6]):
                ma_s_up_5d = all(df['季線'].iloc[i] > df['季線'].iloc[i-1] for i in range(-1, -6, -1))
                ma_s_dn_5d = all(df['季線'].iloc[i] < df['季線'].iloc[i-1] for i in range(-1, -6, -1))
                above_mas_5d = all(df['Close'].iloc[i] > df['季線'].iloc[i] for i in range(-5, 0))
                below_mas_5d = all(df['Close'].iloc[i] < df['季線'].iloc[i] for i in range(-5, 0))

        ret_5d = 0.0
        has_ret_5d = False
        if len(df) >= 6 and pd.notna(df['Close'].iloc[-6]) and df['Close'].iloc[-6] > 0:
            ret_5d = ((last_p - df['Close'].iloc[-6]) / df['Close'].iloc[-6]) * 100
            has_ret_5d = True

        high_52w = df['High'].tail(252).max() if 'High' in df.columns else 0.0
        low_52w = df['Low'].tail(252).min() if 'Low' in df.columns else 0.0
        pos_52w = ((last_p - low_52w) / (high_52w - low_52w + 1e-9) * 100) if (high_52w - low_52w) > 0 else 50.0

        high_20d = df['High'].tail(20).max() if 'High' in df.columns else 0.0
        low_20d = df['Low'].tail(20).min() if 'Low' in df.columns else 0.0
        
        k_d = float(df['K_d'].iloc[-1]) if 'K_d' in df.columns and pd.notna(df['K_d'].iloc[-1]) else 50.0
        d_d = float(df['D_d'].iloc[-1]) if 'D_d' in df.columns and pd.notna(df['D_d'].iloc[-1]) else 50.0
        
        macd_d = float(df['MACD'].iloc[-1]) if 'MACD' in df.columns and pd.notna(df['MACD'].iloc[-1]) else 0.0
        macds_d = float(df['MACD_Signal'].iloc[-1]) if 'MACD_Signal' in df.columns and pd.notna(df['MACD_Signal'].iloc[-1]) else 0.0

        w_macd_gold, w_kd_gold = False, False
        d_macd_gold, d_kd_gold = False, False
        w_macd_death, w_kd_death = False, False
        d_macd_death, d_kd_death = False, False

        if has_enough_weekly and len(df_w) > 1:
            w_macd_gold = macd_w > macds_w and float(df_w['MACD'].iloc[-2]) <= float(df_w['MACD_Signal'].iloc[-2])
            w_kd_gold = k_w > d_w and float(df_w['K_w'].iloc[-2]) <= float(df_w['D_w'].iloc[-2])
            w_macd_death = macd_w < macds_w and float(df_w['MACD'].iloc[-2]) >= float(df_w['MACD_Signal'].iloc[-2])
            w_kd_death = k_w < d_w and float(df_w['K_w'].iloc[-2]) >= float(df_w['D_w'].iloc[-2])

        if len(df) > 1:
            d_macd_gold = macd_d > macds_d and float(df['MACD'].iloc[-2]) <= float(df['MACD_Signal'].iloc[-2])
            d_kd_gold = k_d > d_d and float(df['K_d'].iloc[-2]) <= float(df['D_d'].iloc[-2])
            d_macd_death = macd_d < macds_d and float(df['MACD'].iloc[-2]) >= float(df['MACD_Signal'].iloc[-2])
            d_kd_death = k_d < d_d and float(df['K_d'].iloc[-2]) >= float(df['D_d'].iloc[-2])

        tags = []
        bull_score = 0
        bear_score = 0

        has_w_macd_low_gold = w_macd_gold and (macd_w < 0)
        has_w_kd_low_gold = w_kd_gold and (k_w < 30)
        has_w_macd_high_death = w_macd_death and (macd_w > 0)
        has_w_kd_high_death = w_kd_death and (k_w > 70)

        if w_macd_gold:
            tags.append("週MACD零下金叉" if has_w_macd_low_gold else "週MACD一般金叉")
            bull_score += 4
        if w_kd_gold:
            tags.append("週KD低檔金叉" if has_w_kd_low_gold else "週KD一般金叉")
            bull_score += 3
        if d_macd_gold:
            tags.append("日MACD零下金叉" if macd_d < 0 else "日MACD一般金叉")
            bull_score += 2
        if d_kd_gold:
            tags.append("日KD低檔金叉" if k_d < 30 else "日KD一般金叉")
            bull_score += 1
            
        if ma20_up_5d and ma_s_up_5d: tags.append("月季線雙上彎≥5日"); bull_score += 2
        elif ma20_up_5d: tags.append("月線上彎≥5日"); bull_score += 1
        elif ma_s_up_5d: tags.append("季線上彎≥5日"); bull_score += 1
        
        if above_ma20_5d and above_mas_5d: tags.append("站上月季線≥5日"); bull_score += 2
        elif above_ma20_5d: tags.append("站上月線≥5日"); bull_score += 1
        elif above_mas_5d: tags.append("站上季線≥5日"); bull_score += 1
        
        if has_ret_5d and ret_5d >= 5.0: tags.append(f"近5日上漲{ret_5d:.1f}%"); bull_score += 1

        if w_macd_death:
            tags.append("週MACD零上死叉" if has_w_macd_high_death else "週MACD一般死叉")
            bear_score += 4
        if w_kd_death:
            tags.append("週KD高檔死叉" if has_w_kd_high_death else "週KD一般死叉")
            bear_score += 3
        if d_macd_death:
            tags.append("日MACD零上死叉" if macd_d > 0 else "日MACD一般死叉")
            bear_score += 2
        if d_kd_death:
            tags.append("日KD高檔死叉" if k_d > 70 else "日KD一般死叉")
            bear_score += 1
            
        if is_break_ma: tags.append("跌破短中線"); bear_score += 1
        
        if ma20_dn_5d and ma_s_dn_5d: tags.append("月季線雙下彎≥5日"); bear_score += 2
        elif ma20_dn_5d: tags.append("月線下彎≥5日"); bear_score += 1
        elif ma_s_dn_5d: tags.append("季線下彎≥5日"); bear_score += 1
        
        if below_ma20_5d and below_mas_5d: tags.append("跌破月季線≥5日"); bear_score += 2
        elif below_ma20_5d: tags.append("跌破月線≥5日"); bear_score += 1
        elif below_mas_5d: tags.append("跌破季線≥5日"); bear_score += 1
        
        if has_ret_5d and ret_5d <= -5.0: tags.append(f"近5日下跌{abs(ret_5d):.1f}%"); bear_score += 1

        if high_52w > 0 and (high_52w - last_p) / high_52w >= 0.15:
            tags.append(f"近高點回落{((high_52w - last_p) / high_52w)*100:.1f}%"); bear_score += 2
        if high_20d > 0 and (high_20d - last_p) / high_20d >= 0.10:
            tags.append(f"20日回落{((high_20d - last_p) / high_20d)*100:.1f}%"); bear_score += 1
        if len(df) >= 20 and high_20d > 0 and low_20d > 0:
            amp_20d = (high_20d - low_20d) / low_20d
            if amp_20d <= 0.07: tags.append(f"💤20日窄幅盤整")

        is_strong_buy_eligible = has_w_macd_low_gold or has_w_kd_low_gold
        is_strong_sell_eligible = has_w_macd_high_death or has_w_kd_high_death

        if bull_score > bear_score:
            if bull_score >= 3 and is_strong_buy_eligible:
                action = "[🚀 強勢買進]"
            else:
                action = "[📈 短多轉折]"
        elif bear_score > bull_score:
            if bear_score >= 3 and is_strong_sell_eligible:
                action = "[🛑 強制賣出]"
            else:
                action = "[⚠️ 弱勢減碼]"
        else:
            if bull_score == 0 and bear_score == 0: 
                action = "[➖ 趨勢延續]"
            elif bull_score >= 3 and is_strong_buy_eligible: 
                action = "[⚔️ 多空交戰(偏強)]"
            elif bear_score >= 3 and is_strong_sell_eligible:
                action = "[⚔️ 多空交戰(偏弱)]"
            elif bull_score > 0:
                action = "[⚔️ 多空交戰(震盪)]"
            else:
                action = "[⚔️ 多空交戰]"

        alert_str = f"{action} " + ", ".join(tags) if tags else action

        f_info = get_fundamental_info(sym)
        pe_val = f_info.get('trailingPE')
        try:
            pe_val = float(pe_val)
            pe_str = f"{pe_val:.1f}" if pd.notna(pe_val) else "無"
        except:
            pe_val = None
            pe_str = "無"
            
        beta_val = f_info.get('beta')
        try:
            beta_str = f"{float(beta_val):.2f}" if pd.notna(float(beta_val)) else "無"
        except:
            beta_str = "無"

        return {
            "市場": market, "標的": f"{name} ({sym})", "代號": sym.split('.')[0], 
            "狀態警示": alert_str, "🚨警示": alert_str, "均線位階": ma_status_str,
            "52週位置": f"{pos_52w:.1f} %", "Beta": beta_str, 
            "日KD": f"K:{k_d:.1f}/D:{d_d:.1f}",
            "週KD": f"K:{k_w:.1f}/D:{d_w:.1f}",
            "日MACD": f"DIF:{macd_d:.2f}",
            "週MACD": f"DIF:{macd_w:.2f}",
            "P/E": pe_str, "收盤價": last_p, "MA20": ma20, "季線": ma_season,
            "tags": tags, "bull_score": bull_score, "bear_score": bear_score, "action": action,
            "_raw_pe": pe_val, "_sym": sym, "_name": name
        }
    except Exception as e: 
        return None

# ==========================================
# 3. 網頁 UI 渲染
# ==========================================
st.title("📱 行動投資隨身儀表板")

col_l, col_r = st.columns([1, 2])
with col_l:
    if st.button("🔄 刷新"):
        st.cache_data.clear()
        st.rerun()
with col_r:
    st.caption(f"更新:{datetime.now().strftime('%H:%M')}")

tab1, tab_hl, tab_comp, tab2, tab3, tab_etf, tab4, tab5 = st.tabs(["💰資產", "🎯亮點", "🆚比較", "📈技術", "🏆績效", "🧩成分", "📖心得", "📝管理"])

with tab1:
    with st.spinner("載入報價與算資產中..."):
        usdtwd = get_usdtwd()
        total_market_value, total_dividends_2026, total_dividends_1y = 0, 0, 0
        asset_allocation = {}
        individual_holdings = [] 

        for item in PORTFOLIO_TW:
            ticker_str = str(item.get('Ticker', '')).strip()
            if not ticker_str or ticker_str == 'nan': continue
            
            ticker = get_yf_ticker_tw(ticker_str)
            asset_type = str(item.get('類別', '台股未分類')).strip()
            
            price, div_2026, div_1y = get_basic_data(ticker)
            tot_shares = safe_float(item.get('Shares')) + safe_float(item.get('出借'))
            
            if price > 0 and tot_shares > 0:
                val = price * tot_shares
                div_tot_2026 = div_2026 * tot_shares
                div_tot_1y = div_1y * tot_shares
                total_market_value += val
                total_dividends_2026 += div_tot_2026
                total_dividends_1y += div_tot_1y
                asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val
                
                disp_qty = f"{int(tot_shares/1000)}張" if tot_shares >= 1000 and tot_shares % 1000 == 0 else f"{tot_shares:g}股"
                name_str = str(item.get('名稱', '')).strip()
                display_name = name_str if name_str and name_str != 'nan' else ticker_str
                individual_holdings.append({'標的': display_name, '標的與股數': f"{display_name} ({disp_qty})", '總市值': val, '預估股息': div_tot_2026, '類別': asset_type})

        for item in PORTFOLIO_US:
            ticker_str = str(item.get('Ticker', '')).strip()
            if not ticker_str or ticker_str == 'nan': continue
            
            asset_type = str(item.get('類別', '美股未分類')).strip()
            
            price, div_2026, div_1y = get_basic_data(ticker_str)
            tot_shares = safe_float(item.get('Shares')) + safe_float(item.get('複委託'))
            
            if price > 0 and tot_shares > 0:
                val = price * tot_shares * usdtwd
                div_tot_2026 = div_2026 * tot_shares * usdtwd
                div_tot_1y = div_1y * tot_shares * usdtwd
                total_market_value += val
                total_dividends_2026 += div_tot_2026
                total_dividends_1y += div_tot_1y
                asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val
                
                disp_qty = f"{tot_shares:g}股"
                name_str = str(item.get('名稱', '')).strip()
                display_name = name_str if name_str and name_str != 'nan' else ticker_str
                individual_holdings.append({'標的': display_name, '標的與股數': f"{display_name} ({disp_qty})", '總市值': val, '預估股息': div_tot_2026, '類別': asset_type})

        col_m1, col_m2 = st.columns(2)
        col_m1.metric("總市值", f"${total_market_value:,.0f}")
        col_m2.metric("目前匯率", f"{usdtwd:.3f}")
        
        col_m3, col_m4 = st.columns(2)
        col_m3.metric("2026 預估股息", f"${total_dividends_2026:,.0f}")
        col_m4.metric("近一年累計股息", f"${total_dividends_1y:,.0f}")

        history_error = False
        df_history_to_display = pd.DataFrame()
        try:
            df_history = conn.read(worksheet="Value_History", ttl=0)
            if df_history is not None and not df_history.empty:
                df_history.columns = [str(c).strip().replace(' ', '_') for c in df_history.columns]
                df_history = df_history.loc[:, ~df_history.columns.duplicated()]
                
                if 'Date' in df_history.columns and 'Total_Value' in df_history.columns:
                    df_history['Date'] = pd.to_datetime(df_history['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
                    df_history = df_history.dropna(subset=['Date'])
                    
                    df_history['Total_Value'] = pd.to_numeric(
                        df_history['Total_Value'].astype(str).str.replace(r'[^\d.-]', '', regex=True), 
                        errors='coerce'
                    ).fillna(0)
                    
                    today_str = datetime.now().strftime('%Y-%m-%d')
                    now_time = datetime.now().strftime('%H:%M:%S')
                    
                    if len(df_history) >= 1:
                        if today_str in df_history['Date'].values:
                            idx = df_history.index[df_history['Date'] == today_str].tolist()[0]
                            existing_val = safe_float(df_history.at[idx, 'Total_Value'])
                            if abs(existing_val - total_market_value) > 1:
                                df_history.at[idx, 'Total_Value'] = total_market_value
                                df_history.at[idx, 'Last_Updated'] = now_time
                                conn.update(worksheet="Value_History", data=df_history)
                        else:
                            new_row = pd.DataFrame([{'Date': today_str, 'Total_Value': total_market_value, 'Last_Updated': now_time}])
                            df_history = pd.concat([df_history, new_row], ignore_index=True)
                            conn.update(worksheet="Value_History", data=df_history)
                        df_history_to_display = df_history
                    else:
                        history_error = True
                else:
                    history_error = True
            else:
                history_error = True
        except Exception:
            history_error = True

        if history_error or df_history_to_display.empty or 'Total_Value' not in df_history_to_display.columns:
            df_history_to_display = pd.DataFrame([{'Date': datetime.now().strftime('%Y-%m-%d'), 'Total_Value': total_market_value}])

        if not history_error and not df_history_to_display.empty and len(df_history_to_display) > 1:
            st.divider()
            st.caption("📈 總市值每日變化趨勢")
            df_history_to_display['Total_Value'] = pd.to_numeric(df_history_to_display['Total_Value'], errors='coerce').fillna(0)
            fig_hist = px.line(df_history_to_display, x='Date', y='Total_Value', markers=True)
            fig_hist.update_traces(text=df_history_to_display['Total_Value'], textposition="top center", texttemplate='%{text:,.0f}')
            fig_hist.update_layout(height=260, margin=dict(t=10, b=10, l=10, r=10), yaxis_title=None, xaxis_title=None)
            st.plotly_chart(fig_hist, use_container_width=True)

        if asset_allocation:
            st.divider()
            st.caption("📊 資產類別佔比")
            df_allocation = pd.DataFrame(list(asset_allocation.items()), columns=['類別', '市值'])
            unique_categories = df_allocation['類別'].unique().tolist()
            plotly_colors = px.colors.qualitative.Safe + px.colors.qualitative.Plotly 
            category_color_map = {cat: plotly_colors[i % len(plotly_colors)] for i, cat in enumerate(unique_categories)}
            
            fig_pie = px.pie(df_allocation, values='市值', names='類別', hole=0.4, color='類別', color_discrete_map=category_color_map)
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            fig_pie.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
            st.plotly_chart(fig_pie, use_container_width=True)

        df_ind = pd.DataFrame(individual_holdings)
        if not df_ind.empty:
            st.divider()
            st.caption("📊 各標的總市值分佈 (TWD)")
            df_mv_sorted = df_ind.sort_values(by='總市值', ascending=True)
            dynamic_height = max(300, len(df_mv_sorted) * 35)
            
            fig_mv_bar = px.bar(df_mv_sorted, x='總市值', y='標的與股數', orientation='h', color='類別', text_auto='.2s', color_discrete_map=category_color_map)
            fig_mv_bar.update_layout(height=dynamic_height, margin=dict(l=10, r=10, t=10, b=10), showlegend=False, yaxis={'categoryorder':'array', 'categoryarray': df_mv_sorted['標的與股數']})
            st.plotly_chart(fig_mv_bar, use_container_width=True)

            st.caption("📊 各標的預估股息分佈 (TWD)")
            df_div_sorted = df_ind.sort_values(by='預估股息', ascending=True)
            fig_div_bar = px.bar(df_div_sorted, x='預估股息', y='標的與股數', orientation='h', color='類別', text_auto='.2s', color_discrete_map=category_color_map)
            fig_div_bar.update_layout(height=dynamic_height, margin=dict(l=10, r=10, t=10, b=10), showlegend=False, yaxis={'categoryorder':'array', 'categoryarray': df_div_sorted['標的與股數']})
            st.plotly_chart(fig_div_bar, use_container_width=True)

with tab_hl:
    with st.spinner("掃描技術訊號中..."):
        ta_results = []
        target_options = {}
        
        bullish_strong = [] 
        bullish_daily = []  
        bearish_strong = [] 
        bearish_daily = []
        
        scan_dict = {}
        for item in PORTFOLIO_TW:
            t = str(item.get('Ticker', '')).strip()
            if t and t != 'nan':
                sym = get_yf_ticker_tw(t)
                name = str(item.get('名稱', '')).strip()
                scan_dict[sym] = name if name and name != 'nan' else t
                
        for item in PORTFOLIO_US:
            t = str(item.get('Ticker', '')).strip()
            if t and t != 'nan':
                name = str(item.get('名稱', '')).strip()
                scan_dict[t] = name if name and name != 'nan' else t

        for sym, name in scan_dict.items():
            res = process_technical_analysis(sym, name, '台股' if sym.endswith('.TW') or sym.endswith('.TWO') else '美股')
            if res:
                ta_results.append(res)
                target_options[f"{name}({sym.split('.')[0]})"] = sym
                
                pe_val = res.get('_raw_pe')
                pe_str = f"PE:{pe_val:.1f}" if pd.notna(pe_val) and pe_val is not None else "無PE"
                name_disp = f"{name}({sym.split('.')[0]})"
                
                bull_score = res.get('bull_score', 0)
                bear_score = res.get('bear_score', 0)
                action = res.get('action', '')
                
                item_data = {'name': name_disp, 'pe': pe_val if pd.notna(pe_val) and pe_val is not None else 999, 'pe_str': pe_str, 'tags': res.get('tags', []), 'bull_score': bull_score, 'bear_score': bear_score, 'price': res.get('價格', 0)}
                
                if "[🚀 強勢買進]" in action:
                    bullish_strong.append(item_data)
                elif "[📈 短多轉折]" in action:
                    bullish_daily.append(item_data)
                elif "[🛑 強制賣出]" in action:
                    bearish_strong.append(item_data)
                elif "[⚠️ 弱勢減碼]" in action:
                    bearish_daily.append(item_data)

        bullish_strong = sorted(bullish_strong, key=lambda x: (-x['bull_score'], x['pe']))[:10]
        bullish_daily = sorted(bullish_daily, key=lambda x: (-x['bull_score'], x['pe']))[:10]
        bearish_strong = sorted(bearish_strong, key=lambda x: (-x['bear_score'], x['pe']))[:10]
        bearish_daily = sorted(bearish_daily, key=lambda x: (-x['bear_score'], x['pe']))[:10]
        
    def format_mobile_items(items):
        if not items: return "> 目前無符合條件標的"
        res_str = ""
        for x in items:
            tags_str = ", ".join(x['tags'])
            res_str += f"- **{x['name']}** ({x['pe_str']})\n  - `[{tags_str}]`\n"
        return res_str

    st.markdown("### 📊 盤後技術摘要 (Top 10)")
    st.caption("依技術強度與指標優先，同級別低本益比優先顯示。")
    
    with st.container():
        st.success(f"🔥 **[🚀 強勢買進] Top 10**\n\n{format_mobile_items(bullish_strong)}")
        st.info(f"📈 **[📈 短多轉折] Top 10**\n\n{format_mobile_items(bullish_daily)}")
        st.error(f"🛑 **[🛑 強制賣出] Top 10**\n\n{format_mobile_items(bearish_strong)}")
        st.warning(f"⚠️ **[⚠️ 弱勢減碼] Top 10**\n\n{format_mobile_items(bearish_daily)}")

with tab_comp:
    st.markdown("### 🆚 多檔標的走勢比較")
    st.caption("選擇 2~4 檔標的，比較其區間累計報酬率走勢。")
    
    if 'target_options' in locals() and target_options:
        all_options_list = list(target_options.keys())
        default_selections = all_options_list[:2] if len(all_options_list) >= 2 else None
        
        comp_targets = st.multiselect("請選擇標的 (最多4檔)：", options=all_options_list, default=default_selections, max_selections=4)
        comp_period = st.selectbox("比較期間", ["半年", "一年", "三年"], index=1)
            
        if comp_targets:
            with st.spinner("載入比較數據中..."):
                period_map = {"半年": "6mo", "一年": "1y", "三年": "3y"}
                yf_period = period_map[comp_period]
                
                comp_pct_dict = {}
                for tgt in comp_targets:
                    sym = target_options[tgt]
                    try:
                        hist = yf.Ticker(sym).history(period=yf_period)
                        if not hist.empty and 'Close' in hist.columns:
                            s = hist['Close'].dropna()
                            if len(s) > 0:
                                s.index = pd.to_datetime(s.index).normalize()
                                s = s[~s.index.duplicated(keep='last')]
                                first_p = float(s.iloc[0])
                                if first_p > 0:
                                    comp_pct_dict[tgt] = ((s / first_p) - 1) * 100
                    except: pass
                
                if comp_pct_dict:
                    df_comp_pct = pd.DataFrame(comp_pct_dict).ffill().bfill()
                    if not df_comp_pct.empty:
                        fig_comp = px.line(df_comp_pct, x=df_comp_pct.index, y=df_comp_pct.columns)
                        fig_comp.update_layout(hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), yaxis_title="累計含息報酬率 (%)", xaxis_title=None)
                        st.plotly_chart(fig_comp, use_container_width=True)
                    else:
                        st.warning("選定期間內無足夠數據可供繪製比較圖。")
                else:
                    st.warning("無法取得選定標的的歷史走勢資料。")

            st.divider()
            st.markdown("### 🧩 比較標的之 Top 10 核心持股")
            
            csv_url_comp = "https://docs.google.com/spreadsheets/d/1_crBmjMxgm9qpYeycg_TnLStt3phN6vM4XILmD9x0Yc/gviz/tq?tqx=out:csv&gid=892058804"
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                resp = requests.get(csv_url_comp, headers=headers, timeout=10)
                resp.raise_for_status()
                df_etf_comp_db = pd.read_csv(io.StringIO(resp.text)).dropna(how='all')
            except Exception:
                df_etf_comp_db = pd.DataFrame()

            if not df_etf_comp_db.empty and len(df_etf_comp_db.columns) >= 3:
                etf_c = df_etf_comp_db.columns[0]
                name_c = df_etf_comp_db.columns[1]
                weight_c = df_etf_comp_db.columns[2]
                
                for tgt in comp_targets:
                    st.markdown(f"#### 📌 {tgt}")
                    sym = target_options[tgt]
                    clean_code = sym.split('.')[0]
                    
                    sub_df = df_etf_comp_db[
                        df_etf_comp_db[etf_c].astype(str).str.strip().str.contains(clean_code, case=False, na=False) |
                        df_etf_comp_db[etf_c].astype(str).str.strip().apply(lambda x: x in tgt)
                    ].copy()
                    
                    if not sub_df.empty:
                        sub_df[weight_c] = sub_df[weight_c].astype(str).str.replace(r'[^\d.-]', '', regex=True)
                        sub_df[weight_c] = pd.to_numeric(sub_df[weight_c], errors='coerce')
                        sub_df = sub_df.dropna(subset=[weight_c]).sort_values(by=weight_c, ascending=False).head(10)
                        
                        if not sub_df.empty:
                            top10_sum = sub_df[weight_c].sum()
                            st.caption(f"**Top 10 權重合計：{top10_sum:.2f}%**")
                            
                            disp_df = sub_df[[name_c, weight_c]].copy()
                            disp_df.columns = ["成分股名稱", "權重 (%)"]
                            disp_df["權重 (%)"] = disp_df["權重 (%)"].apply(lambda x: f"{x:.2f}%")
                            st.dataframe(disp_df, hide_index=True, use_container_width=True)
                        else:
                            st.caption("ℹ️ 暫無有效的權重數值。")
                    else:
                        st.caption("ℹ️ 個別股票或未收錄成分股資料。")
                    st.write("") 
            else:
                st.caption("未連線至 ETF 持股資料庫，無法顯示成分股比對。")
    else:
        st.info("請先確認持股清單並等待資料載入。")

with tab2:
    with st.expander("💡 狀態警示規則與名詞定義說明", expanded=False):
        st.markdown("""
        #### 一、 綜合動作評級 (依多空分數與指標嚴格判定)
        * **[🚀 強勢買進]**：多方分數 ≥ 3 **且** 具備「週KD低檔金叉(K<30)」或「週MACD零下金叉」。
        * **[📈 短多轉折]**：多方分數 > 0 (未達強勢買進標準者，如日線金叉或分數雖高但欠缺週低檔金叉)。
        * **[🛑 強制賣出]**：空方分數 ≥ 3 **且** 具備「週KD高檔死叉(K>70)」或「週MACD零上死叉」。
        * **[⚠️ 弱勢減碼]**：空方分數 > 0 (未達強制賣出標準者，如日線死叉或分數雖高但欠缺週高檔死叉)。
        * **[⚔️ 多空交戰]**：同時觸發多空條件，依分數較高者顯示偏強或偏弱。
        * **[➖ 趨勢延續]**：無明顯多空觸發訊號。

        #### 二、 標籤名詞定義
        * **指標交叉**：KD/MACD 日線或週線發生黃金交叉(金叉)或死亡交叉(死叉)。
        * **均線轉折**：月線或季線連續 5 個交易日遞增(上彎)或遞減(下彎)。
        * **價格穿越**：收盤價連續 5 個交易日維持在均線之上(站上)或之下(跌破)。
        * **短期動能**：近 5 個交易日累計漲/跌幅達 5% (含) 以上。
        * **高檔回落**：距過去 52 週最高價跌幅達 15% (或 20日最高價回落 10%)。
        """)
        
    if ta_results: 
        df_ta = pd.DataFrame(ta_results)
        df_ta = df_ta.drop(columns=['tags', 'bull_score', 'bear_score', '_raw_pe', '_sym', '_name'], errors='ignore')
        # 🚀 確保不會再因為找不到 key 報錯，動態篩選出存在於 DataFrame 的欄位
        display_cols = ["標的", "🚨警示", "收盤價", "52週位置"]
        display_cols = [c for c in display_cols if c in df_ta.columns]
        
        st.dataframe(
            df_ta[display_cols], 
            width="stretch", 
            hide_index=True, 
            height=350,
            column_config={
                "🚨警示": st.column_config.TextColumn("🚨 狀態標籤與動作", width="large")
            }
        )

    st.divider()
    selected_name = st.selectbox("查看詳細線圖：", options=list(target_options.keys()) if target_options else [])
    if selected_name:
        sym = target_options[selected_name]
        df_chart = get_stock_data(sym)
        if df_chart is not None:
            df_plot = df_chart.tail(80) 
            fig_tech = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
            
            if 'Open' in df_plot.columns and 'High' in df_plot.columns and 'Low' in df_plot.columns:
                fig_tech.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name='K線', increasing_line_color='red', decreasing_line_color='green'), row=1, col=1)
            else:
                fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Close'], mode='lines', name='收盤價'), row=1, col=1)
                
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MA20'], line=dict(color='blue', width=1.5), name='MA20'), row=1, col=1)
            
            if 'K_d' in df_plot.columns:
                fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['K_d'], line=dict(color='yellow', width=1.2), name='K'), row=2, col=1)
                fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['D_d'], line=dict(color='orange', width=1.2), name='D'), row=2, col=1)
                
            fig_tech.update_layout(xaxis_rangeslider_visible=False, height=400, margin=dict(t=20, b=10, l=10, r=10), showlegend=False)
            st.plotly_chart(fig_tech)

with tab3:
    st.markdown("一覽所有持股與觀察清單的**短中長線報酬率**、**超額大盤表現 (Alpha)**、**基本面財報指標**與**近一年真實配息紀錄**。")
    with st.spinner("正在計算各標的績效與配息資料..."):
        bench_returns = get_benchmark_returns()
        perf_results = []
        scan_list = []
        
        for item in PORTFOLIO_TW:
            t = str(item.get('Ticker', '')).strip()
            if t and t != 'nan': scan_list.append((get_yf_ticker_tw(t), t, '台股'))
                
        for item in PORTFOLIO_US:
            t = str(item.get('Ticker', '')).strip()
            if t and t != 'nan': scan_list.append((t, t, '美股'))
                
        for sym, display_ticker, market in scan_list:
            res = get_perf_div_data(sym, display_ticker, market, bench_returns)
            if res: perf_results.append(res)
                
        if perf_results:
            df_perf = pd.DataFrame(perf_results)
            # 🚀 確保手機版不會因 KeyError 崩潰，動態比對欄位
            display_cols = ["代號", "收盤", "季含息報酬", "年含息報酬", "對大盤", "殖利率", "ROE"]
            display_cols = [c for c in display_cols if c in df_perf.columns]
            
            st.dataframe(
                df_perf[display_cols],
                width="stretch",
                column_config={
                    "代號": st.column_config.TextColumn("代號"),
                    "收盤": st.column_config.NumberColumn("收盤", format="%.2f"),
                    "季含息報酬": st.column_config.NumberColumn("季含息報酬 (%)", format="%+.1f"),
                    "年含息報酬": st.column_config.NumberColumn("年含息報酬 (%)", format="%+.1f"),
                    "對大盤": st.column_config.NumberColumn("對大盤 (%)", format="%+.1f"),
                    "殖利率": st.column_config.NumberColumn("殖利率 (%)", format="%.1f"),
                    "ROE": st.column_config.NumberColumn("ROE (%)", format="%.1f")
                },
                hide_index=True, height=450
            )

# ==========================================
# 🔥 終極修訂版：ETF 匯出直連抓取 (行動版)
# ==========================================
with tab_etf:
    st.markdown("### 🧩 ETF Top 10 成分股")
    
    csv_url = "https://docs.google.com/spreadsheets/d/1_crBmjMxgm9qpYeycg_TnLStt3phN6vM4XILmD9x0Yc/gviz/tq?tqx=out:csv&gid=892058804"
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'}
        response = requests.get(csv_url, headers=headers, timeout=15)
        response.raise_for_status() 
        df_etf_db = pd.read_csv(io.StringIO(response.text))
        read_success = True
        err_msg = ""
    except Exception as e:
        df_etf_db = pd.DataFrame()
        read_success = False
        err_msg = str(e)

    if not read_success:
        st.error(f"❌ 無法讀取 ETF 試算表！\n錯誤：`{err_msg}`")
        st.info("💡 請確認該試算表的共用權限已設定為「知道連結的人均可檢視」。")
    elif df_etf_db is None or df_etf_db.empty:
        st.warning("⚠️ 成功連線，但資料是空的。請確認爬蟲已寫入資料。")
    else:
        df_etf_db = df_etf_db.dropna(how='all')
        
        with st.expander("🛠️ 展開查看原始讀取資料", expanded=False):
            st.dataframe(df_etf_db.head())

        if len(df_etf_db.columns) < 3:
            st.error(f"⚠️ 欄位數量異常，只讀到 {len(df_etf_db.columns)} 欄。")
        else:
            etf_col = df_etf_db.columns[0]
            name_col = df_etf_db.columns[1]
            weight_col = df_etf_db.columns[2]
            
            raw_etfs = df_etf_db[etf_col].dropna().astype(str).str.strip().unique().tolist()
            etf_options = [x for x in raw_etfs if x and x.lower() not in ['etf', 'etf代號', 'ticker', 'nan', 'none'] and '代號' not in x]
            
            if not etf_options:
                st.warning("⚠️ 未解析出有效的 ETF 代號！")
            else:
                selected_etf = st.selectbox("👉 選擇要查詢的 ETF：", options=etf_options)
                
                if selected_etf:
                    df_show = df_etf_db[df_etf_db[etf_col].astype(str).str.strip() == selected_etf].copy()
                    
                    try:
                        plot_df = df_show.copy()
                        plot_df[name_col] = plot_df[name_col].astype(str).str.strip()
                        
                        # 暴力清洗權重欄位：移除 % 符號、逗點與空白
                        plot_df[weight_col] = plot_df[weight_col].astype(str).str.replace(r'[^\d.-]', '', regex=True)
                        plot_df[weight_col] = pd.to_numeric(plot_df[weight_col], errors='coerce')
                        
                        plot_df = plot_df.dropna(subset=[weight_col]).sort_values(by=weight_col, ascending=True)
                        
                        if not plot_df.empty:
                            plot_df_top10 = plot_df.tail(10)
                            top10_sum = plot_df_top10[weight_col].sum()
                            
                            st.markdown(f"#### 🎯 前十大持股佔比總和： **{top10_sum:.2f}%**")
                            
                            plot_df_top10['文字標籤'] = plot_df_top10[weight_col].apply(lambda x: f"{x:.2f}%")
                            
                            fig_etf = px.bar(plot_df_top10, x=weight_col, y=name_col, orientation='h', title=f"{selected_etf} 核心持股", text='文字標籤')
                            fig_etf.update_traces(textposition='outside')
                            fig_etf.update_yaxes(type='category') 
                            fig_etf.update_layout(height=400, yaxis_title=None, xaxis_title="%", margin=dict(l=10, r=10, t=30, b=10))
                            st.plotly_chart(fig_etf, use_container_width=True)
                        else:
                            st.info("無效的權重數值。")
                    except Exception as ex:
                        st.warning(f"圖表繪製發生錯誤：\n\n{traceback.format_exc()}")
                            
                    st.dataframe(df_show, hide_index=True, use_container_width=True)

with tab4:
    st.markdown("### 📖 每日看盤心得")
    journal_error = False
    try:
        df_journal = conn.read(worksheet="Trading_Journal", ttl=0)
        if df_journal is not None and 'Date' in df_journal.columns and not df_journal.empty:
            df_journal['Date'] = pd.to_datetime(df_journal['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
            df_journal = df_journal.dropna(subset=['Date'])
            
            if len(df_journal) < 1:
                st.warning("⚠️ 系統偵測到看盤心得無歷史資料，已啟動防寫保護。請手動輸入第一筆紀錄以解鎖。")
                journal_error = True
        else:
            journal_error = True
    except Exception:
        journal_error = True

    if journal_error:
        st.info("請於試算表確認 `Trading_Journal` 工作表格式是否正確。")
    else:
        today_str = datetime.now().strftime('%Y-%m-%d')
        now_time = datetime.now().strftime('%H:%M:%S')

        existing_note = ""
        if today_str in df_journal['Date'].values:
            existing_note = str(df_journal.loc[df_journal['Date'] == today_str, 'Notes'].iloc[0])
            if existing_note == 'nan': existing_note = ""

        with st.form("m_journal_form"):
            note_input = st.text_area(f"[{today_str}] 紀錄：", value=existing_note, height=150)
            if st.form_submit_button("💾 儲存心得"):
                with st.spinner("儲存中..."):
                    if today_str in df_journal['Date'].values:
                        idx = df_journal.index[df_journal['Date'] == today_str].tolist()[0]
                        df_journal.at[idx, 'Notes'] = note_input
                        df_journal.at[idx, 'Last_Updated'] = now_time
                    else:
                        new_row = pd.DataFrame([{'Date': today_str, 'Notes': note_input, 'Last_Updated': now_time}])
                        df_journal = pd.concat([df_journal, new_row], ignore_index=True)
                    try:
                        conn.update(worksheet="Trading_Journal", data=df_journal)
                        st.success("儲存成功！")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error("寫入失敗")
        
        st.divider()
        st.caption("📚 歷史回顧")
        if not df_journal.empty:
            for _, row in df_journal.sort_values(by='Date', ascending=False).iterrows():
                with st.expander(f"📅 {row['Date']}"):
                    st.write(row['Notes'])

with tab5:
    st.markdown("### ✏️ 雲端隨身記帳")
    st.caption("更改後點擊下方按鈕即可同步至雲端 Sheets。")
    
    st.subheader("🇹🇼 台股名單")
    edited_tw = st.data_editor(df_tw, num_rows="dynamic", width="stretch", key="m_tw_editor")
    if st.button("💾 儲存台股變更"):
        try:
            conn.update(worksheet="TW_Portfolio", data=edited_tw)
            st.success("更新成功！")
        except Exception as e: st.error(f"錯誤:{e}")
            
    st.divider()
    
    st.subheader("🇺🇸 美股名單")
    edited_us = st.data_editor(df_us, num_rows="dynamic", width="stretch", key="m_us_editor")
    if st.button("💾 儲存美股變更"):
        try:
            conn.update(worksheet="US_Portfolio", data=edited_us)
            st.success("更新成功！")
        except Exception as e: st.error(f"錯誤:{e}")
