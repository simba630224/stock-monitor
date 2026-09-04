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

st.set_page_config(page_title="行動隨身投資儀表板", layout="wide")

# ==========================================
# 🔒 權限驗證閘門 (只有通過驗證才能載入後續資料)
# ==========================================
def check_password():
    """驗證成功回傳 True，否則顯示輸入框並終止後續程式執行"""
    if st.session_state.get("authenticated", False):
        return True

    # 取得設定的密碼 (優先讀取 Secrets，若無則使用預設值 admin888)
    correct_password = st.secrets.get("APP_PASSWORD", "19770614")

    st.markdown("### 🔒 個人投資儀表板 (受保護存取)")
    pwd_input = st.text_input("請輸入存取密碼：", type="password")

    if st.button("🔑 登入"):
        if pwd_input == correct_password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("❌ 密碼錯誤，請重新輸入！")

    return False

# 若未通過驗證，立即中斷執行，防止未授權讀取
if not check_password():
    st.stop()

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
# 1. 資料庫連線與安全快取模組 (🚀 解決打字清空與覆蓋問題)
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

# 🛑 請將您的 Technical_DB 試算表網址貼在引號內！
TECHNICAL_DB_URL = "https://docs.google.com/spreadsheets/d/15F1CRaVUlgQpwbYqFQCwFiyCjmMksEBEd5CnIvF_zFs/edit" 

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
            st.error(f"讀取 Technical_DB 失敗，請確認網址。({e})")
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
        except: time.sleep(0.5)
    return 0.0, 0.0, 0.0

@st.cache_data(ttl=600)
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

@st.cache_data(ttl=600)
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
# 3. 手機版隨身 UI 渲染與 Fragment 元件
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

# ------------------------------------------
# TAB 1: 投資組合總覽
# ------------------------------------------
with tab1:
    with st.spinner("載入報價與算資產中..."):
        usdtwd = get_usdtwd()
        total_market_value, total_dividends_2026, total_dividends_1y = 0, 0, 0
        asset_allocation = {}
        individual_holdings = [] 

        for item in PORTFOLIO_TW:
            if pd.notna(item.get('Ticker')):
                ticker_str = str(item['Ticker']).strip()
                if not ticker_str or ticker_str.lower() in ['nan', 'none', '']: continue
                ticker = get_yf_ticker_tw(ticker_str)
                asset_type = str(item.get('類別', '台股未分類')).strip()
                if not asset_type or asset_type.lower() == 'nan': asset_type = '台股未分類'
                
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
                    display_name = format_display_name(item.get('名稱'), ticker_str)
                    individual_holdings.append({'標的': display_name, '標的與股數': f"{display_name} ({disp_qty})", '總市值': val, '預估股息': div_tot_2026, '類別': asset_type})

        for item in PORTFOLIO_US:
            if pd.notna(item.get('Ticker')):
                ticker_str = str(item['Ticker']).strip()
                if not ticker_str or ticker_str.lower() in ['nan', 'none', '']: continue
                asset_type = str(item.get('類別', '美股未分類')).strip()
                if not asset_type or asset_type.lower() == 'nan': asset_type = '美股未分類'
                
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
                    display_name = format_display_name(item.get('名稱'), ticker_str)
                    individual_holdings.append({'標的': display_name, '標的與股數': f"{display_name} ({disp_qty})", '總市值': val, '預估股息': div_tot_2026, '類別': asset_type})

        col_m1, col_m2 = st.columns(2)
        col_m1.metric("總市值", f"${total_market_value:,.0f}")
        col_m2.metric("目前匯率", f"{usdtwd:.3f}")
        
        col_m3, col_m4 = st.columns(2)
        col_m3.metric("2026 預估股息", f"${total_dividends_2026:,.0f}")
        col_m4.metric("近一年累計股息", f"${total_dividends_1y:,.0f}")

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

