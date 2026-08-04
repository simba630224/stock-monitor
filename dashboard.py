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
from streamlit_gsheets import GSheetsConnection

warnings.filterwarnings('ignore')

st.set_page_config(page_title="個人投資組合與技術分析儀表板", layout="wide")

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

try:
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0)
    if df_tw is not None and not df_tw.empty:
        df_tw.columns = [str(c).strip() for c in df_tw.columns]
        df_tw = df_tw.dropna(subset=['Ticker'])
        if '名稱' not in df_tw.columns: df_tw['名稱'] = ''
        if 'Shares' not in df_tw.columns: df_tw['Shares'] = 0.0
        if '出借' not in df_tw.columns: df_tw['出借'] = 0.0
        if '類別' not in df_tw.columns: df_tw['類別'] = '台股'
        PORTFOLIO_TW = df_tw.to_dict('records')
    else:
        PORTFOLIO_TW = []
        df_tw = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "出借", "類別"])
except Exception as e:
    PORTFOLIO_TW = []
    df_tw = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "出借", "類別"])

try:
    df_us = conn.read(worksheet="US_Portfolio", ttl=0)
    if df_us is not None and not df_us.empty:
        df_us.columns = [str(c).strip() for c in df_us.columns]
        df_us = df_us.dropna(subset=['Ticker'])
        if '名稱' not in df_us.columns: df_us['名稱'] = ''
        if 'Shares' not in df_us.columns: df_us['Shares'] = 0.0
        if '複委託' not in df_us.columns: df_us['複委託'] = 0.0
        if '類別' not in df_us.columns: df_us['類別'] = '美股'
        PORTFOLIO_US = df_us.to_dict('records')
    else:
        PORTFOLIO_US = []
        df_us = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "複委託", "類別"])
except Exception as e:
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
                
                def fmt_pct_text(val):
                    if is_etf: return "ETF/不適用"
                    if val is not None and pd.notna(val): return f"{val * 100:.1f} %"
                    return "暫無資料"

                gross_m = fmt_pct_text(f_info.get('grossMargins'))
                op_m = fmt_pct_text(f_info.get('operatingMargins'))
                prof_m = fmt_pct_text(f_info.get('profitMargins'))
                
                roe_raw = f_info.get('returnOnEquity')
                roe_val = roe_raw * 100 if roe_raw is not None and not is_etf else None

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
                    "近一季報酬": ret_1q, "近半年報酬": ret_6m, "近一年報酬": ret_1y,
                    "相對大盤": rel_val, "近一年殖利率": yield_1y, "總配息金額": tot_div,
                    "近一年配息明細": div_history_str, "毛利率": gross_m, "營益率": op_m, "淨利率": prof_m, "ROE": roe_val
                }
        except: time.sleep(1)
    return None

