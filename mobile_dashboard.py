import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import numpy as np
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 網頁基本設定 (手機版採用 centered 讓兩側留白變小)
# ==========================================
st.set_page_config(page_title="隨身投資儀表板", page_icon="📱", layout="centered")
st.title("📱 隨身投資監測儀表板")

# 建立 Google Sheets 連線 (取代舊版 get_gspread_client)
conn = st.connection("gsheets", type=GSheetsConnection)

# ==========================================
# 核心工具函式 (與電腦版完全對齊)
# ==========================================
def get_yf_ticker_tw(ticker, is_us=False):
    if is_us:
        return ticker
    ticker_str = str(ticker).strip().upper()
    if ticker_str.endswith('.TW') or ticker_str.endswith('.TWO'):
        return ticker_str
    if ticker_str.endswith('B') or ticker_str.endswith('C'):
        return f"{ticker_str}.TWO"
    if ticker_str in ['009815', '00981A', '00988A'] or not ticker_str.isdigit():
        if ticker_str in ['00981A', '00988A']:
            return f"{ticker_str}.TW"
        return f"{ticker_str}.TWO"
    return f"{ticker_str}.TW"

@st.cache_data(ttl=900)
def fetch_stock_data(ticker_list, is_us=False):
    data_dict = {}
    for t in ticker_list:
        yf_t = get_yf_ticker_tw(t, is_us)
        try:
            df = yf.Ticker(yf_t).history(period="3y", auto_adjust=True)
            if not df.empty:
                data_dict[t] = df
        except Exception:
            continue
    return data_dict

def calculate_technical_indicators(df):
    if df.empty or len(df) < 5:
        return None
    
    res = {}
    
    # 日線
    df['Low_9'] = df['Low'].rolling(window=9, min_periods=1).min()
    df['High_9'] = df['High'].rolling(window=9, min_periods=1).max()
    df['RSV'] = (df['Close'] - df['Low_9']) / (df['High_9'] - df['Low_9']) * 100
    df['RSV'] = df['RSV'].fillna(50)
    df['K'] = df['RSV'].ewm(com=2, adjust=False).mean()
    df['D'] = df['K'].ewm(com=2, adjust=False).mean()
    df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # 週線
    df_w = df.resample('W').agg({'Open':'first', 'High':'max', 'Low':'min', 'Close':'last'}).dropna()
    if len(df_w) >= 15:
        df_w['Low_9'] = df_w['Low'].rolling(window=9, min_periods=1).min()
        df_w['High_9'] = df_w['High'].rolling(window=9, min_periods=1).max()
        df_w['RSV'] = (df_w['Close'] - df_w['Low_9']) / (df_w['High_9'] - df_w['Low_9']) * 100
        df_w['RSV'] = df_w['RSV'].fillna(50)
        df_w['K_w'] = df_w['RSV'].ewm(com=2, adjust=False).mean()
        df_w['D_w'] = df_w['K_w'].ewm(com=2, adjust=False).mean()
        df_w['EMA12'] = df_w['Close'].ewm(span=12, adjust=False).mean()
        df_w['EMA26'] = df_w['Close'].ewm(span=26, adjust=False).mean()
        df_w['MACD_w'] = df_w['EMA12'] - df_w['EMA26']
        df_w['Signal_w'] = df_w['MACD_w'].ewm(span=9, adjust=False).mean()
    
    res['close'] = df['Close'].iloc[-1]
    res['k_d'] = df['K'].iloc[-1]
    res['d_d'] = df['D'].iloc[-1]
    res['macd_d'] = df['MACD'].iloc[-1]
    res['signal_d'] = df['Signal'].iloc[-1]
    
    if len(df) > 1:
        res['k_d_prev'] = df['K'].iloc[-2]
        res['d_d_prev'] = df['D'].iloc[-2]
        res['macd_d_prev'] = df['MACD'].iloc[-2]
        res['signal_d_prev'] = df['Signal'].iloc[-2]
    else:
        res['k_d_prev'] = res['d_d_prev'] = res['macd_d_prev'] = res['signal_d_prev'] = 0
        
    if len(df_w) >= 15:
        res['k_w'] = df_w['K_w'].iloc[-1]
        res['d_w'] = df_w['D_w'].iloc[-1]
        res['macd_w'] = df_w['MACD_w'].iloc[-1]
        res['signal_w'] = df_w['Signal_w'].iloc[-1]
        if len(df_w) > 1:
            res['k_w_prev'] = df_w['K_w'].iloc[-2]
            res['d_w_prev'] = df_w['D_w'].iloc[-2]
            res['macd_w_prev'] = df_w['MACD_w'].iloc[-2]
            res['signal_w_prev'] = df_w['Signal_w'].iloc[-2]
        else:
            res['k_w_prev'] = res['d_w_prev'] = res['macd_w_prev'] = res['signal_w_prev'] = 0
    else:
        res['k_w'] = res['d_w'] = res['macd_w'] = res['signal_w'] = None

    return res