# ------------------------------------------
# TAB HL: 技術亮點摘要 
# ------------------------------------------
with tab_hl:
    df_db = load_technical_db()
    
    if df_db.empty:
        st.warning("⚠️ 尚未讀取到 `Technical_DB` 資料庫。請確認：\n1. 第 46 行已填入 `TECHNICAL_DB_URL`\n2. GitHub Actions 已寫入資料")
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

            def format_mobile_items(sub_df):
                if sub_df.empty: return "> 目前無符合條件標的"
                res = ""
                for _, r in sub_df.iterrows():
                    pe_val = r['_raw_pe']
                    try:
                        pe_str = f"PE:{float(pe_val):.1f}" if pd.notna(pe_val) else "無PE"
                    except:
                        pe_str = "無PE"
                    tags_str = r['tags']
                    name_disp = r['顯示名稱']
                    res += f"- **{name_disp}** ({pe_str})\n  - `[{tags_str}]`\n"
                return res

            is_short_term = df_db['策略'].str.contains('短', case=False, na=False)
            df_short = df_db[is_short_term]
            df_normal = df_db[~is_short_term]

            st.markdown("### 📊 技術亮點與警示摘要")
            
            st.markdown("#### ⚡ 短線進出專區 (創高破底)")
            if not df_short.empty:
                bullish_short = df_short[df_short['bull_score'] >= df_short['bear_score']].sort_values(by=['bull_score', '_raw_pe'], ascending=[False, True])
                bearish_short = df_short[df_short['bull_score'] < df_short['bear_score']].sort_values(by=['bear_score', '_raw_pe'], ascending=[False, True])
                
                with st.container():
                    st.success(f"**🚀 短線偏多 / 創高動能**\n\n{format_mobile_items(bullish_short)}")
                    st.error(f"**🩸 短線偏空 / 破底風險**\n\n{format_mobile_items(bearish_short)}")
            else:
                st.info("尚無短線標的。請於側邊欄「策略」標註『短線』啟用此區。")

            st.divider()

            st.markdown("#### 📈 波段與長期投資 (Top 10)")
            bullish_strong = df_normal[df_normal['action'].str.contains(r'\[🚀 強勢買進\]', regex=True, na=False)].sort_values(by=['bull_score', '_raw_pe'], ascending=[False, True]).head(10)
            bullish_daily = df_normal[df_normal['action'].str.contains(r'\[📈 短多轉折\]', regex=True, na=False)].sort_values(by=['bull_score', '_raw_pe'], ascending=[False, True]).head(10)
            bearish_strong = df_normal[df_normal['action'].str.contains(r'\[🛑 強制賣出\]', regex=True, na=False)].sort_values(by=['bear_score', '_raw_pe'], ascending=[False, True]).head(10)
            bearish_daily = df_normal[df_normal['action'].str.contains(r'\[⚠️ 弱勢減碼\]', regex=True, na=False)].sort_values(by=['bear_score', '_raw_pe'], ascending=[False, True]).head(10)

            with st.container():
                st.success(f"🔥 **[🚀 強勢買進]**\n\n{format_mobile_items(bullish_strong)}")
                st.info(f"📈 **[📈 短多轉折]**\n\n{format_mobile_items(bullish_daily)}")
                st.error(f"🛑 **[🛑 強制賣出]**\n\n{format_mobile_items(bearish_strong)}")
                st.warning(f"⚠️ **[⚠️ 弱勢減碼]**\n\n{format_mobile_items(bearish_daily)}")
        except Exception as e:
            st.error("摘要產生錯誤，請檢查資料庫。")

