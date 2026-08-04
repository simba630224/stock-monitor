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

st.set_page_config(page_title="行動隨身投資儀表板", layout="wide")

# ==========================================
# 0. 輔助函式：強力防呆安全轉換
# ==========================================
def safe_float(val):
    try:
        if isinstance(val, str):
            val = re.sub(r'[^\d.-]', '', val)
        return float(val) if pd.notna(val) and str(val).strip() != '' else 0.0
    except:
        return 0.0

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

@st.cache_data(ttl=600)
def get_basic_data(ticker):
    for _ in range(3):
        try:
            time.sleep(0.2)
            hist = yf.Ticker(ticker).history(period="1y")
            if not hist.empty:
                price = float(hist['Close'].dropna().iloc[-1])
                div_2026 = float(hist['Dividends'][hist.index.year == 2026].sum()) if 'Dividends' in hist.columns else 0.0
                div_1y = float(hist['Dividends'].sum()) if 'Dividends' in hist.columns else 0.0
                return price, div_2026, div_1y
        except:
            time.sleep(0.5)
    return 0.0, 0.0, 0.0

@st.cache_data(ttl=600)
def get_usdtwd():
    try:
        hist = yf.Ticker("TWD=X").history(period="5d")
        if not hist.empty: return float(hist['Close'].dropna().iloc[-1])
    except: pass
    return 32.5

@st.cache_data(ttl=3600)
def get_benchmark_returns():
    benchmarks = {'台股': 0.0, '美股': 0.0}
    try:
        tw_hist = yf.Ticker("^TWII").history(period="1y").dropna(subset=['Close'])
        benchmarks['台股'] = ((tw_hist['Close'].iloc[-1] - tw_hist['Close'].iloc[0]) / tw_hist['Close'].iloc[0]) * 100
    except: pass
    try:
        us_hist = yf.Ticker("^GSPC").history(period="1y").dropna(subset=['Close'])
        benchmarks['美股'] = ((us_hist['Close'].iloc[-1] - us_hist['Close'].iloc[0]) / us_hist['Close'].iloc[0]) * 100
    except: pass
    return benchmarks

@st.cache_data(ttl=3600)
def get_fundamental_info(sym):
    try:
        info = yf.Ticker(sym).info
        return {
            'quoteType': info.get('quoteType'),
            'returnOnEquity': info.get('returnOnEquity'),
            'trailingPE': info.get('trailingPE'),
            'forwardPE': info.get('forwardPE')
        }
    except: return {}

@st.cache_data(ttl=600)
def get_stock_data(sym):
    try:
        df = yf.download(sym, period="3y", progress=False, threads=False)
        if not df.empty and len(df) >= 2:
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df.index = df.index.tz_localize(None) if df.index.tz is not None else df.index
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna(subset=['Close'])
            if 'Close' not in df.columns: return None
            
            df['MA10'] = df['Close'].rolling(10, min_periods=1).mean()
            df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
            
            is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
            season_len = 60 if is_tw else 50
            df['MA_season'] = df['Close'].rolling(season_len, min_periods=1).mean()
            
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
            return df
    except: pass
    return None

@st.cache_data(ttl=600)
def get_perf_div_data(sym, display_ticker, market, bench_returns):
    try:
        hist = yf.Ticker(sym).history(period="2y", auto_adjust=True)
        if not hist.empty:
            curr_p = float(hist['Close'].dropna().iloc[-1])
            valid_hist = hist['Close'].dropna()
            
            ret_1q = (((curr_p - valid_hist.iloc[-63]) / valid_hist.iloc[-63]) * 100) if len(valid_hist) > 63 else 0.0
            ret_1y = (((curr_p - valid_hist.iloc[-252]) / valid_hist.iloc[-252]) * 100) if len(valid_hist) > 252 else (((curr_p - valid_hist.iloc[0]) / valid_hist.iloc[0]) * 100)

            bench_ret = bench_returns.get(market, 0.0)
            rel_val = ret_1y - bench_ret

            f_info = get_fundamental_info(sym)
            is_etf = 'ETF' in str(f_info.get('quoteType', '')).upper()
            
            roe_raw = f_info.get('returnOnEquity')
            roe_val = roe_raw * 100 if roe_raw is not None and not is_etf else None

            tot_div = float(hist['Dividends'][hist['Dividends'] > 0].sum()) if 'Dividends' in hist.columns else 0.0
            yield_1y = (tot_div / curr_p) * 100 if curr_p > 0 and tot_div > 0 else 0.0

            return {
                "市場": market, "代號": display_ticker, "收盤": curr_p,
                "季報酬": ret_1q, "年報酬": ret_1y,
                "對大盤": rel_val, "殖利率": yield_1y, "ROE": roe_val
            }
    except: pass
    return None

