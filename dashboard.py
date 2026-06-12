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
    """安全地將資料轉換為浮點數，遇到空白或非數字則回傳 0.0"""
    try:
        return float(val) if pd.notna(val) and str(val).strip() != '' else 0.0
    except:
        return 0.0

# ==========================================
# 1. 資料庫與清單設定 (Google Sheets 雙分頁連線)
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

# 讀取台股
try:
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0)
    df_tw = df_tw.dropna(subset=['Ticker'])
    # 自動補齊台股所需欄位
    if 'Shares' not in df_tw.columns: df_tw['Shares'] = 0.0
    if '出借' not in df_tw.columns: df_tw['出借'] = 0.0
    PORTFOLIO_TW = df_tw.to_dict('records')
except Exception as e:
    st.error(f"⚠️ 無法讀取台股資料，請確認試算表內有『TW_Portfolio』工作表。錯誤: {e}")
    PORTFOLIO_TW = []
    df_tw = pd.DataFrame(columns=["Ticker", "Shares", "出借"])

# 讀取美股
try:
    df_us = conn.read(worksheet="US_Portfolio", ttl=0)
    df_us = df_us.dropna(subset=['Ticker'])
    # 自動補齊美股所需欄位
    if 'Shares' not in df_us.columns: df_us['Shares'] = 0.0
    if '複委託' not in df_us.columns: df_us['複委託'] = 0.0
    PORTFOLIO_US = df_us.to_dict('records')
except Exception as e:
    st.warning(f"⚠️ 無法讀取美股資料，請確認試算表內有『US_Portfolio』工作表。錯誤: {e}")
    PORTFOLIO_US = []
    df_us = pd.DataFrame(columns=["Ticker", "Shares", "複委託"])

# 技術分析觀察清單
TW_CORE = [
    {'symbol': '2330.TW', 'name': '台積電'}, {'symbol': '2317.TW', 'name': '鴻海'},
    {'symbol': '2454.TW', 'name': '聯發科'}, {'symbol': '2308.TW', 'name': '台達電'},
    {'symbol': '3008.TW', 'name': '大立光'}, {'symbol': '0050.TW', 'name': '元大台灣50'},
    {'symbol': '006208.TW', 'name': '富邦台50'},
    {'symbol': '00878.TW', 'name': '國泰永續高股息'}, {'symbol': '00713.TW', 'name': '元大台灣高息低波'},
    {'symbol': '00919.TW', 'name': '群益台灣精選高息'}, {'symbol': '009812.TW', 'name': '野村日本東證ETF'},
    {'symbol': '00922.TW', 'name': '國泰台灣領袖50'}, {'symbol': '00923.TW', 'name': '群益台灣ESG低碳'},
    {'symbol': '00830.TW', 'name': '國泰費城半導體'}, {'symbol': '00981A.TW', 'name': '主動統一台股增長'},
    {'symbol': '00988A.TW', 'name': '主動統一全球創新'}, {'symbol': '009815.TW', 'name': '大華美國MAG7+'}
]

US_WATCH = [
    {'symbol': 'NVDA', 'name': '輝達 Nvidia'}, {'symbol': 'MSFT', 'name': '微軟 Microsoft'},
    {'symbol': 'GOOGL', 'name': '谷歌 Google'}, {'symbol': 'VOO', 'name': '標普500 VOO'},
    {'symbol': 'QQQ', 'name': '納斯達克 QQQ'}, {'symbol': 'VT', 'name': '領航全球股票 VT'},
    {'symbol': 'VWRA.L', 'name': '富時全球全指 VWRA'}
]

# ==========================================
# 2. 核心抓取與計算邏輯 (加入台美股均線分流)
# ==========================================
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip()
    return f"{ticker}.TWO" if re.match(r'^\d+B$', ticker) else f"{ticker}.TW"