# ------------------------------------------
# TAB 3: 多檔走勢比較 
# ------------------------------------------
with tab_comp:
    st.markdown("### 🆚 標的走勢比較")
    
    comp_options = {}
    for item in PORTFOLIO_TW:
        sym_raw = str(item.get('Ticker', '')).strip()
        if sym_raw and sym_raw.lower() not in ['nan', 'none']:
            sym = get_yf_ticker_tw(sym_raw)
            disp_name = format_display_name(item.get('名稱'), sym_raw)
            comp_options[disp_name] = sym
            
    for item in PORTFOLIO_US:
        sym_raw = str(item.get('Ticker', '')).strip()
        if sym_raw and sym_raw.lower() not in ['nan', 'none']:
            disp_name = format_display_name(item.get('名稱'), sym_raw)
            comp_options[disp_name] = sym_raw
            
    if comp_options:
        all_options_list = list(comp_options.keys())
        comp_targets = st.multiselect("選擇標的 (最多4檔)：", options=all_options_list, max_selections=4, key="m_comp_ms")
        comp_period = st.selectbox("比較期間", ["半年", "一年", "三年"], index=1)
            
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
                        fig_comp = px.line(df_comp_pct, x=df_comp_pct.index, y=df_comp_pct.columns, labels={'value': '含息報酬(%)'})
                        fig_comp.update_layout(hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), xaxis_title=None)
                        st.plotly_chart(fig_comp, use_container_width=True)
                    else: st.warning("無足夠數據繪圖。")
                else: st.warning("無法取得歷史資料。")

            st.divider()
            st.markdown("### 🧩 Top 10 核心持股比對")
            csv_url_comp = "https://docs.google.com/spreadsheets/d/1_crBmjMxgm9qpYeycg_TnLStt3phN6vM4XILmD9x0Yc/gviz/tq?tqx=out:csv&gid=892058804"
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                resp = requests.get(csv_url_comp, headers=headers, timeout=10)
                resp.raise_for_status()
                df_etf_comp_db = pd.read_csv(io.StringIO(resp.text)).dropna(how='all')
            except Exception: df_etf_comp_db = pd.DataFrame()

            if not df_etf_comp_db.empty and len(df_etf_comp_db.columns) >= 3:
                etf_c = df_etf_comp_db.columns[0]
                name_c = df_etf_comp_db.columns[1]
                weight_c = df_etf_comp_db.columns[2]
                
                for tgt in comp_targets:
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
                        
                        sub_df = sub_df.sort_values(by=weight_c, ascending=False).drop_duplicates(subset=[name_c], keep='first').head(10)
                        
                        if not sub_df.empty:
                            top10_sum = sub_df[weight_c].sum()
                            st.caption(f"**Top 10 權重合計：{top10_sum:.2f}%**")
                            disp_df = sub_df[[name_c, weight_c]].copy()
                            disp_df.columns = ["成分股", "權重(%)"]
                            disp_df["權重(%)"] = disp_df["權重(%)"].apply(lambda x: f"{x:.2f}%")
                            st.dataframe(disp_df, hide_index=True, use_container_width=True)
                        else: st.caption("無有效權重數值。")
                    else: st.caption("未收錄成分股資料。")
                    st.write("") 
            else: st.caption("無法連線 ETF 資料庫。")
    else: st.info("清單中無有效標的。")

