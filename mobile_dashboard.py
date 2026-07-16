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

st.set_page_config(page_title="行動隨身投資儀表板", layout="wide")

def safe_float(val):
    try:
        return float(val) if pd.notna(val) and str(val).strip() != '' else 0.0
    except:
        return 0.0

conn = st.connection("gsheets", type=GSheetsConnection)

try:
    df_tw = conn.read(worksheet="TW_Portfolio", ttl=0).dropna(subset=['Ticker'])
    if '名稱' not in df_tw.columns: df_tw['名稱'] = ''
    if 'Shares' not in df_tw.columns: df_tw['Shares'] = 0.0
    if '出借' not in df_tw.columns: df_tw['出借'] = 0.0
    if '類別' not in df_tw.columns: df_tw['類別'] = '台股'
    PORTFOLIO_TW = df_tw.to_dict('records')
except:
    PORTFOLIO_TW = []
    df_tw = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "出借", "類別"])

try:
    df_us = conn.read(worksheet="US_Portfolio", ttl=0).dropna(subset=['Ticker'])
    if '名稱' not in df_us.columns: df_us['名稱'] = ''
    if 'Shares' not in df_us.columns: df_us['Shares'] = 0.0
    if '複委託' not in df_us.columns: df_us['複委託'] = 0.0
    if '類別' not in df_us.columns: df_us['類別'] = '美股'
    PORTFOLIO_US = df_us.to_dict('records')