def analyze_signals(tech_data, pe_ratio):
    if not tech_data:
        return None
    
    score = 0
    tags = []
    status = "neutral" 
    
    # 週線 MACD
    if tech_data['macd_w'] is not None:
        if tech_data['macd_w_prev'] <= tech_data['signal_w_prev'] and tech_data['macd_w'] > tech_data['signal_w'] and tech_data['macd_w'] < 0:
            score += 4
            tags.append("週MACD金叉")
        elif tech_data['macd_w_prev'] >= tech_data['signal_w_prev'] and tech_data['macd_w'] < tech_data['signal_w'] and tech_data['macd_w'] > 0:
            status = "bearish"
            tags.append("週MACD死叉")
            
    # 週線 KD
    if tech_data['k_w'] is not None:
        if tech_data['k_w_prev'] <= tech_data['d_w_prev'] and tech_data['k_w'] > tech_data['d_w'] and tech_data['k_w'] < 30:
            score += 3
            tags.append("週KD金叉")
        elif tech_data['k_w_prev'] >= tech_data['d_w_prev'] and tech_data['k_w'] < tech_data['d_w'] and tech_data['k_w'] > 70:
            status = "bearish"
            tags.append("週KD死叉")

    # 日線 MACD
    if tech_data['macd_d_prev'] <= tech_data['signal_d_prev'] and tech_data['macd_d'] > tech_data['signal_d'] and tech_data['macd_d'] < 0:
        score += 2
        tags.append("日MACD金叉")
    elif tech_data['macd_d_prev'] >= tech_data['signal_d_prev'] and tech_data['macd_d'] < tech_data['signal_d'] and tech_data['macd_d'] > 0:
        status = "bearish"
        tags.append("日MACD死叉")

    # 日線 KD
    if tech_data['k_d_prev'] <= tech_data['d_d_prev'] and tech_data['k_d'] > tech_data['d_d'] and tech_data['k_d'] < 30:
        score += 1
        tags.append("日KD金叉")
    elif tech_data['k_d_prev'] >= tech_data['d_d_prev'] and tech_data['k_d'] < tech_data['d_d'] and tech_data['k_d'] > 70:
        status = "bearish"
        tags.append("日KD死叉")
        
    if status != "bearish" and score > 0:
        status = "bullish"
        
    return {
        "status": status,
        "score": score,
        "tags": tags,
        "pe": pe_ratio if pe_ratio else 999 
    }

# ==========================================
# 載入設定與資料
# ==========================================
with st.spinner('連線同步中...'):
    try:
        df_tw = conn.read(worksheet="TW_Portfolio")
        df_us = conn.read(worksheet="US_Portfolio")
    except Exception as e:
        st.error(f"連線錯誤: {e}")
        st.stop()

# ==========================================
# 手機版頁面分頁配置 (簡化文字以適應螢幕)
# ==========================================
tab1, tab2, tab3, tab4, tab5 = st.tabs(["💰 總覽", "🎯 亮點", "🆚 比較", "📊 績效", "📖 日誌"])

# --- Tab 1: 總覽 ---
with tab1:
    st.markdown("### 📈 總市值趨勢")
    
    current_total_value = 2170000 # 範例數值
    today_str = datetime.now().strftime("%Y-%m-%d")
    current_time_str = datetime.now().strftime("%H:%M:%S")
    
    try:
        df_history = conn.read(worksheet="Value_History")
        df_history = df_history.dropna(how='all')
        
        if len(df_history) > 0:
            df_history['Date'] = df_history['Date'].astype(str)
            if today_str in df_history['Date'].values:
                df_history.loc[df_history['Date'] == today_str, 'Total_Value'] = current_total_value
                df_history.loc[df_history['Date'] == today_str, 'Last_Updated'] = current_time_str
            else:
                new_row = pd.DataFrame([{"Date": today_str, "Total_Value": current_total_value, "Last_Updated": current_time_str}])
                df_history = pd.concat([df_history, new_row], ignore_index=True)
                
            conn.update(worksheet="Value_History", data=df_history)
            st.line_chart(data=df_history.set_index('Date')['Total_Value'], height=250)
        else:
            st.warning("⚠️ 偵測到歷史紀錄為空，已啟用防寫保護。")
            st.line_chart(pd.DataFrame([{"Date": today_str, "Total_Value": current_total_value}]).set_index('Date'), height=250)
    except Exception as e:
        st.error("歷史市值同步失敗。")

