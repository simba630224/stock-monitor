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
import requests
import io
from streamlit_gsheets import GSheetsConnection

warnings.filterwarnings('ignore')

st.set_page_config(page_title="個人投資組合與技術分析儀表板", layout="wide")

# ==========================================
# 0. 輔助函式：強力防呆安全轉換與名稱格式化
# ==========================================
def safe_float(val):
    try:
        if isinstance(val, str):
            val = re.sub(r'[^\d.-]', '', val)
        return float(val) if pd.notna(val) and str(val).strip() != '' else 0.0
    except:
        return 0.0

def format_display_name(name_raw, sym_raw):
    """絕對乾淨的名稱格式化：防殺所有 nan 與空值"""
    sym = str(sym_raw).strip() if pd.notna(sym_raw) else ""
    if sym.lower() in ['nan', 'none', 'null', '']: sym = ""
    
    name = str(name_raw).strip() if pd.notna(name_raw) else ""
    if name.lower() in ['nan', 'none', 'null', '']: name = ""
    
    if name and sym: return f"{name} ({sym})"
    if not name and sym: return sym
    if name and not sym: return name
    return "未知標的"

# ==========================================
# 1. 資料庫連線與安全快取模組
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

# 🛑 Technical_DB 網址
TECHNICAL_DB_URL = "https://docs.google.com/spreadsheets/d/15F1CRaVUlgQpwbYqFQCwFiyCjmMksEBEd5CnIvF_zFs/edit" 

# 🛑 每日快報 資料庫網址
DAILY_REPORT_URL = "https://docs.google.com/spreadsheets/d/1StOQTEpoTNSLU140CnOeUO94m0dZ5imX4oH0wlqAQZw/export?format=csv&gid=1670790073"

# 🛑 ETF 持股 資料庫網址
ETF_DB_URL = "https://docs.google.com/spreadsheets/d/1_crBmjMxgm9qpYeycg_TnLStt3phN6vM4XILmD9x0Yc/edit"


def fetch_and_clean_portfolio(worksheet_name, default_category):
    try:
        df = conn.read(worksheet=worksheet_name, ttl=0)
        if df is None or df.empty:
            return pd.DataFrame()
            
        df.columns = [str(c).strip() for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]
        
        col_map = {}
        for c in df.columns:
            cl = str(c).strip().lower()
            if cl in ['ticker', 'symbol', '代號', '股票代號', '標的代號']: col_map[c] = 'Ticker'
            elif cl in ['name', '名稱', '標的名稱', '股票名稱']: col_map[c] = '名稱'
            elif cl in ['shares', '股數', '持有股數', '庫存', '數量']: col_map[c] = 'Shares'
            elif cl in ['出借', '借券', '複委託']: col_map[c] = '出借' if default_category == '台股' else '複委託'
            elif cl in ['類別', 'category', '分類', '市場']: col_map[c] = '類別'
            elif cl in ['策略', '短線', '交易屬性']: col_map[c] = '策略'
            
        df = df.rename(columns=col_map)
        
        if 'Ticker' not in df.columns and len(df.columns) > 0:
            df = df.rename(columns={df.columns[0]: 'Ticker'})
            
        if 'Ticker' in df.columns:
            df['Ticker'] = df['Ticker'].astype(str).str.strip()
            df['Ticker'] = df['Ticker'].str.replace(r'\.0$', '', regex=True)
            if default_category == '台股':
                df['Ticker'] = df['Ticker'].apply(lambda x: x.zfill(4) if x.isdigit() and len(x) < 4 else x)
            df = df[~df['Ticker'].str.lower().isin(['nan', 'none', 'null', '<na>', ''])]
        else:
            return pd.DataFrame()
            
        if '名稱' not in df.columns: df['名稱'] = ''
        df['名稱'] = df['名稱'].astype(str).replace(['nan', 'None', 'NaN', 'null', '<NA>'], '')
        
        if 'Shares' not in df.columns: df['Shares'] = 0.0
        df['Shares'] = pd.to_numeric(df['Shares'], errors='coerce').fillna(0.0)
        
        if '策略' not in df.columns: df['策略'] = ''
        df['策略'] = df['策略'].astype(str).replace(['nan', 'None', 'NaN', 'null', '<NA>'], '')
        
        if default_category == '台股' and '出借' not in df.columns: df['出借'] = 0.0
        elif default_category == '美股' and '複委託' not in df.columns: df['複委託'] = 0.0
        
        if '出借' in df.columns: df['出借'] = pd.to_numeric(df['出借'], errors='coerce').fillna(0.0)
        if '複委託' in df.columns: df['複委託'] = pd.to_numeric(df['複委託'], errors='coerce').fillna(0.0)
        
        if '類別' not in df.columns: df['類別'] = default_category
        
        ordered_cols = ['Ticker', '名稱', 'Shares', '出借' if default_category=='台股' else '複委託', '類別', '策略']
        df = df.reindex(columns=[c for c in ordered_cols if c in df.columns] + [c for c in df.columns if c not in ordered_cols])
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=600)
def get_tw_portfolio():
    df = fetch_and_clean_portfolio("TW_Portfolio", "台股")
    if df.empty: df = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "出借", "類別", "策略"])
    return df

@st.cache_data(ttl=600)
def get_us_portfolio():
    df = fetch_and_clean_portfolio("US_Portfolio", "美股")
    if df.empty: df = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "複委託", "類別", "策略"])
    return df

df_tw = get_tw_portfolio()
df_us = get_us_portfolio()

PORTFOLIO_TW = df_tw.to_dict('records') if not df_tw.empty else []
PORTFOLIO_US = df_us.to_dict('records') if not df_us.empty else []

@st.cache_data(ttl=600)
def load_technical_db():
    db_url = TECHNICAL_DB_URL.strip() or st.secrets.get("TECHNICAL_DB_URL")
    if db_url:
        try:
            df_db = conn.read(spreadsheet=db_url, ttl=600)
            if df_db is not None and not df_db.empty:
                df_db.columns = [str(c).strip() for c in df_db.columns]
                return df_db
        except Exception as e:
            st.error(f"讀取 Technical_DB 時發生連線錯誤，請確認網址。({e})")
            return pd.DataFrame()
    try:
        df_db = conn.read(worksheet="Technical_DB", ttl=600)
        if df_db is not None and not df_db.empty:
            df_db.columns = [str(c).strip() for c in df_db.columns]
            return df_db
    except: pass
    return pd.DataFrame()

