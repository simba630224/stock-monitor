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
# 2. 核心抓取與計算邏輯 (精準修正 4 位與 6 位數上市櫃規格)
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
        pos_52w = ((last_p - low_52w) / (high_52w - low_52w + 1e-9) * 100) if (high_52w - low_52w) > 0 else 50.0

        high_20d = df['High'].tail(20).max() if len(df) > 0 else 0
        low_20d = df['Low'].tail(20).min() if len(df) > 0 else 0
        
        k_d = float(df['K_d'].iloc[-1]) if len(df) > 0 and pd.notna(df['K_d'].iloc[-1]) else 0
        d_d = float(df['D_d'].iloc[-1]) if len(df) > 0 and pd.notna(df['D_d'].iloc[-1]) else 0
        pk_d = float(df['K_d'].iloc[-2]) if len(df) > 1 and pd.notna(df['K_d'].iloc[-2]) else 0
        pd_d = float(df['D_d'].iloc[-2]) if len(df) > 1 and pd.notna(df['D_d'].iloc[-2]) else 0
        
        k_w = float(df_w['K_w'].iloc[-1]) if has_enough_weekly and pd.notna(df_w['K_w'].iloc[-1]) else 0.0
        d_w = float(df_w['D_w'].iloc[-1]) if has_enough_weekly and pd.notna(df_w['D_w'].iloc[-1]) else 0.0
        pk_w = float(df_w['K_w'].iloc[-2]) if len(df_w) > 1 and pd.notna(df_w['K_w'].iloc[-2]) else 0.0
        pd_w = float(df_w['D_w'].iloc[-2]) if len(df_w) > 1 and pd.notna(df_w['D_w'].iloc[-2]) else 0.0

        macd_d = float(df['MACD'].iloc[-1]) if len(df) > 0 and pd.notna(df['MACD'].iloc[-1]) else 0
        macds_d = float(df['MACD_Signal'].iloc[-1]) if len(df) > 0 and pd.notna(df['MACD_Signal'].iloc[-1]) else 0
        pmacd_d = float(df['MACD'].iloc[-2]) if len(df) > 1 and pd.notna(df['MACD'].iloc[-2]) else 0
        pmacds_d = float(df['MACD_Signal'].iloc[-2]) if len(df) > 1 and pd.notna(df['MACD_Signal'].iloc[-2]) else 0
        
        macd_w = float(df_w['MACD'].iloc[-1]) if has_enough_weekly and pd.notna(df_w['MACD'].iloc[-1]) else 0.0
        macds_w = float(df_w['MACD_Signal'].iloc[-1]) if has_enough_weekly and pd.notna(df_w['MACD_Signal'].iloc[-1]) else 0.0
        pmacd_w = float(df_w['MACD'].iloc[-2]) if len(df_w) > 1 and pd.notna(df_w['MACD'].iloc[-2]) else 0.0
        pmacds_w = float(df_w['MACD_Signal'].iloc[-2]) if len(df_w) > 1 and pd.notna(df_w['MACD_Signal'].iloc[-2]) else 0.0
        
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
        macd_d_status = eval_macd_status(macd_d, macds_d, pmacd_d, pmacds_d)
        
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
        elif k_d < d_d and pk_d >= pd_d and d_d > 0:
            alerts.append("日KD高檔死叉" if k_d > 70 else "日KD死叉")
            
        if has_enough_weekly:
            if k_w > d_w and pk_w <= pd_w and k_w > 0:
                alerts.append("週KD低檔金叉" if k_w < 30 else "週KD金叉")
            elif k_w < d_w and pk_w >= pd_w and d_w > 0:
                alerts.append("週KD高檔死叉" if k_w > 70 else "週KD死叉")
        
        if macd_d > macds_d and pmacd_d <= pmacds_d and (macd_d != 0 or macds_d != 0):
            alerts.append("日MACD零下金叉" if macd_d < 0 else "日MACD金叉")
        elif macd_d < macds_d and pmacd_d >= pmacds_d and (macd_d != 0 or macds_d != 0):
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
        try:
            pe_val = yf.Ticker(sym).info.get('trailingPE')
            if pd.notna(pe_val): pe_str = f"{pe_val:.1f}"
        except: pass

        f_info = get_fundamental_info(sym)
        beta_val = f_info.get('beta')
        try:
            beta_str = f"{float(beta_val):.2f}" if beta_val is not None and str(beta_val).strip() != '' else "無"
        except: 
            beta_str = "無"

        return {
            "市場": market, 
            "標的": f"{name} ({sym})", 
            "狀態警示": alert_str, 
            "52週位置": f"{pos_52w:.1f} %",
            "Beta": beta_str,
            "日KD": f"K:{k_d:.1f}/D:{d_d:.1f} ({kd_d_status})",
            "週KD": f"K:{k_w:.1f}/D:{d_w:.1f} ({kd_w_status})" if has_enough_weekly else "資料不足",
            "日MACD": f"DIF:{macd_d:.2f} ({macd_d_status})",
            "週MACD": f"DIF:{macd_w:.2f} ({macd_w_status})" if has_enough_weekly else "資料不足",
            "P/E": pe_str,
            "收盤價": last_p, 
            "MA20": ma20, 
            "季線": ma_season, 
            "半年線": ma_half, 
            "年線": ma_year
        }
        
    except Exception as e:
        return {
            "市場": "⚠️ 異常",
            "標的": f"{name} ({sym})",
            "狀態警示": f"載入失敗: {str(e)}",
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
                    
                    if total_shares >= 1000 and total_shares % 1000 == 0:
                        disp_qty = f"{int(total_shares/1000)}張"
                    else:
                        disp_qty = f"{total_shares:g}股"
                        
                    name_str = str(item.get('名稱', '')).strip()
                    display_name = name_str if name_str and name_str != 'nan' else ticker_str
                        
                    individual_holdings.append({
                        '標的': display_name, 
                        '標的與股數': f"{display_name} ({disp_qty})", 
                        '總市值': val, 
                        '股息': div_tot, 
                        '類別': asset_type,
                        '總股數': total_shares
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
                        '標的': display_name, 
                        '標的與股數': f"{display_name} ({disp_qty})", 
                        '總市值': val, 
                        '股息': div_tot, 
                        '類別': asset_type,
                        '總股數': total_shares
                    })

    col1, col2, col3 = st.columns(3)
    col1.metric("總市值 (TWD)", f"${total_market_value:,.0f}")
    col2.metric("2026 累計股息預估 (TWD)", f"${total_dividends_2026:,.0f}")
    col3.metric("目前匯率 (USD/TWD)", f"{usdtwd:.3f}")

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
            fig_mv_bar.update_yaxes(title='標的 (總數量)')
            st.plotly_chart(fig_mv_bar, use_container_width=True)
            
        with col_bar2:
            df_div_sorted = df_ind.sort_values(by='股息', ascending=True)
            fig_div_bar = px.bar(df_div_sorted, x='股息', y='標的與股數', orientation='h', title='各標的預估股息 (TWD)', color='類別', text_auto='.2s', hover_data=['標的', '總股數'], color_discrete_map=category_color_map)
            fig_div_bar.update_layout(height=800, margin=dict(l=0, r=0, t=30, b=0), showlegend=False, yaxis={'categoryorder':'array', 'categoryarray': df_div_sorted['標的與股數']})
            fig_div_bar.update_yaxes(title='標的 (總數量)')
            st.plotly_chart(fig_div_bar, use_container_width=True)

with tab2:
    st.markdown("自動偵測窄幅盤整、均線糾結，以及 **KD / MACD** 的進階交叉判定。（台股採 60/120/240日線；美股採 50/100/200日線）")
    
    with st.expander("💡 狀態警示名詞定義說明", expanded=False):
        st.markdown("""
        * **綜合買賣評級**：系統依據技術指標自動判斷的交易建議。
            * **🚀 買進**：出現低檔金叉或零下金叉等強烈翻多訊號。
            * **🛑 賣出**：出現高檔死叉、零上死叉或由高點大幅回落等強烈翻空訊號。
            * **🔼 加碼**：出現一般金叉等偏多訊號。
            * **⚠️ 減碼**：跌破月線、20日高點回落或一般死叉等偏空訊號。
            * **➖ 持平**：處於盤整或趨勢延續中，無明顯轉折訊號。
        * **💤 窄幅盤整 (振幅壓縮)**：過去 20 個交易日的最高價與最低價，上下振幅壓縮在 7% 以內，代表價格正處於狹幅箱型整理。
        * **🌀 均線糾結 (醞釀表態)**：短線 (10日)、中線 (20日) 與長線 (季線) 三條均線的數值差距在 3% 以內，隨時可能爆發新方向。
        * **52週位置 (%)**：目前收盤價處於近 1 年最高價與最低價區間的相對百分比位置。100% 代表正處於最高點。
        * **Beta 係數**：衡量相對大盤的波動度。Beta = 1.0 代表波動與大盤同步。
        """)
    
    with st.spinner("正在計算各標的技術指標..."):
        ta_results = []
        target_options = {} 
        
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
            res = process_technical_analysis(sym, name)
            if res: 
                ta_results.append(res)
                if "⚠️ 異常" not in res.get("市場", ""):
                    target_options[f"{name} ({sym})"] = sym
            
        if ta_results:
            df_ta = pd.DataFrame(ta_results)
            st.dataframe(
                df_ta, 
                column_config={
                    "市場": st.column_config.TextColumn("市場", width="small"),
                    "標的": st.column_config.TextColumn("名稱 (代號)", width="medium"),
                    "狀態警示": st.column_config.TextColumn("🚨 狀態警示", width="large"),
                    "52週位置": st.column_config.TextColumn("52週位置", width="small"),
                    "Beta": st.column_config.TextColumn("Beta 係數", width="small"),
                    "日KD": st.column_config.TextColumn("日 KD 狀態", width="medium"),
                    "週KD": st.column_config.TextColumn("週 KD 狀態", width="medium"),
                    "日MACD": st.column_config.TextColumn("日 MACD", width="medium"),
                    "週MACD": st.column_config.TextColumn("週 MACD", width="medium"),
                    "P/E": st.column_config.TextColumn("P/E", width="small"),
                    "收盤價": st.column_config.NumberColumn("收盤價", format="%.2f"),
                    "MA20": st.column_config.NumberColumn("MA20", format="%.2f"),
                    "季線": st.column_config.NumberColumn("季線", format="%.2f"),
                    "半年線": st.column_config.NumberColumn("半年線", format="%.2f"),
                    "年線": st.column_config.NumberColumn("年線", format="%.2f"),
                },
                hide_index=True,
                use_container_width=True,
                height=450
            )

    st.divider()
    
    st.subheader("📈 個股/ETF 詳細技術線圖 (含 MA / KD / MACD)")
    
    col_select_stock, col_select_period = st.columns([2, 1])
    with col_select_stock:
        options_list = list(target_options.keys()) if target_options else ["暫無可繪圖標的"]
        selected_name = st.selectbox("請選擇要查看技術線圖的標的：", options=options_list)
        
    with col_select_period:
        period_label = st.selectbox("請選擇 K 線圖時間軸顯示範圍：", options=["半年 (150日)", "一年 (252日)", "三年 (完整數據)"], index=0)
    
    if period_label == "半年 (150日)":
        tail_days = 150
    elif period_label == "一年 (252日)":
        tail_days = 252
    else:
        tail_days = 9999 
        
    if selected_name and selected_name != "暫無可繪圖標的":
        sym = target_options[selected_name]
        df_chart = get_stock_data(sym)
        if df_chart is not None:
            df_plot = df_chart.tail(tail_days)
            is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
            
            season_label = "MA60 (季線)" if is_tw else "MA50 (季線)"
            half_label = "MA120 (半年線)" if is_tw else "MA100 (半年線)"
            year_label = "MA240 (年線)" if is_tw else "MA200 (年線)"
            
            fig_tech = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                                     vertical_spacing=0.04, row_heights=[0.5, 0.25, 0.25],
                                     subplot_titles=(f"{selected_name} - 走勢圖 ({period_label})", "日 KD 指標", "MACD 指標 (12,26,9)"))
            
            fig_tech.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name='K線', increasing_line_color='red', decreasing_line_color='green'), row=1, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MA10'], line=dict(color='yellow', width=1.5), name='MA10'), row=1, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MA20'], line=dict(color='blue', width=1.5), name='MA20'), row=1, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['季線'], line=dict(color='orange', width=1.5), name=season_label), row=1, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['半年線'], line=dict(color='magenta', width=1.5), name=half_label), row=1, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['年線'], line=dict(color='cyan', width=1.5), name=year_label), row=1, col=1)
            
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['K_d'], line=dict(color='blue', width=1.5), name='K值 (日)'), row=2, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['D_d'], line=dict(color='orange', width=1.5), name='D值 (日)'), row=2, col=1)
            fig_tech.add_hline(y=80, line_dash="dash", line_color="red", row=2, col=1)
            fig_tech.add_hline(y=20, line_dash="dash", line_color="green", row=2, col=1)
            
            macd_colors = ['red' if val >= 0 else 'green' for val in df_plot['MACD_Hist']]
            fig_tech.add_trace(go.Bar(x=df_plot.index, y=df_plot['MACD_Hist'], marker_color=macd_colors, name='OSC 柱狀圖'), row=3, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MACD'], line=dict(color='blue', width=1.5), name='MACD (DIF)'), row=3, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MACD_Signal'], line=dict(color='orange', width=1.5), name='Signal (DEA)'), row=3, col=1)
            
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
            if t and t != 'nan':
                sym = get_yf_ticker_tw(t)
                scan_list.append((sym, t, '台股'))
                
        for item in PORTFOLIO_US:
            t = str(item.get('Ticker', '')).strip()
            if t and t != 'nan':
                scan_list.append((t, t, '美股'))
                
        for sym, display_ticker, market in scan_list:
            res = get_perf_div_data(sym, display_ticker, market, bench_returns)
            if res:
                perf_results.append(res)
                
        if perf_results:
            df_perf = pd.DataFrame(perf_results)
            st.dataframe(
                df_perf,
                column_config={
                    "市場": st.column_config.TextColumn("市場", width="small"),
                    "標的": st.column_config.TextColumn("代號", width="small"),
                    "最新收盤價": st.column_config.NumberColumn("收盤價", format="%.2f"),
                    "近一季報酬": st.column_config.NumberColumn("近一季報酬", format="%.2f %%"),
                    "近半年報酬": st.column_config.NumberColumn("近半年報酬", format="%.2f %%"),
                    "近一年報酬": st.column_config.NumberColumn("近一年報酬", format="%.2f %%"),
                    "相對大盤(1年)": st.column_config.TextColumn("相對大盤 (1年)", width="medium"),
                    "近一年殖利率": st.column_config.NumberColumn("近一年殖利率", format="%.2f %%"),
                    "總配息金額": st.column_config.NumberColumn("近一年總配息", format="%.2f"),
                    "近一年配息明細": st.column_config.TextColumn("近一年配息紀錄 (每次發放金額)", width="large"),
                    "毛利率": st.column_config.TextColumn("毛利率", width="small"),
                    "營益率": st.column_config.TextColumn("營益率", width="small"),
                    "淨利率": st.column_config.TextColumn("淨利率", width="small"),
                    "ROE": st.column_config.TextColumn("ROE", width="small"),
                },
                hide_index=True,
                use_container_width=True,
                height=600
            )