def classify_asset(ticker, market):
    ticker = str(ticker).strip().upper()
    if ticker in ['VT', 'VWRA.L', '009812', '009812.TW']: return '全球ETF'
    if market == 'TW':
        if ticker.endswith('B'): return '債券ETF'
        if ticker.startswith('00'):
            if ticker in ['00646', '00757', '00662', '00830', '009811', '00712', '00717', '009800', '009813','009815', '00988A']: return '美股ETF與個股'
            if ticker in ['0050', '006208', '00692', '00922', '00923']: return '台股市值型ETF'
            if ticker in ['0056', '00878', '00919', '00713']: return '台股高股息型ETF'
            return '台股其他ETF'
        return '台股個股'
    elif market == 'US':
        if ticker in ['BND', 'BNDW', 'BNDX', 'IEF', 'TLT', 'SHY']: return '債券ETF'
        return '美股ETF與個股'
    return '其他'

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

@st.cache_data(ttl=900)
def get_stock_data(sym):
    """抓取股票歷史資料並計算技術指標 (包含台美股均線分流計算)"""
    is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
    for _ in range(3):
        try:
            time.sleep(0.3)
            df = yf.download(sym, period="3y", progress=False)
            if not df.empty and len(df) >= 252:
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                df.index = df.index.tz_localize(None)
                df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
                
                # 均線分流計算
                df['MA10'] = df['Close'].rolling(10).mean()
                df['MA20'] = df['Close'].rolling(20).mean()
                
                if is_tw:
                    df['季線'] = df['Close'].rolling(60).mean()
                    df['半年線'] = df['Close'].rolling(120).mean()
                    df['年線'] = df['Close'].rolling(240).mean()
                else:
                    df['季線'] = df['Close'].rolling(50).mean()
                    df['半年線'] = df['Close'].rolling(100).mean()
                    df['年線'] = df['Close'].rolling(200).mean()
                
                # KD 計算
                low_min = df['Low'].rolling(9).min()
                high_max = df['High'].rolling(9).max()
                rsv = (df['Close'] - low_min) / (high_max - low_min) * 100
                df['K_d'] = rsv.ewm(com=2, adjust=False).mean()
                df['D_d'] = df['K_d'].ewm(com=2, adjust=False).mean()
                
                # MACD 計算
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
def process_technical_analysis(sym, name):
    try:
        df = get_stock_data(sym)
        if df is None: return None
        is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
        market = '台股' if is_tw else '美股'
        
        # 週線資料轉置與指標計算
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        df_w['K_w'] = ((df_w['Close'] - df_w['Low'].rolling(9).min()) / (df_w['High'].rolling(9).max() - df_w['Low'].rolling(9).min()) * 100).ewm(com=2, adjust=False).mean()
        df_w['D_w'] = df_w['K_w'].ewm(com=2, adjust=False).mean()
        
        df_w['EMA12'] = df_w['Close'].ewm(span=12, adjust=False).mean()
        df_w['EMA26'] = df_w['Close'].ewm(span=26, adjust=False).mean()
        df_w['MACD'] = df_w['EMA12'] - df_w['EMA26']
        df_w['MACD_Signal'] = df_w['MACD'].ewm(span=9, adjust=False).mean()
        
        # 讀取最新指標值
        last_p = float(df['Close'].iloc[-1])
        ma20 = float(df['MA20'].iloc[-1]) if pd.notna(df['MA20'].iloc[-1]) else 0
        ma_season = float(df['季線'].iloc[-1]) if pd.notna(df['季線'].iloc[-1]) else 0
        ma_half = float(df['半年線'].iloc[-1]) if pd.notna(df['半年線'].iloc[-1]) else 0
        ma_year = float(df['年線'].iloc[-1]) if pd.notna(df['年線'].iloc[-1]) else 0
        high_52w = df['High'].tail(252).max()
        
        k_d, d_d = float(df['K_d'].iloc[-1]), float(df['D_d'].iloc[-1])
        pk_d, pd_d = float(df['K_d'].iloc[-2]), float(df['D_d'].iloc[-2])
        k_w, d_w = float(df_w['K_w'].iloc[-1]), float(df_w['D_w'].iloc[-1])
        pk_w, pd_w = float(df_w['K_w'].iloc[-2]), float(df_w['D_w'].iloc[-2])
        
        kd_d_status = "🟢 金叉轉強" if (k_d > d_d and pk_d <= pd_d) else ("🔴 死亡交叉" if (k_d < d_d and pk_d >= pd_d) else "趨勢延續")
        kd_w_status = "🟢 金叉轉強" if (k_w > d_w and pk_w <= pd_w) else ("🔴 死亡交叉" if (k_w < d_w and pk_w >= pd_w) else "趨勢延續")

        macd_d, macds_d = float(df['MACD'].iloc[-1]), float(df['MACD_Signal'].iloc[-1])
        pmacd_d, pmacds_d = float(df['MACD'].iloc[-2]), float(df['MACD_Signal'].iloc[-2])
        macd_w, macds_w = float(df_w['MACD'].iloc[-1]), float(df_w['MACD_Signal'].iloc[-1])
        pmacd_w, pmacds_w = float(df_w['MACD'].iloc[-2]), float(df_w['MACD_Signal'].iloc[-2])
        
        macd_d_status = "🟢 金叉" if (macd_d > macds_d and pmacd_d <= pmacds_d) else ("🔴 死叉" if (macd_d < macds_d and pmacd_d >= pmacds_d) else "趨勢延續")
        macd_w_status = "🟢 金叉" if (macd_w > macds_w and pmacd_w <= pmacds_w) else ("🔴 死叉" if (macd_w < macds_w and pmacd_w >= pmacds_w) else "趨勢延續")
        
        # 警示判斷
        alerts = []
        if last_p < ma20: alerts.append("跌破MA20")
        if high_52w > 0 and (high_52w - last_p) / high_52w >= 0.10:
            drop_pct = ((high_52w - last_p) / high_52w) * 100
            alerts.append(f"回落{drop_pct:.1f}%")
            
        if (k_d > d_d and pk_d <= pd_d) and k_d < 30: alerts.append("日KD低檔金叉")
        if (k_d < d_d and pk_d >= pd_d) and k_d > 70: alerts.append("日KD高檔死叉")
        if (k_w > d_w and pk_w <= pd_w) and k_w < 30: alerts.append("週KD低檔金叉")
        if (k_w < d_w and pk_w >= pd_w) and k_w > 70: alerts.append("週KD高檔死叉")
        
        if (macd_d > macds_d and pmacd_d <= pmacds_d) and macd_d < 0: alerts.append("日MACD零下金叉")
        if (macd_d < macds_d and pmacd_d >= pmacds_d) and macd_d > 0: alerts.append("日MACD零上死叉")
            
        alert_str = "⚠️ " + " / ".join(alerts) if alerts else "✅ 正常"

        pe_str = "無"
        try:
            pe_val = yf.Ticker(sym).info.get('trailingPE')
            if pd.notna(pe_val): pe_str = f"{pe_val:.1f}"
        except: pass

        return {
            "市場": market, "標的": f"{name} ({sym})", 
            "狀態警示": alert_str, "收盤價": last_p, "近一年高點": high_52w,
            "MA20": ma20, "季線": ma_season, "半年線": ma_half, "年線": ma_year,
            "日KD": f"K:{k_d:.1f}/D:{d_d:.1f} ({kd_d_status})",
            "週KD": f"K:{k_w:.1f}/D:{d_w:.1f} ({kd_w_status})",
            "日MACD": f"DIF:{macd_d:.2f} ({macd_d_status})",
            "週MACD": f"DIF:{macd_w:.2f} ({macd_w_status})",
            "P/E": pe_str
        }
    except Exception as e:
        return None

