import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import re
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

# 設定網頁標題與排版 (寬螢幕模式)
st.set_page_config(page_title="個人投資組合與技術分析儀表板", layout="wide")

# ==========================================
# 1. 資料庫與清單設定
# ==========================================
PORTFOLIO_TW = [
    {'Ticker': '0050', 'Shares': 4332}, {'Ticker': '0056', 'Shares': 8000},
    {'Ticker': '006208', 'Shares': 6000}, {'Ticker': '00646', 'Shares': 149 + 11000},
    {'Ticker': '00662', 'Shares': 600 + 2000}, {'Ticker': '00679B', 'Shares': 10000},
    {'Ticker': '00687B', 'Shares': 3438}, {'Ticker': '00692', 'Shares': 2000 + 15000},
    {'Ticker': '00697B', 'Shares': 2262}, {'Ticker': '00712', 'Shares': 2918 + 7000},
    {'Ticker': '00713', 'Shares': 1853 + 13000}, {'Ticker': '00719B', 'Shares': 7042},
    {'Ticker': '00757', 'Shares': 324 + 3000}, {'Ticker': '00772B', 'Shares': 100 + 18000},
    {'Ticker': '00830', 'Shares': 695 + 7000}, {'Ticker': '00878', 'Shares': 4108 + 46000},
    {'Ticker': '00919', 'Shares': 4116+29000}, {'Ticker': '00922', 'Shares': 22000+0},
    {'Ticker': '00923', 'Shares': 23000+5000}, {'Ticker': '00937B', 'Shares': 3665 + 19000},
    {'Ticker': '009800', 'Shares': 14000 + 1000}, {'Ticker': '009812', 'Shares': 6273 + 18000},
    {'Ticker': '009813', 'Shares': 2710 + 39000}, {'Ticker': '009815', 'Shares': 0+15000},
    {'Ticker': '009816', 'Shares': 1000}, {'Ticker': '00981A', 'Shares': 7000+2000},
    {'Ticker': '00988A', 'Shares': 2417 + 9000}, {'Ticker': '1216', 'Shares': 2000},
    {'Ticker': '2317', 'Shares': 154}, {'Ticker': '2330', 'Shares': 38},
    {'Ticker': '2412', 'Shares': 9000}, {'Ticker': '2454', 'Shares': 1},
]

PORTFOLIO_US = [
    {'Ticker': 'AOR', 'Shares': 0.19}, {'Ticker': 'BNDW', 'Shares': 37.6},
    {'Ticker': 'META', 'Shares': 2.0}, {'Ticker': 'NVDA', 'Shares': 1.0},
    {'Ticker': 'QQQ', 'Shares': 17.8 + 2.6}, {'Ticker': 'VNQ', 'Shares': 8.0 + 27.62 + 19.39},
    {'Ticker': 'VOO', 'Shares': 10.0 + 5.31}, {'Ticker': 'VT', 'Shares': 202.49 + 86.19 + 76.78 + 105.63},
    {'Ticker': 'VWRA.L', 'Shares': 194.0}, {'Ticker': 'CSPX.L', 'Shares': 9.0},
    {'Ticker': 'VXUS', 'Shares': 24.0},
]

# 技術分析觀察清單
TW_CORE = [
    {'symbol': '2330.TW', 'name': '台積電'}, {'symbol': '2317.TW', 'name': '鴻海'},
    {'symbol': '2454.TW', 'name': '聯發科'}, {'symbol': '2308.TW', 'name': '台達電'},
    {'symbol': '3008.TW', 'name': '大立光'}, {'symbol': '0050.TW', 'name': '元大台灣50'},
    {'symbol': '00878.TW', 'name': '國泰永續高股息'}, {'symbol': '00713.TW', 'name': '元大台灣高息低波'},
    {'symbol': '00919.TW', 'name': '群益台灣精選高息'}, {'symbol': '009812.TW', 'name': '野村日本東證ETF'},
    {'symbol': '00922.TW', 'name': '國泰台灣領袖50'}, {'symbol': '00923.TW', 'name': '群益台灣ESG低碳'},
    {'symbol': '00830.TW', 'name': '國泰費城半導體'}, {'symbol': '00981A.TW', 'name': '主動統一台股增長'},
    {'symbol': '00988A.TW', 'name': '主動統一全球創新'}, {'symbol': '009815.TW', 'name': '大華美國MAG7+'}
]

US_WATCH = [
    {'symbol': 'NVDA', 'name': '輝達 Nvidia'}, {'symbol': 'MSFT', 'name': '微軟 Microsoft'},
    {'symbol': 'GOOGL', 'name': '谷歌 Google'}, {'symbol': 'VOO', 'name': '標普500 VOO'},
    {'symbol': 'QQQ', 'name': '納斯達克 QQQ'}
]

