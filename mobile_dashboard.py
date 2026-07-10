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
    if ticker.endswith('B') or ticker.endswith('C'): return f"{ticker}.TWO"
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
            'returnOnEquity': info.get('returnOnEquity')
        }
    except: return {}

@st.cache_data(ttl=600)
def get_stock_data(sym):
    try:
        df = yf.download(sym, period="3y", progress=False)
        if not df.empty and len(df) >= 2:
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df.index = df.index.tz_localize(None) if df.index.tz else df.index
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna(subset=['Close'])
            if 'Close' not in df.columns: return None
            
            df['MA10'] = df['Close'].rolling(10, min_periods=1).mean()
            df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
            
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
        hist = yf.Ticker(sym).history(period="1y")
        if not hist.empty:
            curr_p = float(hist['Close'].dropna().iloc[-1])
            valid_hist = hist['Close'].dropna()
            
            ret_1q = (((curr_p - valid_hist.iloc[-63]) / valid_hist.iloc[-63]) * 100) if len(valid_hist) > 63 else 0.0
            ret_1y = (((curr_p - valid_hist.iloc[0]) / valid_hist.iloc[0]) * 100) if len(valid_hist) > 0 else 0.0

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
                "季報酬": f"{ret_1q:.1f}%", "年報酬": f"{ret_1y:.1f}%",
                "對大盤": rel_str_display, "殖利率": f"{yield_1y:.1f}%", "ROE": roe
            }
    except: pass
    return None

@st.cache_data(ttl=600)
def process_technical_analysis(sym, name):
    try:
        df = get_stock_data(sym)
        if df is None or df.empty: return None
        
        has_enough_weekly = False
        k_w, d_w, macd_w, macds_w = 0.0, 0.0, 0.0, 0.0
        pk_w, pd_w, pmacd_w, pmacds_w = 0.0, 0.0, 0.0, 0.0
        
        try:
            agg_dict = {'Close': 'last'}
            if 'Open' in df.columns: agg_dict['Open'] = 'first'
            if 'High' in df.columns: agg_dict['High'] = 'max'
            if 'Low' in df.columns: agg_dict['Low'] = 'min'
            df_w = df.resample('W-FRI').agg(agg_dict).dropna(subset=['Close'])
            if len(df_w) >= 2:
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
        
        high_52w = df['High'].tail(252).max() if 'High' in df.columns else 0.0
        low_52w = df['Low'].tail(252).min() if 'Low' in df.columns else 0.0
        pos_52w = ((last_p - low_52w) / (high_52w - low_52w + 1e-9) * 100) if (high_52w - low_52w) > 0 else 50.0

        high_20d = df['High'].tail(20).max() if 'High' in df.columns else 0.0
        
        alerts = []
        if last_p < ma20 and ma20 > 0: alerts.append("跌破MA20")
        
        # 🚨 更新：近高點回落改為 15%
        if high_52w > 0 and (high_52w - last_p) / high_52w >= 0.15: alerts.append(f"近高點回落{((high_52w - last_p) / high_52w)*100:.1f}%")
        # 🚨 更新：20日高點回落改為 10%
        if high_20d > 0 and (high_20d - last_p) / high_20d >= 0.10: alerts.append(f"20日回落{((high_20d - last_p) / high_20d)*100:.1f}%")
            
        if has_enough_weekly:
            if k_w > d_w and pk_w <= pd_w and k_w > 0: alerts.append("週KD金叉")
            elif k_w < d_w and pk_w >= pd_w and d_w > 0: alerts.append("週KD死叉")
            
            if macd_w > macds_w and pmacd_w <= pmacds_w and (macd_w != 0 or macds_w != 0): alerts.append("週MACD金叉")
            elif macd_w < macds_w and pmacd_w >= pmacds_w and (macd_w != 0 or macds_w != 0): alerts.append("週MACD死叉")
            
        # 🌟 結合手機版的綜合買賣評級邏輯
        action = "➖ 持平"
        has_buy = any(x in a for a in alerts for x in ["週KD金叉", "週KD低檔金叉", "週MACD金叉", "週MACD零下金叉"])
        has_sell = any(x in a for a in alerts for x in ["週KD死叉", "週KD高檔死叉", "週MACD死叉", "週MACD零上死叉", "近高點回落"])
        has_reduce = any(x in a for a in alerts for x in ["20日回落"])
        
        if has_sell: action = "🛑 賣出"
        elif has_buy: action = "🚀 買進"
        elif has_reduce: action = "⚠️ 減碼"

        alert_str = f"[{action}] " + ("/".join(alerts) if alerts else "趨勢延續")
        kd_display = f"K:{float(df['K_d'].iloc[-1]):.0f}/D:{float(df['D_d'].iloc[-1]):.0f}" if 'K_d' in df.columns else "-"

        return {"代號": sym.split('.')[0], "🚨警示": alert_str, "價格": last_p, "52週位置": f"{pos_52w:.0f}%", "日KD": kd_display}
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