# --- Tab 2: 亮點 (手機版直式排版) ---
with tab2:
    st.markdown("### 🎯 盤後亮點摘要")
    tw_tickers = df_tw['Ticker'].dropna().astype(str).tolist() if 'Ticker' in df_tw.columns else []
    
    with st.spinner("掃描技術訊號中..."):
        tw_data = fetch_stock_data(tw_tickers, is_us=False)
        bullish_list, bearish_list = [], []
        
        for t, df in tw_data.items():
            name = df_tw.loc[df_tw['Ticker'].astype(str) == t, '名稱'].values
            stock_name = name[0] if len(name) > 0 else t
            
            try:
                info = yf.Ticker(get_yf_ticker_tw(t, False)).info
                pe = info.get('trailingPE', 999)
            except:
                pe = 999
                
            tech = calculate_technical_indicators(df)
            analysis = analyze_signals(tech, pe)
            
            if analysis:
                pe_str = f"{analysis['pe']:.1f}" if analysis['pe'] != 999 else "無"
                label = f"**{stock_name} ({t})** | PE: {pe_str}  \n└ [{', '.join(analysis['tags'])}]"
                
                if analysis['status'] == "bullish":
                    bullish_list.append({"label": label, "score": analysis['score'], "pe": analysis['pe']})
                elif analysis['status'] == "bearish":
                    bearish_list.append({"label": label, "score": analysis['score'], "pe": analysis['pe']})

        bullish_list.sort(key=lambda x: (-x['score'], x['pe']))
        bearish_list.sort(key=lambda x: (-x['score'], x['pe']))
        
        # 多方區塊 (單欄)
        st.success("🔥 多方強勢 (Top 5)")
        if bullish_list:
            for item in bullish_list[:5]:
                st.markdown(f"🟢 {item['label']}")
        else:
            st.write("無符合標的")
            
        st.divider()
        
        # 空方區塊 (單欄)
        st.error("⛈️ 空方警示 (Top 5)")
        if bearish_list:
            for item in bearish_list[:5]:
                st.markdown(f"🔴 {item['label']}")
        else:
            st.write("無符合標的")

# --- Tab 3: 走勢比較 ---
with tab3:
    st.markdown("### 🆚 走勢比較")
    compare_tickers = st.multiselect("選擇標的 (最多4檔)", tw_tickers, default=tw_tickers[:2] if len(tw_tickers)>=2 else tw_tickers)
    period = st.selectbox("區間", ["半年", "一年", "三年"], index=1)
    period_map = {"半年": "6mo", "一年": "1y", "三年": "3y"}
    
    if compare_tickers:
        with st.spinner("載入比較資料..."):
            compare_data = pd.DataFrame()
            for t in compare_tickers[:4]:
                df_temp = yf.Ticker(get_yf_ticker_tw(t, False)).history(period=period_map[period], auto_adjust=True)
                if not df_temp.empty:
                    df_temp.index = df_temp.index.normalize() # 切齊時區防報錯
                    pct_change = (df_temp['Close'] / df_temp['Close'].iloc[0] - 1) * 100
                    compare_data[t] = pct_change
            
            if not compare_data.empty:
                compare_data = compare_data.dropna(how='all')
                st.line_chart(compare_data, height=250)
            else:
                st.warning("無歷史資料")

# --- Tab 4: 績效 ---
with tab4:
    st.markdown("### 📊 績效追蹤")
    sample_perf_df = pd.DataFrame({
        "代號": ["0050", "2330", "VOO"],
        "近期報酬(%)": [5.2, -1.3, 12.5]
    })
    
    st.dataframe(
        sample_perf_df,
        column_config={
            "近期報酬(%)": st.column_config.NumberColumn(format="%+.2f")
        },
        use_container_width=True,
        hide_index=True
    )

# --- Tab 5: 每日看盤心得 ---
with tab5:
    st.markdown("### 📖 日誌")
    try:
        df_journal = conn.read(worksheet="Trading_Journal")
        df_journal = df_journal.dropna(how='all')
        
        today_journal = ""
        if len(df_journal) > 0 and today_str in df_journal['Date'].astype(str).values:
            today_journal = str(df_journal.loc[df_journal['Date'].astype(str) == today_str, 'Content'].values[0])
            
        new_journal = st.text_area("✍️ 記錄今日心得", value=today_journal, height=120)
        
        if st.button("💾 儲存", use_container_width=True):
            if len(df_journal) > 0:
                df_journal['Date'] = df_journal['Date'].astype(str)
                if today_str in df_journal['Date'].values:
                    df_journal.loc[df_journal['Date'] == today_str, 'Content'] = new_journal
                else:
                    new_row = pd.DataFrame([{"Date": today_str, "Content": new_journal}])
                    df_journal = pd.concat([df_journal, new_row], ignore_index=True)
                conn.update(worksheet="Trading_Journal", data=df_journal)
                st.success("已儲存！")
            else:
                st.warning("日誌為空，已啟用防寫保護。")
                
        st.divider()
        if len(df_journal) > 0:
            for idx, row in df_journal.sort_values(by='Date', ascending=False).iterrows():
                with st.expander(f"📅 {row['Date']}"):
                    st.write(row['Content'])
    except Exception as e:
        st.error("日誌同步失敗")