@st.cache_data(ttl=900)
def process_technical_analysis(sym, name, market):
    try:
        df = get_stock_data(sym)
        if df is None or df.empty or len(df) < 35: return None
            
        has_enough_weekly = False
        k_w, d_w, macd_w, macds_w = 0.0, 0.0, 0.0, 0.0
        pk_w, pd_w, pmacd_w, pmacds_w = 0.0, 0.0, 0.0, 0.0
        
        try:
            agg_dict = {'Close': 'last'}
            if 'Open' in df.columns: agg_dict['Open'] = 'first'
            if 'High' in df.columns: agg_dict['High'] = 'max'
            if 'Low' in df.columns: agg_dict['Low'] = 'min'
            if 'Volume' in df.columns: agg_dict['Volume'] = 'sum'
            
            df_w = df.resample('W-FRI').agg(agg_dict).dropna(subset=['Close'])
            if len(df_w) >= 15: 
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
                
                k_w = float(df_w['K_w'].iloc[-1]) if pd.notna(df_w['K_w'].iloc[-1]) else 0.0
                d_w = float(df_w['D_w'].iloc[-1]) if pd.notna(df_w['D_w'].iloc[-1]) else 0.0
                macd_w = float(df_w['MACD'].iloc[-1]) if pd.notna(df_w['MACD'].iloc[-1]) else 0.0
                macds_w = float(df_w['MACD_Signal'].iloc[-1]) if pd.notna(df_w['MACD_Signal'].iloc[-1]) else 0.0
                
                if len(df_w) > 1:
                    pk_w = float(df_w['K_w'].iloc[-2]) if pd.notna(df_w['K_w'].iloc[-2]) else 0.0
                    pd_w = float(df_w['D_w'].iloc[-2]) if pd.notna(df_w['D_w'].iloc[-2]) else 0.0
                    pmacd_w = float(df_w['MACD'].iloc[-2]) if pd.notna(df_w['MACD'].iloc[-2]) else 0.0
                    pmacds_w = float(df_w['MACD_Signal'].iloc[-2]) if pd.notna(df_w['MACD_Signal'].iloc[-2]) else 0.0
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

        # 🚀 判斷月/季線連續上/下彎 >= 5日，以及站上/跌破 >= 5日
        ma20_up_5d = False
        ma_s_up_5d = False
        ma20_dn_5d = False
        ma_s_dn_5d = False
        above_ma20_5d = False
        below_ma20_5d = False
        above_mas_5d = False
        below_mas_5d = False

        if len(df) >= 6 and pd.notna(df['季線'].iloc[-6]):
            ma20_up_5d = all(df['MA20'].iloc[i] > df['MA20'].iloc[i-1] for i in range(-1, -6, -1))
            ma_s_up_5d = all(df['季線'].iloc[i] > df['季線'].iloc[i-1] for i in range(-1, -6, -1))
            
            ma20_dn_5d = all(df['MA20'].iloc[i] < df['MA20'].iloc[i-1] for i in range(-1, -6, -1))
            ma_s_dn_5d = all(df['季線'].iloc[i] < df['季線'].iloc[i-1] for i in range(-1, -6, -1))
            
            above_ma20_5d = all(df['Close'].iloc[i] > df['MA20'].iloc[i] for i in range(-5, 0))
            below_ma20_5d = all(df['Close'].iloc[i] < df['MA20'].iloc[i] for i in range(-5, 0))
            above_mas_5d = all(df['Close'].iloc[i] > df['季線'].iloc[i] for i in range(-5, 0))
            below_mas_5d = all(df['Close'].iloc[i] < df['季線'].iloc[i] for i in range(-5, 0))

        # 🚀 新增：近 5 日累計漲跌幅 5% 判定
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
        pk_d = float(df['K_d'].iloc[-2]) if len(df) > 1 and 'K_d' in df.columns and pd.notna(df['K_d'].iloc[-2]) else 50.0
        pd_d = float(df['D_d'].iloc[-2]) if len(df) > 1 and 'K_d' in df.columns and pd.notna(df['K_d'].iloc[-2]) else 50.0
        
        macd_d = float(df['MACD'].iloc[-1]) if pd.notna(df['MACD'].iloc[-1]) else 0.0
        macds_d = float(df['MACD_Signal'].iloc[-1]) if pd.notna(df['MACD_Signal'].iloc[-1]) else 0.0
        pmacd_d = float(df['MACD'].iloc[-2]) if len(df) > 1 and pd.notna(df['MACD'].iloc[-2]) else 0.0
        pmacds_d = float(df['MACD_Signal'].iloc[-2]) if len(df) > 1 and pd.notna(df['MACD_Signal'].iloc[-2]) else 0.0
        
        def eval_kd_status(curr_fast, curr_slow, prev_fast, prev_slow):
            if curr_fast > curr_slow and prev_fast <= prev_slow: return "🟢 KD低檔金叉" if curr_fast < 30 else "🟢 KD一般金叉"
            if curr_fast < curr_slow and prev_fast >= prev_slow: return "🔴 KD高檔死叉" if curr_fast > 70 else "🔴 KD一般死叉"
            if curr_fast >= curr_slow: return "📈 已金叉，且向上發散"
            return "📉 已死叉，且向下發散"
            
        def eval_macd_status(curr_fast, curr_slow, prev_fast, prev_slow):
            if curr_fast > curr_slow and prev_fast <= prev_slow: return "🟢 MACD零下金叉" if curr_fast < 0 else "🟢 MACD一般金叉"
            if curr_fast < curr_slow and prev_fast >= prev_slow: return "🔴 MACD零上死叉" if curr_fast > 0 else "🔴 MACD一般死叉"
            if curr_fast >= curr_slow: return "📈 已金叉，且向上發散"
            return "📉 已死叉，且向下發散"

        kd_d_status = eval_kd_status(k_d, d_d, pk_d, pd_d)
        macd_d_status = eval_macd_status(macd_d, macds_d, pmacd_d, pmacds_d)
        kd_w_status = eval_kd_status(k_w, d_w, pk_w, pd_w) if has_enough_weekly else "資料不足"
        macd_w_status = eval_macd_status(macd_w, macds_w, pmacd_w, pmacds_w) if has_enough_weekly else "資料不足"
        
        alerts = []
        if is_break_ma: alerts.append("跌破月/季線")
        
        if ma20_up_5d and ma_s_up_5d: alerts.append("月/季線上彎≥5日")
        elif ma20_up_5d: alerts.append("月線上彎≥5日")
        elif ma_s_up_5d: alerts.append("季線上彎≥5日")
        
        if ma20_dn_5d and ma_s_dn_5d: alerts.append("月/季線下彎≥5日")
        elif ma20_dn_5d: alerts.append("月線下彎≥5日")
        elif ma_s_dn_5d: alerts.append("季線下彎≥5日")
        
        if above_ma20_5d and above_mas_5d: alerts.append("站上月/季線≥5日")
        elif above_ma20_5d: alerts.append("站上月線≥5日")
        elif above_mas_5d: alerts.append("站上季線≥5日")
        
        if below_ma20_5d and below_mas_5d: alerts.append("跌破月/季線≥5日")
        elif below_ma20_5d: alerts.append("跌破月線≥5日")
        elif below_mas_5d: alerts.append("跌破季線≥5日")

        # 近 5 日漲跌幅警示加入
        if has_ret_5d:
            if ret_5d >= 5.0: alerts.append(f"近5日上漲{ret_5d:.1f}%")
            elif ret_5d <= -5.0: alerts.append(f"近5日下跌{abs(ret_5d):.1f}%")
        
        if high_52w > 0 and (high_52w - last_p) / high_52w >= 0.15:
            alerts.append(f"近高點回落{((high_52w - last_p) / high_52w)*100:.1f}%")
        if high_20d > 0 and (high_20d - last_p) / high_20d >= 0.10:
            alerts.append(f"20日回落{((high_20d - last_p) / high_20d)*100:.1f}%")
        if len(df) >= 20 and high_20d > 0 and low_20d > 0:
            amp_20d = (high_20d - low_20d) / low_20d
            if amp_20d <= 0.07: alerts.append(f"💤 20日窄幅盤整(振幅{amp_20d*100:.1f}%)")
            
        action = "➖ 持平"
        has_buy = any(x in kd_w_status or x in macd_w_status for x in ["低檔金叉", "零下金叉"])
        has_sell = any(x in kd_w_status or x in macd_w_status for x in ["高檔死叉", "零上死叉"]) or "近高點回落" in " ".join(alerts)
        has_reduce = "20日回落" in " ".join(alerts)
        
        if has_sell: action = "🛑 賣出"
        elif has_buy: action = "🚀 買進"
        elif has_reduce: action = "⚠️ 減碼"

        alert_str = f"[{action}] " + (" / ".join(alerts) if alerts else "趨勢延續")

        f_info = get_fundamental_info(sym)
        pe_val = f_info.get('trailingPE')
        pe_str = f"{float(pe_val):.1f}" if pe_val is not None and pd.notna(pe_val) else "無"
        beta_val = f_info.get('beta')
        beta_str = f"{float(beta_val):.2f}" if beta_val is not None and pd.notna(beta_val) else "無"

        return {
            "市場": market, "標的": f"{name} ({sym})", "狀態警示": alert_str, "均線位階": ma_status_str,
            "52週位置": f"{pos_52w:.1f} %", "Beta": beta_str, 
            "日KD": f"K:{k_d:.1f}/D:{d_d:.1f} ({kd_d_status})",
            "週KD": f"K:{k_w:.1f}/D:{d_w:.1f} ({kd_w_status})",
            "日MACD": f"DIF:{macd_d:.2f} ({macd_d_status})",
            "週MACD": f"DIF:{macd_w:.2f} ({macd_w_status})",
            "P/E": pe_str, "收盤價": last_p, "MA20": ma20, "季線": ma_season,
            "_raw_kd_d": kd_d_status, "_raw_kd_w": kd_w_status, "_raw_pe": pe_val, "_is_break_ma": is_break_ma,
            "_raw_macd_d": macd_d_status, "_raw_macd_w": macd_w_status,
            "_ma20_up_5d": ma20_up_5d, "_ma_s_up_5d": ma_s_up_5d,
            "_ma20_dn_5d": ma20_dn_5d, "_ma_s_dn_5d": ma_s_dn_5d,
            "_above_ma20_5d": above_ma20_5d, "_below_ma20_5d": below_ma20_5d,
            "_above_mas_5d": above_mas_5d, "_below_mas_5d": below_mas_5d,
            "_has_ret_5d": has_ret_5d, "_ret_5d": ret_5d
        }
    except Exception as e: return None

