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
# 0. 輔助函式：安全轉換與均線位階
# ==========================================
def safe_float(val):
    try:
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
    df_tw = df_tw.dropna(subset=['Ticker'])
    if '名稱' not in df_tw.columns: df_tw['名稱'] = ''
    if 'Shares' not in df_tw.columns: df_tw['Shares'] = 0.0
    if '出借' not in df_tw.columns: df_tw['出借'] = 0.0
    if '類別' not in df_tw.columns: df_tw['類別'] = '台股'
    PORTFOLIO_TW = df_tw.to_dict('records')
except Exception as e:
    st.error(f"⚠️ 無法讀取台股資料。錯誤: {e}")
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
    st.warning(f"⚠️ 無法讀取美股資料。錯誤: {e}")
    PORTFOLIO_US = []
    df_us = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "複委託", "類別"])

# ==========================================
# 2. 核心抓取與計算邏輯
# ==========================================
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip().upper()
    if ticker.endswith('.TW') or ticker.endswith('.TWO'):
        return ticker
    if ticker.endswith('B') or ticker.endswith('C') or ticker == '009815':
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
                data['MA20'] = data['Close'].rolling(window=20, min_periods=1).mean()
                data['MA60'] = data['Close'].rolling(window=60, min_periods=1).mean()
                return data
        except:
            time.sleep(1)
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
            'trailingPE': info.get('trailingPE')
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
        except:
            time.sleep(1)
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
                
                is_new_stock = False
                if len(valid_hist) > 252:
                    ret_1y = ((curr_p - float(valid_hist.iloc[-252])) / float(valid_hist.iloc[-252])) * 100
                else:
                    ret_1y = ((curr_p - float(valid_hist.iloc[0])) / float(valid_hist.iloc[0])) * 100
                    is_new_stock = True

                bench_ret = bench_returns.get(market, 0.0)
                rel_val = ret_1y - bench_ret
                emoji = "🟢" if rel_val >= 0 else "🔴"
                sign = "+" if rel_val > 0 else ""
                suffix = " (上市至今)" if is_new_stock else ""
                rel_str_display = f"{emoji} {sign}{rel_val:.2f} %{suffix}"

                f_info = get_fundamental_info(sym)
                is_etf = 'ETF' in str(f_info.get('quoteType', '')).upper() or 'MUTUALFUND' in str(f_info.get('quoteType', '')).upper()
                
                def fmt_pct(val):
                    if is_etf: return "ETF/不適用"
                    if val is not None and pd.notna(val): return f"{val * 100:.1f} %"
                    return "暫無資料"

                gross_m = fmt_pct(f_info.get('grossMargins'))
                op_m = fmt_pct(f_info.get('operatingMargins'))
                prof_m = fmt_pct(f_info.get('profitMargins'))
                roe = fmt_pct(f_info.get('returnOnEquity'))

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
                    "近一季含息報酬": ret_1q, "近半年含息報酬": ret_6m, "近一年含息報酬": ret_1y,
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
            agg_dict = {'Close': 'last'}
            if 'Open' in df.columns: agg_dict['Open'] = 'first'
            if 'High' in df.columns: agg_dict['High'] = 'max'
            if 'Low' in df.columns: agg_dict['Low'] = 'min'
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

        # 新增均線位階判定
        ma_status_str = analyze_ma_relation(last_p, ma20, ma_season, ma_half, ma_year)
        
        # 跌破判斷
        is_break_ma = (last_p < ma20 and prev_p >= prev_ma20) or (last_p < ma_season and prev_p >= prev_ma_season)
        
        high_52w = df['High'].tail(252).max() if 'High' in df.columns else 0.0
        low_52w = df['Low'].tail(252).min() if 'Low' in df.columns else 0.0
        pos_52w = ((last_p - low_52w) / (high_52w - low_52w + 1e-9) * 100) if (high_52w - low_52w) > 0 else 50.0

        high_20d = df['High'].tail(20).max() if 'High' in df.columns else 0.0
        low_20d = df['Low'].tail(20).min() if 'Low' in df.columns else 0.0
        
        k_d = float(df['K_d'].iloc[-1]) if 'K_d' in df.columns and pd.notna(df['K_d'].iloc[-1]) else 50.0
        d_d = float(df['D_d'].iloc[-1]) if 'D_d' in df.columns and pd.notna(df['D_d'].iloc[-1]) else 50.0
        pk_d = float(df['K_d'].iloc[-2]) if len(df) > 1 and 'K_d' in df.columns and pd.notna(df['K_d'].iloc[-2]) else 50.0
        pd_d = float(df['D_d'].iloc[-2]) if len(df) > 1 and 'D_d' in df.columns and pd.notna(df['D_d'].iloc[-2]) else 50.0
        
        macd_d = float(df['MACD'].iloc[-1]) if pd.notna(df['MACD'].iloc[-1]) else 0.0
        macds_d = float(df['MACD_Signal'].iloc[-1]) if pd.notna(df['MACD_Signal'].iloc[-1]) else 0.0
        pmacd_d = float(df['MACD'].iloc[-2]) if len(df) > 1 and pd.notna(df['MACD'].iloc[-2]) else 0.0
        pmacds_d = float(df['MACD_Signal'].iloc[-2]) if len(df) > 1 and pd.notna(df['MACD_Signal'].iloc[-2]) else 0.0
        
        def eval_kd_status(curr_fast, curr_slow, prev_fast, prev_slow):
            if curr_fast > curr_slow and prev_fast <= prev_slow: return "🟢 KD低檔金叉" if curr_fast < 30 else "🟢 KD金叉"
            if curr_fast < curr_slow and prev_fast >= prev_slow: return "🔴 KD高檔死叉" if curr_fast > 70 else "🔴 KD死叉"
            if curr_fast >= curr_slow: return "📈 已金叉，且向上發散"
            return "📉 已死叉，且向下發散"
            
        def eval_macd_status(curr_fast, curr_slow, prev_fast, prev_slow):
            if curr_fast > curr_slow and prev_fast <= prev_slow: return "🟢 MACD零下金叉" if curr_fast < 0 else "🟢 MACD金叉"
            if curr_fast < curr_slow and prev_fast >= prev_slow: return "🔴 MACD零上死叉" if curr_fast > 0 else "🔴 MACD死叉"
            if curr_fast >= curr_slow: return "📈 已金叉，且向上發散"
            return "📉 已死叉，且向下發散"

        kd_d_status = eval_kd_status(k_d, d_d, pk_d, pd_d)
        macd_d_status = eval_macd_status(macd_d, macds_d, pmacd_d, pmacds_d)
        kd_w_status = eval_kd_status(k_w, d_w, pk_w, pd_w) if has_enough_weekly else "資料不足"
        macd_w_status = eval_macd_status(macd_w, macds_w, pmacd_w, pmacds_w) if has_enough_weekly else "資料不足"
        
        alerts = []
        if is_break_ma: alerts.append("跌破月/季線")
        
        if high_52w > 0 and (high_52w - last_p) / high_52w >= 0.15:
            drop_pct = ((high_52w - last_p) / high_52w) * 100
            alerts.append(f"近高點回落{drop_pct:.1f}%")
            
        if high_20d > 0 and (high_20d - last_p) / high_20d >= 0.10:
            drop_pct_20d = ((high_20d - last_p) / high_20d) * 100
            alerts.append(f"20日回落{drop_pct_20d:.1f}%")
            
        if len(df) >= 20 and high_20d > 0 and low_20d > 0:
            amp_20d = (high_20d - low_20d) / low_20d
            if amp_20d <= 0.07: alerts.append(f"💤 20日窄幅盤整(振幅{amp_20d*100:.1f}%)")
                
        if len(df) >= 60 and ma10 > 0 and ma20 > 0 and ma_season > 0:
            ma_max = max(ma10, ma20, ma_season)
            ma_min = min(ma10, ma20, ma_season)
            if (ma_max - ma_min) / ma_min <= 0.03: alerts.append("🌀 均線糾結")
            
        if "金叉" in kd_d_status: alerts.append(kd_d_status[2:])
        elif "死叉" in kd_d_status: alerts.append(kd_d_status[2:])
            
        if has_enough_weekly:
            if "金叉" in kd_w_status: alerts.append(kd_w_status.replace("🟢 ", "週"))
            elif "死叉" in kd_w_status: alerts.append(kd_w_status.replace("🔴 ", "週"))
            
            if "金叉" in macd_w_status: alerts.append(macd_w_status.replace("🟢 ", "週"))
            elif "死叉" in macd_w_status: alerts.append(macd_w_status.replace("🔴 ", "週"))
            
        action = "➖ 持平"
        has_buy = any(x in a for a in alerts for x in ["週KD金叉", "週MACD金叉"])
        has_sell = any(x in a for a in alerts for x in ["週KD死叉", "週MACD死叉", "近高點回落"])
        has_reduce = any(x in a for a in alerts for x in ["20日回落"])
        
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
            # 儲存供亮點摘要使用的原始資料
            "_raw_kd_d": kd_d_status, "_raw_kd_w": kd_w_status, "_raw_pe": pe_val, "_is_break_ma": is_break_ma
        }
        
    except Exception as e:
        return None

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