# ------------------------------------------
# TAB 4: 技術清單與線圖
# ------------------------------------------
with tab2:
    with st.expander("💡 狀態警示規則說明", expanded=False):
        st.markdown("""
        * **[🚀 強勢買進]**：多方分數 ≥ 3 且具備「週KD低檔金叉(K<30)」或「週MACD零下金叉」。
        * **[📈 短多轉折]**：多方分數 > 0 (未達強勢買進標準者)。
        * **[🛑 強制賣出]**：空方分數 ≥ 3 且具備「週KD高檔死叉(K>70)」或「週MACD零上死叉」。
        * **[⚠️ 弱勢減碼]**：空方分數 > 0 (未達強制賣出標準者)。
        """)
        
    if 'df_db' in locals() and not df_db.empty: 
        display_cols = ["顯示名稱", "策略", "狀態警示", "收盤價", "52週位置"]
        display_cols = [c for c in display_cols if c in df_db.columns]
        st.dataframe(
            df_db[display_cols], 
            use_container_width=True, 
            hide_index=True, 
            height=350,
            column_config={
                "顯示名稱": st.column_config.TextColumn("標的"),
                "策略": st.column_config.TextColumn("策略", width="small"),
                "狀態警示": st.column_config.TextColumn("🚨 狀態標籤與動作", width="large")
            }
        )

    st.divider()
    selected_name = st.selectbox("查看詳細線圖：", options=list(target_options.keys()) if 'target_options' in locals() and target_options else [])
    if selected_name:
        sym = target_options[selected_name]
        with st.spinner("載入圖表中..."):
            df_chart = get_single_stock_chart_data(sym)
            if df_chart is not None and not df_chart.empty:
                df_plot = df_chart.tail(80) 
                fig_tech = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
                
                if 'Open' in df_plot.columns and 'High' in df_plot.columns and 'Low' in df_plot.columns:
                    fig_tech.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name='K線', increasing_line_color='red', decreasing_line_color='green'), row=1, col=1)
                else:
                    fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Close'], mode='lines', name='收盤價'), row=1, col=1)
                    
                fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MA20'], line=dict(color='blue', width=1.5), name='MA20'), row=1, col=1)
                if '季線' in df_plot.columns:
                    fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['季線'], line=dict(color='orange', width=1.5), name="季線"), row=1, col=1)
                
                if 'K_d' in df_plot.columns:
                    fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['K_d'], line=dict(color='blue', width=1.2), name='K'), row=2, col=1)
                    fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['D_d'], line=dict(color='orange', width=1.2), name='D'), row=2, col=1)
                    
                fig_tech.update_layout(xaxis_rangeslider_visible=False, height=400, margin=dict(t=20, b=10, l=10, r=10), showlegend=False)
                st.plotly_chart(fig_tech, use_container_width=True)

# ------------------------------------------
# TAB 5: 績效與股息追蹤 
# ------------------------------------------
with tab3:
    st.markdown("所有標的之含息報酬率與財報指標。")
    with st.spinner("計算績效與配息中..."):
        bench_returns = get_benchmark_returns()
        perf_results = []
        scan_list = []
        
        for item in PORTFOLIO_TW:
            t = str(item.get('Ticker', '')).strip()
            if t and t.lower() not in ['nan', 'none']: scan_list.append((get_yf_ticker_tw(t), t, '台股', item.get('名稱', '')))
                
        for item in PORTFOLIO_US:
            t = str(item.get('Ticker', '')).strip()
            if t and t.lower() not in ['nan', 'none']: scan_list.append((t, t, '美股', item.get('名稱', '')))
                
        for sym, display_ticker, market, raw_name in scan_list:
            disp_name = format_display_name(raw_name, display_ticker)
            res = get_perf_div_data(sym, display_ticker, market, bench_returns, disp_name)
            if res: perf_results.append(res)
                
        if perf_results:
            df_perf = pd.DataFrame(perf_results)
            display_cols = ["顯示名稱", "收盤價", "近一季含息報酬", "近半年含息報酬", "近一年含息報酬", "相對大盤", "近一年殖利率", "總配息金額", "ROE"]
            display_cols = [c for c in display_cols if c in df_perf.columns]
            
            if not df_perf.empty:
                st.dataframe(
                    df_perf[display_cols],
                    use_container_width=True,
                    column_config={
                        "顯示名稱": st.column_config.TextColumn("標的"),
                        "收盤價": st.column_config.NumberColumn("收盤", format="%.2f"),
                        "近一季含息報酬": st.column_config.NumberColumn("季含息(%)", format="%+.1f"),
                        "近半年含息報酬": st.column_config.NumberColumn("半年含息(%)", format="%+.1f"),
                        "近一年含息報酬": st.column_config.NumberColumn("年含息(%)", format="%+.1f"),
                        "相對大盤": st.column_config.NumberColumn("對大盤(%)", format="%+.1f"),
                        "近一年殖利率": st.column_config.NumberColumn("殖利率(%)", format="%.1f"),
                        "總配息金額": st.column_config.NumberColumn("年配息", format="%.2f"),
                        "ROE": st.column_config.NumberColumn("ROE(%)", format="%.1f")
                    },
                    hide_index=True, height=450
                )
            else:
                st.info("尚無可顯示的績效資料。")

