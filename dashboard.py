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
# 2. 核心抓取與計算邏輯 (智慧型代號路由規則)
# ==========================================
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip()
    # 移除使用者可能不小心帶入的後綴
    ticker = ticker.replace('.TW', '').replace('.TWO', '')
    
    # 1. 如果包含任何英文字母 (例如 937B, 981A, 988A) 一律屬於櫃買中心商品
    if re.search(r'[a-zA-Z]', ticker):
        return f"{ticker}.TWO"
    
    # 2. 如果是 6 位數純數字，且為 0098 或是 0097 開頭的新型股票型/主動式/海外型 ETF，也在櫃買中心掛牌
    if ticker.isdigit() and len(ticker) == 6 and (ticker.startswith("0098") or ticker.startswith("0097")):
        return f"{ticker}.TWO"
        
    # 3. 其他標準 4 位數股票、6 位數常規上市 ETF (如 0050, 006208) 走證交所規格
    if not ticker.isdigit() and '.' not in ticker:
        return f"{ticker}.TWO"
        
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
        time.sleep(0.1)
        info = yf.Ticker(sym).info
        return {
            'quoteType': info.get('quoteType'),
            'beta': info.get('beta'),
            'grossMargins': info.get('grossMargins'),
            'operatingMargins': info.get('operatingMargins'),
            'profitMargins': info.get('profitMargins'),
            'returnOnEquity': info.get('returnOnEquity'),
            'trailingPE': info.get('trailingPE')
        }
    except:
        return {}

@st.cache_data(ttl=900)
def get_stock_data(sym):
    is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
    for _ in range(3):
        try:
            time.sleep(0.3)
            df = yf.download(sym, period="3y", progress=False)
            if not df.empty and len(df) >= 2:
                if isinstance(df.columns, pd.MultiIndex): 
                    df.columns = df.columns.get_level_values(0)
                
                if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
                    df.index = df.index.tz_convert(None)
                    
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
                    df['K_d'] = 50.0
                    df['D_d'] = 50.0
                
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
                    "市場": market, "標的": display_ticker, "最新收盤價": curr_p,
                    "近一季報酬": ret_1q, "近半年報酬": ret_6m, "近一年報酬": ret_1y,
                    "相對大盤(1年)": rel_str_display, "近一年殖利率": yield_1y, "總配息金額": tot_div,
                    "近一年配息明細": div_history_str, "毛利率": gross_m, "營益率": op_m, "淨利率": prof_m, "ROE": roe
                }
        except:
            time.sleep(1)
    return None