@st.cache_data(ttl=600)
def process_technical_analysis(sym, name):
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
                
                k_w = float(df_w['K_w'].iloc[-1])
                d_w = float(df_w['D_w'].iloc[-1])
                macd_w = float(df_w['MACD'].iloc[-1])
                macds_w = float(df_w['MACD_Signal'].iloc[-1])
                if len(df_w) > 1:
                    pk_w = float(df_w['K_w'].iloc[-2])
                    pd_w = float(df_w['D_w'].iloc[-2])
                    pmacd_w = float(df_w['MACD'].iloc[-2])
                    pmacds_w = float(df_w['MACD_Signal'].iloc[-2])
        except: pass
        
        last_p = float(df['Close'].iloc[-1])
        ma20 = float(df['MA20'].iloc[-1]) if pd.notna(df['MA20'].iloc[-1]) else 0
        ma_season = float(df['MA_season'].iloc[-1]) if pd.notna(df['MA_season'].iloc[-1]) else 0
        prev_ma_season = float(df['MA_season'].iloc[-2]) if len(df) > 1 and pd.notna(df['MA_season'].iloc[-2]) else 0
        
        is_break_ma = (last_p < ma_season and df['Close'].iloc[-2] >= prev_ma_season)

        ma20_up_5d = False
        ma_s_up_5d = False
        ma20_dn_5d = False
        ma_s_dn_5d = False
        above_ma20_5d = False
        below_ma20_5d = False
        above_mas_5d = False
        below_mas_5d = False

        if len(df) >= 6 and pd.notna(df['MA_season'].iloc[-6]):
            ma20_up_5d = all(df['MA20'].iloc[i] > df['MA20'].iloc[i-1] for i in range(-1, -6, -1))
            ma_s_up_5d = all(df['MA_season'].iloc[i] > df['MA_season'].iloc[i-1] for i in range(-1, -6, -1))
            
            ma20_dn_5d = all(df['MA20'].iloc[i] < df['MA20'].iloc[i-1] for i in range(-1, -6, -1))
            ma_s_dn_5d = all(df['MA_season'].iloc[i] < df['MA_season'].iloc[i-1] for i in range(-1, -6, -1))
            
            above_ma20_5d = all(df['Close'].iloc[i] > df['MA20'].iloc[i] for i in range(-5, 0))
            below_ma20_5d = all(df['Close'].iloc[i] < df['MA20'].iloc[i] for i in range(-5, 0))
            above_mas_5d = all(df['Close'].iloc[i] > df['MA_season'].iloc[i] for i in range(-5, 0))
            below_mas_5d = all(df['Close'].iloc[i] < df['MA_season'].iloc[i] for i in range(-5, 0))

        ret_5d = 0.0
        has_ret_5d = False
        if len(df) >= 6 and pd.notna(df['Close'].iloc[-6]) and df['Close'].iloc[-6] > 0:
            ret_5d = ((last_p - df['Close'].iloc[-6]) / df['Close'].iloc[-6]) * 100
            has_ret_5d = True
            
        high_52w = df['High'].tail(252).max() if 'High' in df.columns else 0.0
        low_52w = df['Low'].tail(252).min() if 'Low' in df.columns else 0.0
        pos_52w = ((last_p - low_52w) / (high_52w - low_52w + 1e-9) * 100) if (high_52w - low_52w) > 0 else 50.0

        high_20d = df['High'].tail(20).max() if 'High' in df.columns else 0.0
        
        k_d = float(df['K_d'].iloc[-1]) if 'K_d' in df.columns else 50.0
        d_d = float(df['D_d'].iloc[-1]) if 'D_d' in df.columns else 50.0
        pk_d = float(df['K_d'].iloc[-2]) if len(df)>1 and 'K_d' in df.columns else 50.0
        pd_d = float(df['D_d'].iloc[-2]) if len(df)>1 and 'D_d' in df.columns else 50.0
        
        macd_d = float(df['MACD'].iloc[-1]) if 'MACD' in df.columns else 0.0
        macds_d = float(df['MACD_Signal'].iloc[-1]) if 'MACD_Signal' in df.columns else 0.0
        pmacd_d = float(df['MACD'].iloc[-2]) if len(df)>1 and 'MACD' in df.columns else 0.0
        pmacds_d = float(df['MACD_Signal'].iloc[-2]) if len(df)>1 and 'MACD_Signal' in df.columns else 0.0

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
        if is_break_ma: alerts.append("跌破季線")
        
        if ma20_up_5d and ma_s_up_5d: alerts.append("月季線雙上彎≥5日")
        elif ma20_up_5d: alerts.append("月線上彎≥5日")
        elif ma_s_up_5d: alerts.append("季線上彎≥5日")
        
        if ma20_dn_5d and ma_s_dn_5d: alerts.append("月季線雙下彎≥5日")
        elif ma20_dn_5d: alerts.append("月線下彎≥5日")
        elif ma_s_dn_5d: alerts.append("季線下彎≥5日")
        
        if above_ma20_5d and above_mas_5d: alerts.append("站上月季線≥5日")
        elif above_ma20_5d: alerts.append("站上月線≥5日")
        elif above_mas_5d: alerts.append("站上季線≥5日")
        
        if below_ma20_5d and below_mas_5d: alerts.append("跌破月季線≥5日")
        elif below_ma20_5d: alerts.append("跌破月線≥5日")
        elif below_mas_5d: alerts.append("跌破季線≥5日")
        
        if has_ret_5d:
            if ret_5d >= 5.0: alerts.append(f"近5日上漲{ret_5d:.1f}%")
            elif ret_5d <= -5.0: alerts.append(f"近5日下跌{abs(ret_5d):.1f}%")
        
        if high_52w > 0 and (high_52w - last_p) / high_52w >= 0.15: 
            alerts.append(f"近高點回落{((high_52w - last_p) / high_52w)*100:.1f}%")
            
        if high_20d > 0 and (high_20d - last_p) / high_20d >= 0.10: 
            alerts.append(f"20日回落{((high_20d - last_p) / high_20d)*100:.1f}%")
            
        action = "➖ 持平"
        has_buy = any(x in kd_w_status or x in macd_w_status for x in ["低檔金叉", "零下金叉"])
        has_sell = any(x in kd_w_status or x in macd_w_status for x in ["高檔死叉", "零上死叉"]) or "近高點回落" in " ".join(alerts)
        has_reduce = "20日回落" in " ".join(alerts)
        
        if has_sell: action = "🛑 賣出"
        elif has_buy: action = "🚀 買進"
        elif has_reduce: action = "⚠️ 減碼"

        alert_str = f"[{action}] " + ("/".join(alerts) if alerts else "趨勢延續")
        kd_display = f"K:{k_d:.0f}/D:{d_d:.0f}"

        f_info = get_fundamental_info(sym)
        pe_val = f_info.get('trailingPE') or f_info.get('forwardPE', 999)

        return {
            "代號": sym.split('.')[0], "🚨警示": alert_str, "價格": last_p, "52週位置": f"{pos_52w:.0f}%", "日KD": kd_display,
            "_raw_kd_d": kd_d_status, "_raw_kd_w": kd_w_status, "_raw_pe": pe_val, "_is_break_ma": is_break_ma,
            "_raw_macd_d": macd_d_status, "_raw_macd_w": macd_w_status, "_name": name, "_sym": sym,
            "_ma20_up_5d": ma20_up_5d, "_ma_s_up_5d": ma_s_up_5d,
            "_ma20_dn_5d": ma20_dn_5d, "_ma_s_dn_5d": ma_s_dn_5d,
            "_above_ma20_5d": above_ma20_5d, "_below_ma20_5d": below_ma20_5d,
            "_above_mas_5d": above_mas_5d, "_below_mas_5d": below_mas_5d,
            "_has_ret_5d": has_ret_5d, "_ret_5d": ret_5d
        }
    except: return None