@st.cache_data(ttl=600)
def load_value_history():
    try:
        return conn.read(worksheet="Value_History", ttl=600)
    except: return pd.DataFrame()

@st.cache_data(ttl=600)
def load_trading_journal():
    try:
        return conn.read(worksheet="Trading_Journal", ttl=600)
    except: return pd.DataFrame()

@st.cache_data(ttl=900)
def load_daily_report():
    try:
        now = datetime.now()
        ws_current = f"Daily Report {now.strftime('%Y-%m')}"
        ws_prev = f"Daily Report {(now.replace(day=1) - pd.Timedelta(days=1)).strftime('%Y-%m')}"
        
        df_list = []
        for ws in [ws_current, ws_prev]:
            try:
                temp_df = conn.read(spreadsheet=DAILY_REPORT_URL, worksheet=ws, ttl=900)
                if temp_df is not None and not temp_df.empty:
                    df_list.append(temp_df)
            except: pass
                
        if not df_list: return pd.DataFrame()
            
        df = pd.concat(df_list, ignore_index=True)
        df.columns = [str(c).strip() for c in df.columns]
        df = df.dropna(how='all').fillna("")
        df = df.replace(['nan', 'NaN', 'None', '<NA>'], '')
        return df
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_etf_holdings():
    try:
        now = datetime.now()
        ws_current = f"{now.strftime('%Y_%m')}_Top20"
        ws_prev = f"{(now.replace(day=1) - pd.Timedelta(days=1)).strftime('%Y_%m')}_Top20"
        
        for ws in [ws_current, ws_prev]:
            try:
                df = conn.read(spreadsheet=ETF_DB_URL, worksheet=ws, ttl=3600)
                if df is not None and not df.empty:
                    df.columns = [str(c).strip() for c in df.columns]
                    return df.dropna(how='all')
            except: pass
            
        try:
            df = conn.read(spreadsheet=ETF_DB_URL, ttl=3600)
            if df is not None and not df.empty:
                df.columns = [str(c).strip() for c in df.columns]
                return df.dropna(how='all')
        except: pass
        
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# ==========================================
# 2. 輕量即時行情與線圖抓取
# ==========================================
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip().upper()
    if ticker.endswith('.TW') or ticker.endswith('.TWO'): return ticker
    if ticker.endswith('B') or ticker.endswith('C') or ticker == '009815': return f"{ticker}.TWO"
    return f"{ticker}.TW"

@st.cache_data(ttl=300)
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
        except: time.sleep(0.5)
    return 0.0, 0.0, 0.0

@st.cache_data(ttl=300)
def get_usdtwd():
    for _ in range(3):
        try:
            time.sleep(0.2)
            hist = yf.Ticker("TWD=X").history(period="5d")
            if not hist.empty: return float(hist['Close'].dropna().iloc[-1])
        except: time.sleep(0.5)
    return 32.5

@st.cache_data(ttl=1800)
def get_fx_data():
    try:
        data = yf.Ticker("TWD=X").history(period="1y").dropna(subset=['Close'])
        if not data.empty:
            data['MA20'] = data['Close'].rolling(window=20, min_periods=1).mean()
            data['MA60'] = data['Close'].rolling(window=60, min_periods=1).mean()
            return data
    except: pass
    return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_benchmark_returns():
    benchmarks = {'台股': 0.0, '美股': 0.0}
    try:
        tw_hist = yf.Ticker("^TWII").history(period="1y", auto_adjust=True).dropna(subset=['Close'])
        if len(tw_hist) > 252: benchmarks['台股'] = ((tw_hist['Close'].iloc[-1] - tw_hist['Close'].iloc[-252]) / tw_hist['Close'].iloc[-252]) * 100
        elif not tw_hist.empty: benchmarks['台股'] = ((tw_hist['Close'].iloc[-1] - tw_hist['Close'].iloc[0]) / tw_hist['Close'].iloc[0]) * 100
    except: pass
    try:
        us_hist = yf.Ticker("^GSPC").history(period="1y", auto_adjust=True).dropna(subset=['Close'])
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
            'returnOnEquity': info.get('returnOnEquity'),
            'trailingPE': info.get('trailingPE')
        }
    except: return {}

# 🚀 包含日漲跌幅(%) 與 近一個月報酬
@st.cache_data(ttl=900)
def get_perf_div_data(sym, display_ticker, market, bench_returns, display_name):
    result = {
        "市場": market, "代號": display_ticker, "顯示名稱": display_name, "收盤價": 0.0, "日漲跌(%)": 0.0,
        "近一個月含息報酬": 0.0, "近一季含息報酬": 0.0, "近半年含息報酬": 0.0, "近一年含息報酬": 0.0,
        "相對大盤": 0.0, "近一年殖利率": 0.0, "總配息金額": 0.0,
        "近一年配息明細": "無配息紀錄", "ROE": None
    }
    for _ in range(3):
        try:
            time.sleep(0.3)
            tk = yf.Ticker(sym)
            hist = tk.history(period="2y", auto_adjust=True) 
            if not hist.empty and len(hist['Close'].dropna()) > 0:
                valid_hist = hist['Close'].dropna()
                curr_p = float(valid_hist.iloc[-1])
                
                # 計算日漲跌
                if len(valid_hist) > 1:
                    prev_p = float(valid_hist.iloc[-2])
                    ret_daily = ((curr_p - prev_p) / prev_p) * 100 if prev_p > 0 else 0.0
                else:
                    ret_daily = 0.0
                
                def calc_ret(days_back):
                    if len(valid_hist) > days_back:
                        past_p = float(valid_hist.iloc[-days_back])
                        return ((curr_p - past_p) / past_p) * 100 if past_p > 0 else 0.0
                    elif len(valid_hist) > 0:
                        past_p = float(valid_hist.iloc[0])
                        return ((curr_p - past_p) / past_p) * 100 if past_p > 0 else 0.0
                    return 0.0

                ret_1m = calc_ret(21)
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
                roe_val = float(roe_raw) * 100 if roe_raw is not None and not is_etf else None

                div_records = []
                tot_div = 0.0
                if 'Dividends' in hist.columns:
                    divs = hist['Dividends'][hist['Dividends'] > 0]
                    for date, val in divs.sort_index(ascending=False).items():
                        div_records.append(f"{date.strftime('%Y-%m-%d')}: ${val:.2f}")
                        tot_div += float(val)

                div_history_str = " / ".join(div_records) if div_records else "無配息紀錄"
                yield_1y = (tot_div / curr_p) * 100 if curr_p > 0 and tot_div > 0 else 0.0

                result.update({
                    "收盤價": curr_p, "日漲跌(%)": float(ret_daily), "近一個月含息報酬": float(ret_1m), 
                    "近一季含息報酬": float(ret_1q), "近半年含息報酬": float(ret_6m), 
                    "近一年含息報酬": float(ret_1y), "相對大盤": float(rel_val), "近一年殖利率": float(yield_1y), 
                    "總配息金額": float(tot_div), "近一年配息明細": div_history_str, "ROE": roe_val
                })
                return result
        except: time.sleep(1)
    return result