@st.cache_data(ttl=900)
def process_technical_analysis(sym, name, market):
    try:
        df = get_stock_data(sym)
        if df is None or df.empty or 'Close' not in df.columns:
            raise ValueError("歷史 K 線數據讀取為空")
            
        has_enough_weekly = False
        k_w, d_w, macd_w, macds_w = 0.0, 0.0, 0.0, 0.0
        pk_w, pd_w, pmacd_w, pmacds_w = 0.0, 0.0, 0.0, 0.0
        
        try:
            agg_dict = {}
            if 'Open' in df.columns: agg_dict['Open'] = 'first'
            if 'High' in df.columns: agg_dict['High'] = 'max'
            if 'Low' in df.columns: agg_dict['Low'] = 'min'
            agg_dict['Close'] = 'last'
            if 'Volume' in df.columns: agg_dict['Volume'] = 'sum'
            
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
                    df_w['K_w'] = 50.0
                    df_w['D_w'] = 50.0
                    
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
        except:
            has_enough_weekly = False
        
        last_p = float(df['Close'].iloc[-1])
        ma10 = float(df['MA10'].iloc[-1]) if pd.notna(df['MA10'].iloc[-1]) else 0.0
        ma20 = float(df['MA20'].iloc[-1]) if pd.notna(df['MA20'].iloc[-1]) else 0.0
        ma_season = float(df['季線'].iloc[-1]) if pd.notna(df['季線'].iloc[-1]) else 0.0
        ma_half = float(df['半年線'].iloc[-1]) if pd.notna(df['半年線'].iloc[-1]) else 0.0
        ma_year = float(df['年線'].iloc[-1]) if pd.notna(df['年線'].iloc[-1]) else 0.0
        
        high_52w = df['High'].tail(252).max() if 'High' in df.columns else 0.0
        low_52w = df['Low'].tail(252).min() if 'Low' in df.columns else 0.0
        pos_52w = ((last_p - low_52w) / (high_52w - low_52w + 1e-9) * 100) if (high_52w - low_52w) > 0 else 50.0

        high_20d = df['High'].tail(20).max() if 'High' in df.columns else 0.0
        low_20d = df['Low'].tail(20).min() if 'Low' in df.columns else 0.0
        
        k_d = float(df['K_d'].iloc[-1]) if 'K_d' in df.columns and pd.notna(df['K_d'].iloc[-1]) else 0.0
        d_d = float(df['D_d'].iloc[-1]) if 'D_d' in df.columns and pd.notna(df['D_d'].iloc[-1]) else 0.0
        pk_d = float(df['K_d'].iloc[-2]) if len(df) > 1 and 'K_d' in df.columns and pd.notna(df['K_d'].iloc[-2]) else 0.0
        pd_d = float(df['D_d'].iloc[-2]) if len(df) > 1 and 'D_d' in df.columns and pd.notna(df['D_d'].iloc[-2]) else 0.0
        
        macd_d = float(df['MACD'].iloc[-1]) if pd.notna(df['MACD'].iloc[-1]) else 0.0
        macds_d = float(df['MACD_Signal'].iloc[-1]) if pd.notna(df['MACD_Signal'].iloc[-1]) else 0.0
        pmacd_d = float(df['MACD'].iloc[-2]) if len(df) > 1 and pd.notna(df['MACD'].iloc[-2]) else 0.0
        macds_d_prev = float(df['MACD_Signal'].iloc[-2]) if len(df) > 1 and pd.notna(df['MACD_Signal'].iloc[-2]) else 0.0
        
        def eval_kd_status(curr_fast, curr_slow, prev_fast, prev_slow):
            if curr_fast > curr_slow and prev_fast <= prev_slow:
                return "🟢 KD低檔金叉" if curr_fast < 30 else "🟢 KD金叉"
            if curr_fast < curr_slow and prev_fast >= prev_slow:
                return "🔴 KD高檔死叉" if curr_fast > 70 else "🔴 KD死叉"
            if curr_fast >= curr_slow: return "📈 已金叉，且向上發散"
            return "📉 已死叉，且向下發散"
            
        def eval_macd_status(curr_fast, curr_slow, prev_fast, prev_slow):
            if curr_fast > curr_slow and prev_fast <= prev_slow:
                return "🟢 MACD零下金叉" if curr_fast < 0 else "🟢 MACD金叉"
            if curr_fast < curr_slow and prev_fast >= prev_slow:
                return "🔴 MACD零上死叉" if curr_fast > 0 else "🔴 MACD死叉"
            if curr_fast >= curr_slow: return "📈 已金叉，且向上發散"
            return "📉 已死叉，且向下發散"

        kd_d_status = eval_kd_status(k_d, d_d, pk_d, pd_d)
        macd_d_status = eval_macd_status(macd_d, macds_d, pmacd_d, macds_d_prev)
        
        kd_w_status = eval_kd_status(k_w, d_w, pk_w, pd_w) if has_enough_weekly else "資料不足"
        macd_w_status = eval_macd_status(macd_w, macds_w, pmacd_w, pmacds_w) if has_enough_weekly else "資料不足"
        
        alerts = []
        if len(df) >= 20 and last_p < ma20 and ma20 > 0: alerts.append("跌破MA20")
        if high_52w > 0 and (high_52w - last_p) / high_52w >= 0.10:
            drop_pct = ((high_52w - last_p) / high_52w) * 100
            alerts.append(f"近高點回落{drop_pct:.1f}%")
        if high_20d > 0 and (high_20d - last_p) / high_20d >= 0.05:
            drop_pct_20d = ((high_20d - last_p) / high_20d) * 100
            alerts.append(f"20日高點回落{drop_pct_20d:.1f}%")
            
        if len(df) >= 20 and high_20d > 0 and low_20d > 0:
            amp_20d = (high_20d - low_20d) / low_20d
            if amp_20d <= 0.07:  
                alerts.append(f"💤 20日窄幅盤整(振幅{amp_20d*100:.1f}%)")
                
        if len(df) >= 60 and ma10 > 0 and ma20 > 0 and ma_season > 0:
            ma_max = max(ma10, ma20, ma_season)
            ma_min = min(ma10, ma20, ma_season)
            if (ma_max - ma_min) / ma_min <= 0.03: 
                alerts.append("🌀 均線糾結(醞釀表態)")
            
        if k_d > d_d and pk_d <= pd_d and k_d > 0:
            alerts.append("日KD低檔金叉" if k_d < 30 else "日KD金叉")
        elif k_d < d_d && pk_d >= pd_d and d_d > 0:
            alerts.append("日KD高檔死叉" if k_d > 70 else "日KD死叉")
            
        if has_enough_weekly:
            if k_w > d_w and pk_w <= pd_w and k_w > 0:
                alerts.append("週KD低檔金叉" if k_w < 30 else "週KD金叉")
            elif k_w < d_w and pk_w >= pd_w and d_w > 0:
                alerts.append("週KD高檔死叉" if k_w > 70 else "週KD死叉")
        
        if macd_d > macds_d and pmacd_d <= macds_d_prev and (macd_d != 0 or macds_d != 0):
            alerts.append("日MACD零下金叉" if macd_d < 0 else "日MACD金叉")
        elif macd_d < macds_d and pmacd_d >= macds_d_prev and (macd_d != 0 or macds_d != 0):
            alerts.append("日MACD零上死叉" if macd_d > 0 else "日MACD死叉")
            
        if has_enough_weekly:
            if macd_w > macds_w and pmacd_w <= pmacds_w and (macd_w != 0 or macds_w != 0):
                alerts.append("週MACD零下金叉" if macd_w < 0 else "週MACD金叉")
            elif macd_w < macds_w and pmacd_w >= pmacds_w and (macd_w != 0 or macds_w != 0):
                alerts.append("週MACD零上死叉" if macd_w > 0 else "週MACD死叉")
            
        action = "➖ 持平"
        has_strong_sell = any(x in a for a in alerts for x in ["高檔死叉", "零上死叉", "高點回落"])
        has_strong_buy = any(x in a for a in alerts for x in ["低檔金叉", "零下金叉"])
        has_sell = any(x in a for a in alerts for x in ["死叉", "跌破MA20", "20日高點回落"])
        has_buy = any(x in a for a in alerts for x in ["金叉"])
        
        if has_strong_sell: action = "🛑 賣出"
        elif has_strong_buy: action = "🚀 買進"
        elif has_sell and not has_buy: action = "⚠️ 減碼"
        elif has_buy and not has_sell: action = "🔼 加碼"

        alert_str = f"[{action}] " + (" / ".join(alerts) if alerts else "趨勢延續")

        pe_str = "無"
        f_info = get_fundamental_info(sym)
        pe_val = f_info.get('trailingPE')
        if pe_val is not None and pd.notna(pe_val):
            try: pe_str = f"{float(pe_val):.1f}"
            except: pe_str = "無"

        beta_val = f_info.get('beta')
        try: beta_str = f"{float(beta_val):.2f}" if beta_val is not None and str(beta_val).strip() != '' else "無"
        except: beta_str = "無"

        return {
            "市場": market, "標的": f"{name} ({sym})", "狀態警示": alert_str, "52週位置": f"{pos_52w:.1f} %",
            "Beta": beta_str, "日KD": f"K:{k_d:.1f}/D:{d_d:.1f} ({kd_d_status})",
            "週KD": f"K:{k_w:.1f}/D:{d_w:.1f} ({kd_w_status})",
            "日MACD": f"DIF:{macd_d:.2f} ({macd_d_status})",
            "週MACD": f"DIF:{macd_w:.2f} ({macd_w_status})",
            "P/E": pe_str, "收盤價": last_p, "MA20": ma20, "季線": ma_season, "半年線": ma_half, "年線": ma_year
        }
        
    except Exception as e:
        return {
            "市場": "⚠️ 異常", "標的": f"{name} ({sym})", "狀態警示": f"載入失敗: {str(e)}",
            "52週位置": "-", "Beta": "-", "日KD": "-", "週KD": "-", "日MACD": "-", "週MACD": "-", "P/E": "-",
            "收盤價": 0.0, "MA20": 0.0, "季線": 0.0, "半年線": 0.0, "年線": 0.0
        }

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

tab1, tab2, tab3 = st.tabs(["💰 投資組合總覽", "📈 技術分析掃描", "🏆 績效與股息追蹤"])

with tab1:
    with st.spinner("正在同步即時報價資料..."):
        usdtwd = get_usdtwd()
        total_market_value, total_dividends_2026 = 0, 0
        asset_allocation = {}
        individual_holdings = [] 

        for item in PORTFOLIO_TW:
            if pd.notna(item.get('Ticker')):
                ticker_str = str(item['Ticker']).strip()
                if not ticker_str: continue
                
                ticker = get_yf_ticker_tw(ticker_str)
                asset_type = str(item.get('類別', '台股')).strip()
                if not asset_type or asset_type == 'nan': asset_type = '台股未分類'
                
                price, div =