# ==========================================
# 3. 手機版隨身 UI 渲染
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

        # ==========================================
        # 📉 歷史資產防呆寫入與繪圖
        # ==========================================
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
            fig_pie = px.pie(df_allocation, values='市值', names='類別', hole=0.4)
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            fig_pie.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
            st.plotly_chart(fig_pie, use_container_width=True)

        df_ind = pd.DataFrame(individual_holdings)
        if not df_ind.empty:
            st.divider()
            st.caption("📊 各標的總市值分佈 (TWD)")
            df_mv_sorted = df_ind.sort_values(by='總市值', ascending=True)
            dynamic_height = max(300, len(df_mv_sorted) * 35)
            
            fig_mv_bar = px.bar(df_mv_sorted, x='總市值', y='標的與股數', orientation='h', color='類別', text_auto='.2s')
            fig_mv_bar.update_layout(height=dynamic_height, margin=dict(l=10, r=10, t=10, b=10), showlegend=False, yaxis={'categoryorder':'array', 'categoryarray': df_mv_sorted['標的與股數']})
            st.plotly_chart(fig_mv_bar, use_container_width=True)

            st.caption("📊 各標的預估股息分佈 (TWD)")
            df_div_sorted = df_ind.sort_values(by='預估股息', ascending=True)
            fig_div_bar = px.bar(df_div_sorted, x='預估股息', y='標的與股數', orientation='h', color='類別', text_auto='.2s')
            fig_div_bar.update_layout(height=dynamic_height, margin=dict(l=10, r=10, t=10, b=10), showlegend=False, yaxis={'categoryorder':'array', 'categoryarray': df_div_sorted['標的與股數']})
            st.plotly_chart(fig_div_bar, use_container_width=True)