# ==========================================
# 4. 後台管理介面 (側邊欄雙分頁編輯)
# ==========================================
with st.sidebar:
    st.header("📝 持股與觀察名單管理")
    st.markdown("想要追蹤某檔股票嗎？**新增代號並將股數設為 0**，它就會自動加入技術分析掃描！")
    
    st.subheader("🇹🇼 台股清單")
    if not df_tw.empty:
        edited_df_tw = st.data_editor(df_tw, num_rows="dynamic", use_container_width=True, key="tw_editor")
        if st.button("💾 儲存台股變更", use_container_width=True):
            with st.spinner("正在寫入台股資料..."):
                try:
                    conn.update(worksheet="TW_Portfolio", data=edited_df_tw)
                    st.success("✅ 台股更新成功！請重新整理網頁。")
                except Exception as e: st.error(f"寫入失敗：{e}")
    else: st.info("台股清單目前為空或未連線。")

    st.divider()

    st.subheader("🇺🇸 美股清單")
    if not df_us.empty:
        edited_df_us = st.data_editor(df_us, num_rows="dynamic", use_container_width=True, key="us_editor")
        if st.button("💾 儲存美股變更", use_container_width=True):
            with st.spinner("正在寫入美股資料..."):
                try:
                    conn.update(worksheet="US_Portfolio", data=edited_df_us)
                    st.success("✅ 美股更新成功！請重新整理網頁。")
                except Exception as e: st.error(f"寫入失敗：{e}")
    else: st.info("美股清單目前為空或未連線。")