# ==========================================
# 3. 網頁 UI 渲染
# ==========================================
st.title("📊 個人投資組合與技術分析儀表板")

col_btn, col_time = st.columns([1, 4])
with col_btn:
    if st.button("🔄 強制刷新報價"):
        st.cache_data.clear()
        st.rerun()
with col_time:
    st.caption(f"數據最後更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

tab1, tab2, tab_comp, tab3, tab_etf, tab4 = st.tabs(["💰 投資組合總覽", "📈 技術分析掃描", "🆚 標的比較", "🏆 績效與股息追蹤", "🧩 ETF持股", "📖 每日看盤心得"])

with tab1:
    with st.spinner("正在同步即時報價資料..."):
        usdtwd = get_usdtwd()
        total_market_value, total_dividends_2026, total_dividends_1y = 0, 0, 0
        asset_allocation = {}
        individual_holdings = [] 

        for item in PORTFOLIO_TW:
            if pd.notna(item.get('Ticker')):
                ticker_str = str(item['Ticker']).strip()
                if not ticker_str: continue
                ticker = get_yf_ticker_tw(ticker_str)
                asset_type = str(item.get('類別', '台股')).strip()
                if not asset_type or asset_type == 'nan': asset_type = '台股未分類'
                
                price, div_2026, div_1y = get_basic_data(ticker)
                shares_own = safe_float(item.get('Shares'))
                shares_lent = safe_float(item.get('出借'))
                total_shares = shares_own + shares_lent
                
                if price > 0 and total_shares > 0:
                    val = price * total_shares
                    div_tot_2026 = div_2026 * total_shares
                    div_tot_1y = div_1y * total_shares
                    total_market_value += val
                    asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val
                    total_dividends_2026 += div_tot_2026
                    total_dividends_1y += div_tot_1y
                    
                    disp_qty = f"{int(total_shares/1000)}張" if total_shares >= 1000 and total_shares % 1000 == 0 else f"{total_shares:g}股"
                    name_str = str(item.get('名稱', '')).strip()
                    display_name = name_str if name_str and name_str != 'nan' else ticker_str
                    individual_holdings.append({'標的': display_name, '標的與股數': f"{display_name} ({disp_qty})", '總市值': val, '股息': div_tot_2026, '類別': asset_type, '總股數': total_shares})

        for item in PORTFOLIO_US:
            if pd.notna(item.get('Ticker')):
                ticker_str = str(item['Ticker']).strip()
                if not ticker_str: continue
                asset_type = str(item.get('類別', '美股')).strip()
                if not asset_type or asset_type == 'nan': asset_type = '美股未分類'
                
                price, div_2026, div_1y = get_basic_data(ticker_str)
                shares_own = safe_float(item.get('Shares'))
                shares_sub = safe_float(item.get('複委託'))
                total_shares = shares_own + shares_sub
                
                if price > 0 and total_shares > 0:
                    val = price * total_shares * usdtwd
                    div_tot_2026 = div_2026 * total_shares * usdtwd
                    div_tot_1y = div_1y * total_shares * usdtwd
                    total_market_value += val
                    asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val
                    total_dividends_2026 += div_tot_2026
                    total_dividends_1y += div_tot_1y
                    
                    disp_qty = f"{total_shares:g}股"
                    name_str = str(item.get('名稱', '')).strip()
                    display_name = name_str if name_str and name_str != 'nan' else ticker_str
                    individual_holdings.append({'標的': display_name, '標的與股數': f"{display_name} ({disp_qty})", '總市值': val, '股息': div_tot_2026, '類別': asset_type, '總股數': total_shares})

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("總市值 (TWD)", f"${total_market_value:,.0f}")
    col2.metric("2026 預估股息 (TWD)", f"${total_dividends_2026:,.0f}")
    col3.metric("近一年累計股息 (TWD)", f"${total_dividends_1y:,.0f}")
    col4.metric("目前匯率 (USD/TWD)", f"{usdtwd:.3f}")

    history_error = False
    df_history_to_display = pd.DataFrame()
    try:
        df_history = conn.read(worksheet="Value_History", ttl=0)
        if df_history is not None and 'Date' in df_history.columns and not df_history.empty:
            df_history['Date'] = pd.to_datetime(df_history['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
            df_history = df_history.dropna(subset=['Date'])
            
            if 'Total_Value' in df_history.columns:
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
    except Exception:
        history_error = True

    if history_error or df_history_to_display.empty:
        df_history_to_display = pd.DataFrame([{'Date': datetime.now().strftime('%Y-%m-%d'), 'Total_Value': total_market_value, 'Last_Updated': datetime.now().strftime('%H:%M:%S')}])

    st.divider()

    if not df_history_to_display.empty and len(df_history_to_display) > 1:
        st.subheader("📈 總市值每日變化趨勢")
        df_history_to_display['Total_Value'] = pd.to_numeric(df_history_to_display['Total_Value'], errors='coerce').fillna(0)
        fig_hist = px.line(df_history_to_display, x='Date', y='Total_Value', text='Total_Value', markers=True)
        fig_hist.update_traces(textposition="top center", texttemplate='%{text:,.0f}')
        fig_hist.update_layout(yaxis_title="總市值 (TWD)", xaxis_title="日期", margin=dict(t=30, b=0, l=0, r=0), height=350)
        st.plotly_chart(fig_hist, use_container_width=True)
    elif len(df_history_to_display) == 1 and not history_error:
        st.info("📊 目前只有一天的紀錄，趨勢圖將在明日自動產生。")

    st.divider()
    
    df_ind = pd.DataFrame(individual_holdings)
    category_color_map = {}
    if not df_ind.empty:
        unique_categories = df_ind['類別'].unique().tolist()
        plotly_colors = px.colors.qualitative.Safe + px.colors.qualitative.Plotly 
        category_color_map = {cat: plotly_colors[i % len(plotly_colors)] for i, cat in enumerate(unique_categories)}
    
    col_chart, col_fx = st.columns([1, 1])
    with col_chart:
        st.subheader("資產配置佔比")
        if asset_allocation:
            df_allocation = pd.DataFrame(list(asset_allocation.items()), columns=['資產類別', '市值 (TWD)'])
            fig_pie = px.pie(df_allocation, values='市值 (TWD)', names='資產類別', hole=0.4, color='資產類別', color_discrete_map=category_color_map)
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            fig_pie.update_layout(margin=dict(t=0, b=0, l=0, r=0), showlegend=False)
            st.plotly_chart(fig_pie, use_container_width=True)
        
    with col_fx:
        st.subheader("USD/TWD 匯率走勢 (1年)")
        fx_data = get_fx_data()
        if not fx_data.empty:
            fig_fx = go.Figure()
            fig_fx.add_trace(go.Scatter(x=fx_data.index, y=fx_data['Close'], mode='lines', name='USD/TWD', line=dict(color='white' if st.get_option('theme.base') == 'dark' else 'black', width=2)))
            fig_fx.add_trace(go.Scatter(x=fx_data.index, y=fx_data['MA20'], mode='lines', name='MA20 (月線)', line=dict(color='#3498db', dash='dash')))
            fig_fx.add_trace(go.Scatter(x=fx_data.index, y=fx_data['MA60'], mode='lines', name='MA60 (季線)', line=dict(color='#e74c3c', dash='dot')))
            fig_fx.update_layout(margin=dict(t=10, b=0, l=0, r=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig_fx, use_container_width=True)

    st.divider()

    st.subheader("📊 各標的總市值與股息分佈")
    if not df_ind.empty:
        col_bar1, col_bar2 = st.columns(2)
        with col_bar1:
            df_mv_sorted = df_ind.sort_values(by='總市值', ascending=True)
            fig_mv_bar = px.bar(df_mv_sorted, x='總市值', y='標的與股數', orientation='h', title='各標的總市值 (TWD)', color='類別', text_auto='.2s', hover_data=['標的', '總股數'], color_discrete_map=category_color_map)
            fig_mv_bar.update_layout(height=800, margin=dict(l=0, r=0, t=30, b=0), showlegend=False, yaxis={'categoryorder':'array', 'categoryarray': df_mv_sorted['標的與股數']})
            st.plotly_chart(fig_mv_bar, use_container_width=True)
            
        with col_bar2:
            df_div_sorted = df_ind.sort_values(by='股息', ascending=True)
            fig_div_bar = px.bar(df_div_sorted, x='股息', y='標的與股數', orientation='h', title='各標的預估股息 (TWD)', color='類別', text_auto='.2s', hover_data=['標的', '總股數'], color_discrete_map=category_color_map)
            fig_div_bar.update_layout(height=800, margin=dict(l=0, r=0, t=30, b=0), showlegend=False, yaxis={'categoryorder':'array', 'categoryarray': df_div_sorted['標的與股數']})
            st.plotly_chart(fig_div_bar, use_container_width=True)

with tab2:
    with st.spinner("正在掃描與運算所有標的指標..."):
        ta_results = []
        target_options = {} 
        
        bullish_strong = [] 
        bullish_daily = []  
        bearish_alerts = [] 
        
        scan_list = []
        for item in PORTFOLIO_TW:
            t = str(item.get('Ticker', '')).strip()
            if t and t != 'nan':
                sym = get_yf_ticker_tw(t)
                name = str(item.get('名稱', '')).strip()
                scan_list.append((sym, name if name and name != 'nan' else t, '台股'))
                
        for item in PORTFOLIO_US:
            t = str(item.get('Ticker', '')).strip()
            if t and t != 'nan':
                name = str(item.get('名稱', '')).strip()
                scan_list.append((t, name if name and name != 'nan' else t, '美股'))

        for sym, name, market in scan_list:
            res = process_technical_analysis(sym, name, market)
            if res: 
                ta_results.append(res)
                target_options[f"{name} ({sym})"] = sym
                
                pe_val = res.get('_raw_pe')
                if pd.isna(pe_val) or pe_val is None: pe_val = 999
                pe_str = f"PE:{pe_val:.1f}" if pe_val != 999 else "無PE"
                name_disp = f"{name} ({pe_str})"
                
                kd_d = res.get('_raw_kd_d', '')
                kd_w = res.get('_raw_kd_w', '')
                macd_d = res.get('_raw_macd_d', '')
                macd_w = res.get('_raw_macd_w', '')
                
                w_macd_gold = "🟢 MACD零下金叉" in macd_w
                w_kd_gold = "🟢 KD低檔金叉" in kd_w
                d_macd_gold = "🟢 MACD零下金叉" in macd_d
                d_kd_gold = "🟢 KD低檔金叉" in kd_d

                w_macd_death = "🔴 MACD零上死叉" in macd_w
                w_kd_death = "🔴 KD高檔死叉" in kd_w
                d_macd_death = "🔴 MACD零上死叉" in macd_d
                d_kd_death = "🔴 KD高檔死叉" in kd_d
                
                is_break = res.get('_is_break_ma', False)
                ma20_up_5d = res.get('_ma20_up_5d', False)
                ma_s_up_5d = res.get('_ma_s_up_5d', False)
                ma20_dn_5d = res.get('_ma20_dn_5d', False)
                ma_s_dn_5d = res.get('_ma_s_dn_5d', False)
                above_ma20_5d = res.get('_above_ma20_5d', False)
                below_ma20_5d = res.get('_below_ma20_5d', False)
                above_mas_5d = res.get('_above_mas_5d', False)
                below_mas_5d = res.get('_below_mas_5d', False)
                has_ret_5d = res.get('_has_ret_5d', False)
                ret_5d = res.get('_ret_5d', 0.0)

                tags = []
                if w_macd_gold: tags.append("週MACD零下金叉")
                if w_kd_gold: tags.append("週KD低檔金叉")
                if d_macd_gold: tags.append("日MACD零下金叉")
                if d_kd_gold: tags.append("日KD低檔金叉")
                
                if ma20_up_5d and ma_s_up_5d: tags.append("月季線雙上彎≥5日")
                elif ma20_up_5d: tags.append("月線上彎≥5日")
                elif ma_s_up_5d: tags.append("季線上彎≥5日")
                
                if above_ma20_5d and above_mas_5d: tags.append("站上月季線≥5日")
                elif above_ma20_5d: tags.append("站上月線≥5日")
                elif above_mas_5d: tags.append("站上季線≥5日")
                
                if has_ret_5d and ret_5d >= 5.0: tags.append("近5日上漲≥5%")
                
                if w_macd_death: tags.append("週MACD零上死叉")
                if w_kd_death: tags.append("週KD高檔死叉")
                if d_macd_death: tags.append("日MACD零上死叉")
                if d_kd_death: tags.append("日KD高檔死叉")
                
                if is_break: tags.append("跌破季線")
                
                if ma20_dn_5d and ma_s_dn_5d: tags.append("月季線雙下彎≥5日")
                elif ma20_dn_5d: tags.append("月線下彎≥5日")
                elif ma_s_dn_5d: tags.append("季線下彎≥5日")
                
                if below_ma20_5d and below_mas_5d: tags.append("跌破月季線≥5日")
                elif below_ma20_5d: tags.append("跌破月線≥5日")
                elif below_mas_5d: tags.append("跌破季線≥5日")
                
                if has_ret_5d and ret_5d <= -5.0: tags.append("近5日下跌≥5%")

                bull_score = (w_macd_gold * 4) + (w_kd_gold * 3) + (d_macd_gold * 2) + (d_kd_gold * 1) + (ma20_up_5d * 1) + (ma_s_up_5d * 1) + (above_ma20_5d * 1) + (above_mas_5d * 1) + ((has_ret_5d and ret_5d >= 5.0) * 1)
                bear_score = (w_macd_death * 4) + (w_kd_death * 3) + (d_macd_death * 2) + (d_kd_death * 1) + (is_break * 1) + (ma20_dn_5d * 1) + (ma_s_dn_5d * 1) + (below_ma20_5d * 1) + (below_mas_5d * 1) + ((has_ret_5d and ret_5d <= -5.0) * 1)
                
                item_data = {'name': name_disp, 'pe': pe_val, 'tags': tags, 'bull_score': bull_score, 'bear_score': bear_score}
                
                if bear_score >= 3: 
                    bearish_alerts.append(item_data)
                elif bull_score >= 3: 
                    bullish_strong.append(item_data)
                elif bear_score > 0: 
                    bearish_alerts.append(item_data)
                elif bull_score > 0: 
                    bullish_daily.append(item_data)

        bullish_strong = sorted(bullish_strong, key=lambda x: (-x['bull_score'], x['pe']))[:10]
        bullish_daily = sorted(bullish_daily, key=lambda x: (-x['bull_score'], x['pe']))[:10]
        bearish_alerts = sorted(bearish_alerts, key=lambda x: (-x['bear_score'], x['pe']))[:10]

        def format_items(items):
            if not items: return "無"
            return "\n".join([f"• **{x['name']}** `[{', '.join(x['tags'])}]`" for x in items])

    st.markdown("### 📊 盤後技術亮點與警示摘要 (Top 10)")
    st.caption("篩選邏輯：嚴格限定「零上/零下、高檔/低檔」交叉。依技術強度排序 (週級別優先)，強度相同時 **本益比 (PE) 低者優先**。")
    
    col_sum1, col_sum2 = st.columns(2)
    with col_sum1:
        st.success(f"**☀️ 多方強勢區 (訊號發動)**\n\n"
                   f"🔥 **週線級別 (波段啟動 Top 10)**：\n{format_items(bullish_strong)}\n\n"
                   f"📈 **日線級別 (短線轉折 Top 10)**：\n{format_items(bullish_daily)}")
    with col_sum2:
        st.error(f"**⛈️ 空方風險區 (破線/死叉 Top 10)**\n\n"
                 f"⚠️ **趨勢轉弱警示**：\n{format_items(bearish_alerts)}")

    st.divider()
    st.markdown("### 📋 完整技術分析清單")
    with st.expander("💡 狀態警示規則與名詞定義說明", expanded=False):
        st.markdown("""
        #### 一、 綜合買賣動作評級
        * **🚀 買進**：「週/日線 KD 低檔金叉」或「週/日線 MACD 零下金叉」。
        * **🛑 賣出**：「週/日線 KD 高檔死叉」、「週/日線 MACD 零上死叉」，或「近一年高點回落達 15%」。
        * **⚠️ 減碼**：「20日高點回落達 10%」。
        * **➖ 持平**：未觸發上述強烈轉折或防禦訊號。

        #### 二、 技術指標交叉過濾 (KD & MACD)
        * **🟢 低檔/零下金叉**：KD 於 30 以下金叉 / MACD 於 0 軸以下金叉。
        * **🟢 一般金叉**：KD 於 30 以上金叉 / MACD 於 0 軸以上金叉。
        * **🔴 高檔/零上死叉**：KD 於 70 以上死叉 / MACD 於 0 軸以上死叉。
        * **🔴 一般死叉**：KD 於 70 以下死叉 / MACD 於 0 軸以下死叉。

        #### 三、 均線動能與破線警示 (MA)
        * **跌破月/季線**：今日剛發生實質跌破月線或季線。
        * **月/季線上彎 ≥ 5日**：月線(MA20)或季線連續 5 個交易日遞增。
        * **月/季線下彎 ≥ 5日**：月線(MA20)或季線連續 5 個交易日遞減。
        * **站上月/季線 ≥ 5日**：收盤價連續 5 個交易日維持在該均線之上。
        * **跌破月/季線 ≥ 5日**：收盤價連續 5 個交易日維持在該均線之下。

        #### 四、 價格回落與漲跌防禦
        * **近5日上漲 ≥ 5%**：近 5 個交易日累計漲幅達 5% (含) 以上。
        * **近5日下跌 ≥ 5%**：近 5 個交易日累計跌幅達 5% (含) 以上。
        * **近高點回落 XX%**：距過去 52 週最高價跌幅達 15% (含) 以上。
        * **20日回落 XX%**：距過去 20 日最高價跌幅達 10% (含) 以上。
        * **💤 20日窄幅盤整**：過去 20 日最高與最低價振幅壓縮在 7% (含) 以內。

        #### 五、 均線位階綜合判定
        * **短中線 (月線與季線)**：🟢 站穩月/季線、🔴 月/季線之下、🟡 守季受月壓、🔵 站月臨季壓。
        * **長線 (半年線與年線)**：🟢 長線多頭、🔴 長線空頭、🟡 守年線(半年下彎)、🔵 臨年線壓(年線下彎)。
        """)
        
    if ta_results:
        df_ta = pd.DataFrame(ta_results)
        df_ta = df_ta.drop(columns=['_raw_kd_d', '_raw_kd_w', '_raw_pe', '_is_break_ma', '_raw_macd_d', '_raw_macd_w', '_ma20_up_5d', '_ma_s_up_5d', '_ma20_dn_5d', '_ma_s_dn_5d', '_above_ma20_5d', '_below_ma20_5d', '_above_mas_5d', '_below_mas_5d', '_has_ret_5d', '_ret_5d'], errors='ignore')
        st.dataframe(
            df_ta, 
            width="stretch",
            column_config={
                "市場": st.column_config.TextColumn("市場", width="small"),
                "標的": st.column_config.TextColumn("名稱 (代號)", width="medium"),
                "狀態警示": st.column_config.TextColumn("🚨 狀態警示", width="large"),
                "均線位階": st.column_config.TextColumn("均線位階", width="medium"),
                "52週位置": st.column_config.TextColumn("52週位置", width="small"),
                "Beta": st.column_config.TextColumn("Beta", width="small"),
                "日KD": st.column_config.TextColumn("日 KD", width="medium"),
                "週KD": st.column_config.TextColumn("週 KD", width="medium"),
            },
            hide_index=True, height=450
        )

    st.divider()
    st.subheader("📈 個股/ETF 詳細技術線圖 (含 MA / KD / MACD)")
    
    col_select_stock, col_select_period = st.columns([2, 1])
    with col_select_stock:
        selected_name = st.selectbox("請選擇要查看技術線圖的標的：", options=list(target_options.keys()) if target_options else ["暫無可繪圖標的"])
    with col_select_period:
        period_label = st.selectbox("請選擇顯示範圍：", options=["半年 (150日)", "一年 (252日)", "三年 (完整數據)"], index=0)
    
    tail_days = 150 if period_label == "半年 (150日)" else (252 if period_label == "一年 (252日)" else 9999)
        
    if selected_name and selected_name != "暫無可繪圖標的":
        sym = target_options[selected_name]
        df_chart = get_stock_data(sym)
        if df_chart is not None:
            df_plot = df_chart.tail(tail_days)
            fig_tech = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.5, 0.25, 0.25], subplot_titles=(f"{selected_name} - 走勢圖", "日 KD 指標", "MACD 指標 (12,26,9)"))
            
            if 'Open' in df_plot.columns and 'High' in df_plot.columns and 'Low' in df_plot.columns:
                fig_tech.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name='K線', increasing_line_color='red', decreasing_line_color='green'), row=1, col=1)
            else:
                fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Close'], mode='lines', name='收盤價'), row=1, col=1)
                
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MA10'], line=dict(color='yellow', width=1.5), name='MA10'), row=1, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MA20'], line=dict(color='blue', width=1.5), name='MA20'), row=1, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['季線'], line=dict(color='orange', width=1.5), name="季線"), row=1, col=1)
            
            if 'K_d' in df_plot.columns:
                fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['K_d'], line=dict(color='blue', width=1.5), name='K值'), row=2, col=1)
                fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['D_d'], line=dict(color='orange', width=1.5), name='D值'), row=2, col=1)
            fig_tech.add_hline(y=80, line_dash="dash", line_color="red", row=2, col=1)
            fig_tech.add_hline(y=20, line_dash="dash", line_color="green", row=2, col=1)
            
            macd_colors = ['red' if val >= 0 else 'green' for val in df_plot['MACD_Hist']]
            fig_tech.add_trace(go.Bar(x=df_plot.index, y=df_plot['MACD_Hist'], marker_color=macd_colors, name='OSC'), row=3, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MACD'], line=dict(color='blue', width=1.5), name='MACD'), row=3, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MACD_Signal'], line=dict(color='orange', width=1.5), name='Signal'), row=3, col=1)
            
            fig_tech.update_layout(xaxis_rangeslider_visible=False, height=800, margin=dict(t=40, b=0, l=0, r=0))
            st.plotly_chart(fig_tech, use_container_width=True)