with tab_hl:
    with st.spinner("掃描技術訊號中..."):
        ta_results = []
        target_options = {}
        
        bullish_strong = [] 
        bullish_daily = []  
        bearish_alerts = [] 
        
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
                target_options[f"{name}({sym.split('.')[0]})"] = sym
                
                pe_val = res.get('_raw_pe')
                if pd.isna(pe_val) or pe_val is None: pe_val = 999
                pe_str = f"{pe_val:.1f}" if pe_val != 999 else "無PE"
                name_disp = f"{name}({sym.split('.')[0]})"
                
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
                ma20_up = res.get('_ma20_up_5d', False)
                ma_s_up = res.get('_ma_s_up_5d', False)
                ma20_dn = res.get('_ma20_dn_5d', False)
                ma_s_dn = res.get('_ma_s_dn_5d', False)
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
                
                if ma20_up and ma_s_up: tags.append("月季線上彎≥5日")
                elif ma20_up: tags.append("月線上彎≥5日")
                elif ma_s_up: tags.append("季線上彎≥5日")
                
                if above_ma20_5d and above_mas_5d: tags.append("站上月季線≥5日")
                elif above_ma20_5d: tags.append("站上月線≥5日")
                elif above_mas_5d: tags.append("站上季線≥5日")
                
                if has_ret_5d and ret_5d >= 5.0: tags.append("近5日上漲≥5%")
                
                if w_macd_death: tags.append("週MACD零上死叉")
                if w_kd_death: tags.append("週KD高檔死叉")
                if d_macd_death: tags.append("日MACD零上死叉")
                if d_kd_death: tags.append("日KD高檔死叉")
                
                if is_break: tags.append("跌破季線")
                
                if ma20_dn and ma_s_dn: tags.append("月季線下彎≥5日")
                elif ma20_dn: tags.append("月線下彎≥5日")
                elif ma_s_dn: tags.append("季線下彎≥5日")
                
                if below_ma20_5d and below_mas_5d: tags.append("跌破月季線≥5日")
                elif below_ma20_5d: tags.append("跌破月線≥5日")
                elif below_mas_5d: tags.append("跌破季線≥5日")
                
                if has_ret_5d and ret_5d <= -5.0: tags.append("近5日下跌≥5%")

                bull_score = (w_macd_gold * 4) + (w_kd_gold * 3) + (d_macd_gold * 2) + (d_kd_gold * 1) + (ma20_up * 1) + (ma_s_up * 1) + (above_ma20_5d * 1) + (above_mas_5d * 1) + ((has_ret_5d and ret_5d >= 5.0) * 1)
                bear_score = (w_macd_death * 4) + (w_kd_death * 3) + (d_macd_death * 2) + (d_kd_death * 1) + (is_break * 1) + (ma20_dn * 1) + (ma_s_dn * 1) + (below_ma20_5d * 1) + (below_mas_5d * 1) + ((has_ret_5d and ret_5d <= -5.0) * 1)
                
                item_data = {'name': name_disp, 'pe': pe_val, 'pe_str': pe_str, 'tags': tags, 'bull_score': bull_score, 'bear_score': bear_score, 'price': res['價格']}
                
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
        
    def format_mobile_items(items):
        if not items: return "> 目前無符合條件標的"
        res_str = ""
        for x in items:
            tags_str = ", ".join(x['tags'])
            res_str += f"- **{x['name']}**\n  - `[{tags_str}]`\n"
        return res_str

    st.markdown("### 📊 盤後技術摘要 (Top 10)")
    st.caption("依技術強度優先，同級別低本益比優先顯示。")
    
    with st.container():
        st.success(f"🔥 **週線強勢區 (波段)**\n\n{format_mobile_items(bullish_strong)}")
        st.info(f"📈 **日線強勢區 (短線)**\n\n{format_mobile_items(bullish_daily)}")
        st.error(f"⚠️ **空方風險區 (破線/死叉)**\n\n{format_mobile_items(bearish_alerts)}")

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
                        fig_comp = px.line(df_comp_pct, x=df_comp_pct.index, y=df_comp_pct.columns)
                        fig_comp.update_layout(hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), yaxis_title="累計報酬率 (%)", xaxis_title=None)
                        st.plotly_chart(fig_comp, use_container_width=True)
                else:
                    st.warning("無法取得歷史資料。")