except:
    PORTFOLIO_US = []
    df_us = pd.DataFrame(columns=["Ticker", "名稱", "Shares", "複委託", "類別"])

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
                return price, div_2026
        except:
            time.sleep(0.5)
    return 0.0, 0.0

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
            rel_str_display = f"{'🟢' if rel_val >= 0 else '🔴'} {'' if rel_val < 0 else '+'}{rel_val:.1f}%"

            f_info = get_fundamental_info(sym)
            is_etf = 'ETF' in str(f_info.get('quoteType', '')).upper()
            roe = f"{f_info.get('returnOnEquity', 0)*100:.1f}%" if f_info.get('returnOnEquity') and not is_etf else "不適用"

            tot_div = float(hist['Dividends'][hist['Dividends'] > 0].sum()) if 'Dividends' in hist.columns else 0.0
            yield_1y = (tot_div / curr_p) * 100 if curr_p > 0 and tot_div > 0 else 0.0

            return {
                "市場": market, "代號": display_ticker, "收盤": curr_p,
                "季含息報酬": f"{ret_1q:.1f}%", "年含息報酬": f"{ret_1y:.1f}%",
                "對大盤": rel_str_display, "殖利率": f"{yield_1y:.1f}%", "ROE": roe
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

        # --- 嚴格狀態判定 (與電腦版、推播版一致) ---
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
        if last_p < ma20 and ma20 > 0: alerts.append("跌破MA20")
        
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

        # 獲取本益比
        f_info = get_fundamental_info(sym)
        pe_val = f_info.get('trailingPE') or f_info.get('forwardPE', 999)

        return {
            "代號": sym.split('.')[0], "🚨警示": alert_str, "價格": last_p, "52週位置": f"{pos_52w:.0f}%", "日KD": kd_display,
            "_raw_kd_d": kd_d_status, "_raw_kd_w": kd_w_status, "_raw_pe": pe_val, "_is_break_ma": is_break_ma,
            "_raw_macd_d": macd_d_status, "_raw_macd_w": macd_w_status, "_name": name, "_sym": sym
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

# 🔥 新增 "🎯亮點" Tab
tab1, tab_hl, tab2, tab3, tab4, tab5 = st.tabs(["💰資產", "🎯亮點", "📈技術", "🏆績效", "📖心得", "📝管理"])

with tab1:
    with st.spinner("載入報價中..."):
        usdtwd = get_usdtwd()
        total_market_value, total_dividends_2026 = 0, 0
        asset_allocation = {}

        for item in PORTFOLIO_TW:
            ticker_str = str(item.get('Ticker', '')).strip()
            if not ticker_str or ticker_str == 'nan': continue
            
            ticker = get_yf_ticker_tw(ticker_str)
            asset_type = str(item.get('類別', '台股未分類')).strip()
            
            price, div = get_basic_data(ticker)
            tot_shares = safe_float(item.get('Shares')) + safe_float(item.get('出借'))
            
            if price > 0 and tot_shares > 0:
                val = price * tot_shares
                total_market_value += val
                total_dividends_2026 += div * tot_shares
                asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val

        for item in PORTFOLIO_US:
            ticker_str = str(item.get('Ticker', '')).strip()
            if not ticker_str or ticker_str == 'nan': continue
            
            asset_type = str(item.get('類別', '美股未分類')).strip()
            
            price, div = get_basic_data(ticker_str)
            tot_shares = safe_float(item.get('Shares')) + safe_float(item.get('複委託'))
            
            if price > 0 and tot_shares > 0:
                val = price * tot_shares * usdtwd
                total_market_value += val
                total_dividends_2026 += div * tot_shares * usdtwd
                asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + val

        st.metric("總市值", f"${total_market_value:,.0f} TWD")
        st.metric("預估股息", f"${total_dividends_2026:,.0f} TWD")
        
        if asset_allocation:
            df_allocation = pd.DataFrame(list(asset_allocation.items()), columns=['類別', '市值'])
            fig_pie = px.pie(df_allocation, values='市值', names='類別', hole=0.4)
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            fig_pie.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
            st.plotly_chart(fig_pie)

# -----------------
# 🎯 盤後技術亮點與警示摘要 (手機優化版)
# -----------------
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
                
                # 亮點分析邏輯
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

                tags = []
                if w_macd_gold: tags.append("週MACD零下金叉")
                if w_kd_gold: tags.append("週KD低檔金叉")
                if d_macd_gold: tags.append("日MACD零下金叉")
                if d_kd_gold: tags.append("日KD低檔金叉")
                if w_macd_death: tags.append("週MACD零上死叉")
                if w_kd_death: tags.append("週KD高檔死叉")
                if d_macd_death: tags.append("日MACD零上死叉")
                if d_kd_death: tags.append("日KD高檔死叉")
                if is_break: tags.append("跌破季線")

                bull_score = (w_macd_gold * 4) + (w_kd_gold * 3) + (d_macd_gold * 2) + (d_kd_gold * 1)
                bear_score = (w_macd_death * 4) + (w_kd_death * 3) + (d_macd_death * 2) + (d_kd_death * 1) + (is_break * 1)
                
                item_data = {'name': name_disp, 'pe': pe_val, 'pe_str': pe_str, 'tags': tags, 'bull_score': bull_score, 'bear_score': bear_score, 'price': res['價格']}
                
                # 互斥分類
                if bear_score >= 3: 
                    bearish_alerts.append(item_data)
                elif bull_score >= 3: 
                    bullish_strong.append(item_data)
                elif bear_score > 0: 
                    bearish_alerts.append(item_data)
                elif bull_score > 0: 
                    bullish_daily.append(item_data)

        # 排序：技術分數(降冪)優先，本益比(PE)(升冪)其次，取 Top 10
        bullish_strong = sorted(bullish_strong, key=lambda x: (-x['bull_score'], x['pe']))[:10]
        bullish_daily = sorted(bullish_daily, key=lambda x: (-x['bull_score'], x['pe']))[:10]
        bearish_alerts = sorted(bearish_alerts, key=lambda x: (-x['bear_score'], x['pe']))[:10]
        
    def format_mobile_items(items):
        if not items: return "> 目前無符合條件標的"
        res_str = ""
        for x in items:
            tags_str = ", ".join(x['tags'])
            res_str += f"- **{x['name']}** (PE:{x['pe_str']})\n  - `[{tags_str}]`\n"
        return res_str

    st.markdown("### 📊 盤後技術摘要 (Top 10)")
    st.caption("依技術強度優先，同級別低本益比優先顯示。")
    
    # 使用 container 包裝，在手機上以單欄垂直堆疊顯示，提升閱讀體驗
    with st.container():
        st.success(f"🔥 **週線強勢區 (波段)**\n\n{format_mobile_items(bullish_strong)}")
        st.info(f"📈 **日線強勢區 (短線)**\n\n{format_mobile_items(bullish_daily)}")
        st.error(f"⚠️ **空方風險區 (破線/死叉)**\n\n{format_mobile_items(bearish_alerts)}")

with tab2:
    with st.expander("💡 狀態警示說明", expanded=False):
        st.markdown("""
        * **🚀 買進**：出現 **週 KD** 或 **週 MACD 黃金交叉**，屬中長線翻多。
        * **🛑 賣出**：出現 **週 KD** 或 **週 MACD 死亡交叉**，或自 **近一年高點回落達 15%**。
        * **⚠️ 減碼**：自 **20 日高點回落達 10%**，短線轉弱。
        * **➖ 持平**：無觸發上述轉折訊號。
        """)
        
    if ta_results: # 使用剛才 tab_hl 已經算好的快取資料
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
            st.dataframe(df_perf[["代號", "季含息報酬", "年含息報酬", "對大盤", "殖利率", "ROE"]], width="stretch", hide_index=True, height=450)

with tab4:
    st.markdown("### 📖 每日看盤心得")
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
        st.info("請於試算表新增 `Trading_Journal` 工作表以啟用此功能。")
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