with tab_comp:
    st.subheader("🆚 多檔標的走勢比較")
    st.caption("選擇 2~4 檔標的，比較其區間累計報酬率走勢。")
    
    if 'target_options' in locals() and target_options:
        all_options_list = list(target_options.keys())
        default_selections = all_options_list[:2] if len(all_options_list) >= 2 else None
        
        comp_col1, comp_col2 = st.columns([3, 1])
        with comp_col1:
            comp_targets = st.multiselect("請選擇比較標的 (最多4檔)：", options=all_options_list, default=default_selections, max_selections=4)
        with comp_col2:
            comp_period = st.radio("比較期間", ["半年", "一年", "三年"], horizontal=True, index=1)
            
        if comp_targets:
            with st.spinner("載入比較數據中..."):
                period_map = {"半年": "6mo", "一年": "1y", "三年": "3y"}
                yf_period = period_map[comp_period]
                
                comp_data = {}
                for tgt in comp_targets:
                    sym = target_options[tgt]
                    try:
                        hist = yf.Ticker(sym).history(period=yf_period)
                        if not hist.empty:
                            hist.index = pd.to_datetime(hist.index).normalize()
                            hist = hist[~hist.index.duplicated(keep='last')]
                            comp_data[tgt] = hist['Close']
                    except: pass
                
                if comp_data:
                    df_comp = pd.DataFrame(comp_data)
                    df_comp = df_comp.ffill().bfill().dropna()
                    if not df_comp.empty:
                        df_comp_pct = (df_comp / df_comp.iloc[0] - 1) * 100
                        fig_comp = px.line(df_comp_pct, x=df_comp_pct.index, y=df_comp_pct.columns, labels={'value': '累計報酬率 (%)', 'variable': '標的', 'index': '日期'})
                        fig_comp.update_layout(hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                        st.plotly_chart(fig_comp, use_container_width=True)
                else:
                    st.warning("無法取得選定標的的歷史資料。")
    else:
        st.info("請先確認持股清單並等待資料載入。")

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
            st.dataframe(
                df_perf,
                width="stretch",
                column_config={
                    "市場": st.column_config.TextColumn("市場", width="small"),
                    "代號": st.column_config.TextColumn("代號", width="small"),
                    "最新收盤價": st.column_config.NumberColumn("收盤價", format="%.2f"),
                    "近一季報酬": st.column_config.NumberColumn("近一季報酬 (%)", format="%+.2f"),
                    "近半年報酬": st.column_config.NumberColumn("近半年報酬 (%)", format="%+.2f"),
                    "近一年報酬": st.column_config.NumberColumn("近一年報酬 (%)", format="%+.2f"),
                    "相對大盤": st.column_config.NumberColumn("相對大盤(1年) (%)", format="%+.2f"),
                    "近一年殖利率": st.column_config.NumberColumn("近一年殖利率 (%)", format="%.2f"),
                    "總配息金額": st.column_config.NumberColumn("近一年總配息", format="%.2f"),
                    "近一年配息明細": st.column_config.TextColumn("近一年配息紀錄", width="large"),
                    "毛利率": st.column_config.TextColumn("毛利率", width="small"),
                    "營益率": st.column_config.TextColumn("營益率", width="small"),
                    "淨利率": st.column_config.TextColumn("淨利率", width="small"),
                    "ROE": st.column_config.NumberColumn("ROE (%)", format="%.2f"),
                },
                hide_index=True, height=600
            )

with tab_etf:
    st.subheader("🧩 ETF Top 10 持股分析")
    st.caption("自動解析您的 ETF 持股結構，掌握真實資金流向與比重。")
    
    csv_url = "https://docs.google.com/spreadsheets/d/1_crBmjMxgm9qpYeycg_TnLStt3phN6vM4XILmD9x0Yc/export?format=csv&gid=892058804"
    
    try:
        df_etf_db = pd.read_csv(csv_url)
        read_success = True
        err_msg = ""
    except Exception as e:
        df_etf_db = pd.DataFrame()
        read_success = False
        err_msg = str(e)

    if not read_success:
        st.error(f"❌ **無法讀取 ETF 試算表！**\n錯誤訊息：`{err_msg}`")
        st.info("💡 **唯一解決方法**：\n請打開您的 ETF 試算表，點擊右上角的 **「共用 (Share)」**，將一般存取權限改為**「知道連結的人均可檢視 (Anyone with the link)」**。這不會洩漏您的隱私，且能讓程式瞬間讀取！")
    elif df_etf_db is None or df_etf_db.empty:
        st.warning("⚠️ 成功連線，但系統讀取到的資料是空的。請確認爬蟲已成功寫入資料。")
    else:
        df_etf_db = df_etf_db.dropna(how='all')
        
        with st.expander("🛠️ 展開查看原始讀取資料 (除錯用)", expanded=False):
            st.dataframe(df_etf_db.head())

        if len(df_etf_db.columns) < 3:
            st.error(f"⚠️ 讀取成功，但欄位數量異常！預期至少 3 欄，但只讀到 {len(df_etf_db.columns)} 欄。")
        else:
            etf_col = df_etf_db.columns[0]
            name_col = df_etf_db.columns[1]
            weight_col = df_etf_db.columns[2]
            
            raw_etfs = df_etf_db[etf_col].dropna().astype(str).str.strip().unique().tolist()
            etf_options = [x for x in raw_etfs if x and x.lower() not in ['etf', 'etf代號', 'ticker', 'nan', 'none'] and '代號' not in x]
            
            if not etf_options:
                st.warning("⚠️ 工作表中未能解析出有效的 ETF 代號！請展開上方原始資料確認第一欄的內容。")
            else:
                col_etf1, col_etf2 = st.columns([1, 2])
                
                with col_etf1:
                    selected_etf = st.selectbox("👉 請選擇要查詢持股比例的 ETF：", options=etf_options, key="pc_etf_select")
                    
                if selected_etf:
                    df_show = df_etf_db[df_etf_db[etf_col].astype(str).str.strip() == selected_etf].copy()
                    
                    with col_etf1:
                        st.dataframe(df_show, hide_index=True, use_container_width=True)
                    
                    with col_etf2:
                        try:
                            plot_df = df_show.copy()
                            plot_df[name_col] = plot_df[name_col].astype(str).str.strip()
                            
                            # 暴力清洗權重欄位：移除 % 符號、逗點與空白
                            plot_df[weight_col] = plot_df[weight_col].astype(str).str.replace(r'[^\d.-]', '', regex=True)
                            plot_df[weight_col] = pd.to_numeric(plot_df[weight_col], errors='coerce')
                            
                            plot_df = plot_df.dropna(subset=[weight_col]).sort_values(by=weight_col, ascending=True)
                            
                            if not plot_df.empty:
                                plot_df['文字標籤'] = plot_df[weight_col].apply(lambda x: f"{x:.2f}%")
                                
                                fig_etf = px.bar(plot_df, x=weight_col, y=name_col, orientation='h', 
                                                 title=f"<b>{selected_etf} 核心持股佔比 (%)</b>", text='文字標籤')
                                fig_etf.update_traces(textposition='outside')
                                fig_etf.update_yaxes(type='category') 
                                fig_etf.update_layout(yaxis_title=None, xaxis_title="持股比例 (%)", height=450, margin=dict(l=10, r=10, t=40, b=10))
                                st.plotly_chart(fig_etf, use_container_width=True)
                            else:
                                st.info("該 ETF 無效的權重數值可供繪製圖表。")
                        except Exception as ex:
                            st.warning(f"無法繪製持股比例圖表，錯誤代碼：\n\n{traceback.format_exc()}")

with tab4:
    st.subheader("📖 每日看盤心得紀錄")
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
        st.info("💡 提示：若要啟用「每日看盤心得」功能，請在您的 Google 試算表中確認 `Trading_Journal` 格式是否正確。")
    else:
        today_str = datetime.now().strftime('%Y-%m-%d')
        now_time = datetime.now().strftime('%H:%M:%S')

        existing_note = ""
        if today_str in df_journal['Date'].values:
            existing_note = str(df_journal.loc[df_journal['Date'] == today_str, 'Notes'].iloc[0])
            if existing_note == 'nan': existing_note = ""

        with st.form("journal_form"):
            note_input = st.text_area(f"撰寫 {today_str} 的看盤心得：", value=existing_note, height=150)
            submitted = st.form_submit_button("💾 儲存心得")

            if submitted:
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
                        st.success("✅ 心得儲存成功！")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"寫入失敗：{e}")
        
        st.divider()
        st.subheader("📚 歷史心得回顧")
        if not df_journal.empty:
            df_history_show = df_journal.sort_values(by='Date', ascending=False)
            for _, row in df_history_show.iterrows():
                with st.expander(f"📅 {row['Date']} (最後更新: {row.get('Last_Updated', '')})"):
                    st.write(row['Notes'])

