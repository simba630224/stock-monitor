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
# 1. 資料庫連線與 Session State 狀態管理 (🚀 解決打字清空與覆蓋問題)
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

# 🛑 請將您的 Technical_DB 試算表網址貼在引號內！
TECHNICAL_DB_URL = "" 

def load_and_standardize_portfolio(worksheet_name, default_category):
    try:
        # 使用 ttl=0 確保每次呼叫都是從 Google Sheets 拿最熱騰騰的資料
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
            # 🚀 解決 Google Sheets 把 2330 存成 2330.0 的浮點數陷阱
            df['Ticker'] = df['Ticker'].str.replace(r'\.0$', '', regex=True)
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

# 🚀 使用 Session State 綁定，保證 st.data_editor 編輯到一半絕對不會被清空
if "tw_portfolio" not in st.session_state:
    st.session_state.tw_portfolio = load_and_standardize_portfolio("TW_Portfolio", "台股")
    if st.session_state.tw_portfolio.empty:
        st.session_state.tw_portfolio = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "出借", "類別", "策略"])

if "us_portfolio" not in st.session_state:
    st.session_state.us_portfolio = load_and_standardize_portfolio("US_Portfolio", "美股")
    if st.session_state.us_portfolio.empty:
        st.session_state.us_portfolio = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "複委託", "類別", "策略"])

df_tw = st.session_state.tw_portfolio
df_us = st.session_state.us_portfolio

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

@st.cache_data(ttl=900)
def get_perf_div_data(sym, display_ticker, market, bench_returns, display_name):
    result = {
        "市場": market, "代號": display_ticker, "顯示名稱": display_name, "收盤價": 0.0,
        "近一季含息報酬": 0.0, "近半年含息報酬": 0.0, "近一年含息報酬": 0.0,
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
                    "收盤價": curr_p, "近一季含息報酬": float(ret_1q), "近半年含息報酬": float(ret_6m), 
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
        # 🚀 刷新時一併清除記憶體內的快取清單，讓網頁真正抓取 Google Sheets 最新進度
        if "tw_portfolio" in st.session_state: del st.session_state["tw_portfolio"]
        if "us_portfolio" in st.session_state: del st.session_state["us_portfolio"]
        st.rerun()
with col_time:
    st.caption(f"數據最後更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

tab1, tab2, tab_comp, tab3, tab_etf, tab4 = st.tabs(["💰 投資組合總覽", "📈 技術分析掃描", "🆚 標的比較", "🏆 績效與觀察總覽", "🧩 ETF持股", "📖 每日看盤心得"])

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
                            df_history = df_history.fillna("") # 🚀 寫入前強制防呆空值
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
        st.warning("⚠️ 尚未讀取到 `Technical_DB` 資料庫。請確認：\n1. 您是否已在上方第 45 行填入 `TECHNICAL_DB_URL`？\n2. 您的 GitHub Actions 是否已經成功執行並寫入資料？")
    else:
        try:
            for col in ['bull_score', 'bear_score']:
                if col not in df_db.columns: df_db[col] = 0
                df_db[col] = pd.to_numeric(df_db[col], errors='coerce').fillna(0)
                
            if '_raw_pe' not in df_db.columns: df_db['_raw_pe'] = np.nan
            df_db['_raw_pe'] = pd.to_numeric(df_db['_raw_pe'], errors='coerce')
            
            for col in ['action', 'tags', '_name', '_sym', '標的', '策略']:
                if col not in df_db.columns: df_db[col] = ""
                df_db[col] = df_db[col].astype(str).replace(['nan', 'None'], '').fillna("")

            df_db['顯示名稱'] = df_db.apply(lambda r: format_display_name(r.get('_name'), r.get('_sym')), axis=1)

            target_options = {}
            for _, row in df_db.iterrows():
                sym = str(row.get('_sym', '')).strip()
                disp_name = row.get('顯示名稱', '')
                if sym and sym.lower() not in ['nan', 'none', '']:
                    target_options[disp_name] = sym

            def format_db_items(sub_df):
                if sub_df.empty: return "無"
                res = []
                for _, r in sub_df.iterrows():
                    pe_val = r.get('_raw_pe')
                    try:
                        pe_str = f"PE:{float(pe_val):.1f}" if pd.notna(pe_val) else "無PE"
                    except:
                        pe_str = "無PE"
                    tags_str = r.get('tags', '')
                    name_disp = r.get('顯示名稱', '未知')
