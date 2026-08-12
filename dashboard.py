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

st.set_page_config(page_title="個人投資組合與技術分析儀表板", layout="wide")

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
# 1. 資料庫連線與資料讀取
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

# 🛑 終極防呆：請直接將您新建的 Technical_DB 試算表網址貼在下方的引號內！
# 例如: TECHNICAL_DB_URL = "https://docs.google.com/spreadsheets/d/1A2B3C4D..."
TECHNICAL_DB_URL = "https://docs.google.com/spreadsheets/d/15F1CRaVUlgQpwbYqFQCwFiyCjmMksEBEd5CnIvF_zFs/edit?gid=0#gid=0" 

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
    except Exception:
        return pd.DataFrame()

df_tw = load_and_standardize_portfolio("TW_Portfolio", "台股")
PORTFOLIO_TW = df_tw.to_dict('records') if not df_tw.empty else []
if df_tw.empty: df_tw = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "出借", "類別"])

df_us = load_and_standardize_portfolio("US_Portfolio", "美股")
PORTFOLIO_US = df_us.to_dict('records') if not df_us.empty else []
if df_us.empty: df_us = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "複委託", "類別"])

# 🚀 讀取預先算好的技術分析資料庫 (已建立完美相容防禦)
@st.cache_data(ttl=60)
def load_technical_db():
    db_url = TECHNICAL_DB_URL.strip() or st.secrets.get("TECHNICAL_DB_URL")
    
    if db_url:
        try:
            df_db = conn.read(spreadsheet=db_url, ttl=60)
            if df_db is not None and not df_db.empty:
                df_db.columns = [str(c).strip() for c in df_db.columns]
                return df_db
        except Exception as e:
            st.error(f"讀取 Technical_DB 時發生連線錯誤，請確認網址與共用權限。({e})")
            return pd.DataFrame()
            
    # 若沒有提供獨立網址，嘗試從預設試算表中尋找
    try:
        df_db = conn.read(worksheet="Technical_DB", ttl=60)
        if df_db is not None and not df_db.empty:
            df_db.columns = [str(c).strip() for c in df_db.columns]
            return df_db
    except: pass
    
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