tab1, tab2, tab3, tab4 = st.tabs(["💰資產", "📈技術", "🏆績效", "📝管理"])

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
            st.plotly_chart(fig_pie, use_container_width=True)

with tab2:
    with st.expander("💡 狀態警示說明", expanded=False):
        st.markdown("""
        * **🚀 買進**：出現週 KD 或週 MACD 黃金交叉，屬中長線翻多。
        * **🛑 賣出**：出現週 KD 或週 MACD 死亡交叉，或近一年高點回落達 15%。
        * **⚠️ 減碼**：自 20 日高點回落達 10%，短線轉弱。
        * **➖ 持平**：無觸發上述轉折訊號。
        """)
        
    with st.spinner("分析指標中..."):
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
                target_options[f"{name}({sym.split('.')[0]})"] = sym
                
        if ta_results:
            df_ta = pd.DataFrame(ta_results)
            st.dataframe(df_ta[["代號", "🚨警示", "價格", "52週位置"]], hide_index=True, use_container_width=True, height=350)

    st.divider()
    selected_name = st.selectbox("查看詳細線圖：", options=list(target_options.keys()))
    if selected_name:
        sym = target_options[selected_name]
        df_chart = get_stock_data(sym)
        if df_chart is not None:
            df_plot = df_chart.tail(80) 
            fig_tech = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
            fig_tech.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name='K線', increasing_line_color='red', decreasing_line_color='green'), row=1, col=1)
            fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MA20'], line=dict(color='blue', width=1.5), name='MA20'), row=1, col=1)
            if 'K_d' in df_plot.columns:
                fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['K_d'], line=dict(color='yellow', width=1.2), name='K'), row=2, col=1)
                fig_tech.add_trace(go.Scatter(x=df_plot.index, y=df_plot['D_d'], line=dict(color='orange', width=1.2), name='D'), row=2, col=1)
            fig_tech.update_layout(xaxis_rangeslider_visible=False, height=400, margin=dict(t=20, b=10, l=10, r=10), showlegend=False)
            st.plotly_chart(fig_tech, use_container_width=True)

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
            st.dataframe(df_perf[["代號", "季報酬", "年報酬", "對大盤", "殖利率", "ROE"]], hide_index=True, use_container_width=True, height=450)

with tab4:
    st.markdown("### ✏️ 雲端隨身記帳")
    st.caption("更改後點擊下方按鈕即可同步至雲端 Sheets。")
    
    st.subheader("🇹🇼 台股名單")
    edited_tw = st.data_editor(df_tw, num_rows="dynamic", use_container_width=True, key="m_tw_editor")
    if st.button("💾 儲存台股變更", use_container_width=True):
        try:
            conn.update(worksheet="TW_Portfolio", data=edited_tw)
            st.success("更新成功！")
        except Exception as e: st.error(f"錯誤:{e}")
            
    st.divider()
    
    st.subheader("🇺🇸 美股名單")
    edited_us = st.data_editor(df_us, num_rows="dynamic", use_container_width=True, key="m_us_editor")
    if st.button("💾 儲存美股變更", use_container_width=True):
        try:
            conn.update(worksheet="US_Portfolio", data=edited_us)
            st.success("更新成功！")
        except Exception as e: st.error(f"錯誤:{e}")