@st.cache_data(ttl=300)
def get_single_stock_chart_data(sym):
    try:
        df = yf.download(sym, period="3y", progress=False, threads=False)
        if not df.empty and len(df) >= 2:
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None: df.index = df.index.tz_convert(None)
            available_cols = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume'] if c in df.columns]
            df = df[available_cols].astype(float).dropna(subset=['Close'])
            if df.empty or len(df) < 2: return None
            
            df['MA10'] = df['Close'].rolling(10, min_periods=1).mean()
            df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
            is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
            df['季線'] = df['Close'].rolling(60 if is_tw else 50, min_periods=1).mean()
            
            if 'High' in df.columns and 'Low' in df.columns:
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
    except: pass
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

tab1, tab2, tab_comp, tab3, tab_etf, tab_report, tab4 = st.tabs([
    "💰 投資組合總覽", "📈 技術分析掃描", "🆚 標的比較", 
    "🏆 績效與觀察總覽", "🧩 ETF持股", "📰 每日快報", "📖 每日看盤心得"
])

# ------------------------------------------
# TAB 1: 投資組合總覽
# ------------------------------------------
with tab1:
    with st.spinner("正在同步即時資產市值..."):
        usdtwd = get_usdtwd()
        total_market_value, total_dividends_2026, total_dividends_1y = 0, 0, 0
        asset_allocation = {}
        individual_holdings = [] 

        for item in PORTFOLIO_TW:
            if pd.notna(item.get('Ticker')):
                ticker_str = str(item['Ticker']).strip()
                if not ticker_str or ticker_str.lower() in ['nan', 'none', '']: continue
                ticker = get_yf_ticker_tw(ticker_str)
                asset_type = str(item.get('類別', '台股')).strip()
                if not asset_type or asset_type.lower() == 'nan': asset_type = '台股未分類'
                
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
                    display_name = format_display_name(item.get('名稱'), ticker_str)
                    individual_holdings.append({'標的': display_name, '標的與股數': f"{display_name} ({disp_qty})", '總市值': val, '股息': div_tot_2026, '類別': asset_type, '總股數': total_shares})

        for item in PORTFOLIO_US:
            if pd.notna(item.get('Ticker')):
                ticker_str = str(item['Ticker']).strip()
                if not ticker_str or ticker_str.lower() in ['nan', 'none', '']: continue
                asset_type = str(item.get('類別', '美股')).strip()
                if not asset_type or asset_type.lower() == 'nan': asset_type = '美股未分類'
                
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
                    display_name = format_display_name(item.get('名稱'), ticker_str)
                    individual_holdings.append({'標的': display_name, '標的與股數': f"{display_name} ({disp_qty})", '總市值': val, '股息': div_tot_2026, '類別': asset_type, '總股數': total_shares})

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("總市值 (TWD)", f"${total_market_value:,.0f}")
    col2.metric("2026 預估股息 (TWD)", f"${total_dividends_2026:,.0f}")
    col3.metric("近一年累計股息 (TWD)", f"${total_dividends_1y:,.0f}")
    col4.metric("目前匯率 (USD/TWD)", f"{usdtwd:.3f}")

    df_history = load_value_history()
    df_history_to_display = pd.DataFrame()
    history_error = False
    
    if not df_history.empty:
        df_history.columns = [str(c).strip().replace(' ', '_') for c in df_history.columns]
        df_history = df_history.loc[:, ~df_history.columns.duplicated()]
        
        if 'Date' in df_history.columns and 'Total_Value' in df_history.columns:
            df_history['Date'] = pd.to_datetime(df_history['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
            df_history = df_history.dropna(subset=['Date'])
            df_history['Total_Value'] = pd.to_numeric(df_history['Total_Value'].astype(str).str.replace(r'[^\d.-]', '', regex=True), errors='coerce').fillna(0)
            
            today_str = datetime.now().strftime('%Y-%m-%d')
            now_time = datetime.now().strftime('%H:%M:%S')
            
            if len(df_history) >= 1:
                if today_str in df_history['Date'].values:
                    idx = df_history.index[df_history['Date'] == today_str].tolist()[0]
                    existing_val = safe_float(df_history.at[idx, 'Total_Value'])
                    if abs(existing_val - total_market_value) > 1:
                        df_history.at[idx, 'Total_Value'] = total_market_value
                        df_history.at[idx, 'Last_Updated'] = now_time
                        try:
                            df_history = df_history.fillna("") 
                            conn.update(worksheet="Value_History", data=df_history)
                            st.cache_data.clear() 
                        except: pass
                else:
                    new_row = pd.DataFrame([{'Date': today_str, 'Total_Value': total_market_value, 'Last_Updated': now_time}])
                    df_history = pd.concat([df_history, new_row], ignore_index=True)
                    try:
                        df_history = df_history.fillna("")
                        conn.update(worksheet="Value_History", data=df_history)
                        st.cache_data.clear()
                    except: pass
                df_history_to_display = df_history
            else: history_error = True
        else: history_error = True
    else: history_error = True

    if history_error or df_history_to_display.empty or 'Total_Value' not in df_history_to_display.columns:
        df_history_to_display = pd.DataFrame([{'Date': datetime.now().strftime('%Y-%m-%d'), 'Total_Value': total_market_value, 'Last_Updated': datetime.now().strftime('%H:%M:%S')}])

    st.divider()

    if not df_history_to_display.empty and len(df_history_to_display) > 1:
        st.subheader("📈 總市值每日變化趨勢")
        df_history_to_display['Total_Value'] = pd.to_numeric(df_history_to_display['Total_Value'], errors='coerce').fillna(0)
        fig_hist = px.line(df_history_to_display, x='Date', y='Total_Value', text='Total_Value', markers=True)
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

# ------------------------------------------
# TAB 2: 技術分析掃描
# ------------------------------------------
with tab2:
    with st.spinner("載入技術分析資料庫中..."):
        df_db = load_technical_db()
        
    if df_db.empty:
        st.warning("⚠️ 尚未讀取到 `Technical_DB` 資料庫。請確認：\n1. 您是否已在上方填入正確的 `TECHNICAL_DB_URL`？\n2. 您的 GitHub Actions 是否已經成功執行並寫入資料？")
    else:
        try:
            for col in ['bull_score', 'bear_score']:
                if col not in df_db.columns: df_db[col] = 0
                df_db[col] = pd.to_numeric(df_db[col], errors='coerce').fillna(0)
                
            if '_raw_pe' not in df_db.columns: df_db['_raw_pe'] = np.nan
            df_db['_raw_pe'] = pd.to_numeric(df_db['_raw_pe'], errors='coerce')
            
            for col in ['action', 'tags', '_name', '_sym', '標的', '策略', '市場']:
                if col not in df_db.columns: df_db[col] = ""
                df_db[col] = df_db[col].astype(str).replace(['nan', 'None'], '').fillna("")
                
            def get_52w_pos(x):
                try: return float(str(x).replace('%', '').strip())
                except: return 50.0
            if '52週位置' in df_db.columns:
                df_db['pos_52w_val'] = df_db['52週位置'].apply(get_52w_pos)
            else: df_db['pos_52w_val'] = 50.0

            # 前端即時策略同步
            strategy_map = {}
            for item in PORTFOLIO_TW:
                t = str(item.get('Ticker', '')).strip().upper()
                s = str(item.get('策略', '')).strip()
                if t:
                    strategy_map[t] = s
                    strategy_map[get_yf_ticker_tw(t)] = s
            for item in PORTFOLIO_US:
                t = str(item.get('Ticker', '')).strip().upper()
                s = str(item.get('策略', '')).strip()
                if t: strategy_map[t] = s

            def resolve_strategy(row):
                sym = str(row.get('_sym', '')).strip().upper()
                clean_sym = sym.split('.')[0]
                if sym in strategy_map and strategy_map[sym]: return strategy_map[sym]
                if clean_sym in strategy_map and strategy_map[clean_sym]: return strategy_map[clean_sym]
                return str(row.get('策略', '')).strip()

            df_db['策略'] = df_db.apply(resolve_strategy, axis=1)
            df_db['顯示名稱'] = df_db.apply(lambda r: format_display_name(r.get('_name'), r.get('_sym')), axis=1)

            target_options = {}
            for _, row in df_db.iterrows():
                sym = str(row.get('_sym', '')).strip()
                disp_name = row.get('顯示名稱', '')
                if sym and sym.lower() not in ['nan', 'none', '']:
                    target_options[disp_name] = sym

            def format_strict_items(sub_df):
                if sub_df.empty: return "> 👻 目前無符合嚴格條件標的，皆已過濾隱藏。"
                res = []
                for _, r in sub_df.iterrows():
                    pe_val = r.get('_raw_pe')
                    try: pe_str = f"PE:{float(pe_val):.1f}" if pd.notna(pe_val) else "PE:無"
                    except: pe_str = "PE:無"
                    
                    bull_s = int(r.get('bull_score', 0))
                    bear_s = int(r.get('bear_score', 0))
                    tags_str = r.get('tags', '')
                    name_disp = r.get('顯示名稱', '未知')
                    
                    res.append(f"• **{name_disp}** (多:{bull_s} 空:{bear_s} | {pe_str})\n  └ `[{tags_str}]`")
                return "\n\n".join(res)

            df_db['tags_str'] = df_db['tags'].astype(str)

            st.markdown("### 📊 技術亮點與警示摘要 (Top 10)") 
            st.caption("嚴格門檻篩選機制：未達絕對特徵之標的將自動過濾隱藏，降低雜訊干擾。排序依據為多空淨得分。")

            m_tabs = st.tabs(["🇹🇼 台股", "🇺🇸 美股"])
            
            for idx, mkt in enumerate(['台股', '美股']):
                with m_tabs[idx]:
                    df_m = df_db[df_db['市場'] == mkt].copy()
                    
                    is_short_term = df_m['策略'].str.contains('短', case=False, na=False)
                    df_short = df_m[is_short_term].copy()
                    df_normal = df_m[~is_short_term].copy()

                    short_bull_cond = df_short['tags_str'].str.contains('創20日收盤高|創50日收盤高', regex=True) | ((df_short['bull_score'] >= 2) & (df_short['bear_score'] == 0))
                    short_bear_cond = df_short['tags_str'].str.contains('破20日收盤低|破50日收盤低', regex=True) | ((df_short['bear_score'] >= 2) & (df_short['bull_score'] == 0))
                    short_cons_cond = (~short_bull_cond) & (~short_bear_cond) & df_short['tags_str'].str.contains('20日窄幅盤整')

                    df_short_bull = df_short[short_bull_cond].copy()
                    df_short_bear = df_short[short_bear_cond].copy()
                    df_short_cons = df_short[short_cons_cond].copy()

                    df_short_bull['sort_score'] = df_short_bull['bull_score'] - df_short_bull['bear_score']
                    df_short_bear['sort_score'] = df_short_bear['bear_score'] - df_short_bear['bull_score']
                    
                    df_short_bull = df_short_bull.sort_values(by=['sort_score', '_raw_pe'], ascending=[False, True]).head(10)
                    df_short_bear = df_short_bear.sort_values(by=['sort_score', '_raw_pe'], ascending=[False, True]).head(10)
                    df_short_cons = df_short_cons.sort_values(by=['_raw_pe'], ascending=[True]).head(10)

                    long_bull_cond = df_normal['tags_str'].str.contains('創52週收盤高', regex=True) | ((df_normal['bull_score'] >= 3) & df_normal['tags_str'].str.contains('週KD低檔金叉|週MACD零下金叉', regex=True)) | ((df_normal['bull_score'] >= 3) & (df_normal['bear_score'] == 0))
                    long_bear_cond = df_normal['tags_str'].str.contains('破52週收盤低', regex=True) | ((df_normal['bear_score'] >= 3) & df_normal['tags_str'].str.contains('週KD高檔死叉|週MACD零上死叉', regex=True)) | ((df_normal['bear_score'] >= 3) & (df_normal['bull_score'] == 0))
                    long_base_cond = (~long_bull_cond) & (~long_bear_cond) & (~df_normal['tags_str'].str.contains('創52週|破52週', regex=True)) & (df_normal['pos_52w_val'] <= 30) & (abs(df_normal['bull_score'] - df_normal['bear_score']) <= 1)

                    df_long_bull = df_normal[long_bull_cond].copy()
                    df_long_bear = df_normal[long_bear_cond].copy()
                    df_long_base = df_normal[long_base_cond].copy()

                    df_long_bull['sort_score'] = df_long_bull['bull_score'] - df_long_bull['bear_score']
                    df_long_bear['sort_score'] = df_long_bear['bear_score'] - df_long_bear['bull_score'] 
                    
                    df_long_bull = df_long_bull.sort_values(by=['sort_score', '_raw_pe'], ascending=[False, True]).head(10)
                    df_long_bear = df_long_bear.sort_values(by=['sort_score', '_raw_pe'], ascending=[False, True]).head(10)
                    df_long_base = df_long_base.sort_values(by=['_raw_pe'], ascending=[True]).head(10)

                    st.markdown(f"#### ⚡ 短線進出專區 ({mkt})")
                    if not df_short.empty:
                        col_s1, col_s2 = st.columns(2)
                        with col_s1:
                            st.success(f"**[🚀 偏多 / 創高動能]**\n\n{format_strict_items(df_short_bull)}")
                        with col_s2:
                            st.error(f"**[🩸 偏空 / 破底風險]**\n\n{format_strict_items(df_short_bear)}")
                        st.info(f"**[⚖️ 盤整 / 壓縮區]**\n\n{format_strict_items(df_short_cons)}")
                    else:
                        st.info(f"💡 尚無 {mkt} 短線標的。請於側邊欄「策略」欄位填寫『短線』。")

                    st.divider()

                    st.markdown(f"#### 📈 波段與長期投資 ({mkt} Top 10)")
                    col_sum1, col_sum2 = st.columns(2)
                    with col_sum1:
                        st.success(f"**[🚀 長多波段 / 攻擊轉折]**\n\n{format_strict_items(df_long_bull)}")
                    with col_sum2:
                        st.error(f"**[🛑 波段轉弱 / 長期風險]**\n\n{format_strict_items(df_long_bear)}")
                    st.info(f"**[⚖️ 長線築底 / 壓縮沉澱]**\n\n{format_strict_items(df_long_base)}")

            st.divider()
            st.markdown("### 📋 完整技術分析清單")
            with st.expander("💡 狀態警示規則與名詞定義說明", expanded=False):
                st.markdown("""
                #### 綜合動作評級 (供參考)
                * **[🚀 強勢買進]**：多方分數 ≥ 3 **且** 具備「週KD低檔金叉(K<30)」或「週MACD零下金叉」。
                * **[📈 短多轉折]**：多方分數 > 0 (未達強勢買進標準者)。
                * **[🛑 強制賣出]**：空方分數 ≥ 3 **且** 具備「週KD高檔死叉(K>70)」或「週MACD零上死叉」。
                * **[⚠️ 弱勢減碼]**：空方分數 > 0 (未達強制賣出標準者)。
                """)

            display_cols = ["市場", "顯示名稱", "策略", "狀態警示", "均線位階", "52週位置", "Beta", "P/E", "日KD", "週KD", "日MACD", "週MACD"]
            display_cols = [c for c in display_cols if c in df_db.columns]
            
            if not df_db.empty and display_cols:
                st.dataframe(
                    df_db[display_cols], 
                    use_container_width=True,
                    column_config={
                        "市場": st.column_config.TextColumn("市場", width="small"),
                        "顯示名稱": st.column_config.TextColumn("名稱 (代號)", width="medium"),
                        "策略": st.column_config.TextColumn("策略屬性", width="small"),
                        "狀態警示": st.column_config.TextColumn("🚨 狀態標籤與動作", width="large"),
                        "均線位階": st.column_config.TextColumn("均線位階", width="medium"),
                        "52週位置": st.column_config.TextColumn("52週位置", width="small"),
                        "Beta": st.column_config.TextColumn("Beta", width="small"),
                        "日KD": st.column_config.TextColumn("日 KD", width="medium"),
                        "週KD": st.column_config.TextColumn("週 KD", width="medium"),
                    },
                    hide_index=True, height=450
                )
        except Exception as e:
            st.error(f"渲染資料表時發生未預期錯誤，請確保資料庫格式正確：\n{e}")

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
            with st.spinner(f"正在擷取並繪製 {selected_name} K線圖..."):
                df_chart = get_single_stock_chart_data(sym)
                if df_chart is not None and not df_chart.empty:
                    df_plot = df_chart.tail(tail_days)
                    fig_tech = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.5, 0.25, 0.25], subplot_titles=(f"{selected_name} - 走勢圖", "日 KD 指標", "MACD 指標 (12,26,9)"))
                    
                    if 'Open' in df_plot.columns and 'High' in df_plot.columns and 'Low' in df_plot.columns:
                        fig_tech.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name='K線', increasing_line_color='red', decreasing_line_color='green'), row=1, col=1)
                    else:
                        fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Close'], mode='lines', name='收盤價'), row=1, col=1)
                        
                    fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MA10'], line=dict(color='yellow', width=1.5), name='MA10'), row=1, col=1)
                    fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MA20'], line=dict(color='blue', width=1.5), name='MA20'), row=1, col=1)
                    if '季線' in df_plot.columns:
                        fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['季線'], line=dict(color='orange', width=1.5), name="季線"), row=1, col=1)
                    
                    if 'K_d' in df_plot.columns:
                        fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['K_d'], line=dict(color='blue', width=1.5), name='K值'), row=2, col=1)
                        fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['D_d'], line=dict(color='orange', width=1.5), name='D值'), row=2, col=1)
                    fig_tech.add_hline(y=80, line_dash="dash", line_color="red", row=2, col=1)
                    fig_tech.add_hline(y=20, line_dash="dash", line_color="green", row=2, col=1)
                    
                    if 'MACD_Hist' in df_plot.columns:
                        macd_hist_vals = df_plot['MACD_Hist'].fillna(0)
                        macd_colors = ['red' if val >= 0 else 'green' for val in macd_hist_vals]
                        fig_tech.add_trace(go.Bar(x=df_plot.index, y=df_plot['MACD_Hist'], marker_color=macd_colors, name='OSC'), row=3, col=1)
                        fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MACD'], line=dict(color='blue', width=1.5), name='MACD'), row=3, col=1)
                        fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MACD_Signal'], line=dict(color='orange', width=1.5), name='Signal'), row=3, col=1)
                    
                    fig_tech.update_layout(xaxis_rangeslider_visible=False, height=800, margin=dict(t=40, b=0, l=0, r=0))
                    st.plotly_chart(fig_tech, use_container_width=True)