# ==========================================
# 2. 核心抓取與計算邏輯 (加入快取避免重複讀取)
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

@st.cache_data(ttl=3600)
def get_basic_data(ticker):
    try:
        hist = yf.Ticker(ticker).history(period="1y")
        price = float(hist['Close'].dropna().iloc[-1]) if not hist.empty else 0.0
        div_2026 = float(hist['Dividends'][hist.index.year == 2026].sum()) if not hist.empty and 'Dividends' in hist.columns else 0.0
        return price, div_2026
    except:
        return 0.0, 0.0

@st.cache_data(ttl=3600)
def get_usdtwd():
    try:
        hist = yf.Ticker("TWD=X").history(period="5d")
        return float(hist['Close'].dropna().iloc[-1]) if not hist.empty else 32.5
    except: return 32.5

@st.cache_data(ttl=3600)
def get_fx_data():
    data = yf.Ticker("TWD=X").history(period="1y").dropna(subset=['Close'])
    data['MA20'] = data['Close'].rolling(window=20).mean()
    data['MA60'] = data['Close'].rolling(window=60).mean()
    return data

@st.cache_data(ttl=3600)
def process_technical_analysis(sym, name):
    try:
        df = yf.download(sym, period="3y", progress=False)
        if df.empty or len(df) < 60: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
        market = '台股' if sym.endswith('.TW') or sym.endswith('.TWO') else '美股'
        
        # 均線計算
        df['MA_S1'] = df['Close'].rolling(20).mean()
        df['MA_S2'] = df['Close'].rolling(60 if market == '台股' else 50).mean()
        
        # KD 計算 (原生 Pandas 寫法，免套件)
        df['K_d'] = ((df['Close'] - df['Low'].rolling(9).min()) / (df['High'].rolling(9).max() - df['Low'].rolling(9).min()) * 100).ewm(com=2, adjust=False).mean()
        df['D_d'] = df['K_d'].ewm(com=2, adjust=False).mean()
        
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        df_w['K_w'] = ((df_w['Close'] - df_w['Low'].rolling(9).min()) / (df_w['High'].rolling(9).max() - df_w['Low'].rolling(9).min()) * 100).ewm(com=2, adjust=False).mean()
        df_w['D_w'] = df_w['K_w'].ewm(com=2, adjust=False).mean()
        if len(df_w) < 2: return None

        last_p = float(df['Close'].iloc[-1])
        ma_s1, ma_s2 = float(df['MA_S1'].iloc[-1]), float(df['MA_S2'].iloc[-1])
        k_d, d_d = float(df['K_d'].iloc[-1]), float(df['D_d'].iloc[-1])
        pk_d, pd_d = float(df['K_d'].iloc[-2]), float(df['D_d'].iloc[-2])
        k_w, d_w = float(df_w['K_w'].iloc[-1]), float(df_w['D_w'].iloc[-1])
        pk_w, pd_w = float(df_w['K_w'].iloc[-2]), float(df_w['D_w'].iloc[-2])

        # 狀態判定
        kd_d_status = "🟢 金叉轉強" if (k_d > d_d and pk_d <= pd_d) else ("🔴 死亡交叉" if (k_d < d_d and pk_d >= pd_d) else "趨勢延續")
        kd_w_status = "🟢 金叉轉強" if (k_w > d_w and pk_w <= pd_w) else ("🔴 死亡交叉" if (k_w < d_w and pk_w >= pd_w) else "趨勢延續")
        
        if last_p > ma_s1 and last_p > ma_s2: ma_status = "🟢 站穩月季線 (強勢)"
        elif last_p < ma_s1 and last_p < ma_s2: ma_status = "🔴 月季線之下 (偏空)"
        elif last_p > ma_s2 and last_p < ma_s1: ma_status = "🟡 守季線/受月線壓"
        else: ma_status = "🔵 站月線/臨季線壓"
        
        # P/E 取得
        pe_str = "無"
        try:
            pe_val = yf.Ticker(sym).info.get('trailingPE')
            if pd.notna(pe_val): pe_str = f"{pe_val:.1f}"
        except: pass

        return {
            "市場": market, "標的": f"{name} ({sym})", "收盤價": f"{last_p:.2f}",
            "均線狀態": ma_status, 
            "日KD": f"K:{k_d:.1f}/D:{d_d:.1f} ({kd_d_status})",
            "週KD": f"K:{k_w:.1f}/D:{d_w:.1f} ({kd_w_status})",
            "P/E": pe_str
        }
    except Exception as e:
        return None

