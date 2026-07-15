import streamlit as st
from streamlit_gsheets import GSheetsConnection
import yfinance as yf
import pandas as pd
import numpy as np
import time
import warnings

warnings.filterwarnings('ignore')
st.set_page_config(page_title="投資組合與盤後技術掃描儀表板", layout="wide")

# --- 1. 計算與判定函數 ---
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip().upper()
    if ticker.endswith(('.TW', '.TWO')): 
        return ticker
    if (ticker.endswith(('B', 'C')) or ticker == '009815'):
        return f"{ticker}.TWO"
    return f"{ticker}.TW"

def check_macd_gc(df):
    if len(df) < 35: return False
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return (hist.iloc[-1] > 0) and (hist.iloc[-2] <= 0)

# --- 2. 讀取 Google Sheets 數據 ---
@st.cache_data(ttl=600)  # 快取 10 分鐘，加快重複載入速度
def load_portfolio_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_tw = conn.read(worksheet="TW_Portfolio")
    df_us = conn.read(worksheet="US_Portfolio")
    return df_tw, df_us

# --- 3. 核心運算渲染 ---
def process_dashboard_scans(df_tw, df_us):
    scan_results = []
    
    # 彙整待掃描的所有標的
    targets = []
    if df_tw is not None and not df_tw.empty:
        df_tw.columns = [str(c).strip() for c in df_tw.columns]
        for _, row in df_tw.iterrows():
            ticker = str(row.get('Ticker', '')).strip()
            name = str(row.get('名稱', '')).strip()
            if ticker and ticker != 'nan':
                targets.append((get_yf_ticker_tw(ticker), name if name and name != 'nan' else ticker, '台股'))
                
    if df_us is not None and not df_us.empty:
        df_us.columns = [str(c).strip() for c in df_us.columns]
        for _, row in df_us.iterrows():
            ticker = str(row.get('Ticker', '')).strip()
            name = str(row.get('名稱', '')).strip()
            if ticker and ticker != 'nan':
                targets.append((ticker, name if name and name != 'nan' else ticker, '美股'))

    # 批次下載歷史價格以優化讀取速度
    symbols = [t[0] for t in targets]
    if not symbols: return []
    
    # 抓取 yfinance 資料
    for sym, name, cat in targets:
        try:
            df = yf.download(sym, period="1y", progress=False, threads=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): 
                df.columns = df.columns.get_level_values(0)
            df = df[['Close']].dropna()
            if len(df) < 35: continue
            
            # 技術狀態計算
            daily_gc = check_macd_gc(df)
            df_w = df.resample('W-FRI').agg({'Close':'last'}).dropna()
            weekly_gc = check_macd_gc(df_w) if len(df_w) >= 35 else False
            
            try:
                info = yf.Ticker(sym).info
                pe = info.get('trailingPE') or info.get('forwardPE', 999)
            except:
                pe = 999
                
            score = 0
            if daily_gc and weekly_gc:
                score = 3
                status = "🔥 雙重金叉 (日+週)"
            elif weekly_gc:
                score = 2
                status = "📊 週線金叉"
            elif daily_gc:
                score = 1
                status = "📈 日線金叉"
            else:
                score = 0
                status = "⚪ 無訊號"
                
            scan_results.append({
                '市場': cat,
                '代號': sym,
                '名稱': name,
                '最新收盤價': f"{df['Close'].iloc[-1]:.2f}",
                '本益比': pe,
                '本益比顯示': f"{pe:.1f}" if pe != 999 else "N/A",
                'status': status,
                'score': score
            })
        except:
            continue
            
    return scan_results

# --- 4. 頁面介面呈現 ---
def main():
    st.title("📈 智慧型個人資產與投資組合 Dashboard")
    st.markdown("同步盤後最新狀態警示與 MACD 技術面黃金交叉篩選")
    
    # 載入資料
    with st.spinner("正在讀取 Google Sheets 投資組合資料..."):
        df_tw, df_us = load_portfolio_data()
        
    # 進行盤後掃描
    with st.spinner("正在執行技術指標計算與本益比對齊分析..."):
        scan_data = process_dashboard_scans(df_tw, df_us)
        
    if scan_data:
        df_scan = pd.DataFrame(scan_data)
        
        # 排除無訊號的標的 (score == 0)
        df_highlights = df_scan[df_scan['score'] > 0]
        
        st.write("---")
        st.subheader("🎯 盤後狀態警示與亮點摘要")
        st.caption("依據排序標準：雙重黃金交叉 > 週黃金交叉 > 日黃金交叉。若條件符合程度相同，低本益比者優先顯示。")
        
        if not df_highlights.empty:
            # 依據符合程度(score)降冪排序，本益比(pe)升冪排序
            df_highlights = df_highlights.sort_values(by=['score', '本益比'], ascending=[False, True])
            
            # 分割台美股顯示
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("### 🇹🇼 台灣市場亮點標的")
                df_tw_high = df_highlights[df_highlights['市場'] == '台股']
                if not df_tw_high.empty:
                    # 分組顯示
                    for status, group in df_tw_high.groupby('status', sort=False):
                        st.info(f"**{status}**")
                        st.dataframe(
                            group[['代號', '名稱', '最新收盤價', '本益比顯示']].rename(columns={'本益比顯示': '本益比'}),
                            hide_index=True,
                            use_container_width=True
                        )
                else:
                    st.write("今日台股持股中無特定黃金交叉亮點。")
                    
            with col2:
                st.markdown("### 🇺🇸 美國市場亮點標的")
                df_us_high = df_highlights[df_highlights['市場'] == '美股']
                if not df_us_high.empty:
                    for status, group in df_us_high.groupby('status', sort=False):
                        st.success(f"**{status}**")
                        st.dataframe(
                            group[['代號', '名稱', '最新收盤價', '本益比顯示']].rename(columns={'本益比顯示': '本益比'}),
                            hide_index=True,
                            use_container_width=True
                        )
                else:
                    st.write("今日美股持股中無特定黃金交叉亮點。")
        else:
            st.info("💡 今日兩大市場所有標的皆無觸及 MACD 黃金交叉警示訊號。")
            
    else:
        st.error("❌ 無法載入或解析持股數據。")

if __name__ == "__main__":
    main()