with st.sidebar:
    st.header("📝 持股與觀察名單管理")
    st.markdown("想要追蹤某檔股票嗎？**新增代號並將股數設為 0**，它就會自動加入技術分析掃描！")
    
    st.subheader("🇹🇼 台股清單")
    if not df_tw.empty:
        edited_df_tw = st.data_editor(df_tw, num_rows="dynamic", width="stretch", key="tw_editor")
        if st.button("💾 儲存台股變更"):
            with st.spinner("正在寫入台股資料..."):
                try:
                    conn.update(worksheet="TW_Portfolio", data=edited_df_tw)
                    st.success("✅ 台股更新成功！請重新整理網頁。")
                except Exception as e: st.error(f"寫入失敗：{e}")
    else: st.info("台股清單目前為空。")

    st.divider()

    st.subheader("🇺🇸 美股清單")
    if not df_us.empty:
        edited_df_us = st.data_editor(df_us, num_rows="dynamic", width="stretch", key="us_editor")
        if st.button("💾 儲存美股變更"):
            with st.spinner("正在寫入美股資料..."):
                try:
                    conn.update(worksheet="US_Portfolio", data=edited_df_us)
                    st.success("✅ 美股更新成功！請重新整理網頁。")
                except Exception as e: st.error(f"寫入失敗：{e}")
    else: st.info("美股清單目前為空。")
