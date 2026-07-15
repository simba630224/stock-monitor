import streamlit as st
from streamlit_gsheets import GSheetsConnection
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.express as px
import warnings

warnings.filterwarnings('ignore')
st.set_page_config(page_title="個人投資組合與技術掃描儀表板", layout="wide")

# --- 1. 輔助運算函式 ---
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip().upper()
    if ticker.endswith(('.TW', '.TWO')): return ticker
    return f"{ticker}.TWO" if (ticker.endswith(('B', 'C')) or ticker == '009815') else f"{ticker}.TW"

def check_macd_gc(df):
    if len(df) < 35: return False
    macd = df['Close'].ewm(span=12, adjust=False).mean() - df['Close'].ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return (hist.iloc[-1] > 0) and (hist.iloc[-2] <= 0)

@st.cache_data(ttl=600)
def load_portfolio_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_tw = conn.read(worksheet="TW_Portfolio")
    df_us = conn.read(worksheet="US_Portfolio")
    return df_tw, df_us

# --- 2. 核心掃描與分流邏輯 ---
@st.cache_data(ttl=300)
def process_all_targets(df_tw, df_us):
    results = []
    targets = []
    
    if df_tw is not None and not df_tw.empty:
        df_tw.columns = [str(c).strip() for c in df_tw.columns]
        for _, row in df_tw.iterrows():
            t = str(row.get('Ticker', '')).strip()
            n = str(row.get('名稱', '')).strip()
            if t and t != 'nan': targets.append((get_yf_ticker_tw(t), n if n and n != 'nan' else t, '台股'))
            
    if df_us is not None and not df_us.empty:
        df_us.columns = [str(c).strip() for c in df_us.columns]
        for _, row in df_us.iterrows():
            t = str(row.get('Ticker', '')).strip()
            n = str(row.get('名稱', '')).strip()
            if t and t != 'nan': targets.append((t, n if n and n != 'nan' else t, '美股'))

    for sym, name, cat in targets:
        try:
            df = yf.download(sym, period="1y", progress=False, threads=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df[['Close', 'High', 'Low']].dropna()
            if len(df) < 60: continue
            
            last_p = df['Close'].iloc[-1]
            
            # MACD 判斷
            daily_gc = check_macd_gc(df)
            df_w = df.resample('W-FRI').agg({'Close':'last'}).dropna()
            weekly_gc = check_macd_gc(df_w) if len(df_w) >= 35 else False
            
            # 均線與 20 日高回檔 (台股 60/120/240, 美股 50/100/200)
            ma_m = df['Close'].rolling(60 if cat == '台股' else 50).mean().iloc[-1]
            high_20 = df['High'].rolling(20).max().iloc[-1]
            pullback = "⚠️ 創20日高後回檔" if (high_20 - last_p) / high_20 > 0.05 else ""
            ma_status = "🟢 季線上" if last_p > ma_m else "🔴 季線下"
            
            try:
                pe = yf.Ticker(sym).info.get('trailingPE') or yf.Ticker(sym).info.get('forwardPE', 999)
            except: pe = 999
                
            score = 3 if (daily_gc and weekly_gc) else (2 if weekly_gc else (1 if daily_gc else 0))
            
            results.append({
                '市場': cat, '代號': sym, '名稱': name,
                '收盤價': f"{last_p:.2f}", '本益比': pe, 
                'PE顯示': f"{pe:.1f}" if pe != 999 else "N/A",
                'score': score, 
                '亮點狀態': "🔥 雙重金叉" if score == 3 else ("📊 週線金叉" if score == 2 else "📈 日線金叉"),
                '均線狀態': ma_status,
                '回檔警示': pullback
            })
        except: continue
    return results

# --- 3. 頁面介面渲染 ---
def main():
    # 側邊欄
    with st.sidebar:
        st.header("⚙️ 儀表板控制項")
        time_axis = st.selectbox("圖表時間軸", ["1個月", "3個月", "半年", "1年"], index=1)
        st.caption("同步更新 Google Sheets 組合清單")
    
    st.title("📈 智慧型個人資產與投資組合 Dashboard")
    
    with st.spinner("讀取 Google Sheets 與下載最新報價中..."):
        df_tw, df_us = load_portfolio_data()
        scan_data = process_all_targets(df_tw, df_us)
        
    df_all = pd.DataFrame(scan_data)
    
    # 區塊 1：資產配置概覽 (保留您的 Plotly 空間)
    st.write("---")
    st.subheader("📊 資產配置與績效概覽")
    if not df_all.empty:
        # 此處保留圓餅圖與資產結構顯示的彈性，用市場分類做簡單示範
        fig = px.pie(df_all, names='市場', title='台美股追蹤標的佔比 (檔數)')
        st.plotly_chart(fig, use_container_width=True)
    
    # 區塊 2：完全分流的亮點與警示清單
    st.write("---")
    if not df_all.empty:
        # 分流：score > 0 的去亮點區，score == 0 的去常規警示區
        df_highlights = df_all[df_all['score'] > 0].sort_values(by=['score', '本益比'], ascending=[False, True])
        df_general = df_all[df_all['score'] == 0].sort_values(by=['市場', '均線狀態'])
        
        # --- 🎯 盤後亮點摘要 ---
        st.subheader("🎯 盤後技術亮點摘要 (MACD)")
        st.caption("嚴格篩選：具備 MACD 黃金交叉訊號之標的。依據雙金叉 > 週線 > 日線排序，同級則低本益比優先。")
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("##### 🇹🇼 台股亮點")
            tw_high = df_highlights[df_highlights['市場'] == '台股']
            if not tw_high.empty:
                st.dataframe(tw_high[['亮點狀態', '代號', '名稱', '收盤價', 'PE顯示']], hide_index=True, use_container_width=True)
            else:
                st.info("今日無亮點")
                
        with col2:
            st.markdown("##### 🇺🇸 美股亮點")
            us_high = df_highlights[df_highlights['市場'] == '美股']
            if not us_high.empty:
                st.dataframe(us_high[['亮點狀態', '代號', '名稱', '收盤價', 'PE顯示']], hide_index=True, use_container_width=True)
            else:
                st.info("今日無亮點")
                
        # --- ⚠️ 常規狀態警示 ---
        st.write("---")
        st.subheader("⚠️ 個股常規狀態與回檔警示")
        st.caption("已排除上方亮點標的。追蹤季線乖離與創 20 日高點後回檔 (>5%) 之狀態。")
        
        col3, col4 = st.columns(2)
        with col3:
            st.markdown("##### 🇹🇼 台股常規追蹤")
            tw_gen = df_general[df_general['市場'] == '台股']
            if not tw_gen.empty:
                st.dataframe(tw_gen[['均線狀態', '代號', '名稱', '收盤價', '回檔警示']], hide_index=True, use_container_width=True)
                
        with col4:
            st.markdown("##### 🇺🇸 美股常規追蹤")
            us_gen = df_general[df_general['市場'] == '美股']
            if not us_gen.empty:
                st.dataframe(us_gen[['均線狀態', '代號', '名稱', '收盤價', '回檔警示']], hide_index=True, use_container_width=True)

if __name__ == "__main__":
    main()