# 🚀 按需抓取單檔股票 K 線圖資料 (On-Demand Chart Fetching)
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
                if not ticker_str or ticker_str == 'nan': continue
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
                if not ticker_str or ticker_str == 'nan': continue
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
                else: history_error = True
            else: history_error = True
        else: history_error = True
    except Exception: history_error = True

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
# TAB 2: 技術分析掃描 (🚀 直接秒速讀取 Technical_DB)
# ------------------------------------------
with tab2:
    df_db = load_technical_db()
    
    if df_db.empty:
        st.warning("⚠️ 尚未讀取到 `Technical_DB` 資料庫。請確認：\n1. 您是否已在上方第 42 行填入 `TECHNICAL_DB_URL`？\n2. 您的 GitHub Actions 是否已經成功執行並寫入資料？")
    else:
        # 🚀 嚴格保護防禦：檢查每個必備欄位，確保絕對不引發 KeyError 或 AttributeError
        for col in ['bull_score', 'bear_score']:
            if col not in df_db.columns:
                df_db[col] = 0
            df_db[col] = pd.to_numeric(df_db[col], errors='coerce').fillna(0)
            
        if '_raw_pe' not in df_db.columns:
            df_db['_raw_pe'] = np.nan
        df_db['_raw_pe'] = pd.to_numeric(df_db['_raw_pe'], errors='coerce')
        
        # 字串欄位處理防呆
        for col in ['action', 'tags', '_name', '_sym', '標的']:
            if col not in df_db.columns:
                df_db[col] = ""
            df_db[col] = df_db[col].astype(str).fillna("")

        # 建立選項，排除空值與無效名稱
        target_options = {}
        for _, row in df_db.iterrows():
            sym = row['_sym'].strip()
            name = row['_name'].strip()
            if sym and name and sym.lower() not in ['nan', 'none'] and name.lower() not in ['nan', 'none']:
                target_options[f"{name} ({sym})"] = sym

        # 分級 Top 10 清單 (即使查無資料也會回傳空 DataFrame，不會崩潰)
        bullish_strong = df_db[df_db['action'].str.contains(r'\[🚀 強勢買進\]', regex=True, na=False)].sort_values(by=['bull_score', '_raw_pe'], ascending=[False, True]).head(10)
        bullish_daily = df_db[df_db['action'].str.contains(r'\[📈 短多轉折\]', regex=True, na=False)].sort_values(by=['bull_score', '_raw_pe'], ascending=[False, True]).head(10)
        bearish_strong = df_db[df_db['action'].str.contains(r'\[🛑 強制賣出\]', regex=True, na=False)].sort_values(by=['bear_score', '_raw_pe'], ascending=[False, True]).head(10)
        bearish_daily = df_db[df_db['action'].str.contains(r'\[⚠️ 弱勢減碼\]', regex=True, na=False)].sort_values(by=['bear_score', '_raw_pe'], ascending=[False, True]).head(10)

        def format_db_items(sub_df):
            if sub_df.empty: return "無"
            res = []
            for _, r in sub_df.iterrows():
                pe_val = r['_raw_pe']
                try:
                    pe_str = f"PE:{float(pe_val):.1f}" if pd.notna(pe_val) else "無PE"
                except:
                    pe_str = "無PE"
                tags_str = r['tags']
                name_disp = r['_name'] if r['_name'] else r['標的']
                res.append(f"• **{name_disp} ({pe_str})** `[{tags_str}]`")
            return "\n".join(res)

        st.markdown("### 📊 盤後技術亮點與警示摘要 (Top 10)")
        st.caption("篩選邏輯：由後端 `main.py` 每日自動運算，依多空評分嚴格分級，同級別低本益比 (PE) 者優先顯示。")
        
        col_sum1, col_sum2 = st.columns(2)
        with col_sum1:
            st.success(f"**☀️ 多方強勢區**\n\n"
                       f"🔥 **[🚀 強勢買進] Top 10**：\n{format_db_items(bullish_strong)}\n\n"
                       f"📈 **[📈 短多轉折] Top 10**：\n{format_db_items(bullish_daily)}")
        with col_sum2:
            st.error(f"**⛈️ 空方風險區**\n\n"
                     f"🛑 **[🛑 強制賣出] Top 10**：\n{format_db_items(bearish_strong)}\n\n"
                     f"⚠️ **[⚠️ 弱勢減碼] Top 10**：\n{format_db_items(bearish_daily)}")

        st.divider()
        st.markdown("### 📋 完整技術分析清單")
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

        display_cols = ["市場", "標的", "狀態警示", "均線位階", "52週位置", "Beta", "P/E", "日KD", "週KD", "日MACD", "週MACD"]
        display_cols = [c for c in display_cols if c in df_db.columns]
        
        st.dataframe(
            df_db[display_cols], 
            use_container_width=True,
            column_config={
                "市場": st.column_config.TextColumn("市場", width="small"),
                "標的": st.column_config.TextColumn("名稱 (代號)", width="medium"),
                "狀態警示": st.column_config.TextColumn("🚨 狀態標籤與動作", width="large"),
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
            with st.spinner(f"正在繪製 {selected_name} K線圖..."):
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
    
    df_db_comp = load_technical_db()
    comp_options = {}
    if not df_db_comp.empty:
        for _, row in df_db_comp.iterrows():
            sym = str(row.get('_sym', '')).strip()
            name = str(row.get('_name', '')).strip()
            if sym and name and sym.lower() not in ['nan', 'none']: comp_options[f"{name} ({sym})"] = sym
            
    if comp_options:
        all_options_list = list(comp_options.keys())
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
                
                comp_pct_dict = {}
                for tgt in comp_targets:
                    sym = comp_options[tgt]
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
                        fig_comp = px.line(df_comp_pct, x=df_comp_pct.index, y=df_comp_pct.columns, labels={'value': '累計含息報酬率 (%)', 'variable': '標的', 'index': '日期'})
                        fig_comp.update_layout(hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                        st.plotly_chart(fig_comp, use_container_width=True)
                    else: st.warning("選定期間內無足夠數據可供繪製比較圖。")
                else: st.warning("無法取得選定標的的歷史走勢資料。")

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
                
                cols_comp = st.columns(len(comp_targets))
                for idx, tgt in enumerate(comp_targets):
                    with cols_comp[idx]:
                        st.markdown(f"#### 📌 {tgt}")
                        sym = comp_options[tgt]
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
                                st.metric("Top 10 權重合計", f"{top10_sum:.2f}%")
                                
                                disp_df = sub_df[[name_c, weight_c]].copy()
                                disp_df.columns = ["成分股名稱", "權重 (%)"]
                                disp_df["權重 (%)"] = disp_df["權重 (%)"].apply(lambda x: f"{x:.2f}%")
                                st.dataframe(disp_df, hide_index=True, use_container_width=True)
                            else: st.caption("ℹ️ 暫無有效的權重數值。")
                        else: st.caption("ℹ️ 個別股票或未收錄成分股資料。")
            else: st.caption("未連線至 ETF 持股資料庫，無法顯示成分股比對。")
    else: st.info("請先確認持股清單並等待資料庫載入。")

# ------------------------------------------
# TAB 4: 績效與觀察總覽
# ------------------------------------------
with tab3:
    st.markdown("一覽所有持股與觀察清單的基本面與走勢指標。")
    df_db_perf = load_technical_db()
    if not df_db_perf.empty:
        disp_p_cols = ["市場", "代號", "標的", "收盤價", "P/E", "Beta", "52週位置", "日KD", "週KD", "日MACD", "週MACD", "狀態警示"]
        disp_p_cols = [c for c in disp_p_cols if c in df_db_perf.columns]
        st.dataframe(df_db_perf[disp_p_cols], hide_index=True, use_container_width=True, height=500)
    else:
        st.info("資料庫未包含足夠資訊，請等待排程更新。")

# ------------------------------------------
# TAB 5: ETF 持股
# ------------------------------------------
with tab_etf:
    st.subheader("🧩 ETF Top 10 持股分析")
    st.caption("自動解析您的 ETF 持股結構，掌握真實資金流向與比重。")
    
    csv_url = "https://docs.google.com/spreadsheets/d/1_crBmjMxgm9qpYeycg_TnLStt3phN6vM4XILmD9x0Yc/gviz/tq?tqx=out:csv&gid=892058804"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'}
        response = requests.get(csv_url, headers=headers, timeout=15)
        response.raise_for_status() 
        df_etf_db = pd.read_csv(io.StringIO(response.text)).dropna(how='all')
        read_success = True
    except Exception as e:
        df_etf_db = pd.DataFrame()
        read_success = False
        err_msg = str(e)

    if not read_success:
        st.error(f"❌ **無法讀取外部 ETF 試算表！**\n錯誤訊息：`{err_msg}`")
    elif df_etf_db is None or df_etf_db.empty:
        st.warning("⚠️ 成功連線，但系統讀取到的資料是空的。")
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
                        plot_df[weight_col] = plot_df[weight_col].astype(str).str.replace(r'[^\d.-]', '', regex=True)
                        plot_df[weight_col] = pd.to_numeric(plot_df[weight_col], errors='coerce')
                        plot_df = plot_df.dropna(subset=[weight_col]).sort_values(by=weight_col, ascending=True)
                        
                        if not plot_df.empty:
                            plot_df_top10 = plot_df.tail(10)
                            top10_sum = plot_df_top10[weight_col].sum()
                            st.markdown(f"#### 🎯 前十大持股權重總和： **{top10_sum:.2f}%**")
                            plot_df_top10['文字標籤'] = plot_df_top10[weight_col].apply(lambda x: f"{x:.2f}%")
                            
                            fig_etf = px.bar(plot_df_top10, x=weight_col, y=name_col, orientation='h', title=f"<b>{selected_etf} 核心持股佔比 (%)</b>", text='文字標籤')
                            fig_etf.update_traces(textposition='outside')
                            fig_etf.update_yaxes(type='category') 
                            fig_etf.update_layout(yaxis_title=None, xaxis_title="持股比例 (%)", height=450, margin=dict(l=10, r=10, t=40, b=10))
                            st.plotly_chart(fig_etf, use_container_width=True)
                    except Exception as ex:
                        st.warning(f"圖表繪製發生錯誤：{ex}")

# ------------------------------------------
# TAB 6: 每日看盤心得
# ------------------------------------------
with tab4:
    st.subheader("📖 每日看盤心得紀錄")
    journal_error = False
    try:
        df_journal = conn.read(worksheet="Trading_Journal", ttl=0)
        if df_journal is not None and 'Date' in df_journal.columns and not df_journal.empty:
            df_journal['Date'] = pd.to_datetime(df_journal['Date'], errors='coerce').dt.strftime('%Y-%m-%d')
            df_journal = df_journal.dropna(subset=['Date'])
            if len(df_journal) < 1: journal_error = True
        else: journal_error = True
    except Exception: journal_error = True

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
                        conn.update(worksheet="Trading_Journal", data=df_journal)
                        st.success("✅ 心得儲存成功！")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e: st.error(f"寫入失敗：{e}")
        
        st.divider()
        st.subheader("📚 歷史心得回顧")
        if not df_journal.empty:
            for _, row in df_journal.sort_values(by='Date', ascending=False).iterrows():
                with st.expander(f"📅 {row['Date']} (最後更新: {row.get('Last_Updated', '')})"):
                    st.write(row['Notes'])

# ------------------------------------------
# 側邊欄：持股管理
# ------------------------------------------
with st.sidebar:
    st.header("📝 持股與觀察名單管理")
    st.markdown("新增代號並將股數設為 0，它就會自動加入每日自動技術掃描！")
    
    st.subheader("🇹🇼 台股清單")
    if not df_tw.empty:
        edited_df_tw = st.data_editor(df_tw, num_rows="dynamic", use_container_width=True, key="tw_editor")
        if st.button("💾 儲存台股變更"):
            try:
                conn.update(worksheet="TW_Portfolio", data=edited_df_tw)
                st.success("✅ 台股更新成功！請重新整理網頁。")
            except Exception as e: st.error(f"寫入失敗：{e}")
            
    st.divider()

    st.subheader("🇺🇸 美股清單")
    if not df_us.empty:
        edited_df_us = st.data_editor(df_us, num_rows="dynamic", use_container_width=True, key="us_editor")
        if st.button("💾 儲存美股變更"):
            try:
                conn.update(worksheet="US_Portfolio", data=edited_df_us)
                st.success("✅ 美股更新成功！請重新整理網頁。")
            except Exception as e: st.error(f"寫入失敗：{e}")
