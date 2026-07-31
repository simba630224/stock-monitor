import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 頁面基本設定 (行動版優化: centered 窄版佈局)
# ==========================================
st.set_page_config(
    page_title="📱 行動版投資儀表板",
    page_icon="📈",
    layout="centered", 
    initial_sidebar_state="collapsed" # 手機版預設收起側邊欄
)

# ==========================================
# 2. 全域變數與資料庫網址 (請替換為您真實的網址)
# ==========================================
PORTFOLIO_SHEET_URL = "您的_Portfolio_streamlit_網址"
HOLDINGS_SHEET_URL = "您的_ETF_Holdings_DB_網址"

# ==========================================
# 3. 資料讀取函式 (加入快取機制提升手機載入速度)
# ==========================================
@st.cache_resource
def get_gspread_client():
    """取得 Google Sheets 授權客戶端"""
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["GCP_CREDENTIALS"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

@st.cache_data(ttl=1800)
def load_portfolio_data():
    """讀取台美股投資組合清單"""
    client = get_gspread_client()
    try:
        sheet = client.open_by_url(PORTFOLIO_SHEET_URL)
        tw_df = pd.DataFrame(sheet.worksheet("TW_Portfolio").get_all_records())
        us_df = pd.DataFrame(sheet.worksheet("US_Portfolio").get_all_records())
        return tw_df, us_df
    except Exception as e:
        st.error(f"讀取投資組合失敗: {e}")
        return pd.DataFrame(), pd.DataFrame()

@st.cache_data(ttl=3600)
def load_etf_holdings():
    """動態讀取當月(或上月)的 ETF 成分股資料"""
    client = get_gspread_client()
    try:
        db_sheet = client.open_by_url(HOLDINGS_SHEET_URL)
        
        # 尋找當月或上月的資料表
        tz_tw = timezone(timedelta(hours=8))
        now = datetime.now(tz_tw)
        current_month_str = now.strftime("%Y_%m_Top20")
        
        first_day = now.replace(day=1)
        last_month = first_day - timedelta(days=1)
        last_month_str = last_month.strftime("%Y_%m_Top20")
        
        try:
            ws = db_sheet.worksheet(current_month_str)
        except gspread.exceptions.WorksheetNotFound:
            ws = db_sheet.worksheet(last_month_str)
            
        df = pd.DataFrame(ws.get_all_records())
        return df
    except Exception as e:
        st.error(f"讀取 ETF 成分股失敗: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_stock_history(ticker, period="6mo"):
    """讀取 yfinance 歷史股價 (技術分析用)"""
    try:
        data = yf.download(ticker, period=period, progress=False)
        return data
    except:
        return pd.DataFrame()

# ==========================================
# 4. 主程式與 UI 介面
# ==========================================
def main():
    st.markdown("<h2 style='text-align: center;'>📱 我的投資儀表板</h2>", unsafe_allow_html=True)
    
    # 載入核心資料
    tw_df, us_df = load_portfolio_data()
    
    # 手機版標籤頁 (加入 Emoji 增加辨識度)
    tab1, tab2, tab3 = st.tabs(["💼 庫存", "📈 走勢", "🔍 ETF"])
    
    # ------------------------------------------
    # 分頁 1: 投資組合 (簡化顯示)
    # ------------------------------------------
    with tab1:
        st.subheader("台股庫存")
        if not tw_df.empty:
            # 手機版隱藏複雜欄位，只顯示代號與股數/成本
            show_cols = [c for c in ['Ticker', 'Shares', 'Cost'] if c in tw_df.columns]
            st.dataframe(tw_df[show_cols], hide_index=True, use_container_width=True)
        else:
            st.info("尚無台股資料")
            
        st.subheader("美股庫存")
        if not us_df.empty:
            show_cols_us = [c for c in ['Ticker', 'Shares', 'Cost'] if c in us_df.columns]
            st.dataframe(us_df[show_cols_us], hide_index=True, use_container_width=True)
        else:
            st.info("尚無美股資料")

    # ------------------------------------------
    # 分頁 2: 技術分析走勢圖 (單欄位滿版)
    # ------------------------------------------
    with tab2:
        st.subheader("個股走勢查詢")
        
        # 彙整所有清單中的標的供選擇
        all_tickers = []
        if not tw_df.empty and 'Ticker' in tw_df.columns:
            # 台股代號補上 .TW 給 yfinance
            all_tickers.extend([f"{t}.TW" if not str(t).endswith('.TW') else str(t) for t in tw_df['Ticker']])
        if not us_df.empty and 'Ticker' in us_df.columns:
            all_tickers.extend(us_df['Ticker'].tolist())
            
        if all_tickers:
            selected_ticker = st.selectbox("請選擇標的：", sorted(list(set(all_tickers))))
            
            # 手機版適合半年或三個月的短線走勢
            hist_data = fetch_stock_history(selected_ticker, period="6mo")
            if not hist_data.empty:
                fig = px.line(
                    hist_data.reset_index(), 
                    x='Date', 
                    y='Close', 
                    title=f"{selected_ticker} 近半年走勢"
                )
                fig.update_layout(
                    xaxis_title="", 
                    yaxis_title="", 
                    margin=dict(l=0, r=0, t=40, b=0), # 縮小圖表邊界適合手機
                    height=300
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("無法取得該標的之歷史資料。")
        else:
            st.info("請先在試算表建立投資組合。")

    # ------------------------------------------
    # 分頁 3: ETF 成分股查詢 (手機友善排版)
    # ------------------------------------------
    with tab3:
        st.subheader("ETF 核心持股")
        df_holdings = load_etf_holdings()
        
        if not df_holdings.empty:
            etf_list = df_holdings['ETF代號'].unique().tolist()
            selected_etf = st.selectbox("選擇 ETF：", options=etf_list, index=0)
            
            # 過濾並排序資料
            target_df = df_holdings[df_holdings['ETF代號'] == selected_etf].copy()
            target_df = target_df.sort_values(by='權重(%)', ascending=False).reset_index(drop=True)
            
            # 圓餅圖 (置中滿版)
            fig_pie = px.pie(
                target_df, 
                values='權重(%)', 
                names='成分股名稱',
                hole=0.4
            )
            fig_pie.update_traces(textposition='inside', textinfo='percent')
            fig_pie.update_layout(
                showlegend=True, 
                legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5), # 圖例放下放，適合手機
                margin=dict(t=10, b=0, l=0, r=0),
                height=350
            )
            st.plotly_chart(fig_pie, use_container_width=True)
            
            # 資料表 (簡化格式)
            st.markdown("#### 📝 明細清單")
            st.dataframe(
                target_df[['成分股名稱', '權重(%)']],
                column_config={
                    "權重(%)": st.column_config.NumberColumn(
                        "權重", format="%.2f %%"
                    )
                },
                hide_index=True,
                use_container_width=True,
                height=300 # 限制高度，避免手機無止盡往下滑
            )
        else:
            st.warning("資料庫載入中或尚無資料...")

if __name__ == "__main__":
    main()
