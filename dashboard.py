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
# 2. 核心抓取與計算邏輯
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
        if df.empty or len(df) < 252: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
        market = '台股' if sym.endswith('.TW') or sym.endswith('.TWO') else '美股'
        
        # 均線計算 (MA10, MA20, MA60, MA120, MA240)
        df['MA10'] = df['Close'].rolling(10).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        df['MA120'] = df['Close'].rolling(120).mean()
        df['MA240'] = df['Close'].rolling(240).mean()
        
        # 近一年(252交易日)最高點
        high_52w = df['High'].tail(252).max()
        
        # KD 計算 (原生 Pandas)
        df['K_d'] = ((df['Close'] - df['Low'].rolling(9).min()) / (df['High'].rolling(9).max() - df['Low'].rolling(9).min()) * 100).ewm(com=2, adjust=False).mean()
        df['D_d'] = df['K_d'].ewm(com=2, adjust=False).mean()
        
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        df_w['K_w'] = ((df_w['Close'] - df_w['Low'].rolling(9).min()) / (df_w['High'].rolling(9).max() - df_w['Low'].rolling(9).min()) * 100).ewm(com=2, adjust=False).mean()
        df_w['D_w'] = df_w['K_w'].ewm(com=2, adjust=False).mean()
        
        last_p = float(df['Close'].iloc[-1])
        ma10 = float(df['MA10'].iloc[-1]) if pd.notna(df['MA10'].iloc[-1]) else 0
        ma20 = float(df['MA20'].iloc[-1]) if pd.notna(df['MA20'].iloc[-1]) else 0
        ma60 = float(df['MA60'].iloc[-1]) if pd.notna(df['MA60'].iloc[-1]) else 0
        ma120 = float(df['MA120'].iloc[-1]) if pd.notna(df['MA120'].iloc[-1]) else 0
        ma240 = float(df['MA240'].iloc[-1]) if pd.notna(df['MA240'].iloc[-1]) else 0
        
        # KD狀態
        k_d, d_d = float(df['K_d'].iloc[-1]), float(df['D_d'].iloc[-1])
        pk_d, pd_d = float(df['K_d'].iloc[-2]), float(df['D_d'].iloc[-2])
        k_w, d_w = float(df_w['K_w'].iloc[-1]), float(df_w['D_w'].iloc[-1])
        pk_w, pd_w = float(df_w['K_w'].iloc[-2]), float(df_w['D_w'].iloc[-2])
        kd_d_status = "🟢 金叉轉強" if (k_d > d_d and pk_d <= pd_d) else ("🔴 死亡交叉" if (k_d < d_d and pk_d >= pd_d) else "趨勢延續")
        kd_w_status = "🟢 金叉轉強" if (k_w > d_w and pk_w <= pd_w) else ("🔴 死亡交叉" if (k_w < d_w and pk_w >= pd_w) else "趨勢延續")
        
        # 狀態警示 (跌破MA20 或 回落10%)
        alerts = []
        if last_p < ma20:
            alerts.append("跌破MA20")
        if high_52w > 0 and (high_52w - last_p) / high_52w >= 0.10:
            drop_pct = ((high_52w - last_p) / high_52w) * 100
            alerts.append(f"回落{drop_pct:.1f}%")
            
        alert_str = "⚠️ " + " / ".join(alerts) if alerts else "✅ 正常"

        # P/E 取得
        pe_str = "無"
        try:
            pe_val = yf.Ticker(sym).info.get('trailingPE')
            if pd.notna(pe_val): pe_str = f"{pe_val:.1f}"
        except: pass

        return {
            "市場": market, "標的": f"{name} ({sym})", 
            "狀態警示": alert_str, "收盤價": last_p, "近一年高點": high_52w,
            "MA10": ma10, "MA20": ma20, "MA60": ma60, "MA120": ma120, "MA240": ma240,
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

tab1, tab2 = st.tabs(["💰 投資組合總覽", "📈 技術分析掃描"])

# ----------------- 分頁 1：投資組合總覽 -----------------
with tab1:
    with st.spinner("正在同步即時報價資料..."):
        usdtwd = get_usdtwd()
        total_market_value, total_dividends_2026 = 0, 0
        asset_allocation = {}
        individual_holdings = [] # 儲存單一個股/ETF資料

        # 處理台股
        for item in PORTFOLIO_TW:
            ticker = get_yf_ticker_tw(item['Ticker'])
            asset_type = classify_asset(item['Ticker'], 'TW')
            price, div = get_basic_data(ticker)
            if price > 0:
                val = price * item['Shares']
                div_tot = div * item['Shares']
                total_market_value += val
                asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val
                total_dividends_2026 += div_tot
                individual_holdings.append({'標的': item['Ticker'], '市值': val, '股息': div_tot, '類別': '台股'})

        # 處理美股
        for item in PORTFOLIO_US:
            asset_type = classify_asset(item['Ticker'], 'US')
            price, div = get_basic_data(item['Ticker'])
            if price > 0:
                val = price * item['Shares'] * usdtwd
                div_tot = div * item['Shares'] * usdtwd
                total_market_value += val
                asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val
                total_dividends_2026 += div_tot
                individual_holdings.append({'標的': item['Ticker'], '市值': val, '股息': div_tot, '類別': '美股'})

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
        fig_pie = px.pie(df_allocation, values='市值 (TWD)', names='資產類別', hole=0.4)
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        fig_pie.update_layout(margin=dict(t=0, b=0, l=0, r=0), showlegend=False)
        st.plotly_chart(fig_pie, use_container_width=True)
        
    with col_fx:
        st.subheader("USD/TWD 匯率走勢 (1年)")
        fx_data = get_fx_data()
        fig_fx = go.Figure()
        fig_fx.add_trace(go.Scatter(x=fx_data.index, y=fx_data['Close'], mode='lines', name='USD/TWD', line=dict(color='white' if st.get_option('theme.base') == 'dark' else 'black', width=2)))
        fig_fx.add_trace(go.Scatter(x=fx_data.index, y=fx_data['MA20'], mode='lines', name='MA20 (月線)', line=dict(color='#3498db', dash='dash')))
        fig_fx.add_trace(go.Scatter(x=fx_data.index, y=fx_data['MA60'], mode='lines', name='MA60 (季線)', line=dict(color='#e74c3c', dash='dot')))
        fig_fx.update_layout(margin=dict(t=10, b=0, l=0, r=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_fx, use_container_width=True)

    st.divider()

    # 各別標的市值與股息長條圖
    st.subheader("📊 各標的市值與股息分佈")
    df_ind = pd.DataFrame(individual_holdings)
    if not df_ind.empty:
        # 依市值排序，讓圖表呈現階梯狀
        df_ind_sorted = df_ind.sort_values(by='市值', ascending=True)
        
        col_bar1, col_bar2 = st.columns(2)
        with col_bar1:
            fig_mv_bar = px.bar(df_ind_sorted, x='市值', y='標的', orientation='h', 
                                title='各標的市值 (TWD)', color='類別', text_auto='.2s')
            fig_mv_bar.update_layout(height=800, margin=dict(l=0, r=0, t=30, b=0), showlegend=False)
            st.plotly_chart(fig_mv_bar, use_container_width=True)
            
        with col_bar2:
            fig_div_bar = px.bar(df_ind_sorted, x='股息', y='標的', orientation='h', 
                                 title='各標的預估股息 (TWD)', color='類別', text_auto='.2s')
            fig_div_bar.update_layout(height=800, margin=dict(l=0, r=0, t=30, b=0), showlegend=False)
            st.plotly_chart(fig_div_bar, use_container_width=True)

# ----------------- 分頁 2：技術分析掃描 -----------------
with tab2:
    st.subheader("🎯 觀察清單技術面掃描")
    st.markdown("包含各天期均線 (MA10~MA240)，並自動警示**跌破月線 (MA20)** 或 **自近一年高點回落大於 10%** 的標的。")
    
    with st.spinner("正在計算各標的技術指標... (約需 10-15 秒)"):
        ta_results = []
        for item in TW_CORE + US_WATCH:
            res = process_technical_analysis(item['symbol'], item['name'])
            if res: ta_results.append(res)
            
        if ta_results:
            df_ta = pd.DataFrame(ta_results)
            st.dataframe(
                df_ta, 
                column_config={
                    "市場": st.column_config.TextColumn("市場", width="small"),
                    "標的": st.column_config.TextColumn("名稱 (代號)", width="medium"),
                    "狀態警示": st.column_config.TextColumn("🚨 狀態警示", width="medium"),
                    "收盤價": st.column_config.NumberColumn("收盤價", format="%.2f"),
                    "近一年高點": st.column_config.NumberColumn("1年高點", format="%.2f"),
                    "MA10": st.column_config.NumberColumn("MA10", format="%.2f"),
                    "MA20": st.column_config.NumberColumn("MA20", format="%.2f"),
                    "MA60": st.column_config.NumberColumn("MA60", format="%.2f"),
                    "MA120": st.column_config.NumberColumn("MA120", format="%.2f"),
                    "MA240": st.column_config.NumberColumn("MA240", format="%.2f"),
                    "日KD": st.column_config.TextColumn("日 KD 狀態", width="large"),
                    "週KD": st.column_config.TextColumn("週 KD 狀態", width="large"),
                    "P/E": st.column_config.TextColumn("本益比", width="small")
                },
                hide_index=True,
                use_container_width=True,
                height=700
            )
        else:
            st.warning("目前無法取得技術分析資料，請稍後再試。")