with tab2:
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
        st.dataframe(df_ta[["代號", "🚨警示", "價格", "52週位置"]], width="stretch", hide_index=True, height=350)

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
    with st.spinner("精算回報率中..."):
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
                    "市場": st.column_config.TextColumn("市場"),
                    "代號": st.column_config.TextColumn("代號"),
                    "收盤": st.column_config.NumberColumn("收盤", format="%.2f"),
                    "季報酬": st.column_config.NumberColumn("季報酬 (%)", format="%+.1f"),
                    "年報酬": st.column_config.NumberColumn("年報酬 (%)", format="%+.1f"),
                    "對大盤": st.column_config.NumberColumn("對大盤(1年) (%)", format="%+.1f"),
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
        df_etf_db = pd.read_csv(csv_url)
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
                        
                        plot_df[weight_col] = plot_df[weight_col].astype(str).str.replace(r'[^\d.-]', '', regex=True)
                        plot_df[weight_col] = pd.to_numeric(plot_df[weight_col], errors='coerce')
                        
                        plot_df = plot_df.dropna(subset=[weight_col]).sort_values(by=weight_col, ascending=True)
                        
                        if not plot_df.empty:
                            plot_df['文字標籤'] = plot_df[weight_col].apply(lambda x: f"{x:.2f}%")
                            
                            fig_etf = px.bar(plot_df, x=weight_col, y=name_col, orientation='h', title=f"{selected_etf} 核心持股", text='文字標籤')
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