tab1, tab2, tab3, tab4 = st.tabs(["💰 投資組合總覽", "📈 技術分析掃描", "🏆 績效與股息追蹤", "📖 每日看盤心得"])

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
                
                price, div = get_basic_data(ticker)
                shares_own = safe_float(item.get('Shares'))
                shares_lent = safe_float(item.get('出借'))
                total_shares = shares_own + shares_lent
                
                if price > 0 and total_shares > 0:
                    val = price * total_shares
                    div_tot = div * total_shares
                    total_market_value += val
                    asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val
                    total_dividends_2026 += div_tot
                    
                    disp_qty = f"{int(total_shares/1000)}張" if total_shares >= 1000 and total_shares % 1000 == 0 else f"{total_shares:g}股"
                    name_str = str(item.get('名稱', '')).strip()
                    display_name = name_str if name_str and name_str != 'nan' else ticker_str
                        
                    individual_holdings.append({
                        '標的': display_name, '標的與股數': f"{display_name} ({disp_qty})", 
                        '總市值': val, '股息': div_tot, '類別': asset_type, '總股數': total_shares
                    })

        for item in PORTFOLIO_US:
            if pd.notna(item.get('Ticker')):
                ticker_str = str(item['Ticker']).strip()
                if not ticker_str: continue
                
                asset_type = str(item.get('類別', '美股')).strip()
                if not asset_type or asset_type == 'nan': asset_type = '美股未分類'
                
                price, div = get_basic_data(ticker_str)
                shares_own = safe_float(item.get('Shares'))
                shares_sub = safe_float(item.get('複委託'))
                total_shares = shares_own + shares_sub
                
                if price > 0 and total_shares > 0:
                    val = price * total_shares * usdtwd
                    div_tot = div * total_shares * usdtwd
                    total_market_value += val
                    asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val
                    total_dividends_2026 += div_tot
                    
                    disp_qty = f"{total_shares:g}股"
                    name_str = str(item.get('名稱', '')).strip()
                    display_name = name_str if name_str and name_str != 'nan' else ticker_str
                    
                    individual_holdings.append({
                        '標的': display_name, '標的與股數': f"{display_name} ({disp_qty})", 
                        '總市值': val, '股息': div_tot, '類別': asset_type, '總股數': total_shares
                    })

    col1, col2, col3 = st.columns(3)
    col1.metric("總市值 (TWD)", f"${total_market_value:,.0f}")
    col2.metric("2026 累計股息預估 (TWD)", f"${total_dividends_2026:,.0f}")
    col3.metric("目前匯率 (USD/TWD)", f"{usdtwd:.3f}")

    history_error = False
    try:
        df_history = conn.read(worksheet="Value_History", ttl=0)
        if df_history is None or df_history.empty or 'Date' not in df_history.columns:
            df_history = pd.DataFrame(columns=['Date', 'Total_Value', 'Last_Updated'])
        else:
            df_history['Date'] = df_history['Date'].astype(str).str.strip()
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        now_time = datetime.now().strftime('%H:%M:%S')
        needs_update = False
        
        if today_str in df_history['Date'].values:
            idx = df_history.index[df_history['Date'] == today_str].tolist()[0]
            existing_val = safe_float(df_history.at[idx, 'Total_Value'])
            if abs(existing_val - total_market_value) > 1:
                df_history.at[idx, 'Total_Value'] = total_market_value
                df_history.at[idx, 'Last_Updated'] = now_time
                needs_update = True
        else:
            new_row = pd.DataFrame([{'Date': today_str, 'Total_Value': total_market_value, 'Last_Updated': now_time}])
            df_history = pd.concat([df_history, new_row], ignore_index=True)
            needs_update = True
            
        if needs_update:
            conn.update(worksheet="Value_History", data=df_history)
            
    except Exception as e:
        history_error = True
        df_history = pd.DataFrame([{'Date': datetime.now().strftime('%Y-%m-%d'), 'Total_Value': total_market_value, 'Last_Updated': datetime.now().strftime('%H:%M:%S')}])

    st.divider()

    if history_error:
        st.info("💡 提示：若要啟用「每日總市值趨勢追蹤」功能，請在您的 Google 試算表中手動新增一個名為 `Value_History` 的工作表（可先留空）。")
    elif not df_history.empty:
        st.subheader("📈 總市值每日變化趨勢")
        fig_hist = px.line(df_history, x='Date', y='Total_Value', text='Total_Value', markers=True)
        fig_hist.update_traces(textposition="top center", texttemplate='%{text:,.0f}')
        fig_hist.update_layout(yaxis_title="總市值 (TWD)", xaxis_title="日期", margin=dict(t=30, b=0, l=0, r=0), height=350)
        st.plotly_chart(fig_hist, use_container_width=True)

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
        summary_golden_d, summary_death_d = [], []
        summary_golden_w, summary_death_w = [], []
        summary_ma_break, summary_low_pe = [], []
        
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
                
                # 分類至盤後摘要
                pe_val = res.get('_raw_pe')
                pe_str = f"P/E: {pe_val:.1f}" if pd.notna(pe_val) else "無 P/E"
                name_pe = f"{name} ({pe_str})"
                
                if "低檔金叉" in res['_raw_kd_d']: summary_golden_d.append(name_pe)
                if "高檔死叉" in res['_raw_kd_d']: summary_death_d.append(name_pe)
                if "低檔金叉" in res['_raw_kd_w']: summary_golden_w.append(name_pe)
                if "高檔死叉" in res['_raw_kd_w']: summary_death_w.append(name_pe)
                if res['_is_break_ma']: summary_ma_break.append(name)
                if pd.notna(pe_val) and pe_val < 25: summary_low_pe.append(name_pe)

    # 🔥 盤後亮點摘要區塊
    st.markdown("### 📊 盤後亮點摘要")
    col_sum1, col_sum2 = st.columns(2)
    with col_sum1:
        st.success(f"**☀️ 多方訊號**\n\n"
                   f"**日KD低檔金叉**：{', '.join(summary_golden_d) if summary_golden_d else '無'}\n\n"
                   f"**週KD低檔金叉**：{', '.join(summary_golden_w) if summary_golden_w else '無'}\n\n"
                   f"**低本益比 (<25)**：{', '.join(summary_low_pe) if summary_low_pe else '無'}")
    with col_sum2:
        st.error(f"**⛈️ 空方警示**\n\n"
                 f"**日KD高檔死叉**：{', '.join(summary_death_d) if summary_death_d else '無'}\n\n"
                 f"**週KD高檔死叉**：{', '.join(summary_death_w) if summary_death_w else '無'}\n\n"
                 f"**跌破月/季線**：{', '.join(summary_ma_break) if summary_ma_break else '無'}")

    st.divider()
    st.markdown("### 📋 完整技術分析清單")
    with st.expander("💡 狀態警示名詞定義說明", expanded=False):
        st.markdown("""
        * **綜合買賣評級**：依據指標判定：🚀 買進 (週金叉)、🛑 賣出 (週死叉或近高點回落 15%)、⚠️ 減碼 (20日高點回落 10%)。
        * **均線位階**：輔助判定長短線多空趨勢，如「站穩 月/季線」代表強勢。
        """)
        
    if ta_results:
        df_ta = pd.DataFrame(ta_results)
        # 移除內部運算用欄位
        df_ta = df_ta.drop(columns=['_raw_kd_d', '_raw_kd_w', '_raw_pe', '_is_break_ma'], errors='ignore')
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
                    "近一季含息報酬": st.column_config.NumberColumn("近一季含息報酬", format="%.2f %%"),
                    "近半年含息報酬": st.column_config.NumberColumn("近半年含息報酬", format="%.2f %%"),
                    "近一年含息報酬": st.column_config.NumberColumn("近一年含息報酬", format="%.2f %%"),
                    "相對大盤(1年)": st.column_config.TextColumn("相對大盤 (1年)", width="medium"),
                    "近一年殖利率": st.column_config.NumberColumn("近一年殖利率", format="%.2f %%"),
                    "總配息金額": st.column_config.NumberColumn("近一年總配息", format="%.2f"),
                    "近一年配息明細": st.column_config.TextColumn("近一年配息紀錄 (每次發放金額)", width="large"),
                    "毛利率": st.column_config.TextColumn("毛利率", width="small"),
                    "營益率": st.column_config.TextColumn("營益率", width="small"),
                    "淨利率": st.column_config.TextColumn("淨利率", width="small"),
                    "ROE": st.column_config.TextColumn("ROE", width="small"),
                },
                hide_index=True, height=600
            )

with tab4:
    st.subheader("📖 每日看盤心得紀錄")
    journal_error = False
    
    try:
        df_journal = conn.read(worksheet="Trading_Journal", ttl=0)
        if df_journal is None or df_journal.empty or 'Date' not in df_journal.columns:
            df_journal = pd.DataFrame(columns=['Date', 'Notes', 'Last_Updated'])
        else:
            df_journal['Date'] = df_journal['Date'].astype(str).str.strip()
    except Exception:
        journal_error = True
        df_journal = pd.DataFrame(columns=['Date', 'Notes', 'Last_Updated'])

    if journal_error:
        st.info("💡 提示：若要啟用「每日看盤心得」功能，請在您的 Google 試算表中手動新增一個名為 `Trading_Journal` 的工作表（可先留空）。")
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
        else:
            st.write("尚無歷史紀錄。")

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