# ------------------------------------------
# TAB 3: 標的比較
# ------------------------------------------
with tab_comp:
    st.subheader("🆚 多檔標的走勢比較")
    st.caption("選擇 2~4 檔標的，比較其區間累計報酬率走勢。")
    
    comp_options = {}
    for item in PORTFOLIO_TW:
        sym_raw = str(item.get('Ticker', '')).strip()
        if sym_raw and sym_raw.lower() not in ['nan', 'none', '']:
            sym = get_yf_ticker_tw(sym_raw)
            disp_name = format_display_name(item.get('名稱'), sym_raw)
            comp_options[disp_name] = sym
            
    for item in PORTFOLIO_US:
        sym_raw = str(item.get('Ticker', '')).strip()
        if sym_raw and sym_raw.lower() not in ['nan', 'none', '']:
            disp_name = format_display_name(item.get('名稱'), sym_raw)
            comp_options[disp_name] = sym_raw
            
    if comp_options:
        all_options_list = list(comp_options.keys())
        
        comp_col1, comp_col2 = st.columns([3, 1])
        with comp_col1:
            comp_targets = st.multiselect("請選擇比較標的 (最多4檔)：", options=all_options_list, max_selections=4, key="comp_ms")
        with comp_col2:
            comp_period = st.radio("比較期間", ["半年", "一年", "三年"], horizontal=True, index=1)
            
        if comp_targets:
            with st.spinner("載入比較數據中..."):
                period_map = {"半年": "6mo", "一年": "1y", "三年": "3y"}
                yf_period = period_map[comp_period]
                
                comp_pct_dict = {}
                for tgt in comp_targets:
                    sym = comp_options[tgt]
                    try:
                        hist = yf.Ticker(sym).history(period=yf_period, auto_adjust=True)
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
                        fig_comp = px.line(df_comp_pct, x=df_comp_pct.index, y=df_comp_pct.columns, labels={'value': '累計含息報酬率 (%)', 'variable': '標的', 'index': '日期'})
                        fig_comp.update_layout(hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                        st.plotly_chart(fig_comp, use_container_width=True)
                    else: st.warning("選定期間內無足夠數據可供繪製比較圖。")
                else: st.warning("無法取得選定標的外歷史走勢資料。")

            st.divider()
            st.markdown("### 🧩 比較標的之 Top 10 核心持股")
            
            with st.spinner("讀取 ETF 資料庫中..."):
                df_etf_comp_db = load_etf_holdings()

            if not df_etf_comp_db.empty and len(df_etf_comp_db.columns) >= 3:
                etf_c = df_etf_comp_db.columns[0]
                name_c = df_etf_comp_db.columns[1]
                weight_c = df_etf_comp_db.columns[2]
                
                cols_comp = st.columns(len(comp_targets))
                for idx, tgt in enumerate(comp_targets):
                    with cols_comp[idx]:
                        st.markdown(f"#### 📌 {tgt}")
                        sym = comp_options[tgt]
                        clean_code = sym.split('.')[0]
                        
                        db_etf_codes = df_etf_comp_db[etf_c].astype(str).str.strip().str.replace(r'\.TW.*', '', regex=True)
                        sub_df = df_etf_comp_db[db_etf_codes == clean_code].copy()
                        
                        if not sub_df.empty:
                            sub_df[name_c] = sub_df[name_c].astype(str).str.strip()
                            sub_df[weight_c] = sub_df[weight_c].astype(str).str.replace(r'[^\d.-]', '', regex=True)
                            sub_df[weight_c] = pd.to_numeric(sub_df[weight_c], errors='coerce')
                            sub_df = sub_df.dropna(subset=[weight_c])
                            
                            sub_df = sub_df.drop_duplicates(subset=[name_c], keep='last').sort_values(by=weight_c, ascending=False).head(10)
                            
                            if not sub_df.empty:
                                top10_sum = sub_df[weight_c].sum()
                                st.metric("Top 10 權重合計", f"{top10_sum:.2f}%")
                                
                                disp_df = sub_df[[name_c, weight_c]].copy()
                                disp_df.columns = ["成分股名稱", "權重 (%)"]
                                disp_df["權重 (%)"] = disp_df["權重 (%)"].apply(lambda x: f"{x:.2f}%")
                                st.dataframe(disp_df, hide_index=True, use_container_width=True)
                            else: st.caption("ℹ️ 暫無有效的權重數值。")
                        else: st.caption("ℹ️ 個別股票或未收錄成分股資料。")
            else: st.caption("未連線至 ETF 持股資料庫，無法顯示成分股比對。")
    else: st.info("您的側邊欄清單中尚未加入任何有效標的。")

# ------------------------------------------
# TAB 4: 績效與觀察總覽
# ------------------------------------------
with tab3:
    st.markdown("一覽所有持股與觀察清單的**當日漲跌**、**短中長線含息報酬率**與**財報配息**。")
    with st.spinner("正在計算各標的績效與配息資料..."):
        bench_returns = get_benchmark_returns()
        perf_results = []
        scan_list = []
        
        for item in PORTFOLIO_TW:
            t = str(item.get('Ticker', '')).strip()
            if t and t.lower() not in ['nan', 'none', '']: 
                scan_list.append((get_yf_ticker_tw(t), t, '台股', item.get('名稱', '')))
                
        for item in PORTFOLIO_US:
            t = str(item.get('Ticker', '')).strip()
            if t and t.lower() not in ['nan', 'none', '']: 
                scan_list.append((t, t, '美股', item.get('名稱', '')))
                
        for sym, display_ticker, market, raw_name in scan_list:
            disp_name = format_display_name(raw_name, display_ticker)
            res = get_perf_div_data(sym, display_ticker, market, bench_returns, disp_name)
            if res: perf_results.append(res)
                
        if perf_results:
            df_perf = pd.DataFrame(perf_results)
            display_cols = ["顯示名稱", "收盤價", "日漲跌(%)", "近一個月含息報酬", "近一季含息報酬", "近半年含息報酬", "近一年含息報酬", "相對大盤", "近一年殖利率", "總配息金額", "近一年配息明細", "ROE"]
            display_cols = [c for c in display_cols if c in df_perf.columns]
            
            if not df_perf.empty:
                st.dataframe(
                    df_perf[display_cols],
                    use_container_width=True,
                    column_config={
                        "顯示名稱": st.column_config.TextColumn("標的"),
                        "收盤價": st.column_config.NumberColumn("收盤", format="%.2f"),
                        "日漲跌(%)": st.column_config.NumberColumn("日漲跌(%)", format="%+.2f"),
                        "近一個月含息報酬": st.column_config.NumberColumn("近一月含息(%)", format="%+.1f"),
                        "近一季含息報酬": st.column_config.NumberColumn("近一季含息(%)", format="%+.1f"),
                        "近半年含息報酬": st.column_config.NumberColumn("近半年含息(%)", format="%+.1f"),
                        "近一年含息報酬": st.column_config.NumberColumn("近一年含息(%)", format="%+.1f"),
                        "相對大盤": st.column_config.NumberColumn("對大盤(1年)(%)", format="%+.1f"),
                        "近一年殖利率": st.column_config.NumberColumn("殖利率(%)", format="%.1f"),
                        "總配息金額": st.column_config.NumberColumn("近一年總配息", format="%.2f"),
                        "ROE": st.column_config.NumberColumn("ROE(%)", format="%.1f")
                    },
                    hide_index=True, height=600
                )
            else:
                st.info("尚無可顯示的績效資料。")

# ------------------------------------------
# TAB 5: ETF 持股
# ------------------------------------------
with tab_etf:
    st.subheader("🧩 ETF Top 10 持股分析")
    st.caption("自動解析您的 ETF 持股結構，掌握真實資金流向與比重。")
    
    with st.spinner("載入 ETF 資料庫中..."):
        df_etf_db = load_etf_holdings()

    if df_etf_db.empty:
        st.warning("⚠️ 成功連線，但系統讀取到的資料是空的，或是無法讀取。")
    else:
        etf_col = df_etf_db.columns[0]
        name_col = df_etf_db.columns[1]
        weight_col = df_etf_db.columns[2]
        
        raw_etfs = df_etf_db[etf_col].dropna().astype(str).str.strip().unique().tolist()
        etf_options = [x for x in raw_etfs if x and x.lower() not in ['etf', 'etf代號', 'ticker', 'nan', 'none'] and '代號' not in x]
        
        if etf_options:
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
                        
                        plot_df = plot_df.drop_duplicates(subset=[name_col], keep='last')
                        
                        plot_df[weight_col] = plot_df[weight_col].astype(str).str.replace(r'[^\d.-]', '', regex=True)
                        plot_df[weight_col] = pd.to_numeric(plot_df[weight_col], errors='coerce')
                        plot_df = plot_df.dropna(subset=[weight_col]).sort_values(by=weight_col, ascending=False).head(10)
                        
                        if not plot_df.empty:
                            top10_sum = plot_df[weight_col].sum()
                            st.markdown(f"#### 🎯 前十大持股權重總和： **{top10_sum:.2f}%**")
                            
                            plot_df_top10 = plot_df.sort_values(by=weight_col, ascending=True)
                            plot_df_top10['文字標籤'] = plot_df_top10[weight_col].apply(lambda x: f"{x:.2f}%")
                            
                            fig_etf = px.bar(plot_df_top10, x=weight_col, y=name_col, orientation='h', title=f"<b>{selected_etf} 核心持股佔比 (%)</b>", text='文字標籤')
                            fig_etf.update_traces(textposition='outside')
                            fig_etf.update_yaxes(type='category') 
                            fig_etf.update_layout(yaxis_title=None, xaxis_title="持股比例 (%)", height=450, margin=dict(l=10, r=10, t=40, b=10))
                            st.plotly_chart(fig_etf, use_container_width=True)
                    except Exception as ex:
                        st.warning(f"圖表繪製發生錯誤：{ex}")

# ------------------------------------------
# TAB 6: 每日快報
# ------------------------------------------
with tab_report:
    st.subheader("📰 每日 Top 10 台美股投資快報")
    st.caption("資料來源：自動化監測與公開資訊彙整")
    
    with st.spinner("載入快報資料中..."):
        df_report = load_daily_report()
        
        if not df_report.empty:
            required_cols = ['執行日期', '市場', '排名', '代號', '公司', '收盤價', '日變動%', '技術訊號', '公開研究／新聞', '來源連結', '50字摘要']
            for c in required_cols:
                if c not in df_report.columns:
                    df_report[c] = ""

            valid_dates = [d for d in df_report['執行日期'].unique() if str(d).strip() != '']
            dates = sorted(valid_dates, reverse=True)
            markets = [m for m in df_report['市場'].unique() if str(m).strip() != '']
            
            if dates:
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    sel_date = st.selectbox("選擇日期", options=dates)
                with col_f2:
                    sel_market = st.selectbox("選擇市場", options=["全部"] + markets)
                    
                filtered_df = df_report[df_report['執行日期'] == sel_date]
                if sel_market != "全部":
                    filtered_df = filtered_df[filtered_df['市場'] == sel_market]
                
                disp_df = filtered_df[['市場', '排名', '代號', '公司', '收盤價', '日變動%', '技術訊號', '公開研究／新聞', '50字摘要', '來源連結']].copy()
                
                disp_df['收盤價'] = pd.to_numeric(disp_df['收盤價'], errors='coerce')
                disp_df['日變動%'] = pd.to_numeric(disp_df['日變動%'], errors='coerce')
                disp_df['排名'] = pd.to_numeric(disp_df['排名'], errors='coerce')
                
                disp_df['來源連結'] = disp_df['來源連結'].apply(lambda x: x if str(x).startswith('http') else None)
                
                st.dataframe(
                    disp_df,
                    use_container_width=True,
                    column_config={
                        "來源連結": st.column_config.LinkColumn("新聞連結", display_text="🔗 點擊閱讀"),
                        "日變動%": st.column_config.NumberColumn("日變動(%)", format="%+.2f"),
                        "收盤價": st.column_config.NumberColumn("收盤價", format="%.2f"),
                        "排名": st.column_config.NumberColumn("排名", format="%d"),
                        "50字摘要": st.column_config.TextColumn("新聞摘要", width="large"),
                        "公開研究／新聞": st.column_config.TextColumn("標題/出處", width="medium"),
                    },
                    hide_index=True,
                    height=600
                )
            else:
                st.info("目前快報資料庫中無日期紀錄。")
        else:
            st.warning("無法載入每日快報資料，請確認網址正確或共用權限已設為「知道連結的任何人皆可檢視」。")

# ------------------------------------------
# TAB 7: 每日看盤心得
# ------------------------------------------
with tab4:
    @st.fragment
    def render_trading_journal():
        st.subheader("📖 每日看盤心得紀錄")
        df_journal = load_trading_journal()
        journal_error = False
        
        if not df_journal.empty:
            if 'Date' in df_journal.columns:
                df_journal['Date'] = pd.to_datetime(df_journal['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
                df_journal = df_journal.dropna(subset=['Date'])
                if len(df_journal) < 1: journal_error = True
            else: journal_error = True
        else: journal_error = True

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
                            df_journal = df_journal.fillna("")
                            conn.update(worksheet="Trading_Journal", data=df_journal)
                            st.cache_data.clear()
                            st.success("✅ 心得儲存成功！")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e: st.error(f"寫入失敗：{e}")
            
            st.divider()
            st.subheader("📚 歷史心得回顧")
            if not df_journal.empty:
                df_history_show = df_journal.sort_values(by='Date', ascending=False)
                for _, row in df_history_show.iterrows():
                    with st.expander(f"📅 {row['Date']} (最後更新: {row.get('Last_Updated', '')})"):
                        st.write(row['Notes'])
    
    render_trading_journal()

# ------------------------------------------
# 側邊欄：持股管理 (🚀 結合 st.form 與 @st.fragment 極速防抖)
# ------------------------------------------
st.sidebar.warning("⚠️ 若您剛在 Google Sheets 外部修改過資料，請先點擊上方 **[🔄 強制刷新報價]**。")
st.sidebar.info("💡 **編輯提示**：現在編輯不會再卡頓！請先修改所有想改的儲存格，再一次點擊「💾 儲存變更」。")

with st.sidebar:
    st.header("📝 持股與觀察名單管理")
    
    @st.fragment
    def manage_tw_portfolio():
        st.subheader("🇹🇼 台股清單")
        if not df_tw.empty:
            cols_tw = ['Ticker', '名稱', 'Shares', '出借', '類別', '策略']
            df_tw_display = df_tw.reindex(columns=[c for c in cols_tw if c in df_tw.columns] + [c for c in df_tw.columns if c not in cols_tw])
            
            with st.form("tw_portfolio_form"):
                edited_df_tw = st.data_editor(df_tw_display, num_rows="dynamic", use_container_width=True, key="tw_editor")
                if st.form_submit_button("💾 儲存台股變更"):
                    with st.spinner("正在清洗並寫入台股資料..."):
                        try:
                            clean_tw = edited_df_tw.copy()
                            clean_tw['Ticker'] = clean_tw['Ticker'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
                            clean_tw['Ticker'] = clean_tw['Ticker'].apply(lambda x: x.zfill(4) if x.isdigit() and len(x) < 4 else x)
                            clean_tw = clean_tw[~clean_tw['Ticker'].str.lower().isin(['nan', 'none', 'null', ''])]
                            clean_tw = clean_tw.fillna("") 
                            
                            conn.update(worksheet="TW_Portfolio", data=clean_tw)
                            st.cache_data.clear()
                            st.success("✅ 台股更新成功！")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e: st.error(f"寫入失敗：{e}")
        else: st.info("台股清單目前為空。")

    manage_tw_portfolio()

    st.divider()

    @st.fragment
    def manage_us_portfolio():
        st.subheader("🇺🇸 美股清單")
        if not df_us.empty:
            cols_us = ['Ticker', '名稱', 'Shares', '複委託', '類別', '策略']
            df_us_display = df_us.reindex(columns=[c for c in cols_us if c in df_us.columns] + [c for c in df_us.columns if c not in cols_us])
            
            with st.form("us_portfolio_form"):
                edited_df_us = st.data_editor(df_us_display, num_rows="dynamic", use_container_width=True, key="us_editor")
                if st.form_submit_button("💾 儲存美股變更"):
                    with st.spinner("正在清洗並寫入美股資料..."):
                        try:
                            clean_us = edited_df_us.copy()
                            clean_us['Ticker'] = clean_us['Ticker'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
                            clean_us = clean_us[~clean_us['Ticker'].str.lower().isin(['nan', 'none', 'null', ''])]
                            clean_us = clean_us.fillna("")
                            
                            conn.update(worksheet="US_Portfolio", data=clean_us)
                            st.cache_data.clear()
                            st.success("✅ 美股更新成功！")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e: st.error(f"寫入失敗：{e}")
        else: st.info("美股清單目前為空。")
        
    manage_us_portfolio()