# ==========================================
# 3. 網頁 UI 渲染
# ==========================================
st.title("📊 個人投資組合與技術分析儀表板")

# 加入強制更新按鈕與即時時間顯示
col_btn, col_time = st.columns([1, 4])
with col_btn:
    if st.button("🔄 強制刷新報價"):
        st.cache_data.clear()
        st.rerun()
with col_time:
    st.caption(f"數據最後更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

tab1, tab2 = st.tabs(["💰 投資組合總覽", "📈 技術分析掃描"])

with tab1:
    with st.spinner("正在同步即時報價資料..."):
        usdtwd = get_usdtwd()
        total_market_value, total_dividends_2026 = 0, 0
        asset_allocation = {}
        individual_holdings = [] 

        # 處理台股加總 (Shares + 出借)
        for item in PORTFOLIO_TW:
            if pd.notna(item.get('Ticker')):
                ticker_str = str(item['Ticker']).strip()
                if not ticker_str: continue
                
                ticker = get_yf_ticker_tw(ticker_str)
                asset_type = classify_asset(ticker_str, 'TW')
                price, div = get_basic_data(ticker)
                
                # 安全讀取並加總
                shares_own = safe_float(item.get('Shares'))
                shares_lent = safe_float(item.get('出借'))
                total_shares = shares_own + shares_lent
                
                if price > 0 and total_shares > 0:
                    val = price * total_shares
                    div_tot = div * total_shares
                    total_market_value += val
                    asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val
                    total_dividends_2026 += div_tot
                    individual_holdings.append({'標的': ticker_str, '總市值': val, '股息': div_tot, '類別': '台股'})

        # 處理美股加總 (Shares + 複委託)
        for item in PORTFOLIO_US:
            if pd.notna(item.get('Ticker')):
                ticker_str = str(item['Ticker']).strip()
                if not ticker_str: continue
                
                asset_type = classify_asset(ticker_str, 'US')
                price, div = get_basic_data(ticker_str)
                
                # 安全讀取並加總
                shares_own = safe_float(item.get('Shares'))
                shares_sub = safe_float(item.get('複委託'))
                total_shares = shares_own + shares_sub
                
                if price > 0 and total_shares > 0:
                    val = price * total_shares * usdtwd
                    div_tot = div * total_shares * usdtwd
                    total_market_value += val
                    asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val
                    total_dividends_2026 += div_tot
                    individual_holdings.append({'標的': ticker_str, '總市值': val, '股息': div_tot, '類別': '美股'})

    col1, col2, col3 = st.columns(3)
    col1.metric("總市值 (TWD)", f"${total_market_value:,.0f}")
    col2.metric("2026 累計股息預估 (TWD)", f"${total_dividends_2026:,.0f}")
    col3.metric("目前匯率 (USD/TWD)", f"{usdtwd:.3f}")

    st.divider()
    
    col_chart, col_fx = st.columns([1, 1])
    with col_chart:
        st.subheader("資產配置佔比")
        if asset_allocation:
            df_allocation = pd.DataFrame(list(asset_allocation.items()), columns=['資產類別', '市值 (TWD)'])
            fig_pie = px.pie(df_allocation, values='市值 (TWD)', names='資產類別', hole=0.4)
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
    df_ind = pd.DataFrame(individual_holdings)
    if not df_ind.empty:
        df_ind_sorted = df_ind.sort_values(by='總市值', ascending=True)
        col_bar1, col_bar2 = st.columns(2)
        with col_bar1:
            fig_mv_bar = px.bar(df_ind_sorted, x='總市值', y='標的', orientation='h', title='各標的總市值 (TWD)', color='類別', text_auto='.2s')
            fig_mv_bar.update_layout(height=800, margin=dict(l=0, r=0, t=30, b=0), showlegend=False)
            st.plotly_chart(fig_mv_bar, use_container_width=True)
        with col_bar2:
            fig_div_bar = px.bar(df_ind_sorted, x='股息', y='標的', orientation='h', title='各標的預估股息 (TWD)', color='類別', text_auto='.2s')
            fig_div_bar.update_layout(height=800, margin=dict(l=0, r=0, t=30, b=0), showlegend=False)
            st.plotly_chart(fig_div_bar, use_container_width=True)

with tab2:
    st.subheader("🎯 觀察清單技術面掃描")
    st.markdown("自動警示跌破月線、高點回落，以及 **KD / MACD 黃金與死亡交叉**。（台股採 60/120/240日線；美股採 50/100/200日線）")
    
    with st.spinner("正在計算各標的技術指標..."):
        ta_results = []
        target_options = {} 
        for item in TW_CORE + US_WATCH:
            res = process_technical_analysis(item['symbol'], item['name'])
            if res: 
                ta_results.append(res)
                target_options[f"{item['name']} ({item['symbol']})"] = item['symbol']
            
        if ta_results:
            df_ta = pd.DataFrame(ta_results)
            st.dataframe(
                df_ta, 
                column_config={
                    "市場": st.column_config.TextColumn("市場", width="small"),
                    "標的": st.column_config.TextColumn("名稱 (代號)", width="medium"),
                    "狀態警示": st.column_config.TextColumn("🚨 狀態警示", width="large"),
                    "收盤價": st.column_config.NumberColumn("收盤價", format="%.2f"),
                    "MA20": st.column_config.NumberColumn("MA20", format="%.2f"),
                    "季線": st.column_config.NumberColumn("季線", format="%.2f"),
                    "半年線": st.column_config.NumberColumn("半年線", format="%.2f"),
                    "年線": st.column_config.NumberColumn("年線", format="%.2f"),
                    "日KD": st.column_config.TextColumn("日 KD 狀態", width="medium"),
                    "週KD": st.column_config.TextColumn("週 KD 狀態", width="medium"),
                    "日MACD": st.column_config.TextColumn("日 MACD", width="medium"),
                    "週MACD": st.column_config.TextColumn("週 MACD", width="medium"),
                },
                hide_index=True,
                use_container_width=True,
                height=450
            )

    st.divider()
    
    st.subheader("📈 個股/ETF 詳細技術線圖 (含 MA / KD / MACD)")
    selected_name = st.selectbox("請選擇要查看技術線圖的標的：", options=list(target_options.keys()))
    
    if selected_name:
        sym = target_options[selected_name]
        df_chart = get_stock_data(sym)
        if df_chart is not None:
            df_plot = df_chart.tail(150)
            is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
            
            # 定義線圖上的均線 Label 提示
            season_label = "MA60 (季線)" if is_tw else "MA50 (季線)"
            half_label = "MA120 (半年線)" if is_tw else "MA100 (半年線)"
            
            fig_tech = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                                     vertical_spacing=0.04, row_heights=[0.5, 0.25, 0.25],
                                     subplot_titles=(selected_name, "日 KD 指標", "MACD 指標 (12,26,9)"))
            
            # Row 1: K線與均線
            fig_tech.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name='K線', increasing_line_color='red', decreasing_line_color='green'), row=1, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MA10'], line=dict(color='yellow', width=1.5), name='MA10'), row=1, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MA20'], line=dict(color='blue', width=1.5), name='MA20'), row=1, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['季線'], line=dict(color='orange', width=1.5), name=season_label), row=1, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['半年線'], line=dict(color='magenta', width=1.5), name=half_label), row=1, col=1)
            
            # Row 2: KD
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['K_d'], line=dict(color='blue', width=1.5), name='K值 (日)'), row=2, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['D_d'], line=dict(color='orange', width=1.5), name='D值 (日)'), row=2, col=1)
            fig_tech.add_hline(y=80, line_dash="dash", line_color="red", row=2, col=1)
            fig_tech.add_hline(y=20, line_dash="dash", line_color="green", row=2, col=1)
            
            # Row 3: MACD
            macd_colors = ['red' if val >= 0 else 'green' for val in df_plot['MACD_Hist']]
            fig_tech.add_trace(go.Bar(x=df_plot.index, y=df_plot['MACD_Hist'], marker_color=macd_colors, name='OSC 柱狀圖'), row=3, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MACD'], line=dict(color='blue', width=1.5), name='MACD (DIF)'), row=3, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MACD_Signal'], line=dict(color='orange', width=1.5), name='Signal (DEA)'), row=3, col=1)
            
            fig_tech.update_layout(xaxis_rangeslider_visible=False, height=800, margin=dict(t=40, b=0, l=0, r=0))
            st.plotly_chart(fig_tech, use_container_width=True)

# ==========================================
# 4. 後台管理介面 (側邊欄雙分頁編輯)
# ==========================================
with st.sidebar:
    st.header("📝 持股雲端管理")
    st.markdown("直接在此編輯股數，並點擊下方按鈕同步至 Google Sheets。")
    
    st.subheader("🇹🇼 台股持股")
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

    st.subheader("🇺🇸 美股持股")
    if not df_us.empty:
        edited_df_us = st.data_editor(df_us, num_rows="dynamic", use_container_width=True, key="us_editor")
        if st.button("💾 儲存美股變更", use_container_width=True):
            with st.spinner("正在寫入美股資料..."):
                try:
                    conn.update(worksheet="US_Portfolio", data=edited_df_us)
                    st.success("✅ 美股更新成功！請重新整理網頁。")
                except Exception as e: st.error(f"寫入失敗：{e}")
    else: st.info("美股清單目前為空或未連線。")