# ------------------------------------------
# TAB 6: ETF 持股 
# ------------------------------------------
with tab_etf:
    st.markdown("### 🧩 ETF Top 10 成分股")
    
    csv_url = "https://docs.google.com/spreadsheets/d/1_crBmjMxgm9qpYeycg_TnLStt3phN6vM4XILmD9x0Yc/gviz/tq?tqx=out:csv&gid=892058804"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(csv_url, headers=headers, timeout=15)
        response.raise_for_status() 
        df_etf_db = pd.read_csv(io.StringIO(response.text)).dropna(how='all')
        read_success = True
    except Exception as e:
        df_etf_db = pd.DataFrame()
        read_success = False
        err_msg = str(e)

    if not read_success:
        st.error(f"❌ 無法讀取 ETF 試算表！\n錯誤：`{err_msg}`")
    elif df_etf_db is None or df_etf_db.empty:
        st.warning("⚠️ 成功連線，但資料是空的。")
    else:
        etf_col = df_etf_db.columns[0]
        name_col = df_etf_db.columns[1]
        weight_col = df_etf_db.columns[2]
        
        raw_etfs = df_etf_db[etf_col].dropna().astype(str).str.strip().unique().tolist()
        etf_options = [x for x in raw_etfs if x and x.lower() not in ['etf', 'etf代號', 'ticker', 'nan', 'none'] and '代號' not in x]
        
        if etf_options:
            selected_etf = st.selectbox("👉 選擇要查詢的 ETF：", options=etf_options, key="m_etf_select")
            if selected_etf:
                df_show = df_etf_db[df_etf_db[etf_col].astype(str).str.strip() == selected_etf].copy()
                try:
                    plot_df = df_show.copy()
                    plot_df[name_col] = plot_df[name_col].astype(str).str.strip()
                    
                    plot_df = plot_df.drop_duplicates(subset=[name_col], keep='last')
                    
                    plot_df[weight_col] = plot_df[weight_col].astype(str).str.replace(r'[^\d.-]', '', regex=True)
                    plot_df[weight_col] = pd.to_numeric(plot_df[weight_col], errors='coerce')
                    plot_df = plot_df.dropna(subset=[weight_col]).sort_values(by=weight_col, ascending=False).head(10)
                    
                    if not plot_df.empty:
                        top10_sum = plot_df[weight_col].sum()
                        st.markdown(f"#### 🎯 Top 10 合計： **{top10_sum:.2f}%**")
                        
                        plot_df_top10 = plot_df.sort_values(by=weight_col, ascending=True)
                        plot_df_top10['文字標籤'] = plot_df_top10[weight_col].apply(lambda x: f"{x:.2f}%")
                        
                        fig_etf = px.bar(plot_df_top10, x=weight_col, y=name_col, orientation='h', title=f"{selected_etf} 核心持股", text='文字標籤')
                        fig_etf.update_traces(textposition='outside')
                        fig_etf.update_yaxes(type='category') 
                        fig_etf.update_layout(height=400, yaxis_title=None, xaxis_title="%", margin=dict(l=10, r=10, t=30, b=10))
                        st.plotly_chart(fig_etf, use_container_width=True)
                except Exception as ex:
                    st.warning(f"圖表繪製發生錯誤：{ex}")
                st.dataframe(df_show, hide_index=True, use_container_width=True)