# ==========================================
# 3. 網頁 UI 渲染
# ==========================================
st.title("📊 個人投資組合與技術分析儀表板")
st.caption(f"數據最後更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# 建立雙分頁
tab1, tab2 = st.tabs(["💰 投資組合總覽", "📈 技術分析掃描"])

# ----------------- 分頁 1：投資組合總覽 -----------------
with tab1:
    with st.spinner("正在同步即時報價資料..."):
        usdtwd = get_usdtwd()
        total_market_value, total_dividends_2026 = 0, 0
        asset_allocation = {}

        for item in PORTFOLIO_TW:
            ticker = get_yf_ticker_tw(item['Ticker'])
            asset_type = classify_asset(item['Ticker'], 'TW')
            price, div = get_basic_data(ticker)
            if price > 0:
                val = price * item['Shares']
                total_market_value += val
                asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val
                total_dividends_2026 += div * item['Shares']

        for item in PORTFOLIO_US:
            asset_type = classify_asset(item['Ticker'], 'US')
            price, div = get_basic_data(item['Ticker'])
            if price > 0:
                val = price * item['Shares'] * usdtwd
                total_market_value += val
                asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val
                total_dividends_2026 += div * item['Shares'] * usdtwd

    # 頂端指標
    col1, col2, col3 = st.columns(3)
    col1.metric("總市值 (TWD)", f"${total_market_value:,.0f}")
    col2.metric("2026 累計股息預估 (TWD)", f"${total_dividends_2026:,.0f}")
    col3.metric("目前匯率 (USD/TWD)", f"{usdtwd:.3f}")

    st.divider()
    
    # 互動式 Plotly 圓餅圖與匯率圖
    col_chart, col_fx = st.columns([1, 1])
    
    with col_chart:
        st.subheader("資產配置佔比")
        df_allocation = pd.DataFrame(list(asset_allocation.items()), columns=['資產類別', '市值 (TWD)'])
        # 使用 Plotly 繪製圓餅圖 (完美支援中文與滑鼠互動)
        fig_pie = px.pie(df_allocation, values='市值 (TWD)', names='資產類別', hole=0.4)
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        fig_pie.update_layout(margin=dict(t=0, b=0, l=0, r=0), showlegend=False)
        st.plotly_chart(fig_pie, use_container_width=True)
        
    with col_fx:
        st.subheader("USD/TWD 匯率走勢 (1年)")
        fx_data = get_fx_data()
        # 使用 Plotly 繪製折線圖
        fig_fx = go.Figure()
        fig_fx.add_trace(go.Scatter(x=fx_data.index, y=fx_data['Close'], mode='lines', name='USD/TWD', line=dict(color='white' if st.get_option('theme.base') == 'dark' else 'black', width=2)))
        fig_fx.add_trace(go.Scatter(x=fx_data.index, y=fx_data['MA20'], mode='lines', name='MA20 (月線)', line=dict(color='#3498db', dash='dash')))
        fig_fx.add_trace(go.Scatter(x=fx_data.index, y=fx_data['MA60'], mode='lines', name='MA60 (季線)', line=dict(color='#e74c3c', dash='dot')))
        fig_fx.update_layout(margin=dict(t=10, b=0, l=0, r=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_fx, use_container_width=True)

# ----------------- 分頁 2：技術分析掃描 -----------------
with tab2:
    st.subheader("🎯 觀察清單技術面掃描")
    st.markdown("針對台美股核心觀察清單進行**均線與 KD 指標**的自動化判定。")
    
    with st.spinner("正在計算各標的技術指標... (約需 10-15 秒)"):
        ta_results = []
        # 合併清單進行掃描
        for item in TW_CORE + US_WATCH:
            res = process_technical_analysis(item['symbol'], item['name'])
            if res: ta_results.append(res)
            
        if ta_results:
            df_ta = pd.DataFrame(ta_results)
            # 將 DataFrame 顯示在網頁上
            st.dataframe(
                df_ta, 
                column_config={
                    "市場": st.column_config.TextColumn("市場", width="small"),
                    "標的": st.column_config.TextColumn("名稱 (代號)", width="medium"),
                    "收盤價": st.column_config.NumberColumn("最新收盤價"),
                    "均線狀態": st.column_config.TextColumn("均線位置", width="medium"),
                    "日KD": st.column_config.TextColumn("日 KD 狀態", width="large"),
                    "週KD": st.column_config.TextColumn("週 KD 狀態", width="large"),
                    "P/E": st.column_config.TextColumn("本益比", width="small")
                },
                hide_index=True,
                use_container_width=True,
                height=600 # 讓表格夠高不必一直捲動
            )
        else:
            st.warning("目前無法取得技術分析資料，請稍後再試。")