# ------------------------------------------
# TAB 7: 每日看盤心得與 Fragment 防卡頓
# ------------------------------------------
with tab4:
    @st.fragment
    def manage_mobile_journal():
        st.markdown("### 📖 每日看盤心得")
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
                            df_journal = df_journal.fillna("")
                            conn.update(worksheet="Trading_Journal", data=df_journal)
                            st.cache_data.clear()
                            st.success("✅ 儲存成功！")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e: st.error("寫入失敗")
            
            st.divider()
            st.caption("📚 歷史回顧")
            if not df_journal.empty:
                df_history_show = df_journal.sort_values(by='Date', ascending=False)
                for _, row in df_history_show.iterrows():
                    with st.expander(f"📅 {row['Date']} (最後更新: {row.get('Last_Updated', '')})"):
                        st.write(row['Notes'])

    manage_mobile_journal()

# ------------------------------------------
# 管理清單與 Fragment 防卡頓
# ------------------------------------------
with tab5:
    st.markdown("### ✏️ 雲端隨身記帳")
    st.caption("⚠️ 在外部修改後，請先按上方[🔄 刷新]。編輯後請點擊空白處再儲存。")
    
    @st.fragment
    def manage_tw_portfolio():
        st.subheader("🇹🇼 台股名單")
        if not df_tw.empty:
            cols_tw = ['Ticker', '名稱', 'Shares', '出借', '類別', '策略']
            df_tw_disp = df_tw.reindex(columns=[c for c in cols_tw if c in df_tw.columns] + [c for c in df_tw.columns if c not in cols_tw])
            
            with st.form("tw_portfolio_form"):
                edited_tw = st.data_editor(df_tw_disp, num_rows="dynamic", use_container_width=True, key="m_tw_editor")
                if st.form_submit_button("💾 儲存台股變更"):
                    with st.spinner("正在清洗並寫入..."):
                        try:
                            clean_tw = edited_tw.copy()
                            clean_tw['Ticker'] = clean_tw['Ticker'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
                            clean_tw['Ticker'] = clean_tw['Ticker'].apply(lambda x: x.zfill(4) if x.isdigit() and len(x) < 4 else x)
                            clean_tw = clean_tw[~clean_tw['Ticker'].str.lower().isin(['nan', 'none', 'null', ''])]
                            clean_tw = clean_tw.fillna("")
                            
                            conn.update(worksheet="TW_Portfolio", data=clean_tw)
                            st.cache_data.clear()
                            st.success("✅ 更新成功！")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e: st.error(f"錯誤:{e}")
        else: st.info("名單為空。")
        
    manage_tw_portfolio()
            
    st.divider()
    
    @st.fragment
    def manage_us_portfolio():
        st.subheader("🇺🇸 美股名單")
        if not df_us.empty:
            cols_us = ['Ticker', '名稱', 'Shares', '複委託', '類別', '策略']
            df_us_disp = df_us.reindex(columns=[c for c in cols_us if c in df_us.columns] + [c for c in df_us.columns if c not in cols_us])
            
            with st.form("us_portfolio_form"):
                edited_us = st.data_editor(df_us_disp, num_rows="dynamic", use_container_width=True, key="m_us_editor")
                if st.form_submit_button("💾 儲存美股變更"):
                    with st.spinner("正在清洗並寫入..."):
                        try:
                            clean_us = edited_us.copy()
                            clean_us['Ticker'] = clean_us['Ticker'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
                            clean_us = clean_us[~clean_us['Ticker'].str.lower().isin(['nan', 'none', 'null', ''])]
                            clean_us = clean_us.fillna("")
                            
                            conn.update(worksheet="US_Portfolio", data=clean_us)
                            st.cache_data.clear()
                            st.success("✅ 更新成功！")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e: st.error(f"錯誤:{e}")
        else: st.info("名單為空。")
        
    manage_us_portfolio()
