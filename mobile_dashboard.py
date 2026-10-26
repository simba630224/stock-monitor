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
import requests
import io
from streamlit_gsheets import GSheetsConnection

warnings.filterwarnings('ignore')

st.set_page_config(page_title="行動隨身投資儀表板", layout="wide")

# ==========================================
# 🔒 權限驗證閘門
# ==========================================
def check_password():
    if st.session_state.get("authenticated", False):
        return True
    correct_password = st.secrets.get("APP_PASSWORD", "19770614")
    st.markdown("### 🔒 個人投資儀表板 (受保護存取)")
    pwd_input = st.text_input("請輸入存取密碼：", type="password")
    if st.button("🔑 登入"):
        if pwd_input == correct_password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("❌ 密碼錯誤！")
    return False

if not check_password(): st.stop()

# ==========================================
# 0. 輔助函式
# ==========================================
def safe_float(val):
    try:
        if isinstance(val, str): val = re.sub(r'[^\d.-]', '', val)
        return float(val) if pd.notna(val) and str(val).strip() != '' else 0.0
    except: return 0.0

def format_display_name(name_raw, sym_raw):
    sym = str(sym_raw).strip() if pd.notna(sym_raw) else ""
    if sym.lower() in ['nan', 'none', 'null', '']: sym = ""
    name = str(name_raw).strip() if pd.notna(name_raw) else ""
    if name.lower() in ['nan', 'none', 'null', '']: name = ""
    if name and sym: return f"{name} ({sym})"
    if not name and sym: return sym
    if name and not sym: return name
    return "未知"

# ==========================================
# 1. 資料庫連線
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)
TECHNICAL_DB_URL = "https://docs.google.com/spreadsheets/d/15F1CRaVUlgQpwbYqFQCwFiyCjmMksEBEd5CnIvF_zFs/edit?gid=0#gid=0"
ETF_DB_URL = "https://docs.google.com/spreadsheets/d/1_crBmjMxgm9qpYeycg_TnLStt3phN6vM4XILmD9x0Yc/edit"

def fetch_and_clean_portfolio(worksheet_name, default_category):
    try:
        df = conn.read(worksheet=worksheet_name, ttl=0)
        if df is None or df.empty: return pd.DataFrame()
        df.columns = [str(c).strip() for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]
        col_map = {}
        for c in df.columns:
            cl = str(c).strip().lower()
            if cl in ['ticker', 'symbol', '代號']: col_map[c] = 'Ticker'
            elif cl in ['name', '名稱']: col_map[c] = '名稱'
            elif cl in ['shares', '股數']: col_map[c] = 'Shares'
            elif cl in ['出借', '複委託']: col_map[c] = '出借' if default_category == '台股' else '複委託'
            elif cl in ['類別', '市場']: col_map[c] = '類別'
            elif cl in ['策略', '短線']: col_map[c] = '策略'
        df = df.rename(columns=col_map)
        if 'Ticker' in df.columns:
            df['Ticker'] = df['Ticker'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
            if default_category == '台股': df['Ticker'] = df['Ticker'].apply(lambda x: x.zfill(4) if x.isdigit() and len(x) < 4 else x)
            df = df[~df['Ticker'].str.lower().isin(['nan', 'none', 'null', ''])]
        else: return pd.DataFrame()
        if '名稱' not in df.columns: df['名稱'] = ''
        if 'Shares' not in df.columns: df['Shares'] = 0.0
        df['Shares'] = pd.to_numeric(df['Shares'], errors='coerce').fillna(0.0)
        if '策略' not in df.columns: df['策略'] = ''
        if default_category == '台股' and '出借' not in df.columns: df['出借'] = 0.0
        elif default_category == '美股' and '複委託' not in df.columns: df['複委託'] = 0.0
        if '出借' in df.columns: df['出借'] = pd.to_numeric(df['出借'], errors='coerce').fillna(0.0)
        if '複委託' in df.columns: df['複委託'] = pd.to_numeric(df['複委託'], errors='coerce').fillna(0.0)
        if '類別' not in df.columns: df['類別'] = default_category
        return df
    except: return pd.DataFrame()

@st.cache_data(ttl=600)
def get_tw_portfolio(): return fetch_and_clean_portfolio("TW_Portfolio", "台股")
@st.cache_data(ttl=600)
def get_us_portfolio(): return fetch_and_clean_portfolio("US_Portfolio", "美股")

df_tw = get_tw_portfolio()
df_us = get_us_portfolio()
PORTFOLIO_TW = df_tw.to_dict('records') if not df_tw.empty else []
PORTFOLIO_US = df_us.to_dict('records') if not df_us.empty else []

@st.cache_data(ttl=600)
def load_technical_db():
    try:
        df_db = conn.read(spreadsheet=TECHNICAL_DB_URL, ttl=600)
        if df_db is not None and not df_db.empty:
            df_db.columns = [str(c).strip() for c in df_db.columns]
            return df_db
    except: pass
    return pd.DataFrame()

@st.cache_data(ttl=600)
def load_value_history():
    try: return conn.read(worksheet="Value_History", ttl=600)
    except: return pd.DataFrame()

@st.cache_data(ttl=600)
def load_trading_journal():
    try: return conn.read(worksheet="Trading_Journal", ttl=600)
    except: return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_etf_holdings():
    try:
        now = datetime.now()
        ws_current = f"{now.strftime('%Y_%m')}_Top20"
        try:
            df = conn.read(spreadsheet=ETF_DB_URL, worksheet=ws_current, ttl=3600)
            if df is not None and not df.empty:
                df.columns = [str(c).strip() for c in df.columns]
                return df.dropna(how='all')
        except: pass
        return pd.DataFrame()
    except: return pd.DataFrame()

# ==========================================
# 2. 輕量行情抓取
# ==========================================
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip().upper()
    if ticker.endswith('.TW') or ticker.endswith('.TWO'): return ticker
    if ticker.endswith('B') or ticker.endswith('C') or ticker == '009815': return f"{ticker}.TWO"
    return f"{ticker}.TW"

@st.cache_data(ttl=600)
def get_basic_data(ticker):
    try:
        hist = yf.Ticker(ticker).history(period="1y")
        if not hist.empty:
            price = float(hist['Close'].dropna().iloc[-1])
            div_2026 = float(hist['Dividends'][hist.index.year == 2026].sum()) if 'Dividends' in hist.columns else 0.0
            div_1y = float(hist['Dividends'].sum()) if 'Dividends' in hist.columns else 0.0
            return price, div_2026, div_1y
    except: pass
    return 0.0, 0.0, 0.0

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
        tw = yf.Ticker("^TWII").history(period="1y")
        if len(tw) > 252: benchmarks['台股'] = ((tw['Close'].iloc[-1] - tw['Close'].iloc[-252]) / tw['Close'].iloc[-252]) * 100
    except: pass
    try:
        us = yf.Ticker("^GSPC").history(period="1y")
        if len(us) > 252: benchmarks['美股'] = ((us['Close'].iloc[-1] - us['Close'].iloc[-252]) / us['Close'].iloc[-252]) * 100
    except: pass
    return benchmarks

@st.cache_data(ttl=900)
def get_perf_div_data(sym, display_ticker, market, bench_returns):
    try:
        tk = yf.Ticker(sym)
        hist = tk.history(period="2y", auto_adjust=True)
        if not hist.empty:
            valid = hist['Close'].dropna()
            curr_p = float(valid.iloc[-1])
            def calc_ret(days):
                if len(valid) > days: return ((curr_p - float(valid.iloc[-days])) / float(valid.iloc[-days])) * 100
                elif len(valid) > 0: return ((curr_p - float(valid.iloc[0])) / float(valid.iloc[0])) * 100
                return 0.0
            ret_1q, ret_6m = calc_ret(63), calc_ret(126)
            ret_1y = ((curr_p - float(valid.iloc[-252])) / float(valid.iloc[-252])) * 100 if len(valid) > 252 else calc_ret(0)
            rel_val = ret_1y - bench_returns.get(market, 0.0)
            
            info = tk.info
            is_etf = 'ETF' in str(info.get('quoteType', '')).upper() or 'MUTUALFUND' in str(info.get('quoteType', '')).upper()
            roe = float(info.get('returnOnEquity', 0)) * 100 if info.get('returnOnEquity') is not None and not is_etf else None
            
            tot_div = float(hist['Dividends'].sum()) if 'Dividends' in hist.columns else 0.0
            yld = (tot_div / curr_p) * 100 if curr_p > 0 else 0.0
            
            return {
                "市場": market, "代號": display_ticker, "收盤價": curr_p,
                "近一季含息報酬": ret_1q, "近半年含息報酬": ret_6m, "近一年含息報酬": ret_1y,
                "相對大盤": rel_val, "近一年殖利率": yld, "ROE": roe
            }
    except: pass
    return None

@st.cache_data(ttl=600)
def get_single_stock_chart_data(sym):
    try:
        df = yf.download(sym, period="3y", progress=False, threads=False)
        if not df.empty and len(df) >= 2:
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df.astype(float).dropna(subset=['Close'])
            df['MA10'] = df['Close'].rolling(10).mean()
            df['MA20'] = df['Close'].rolling(20).mean()
            df['K_d'], df['D_d'] = 50.0, 50.0
            if 'High' in df.columns and 'Low' in df.columns:
                l, h = df['Low'].rolling(9).min(), df['High'].rolling(9).max()
                rsv = (df['Close'] - l) / (h - l + 1e-9) * 100
                df['K_d'] = rsv.ewm(com=2, adjust=False).mean()
                df['D_d'] = df['K_d'].ewm(com=2, adjust=False).mean()
            return df
    except: pass
    return None

# ==========================================
# 3. 手機版 UI
# ==========================================
st.title("📱 行動隨身儀表板")
col_l, col_r = st.columns([1, 2])
with col_l:
    if st.button("🔄 刷新"):
        st.cache_data.clear()
        st.rerun()
with col_r:
    st.caption(f"更新:{datetime.now().strftime('%H:%M')}")

tab1, tab_hl, tab_comp, tab2, tab3, tab_etf, tab4, tab5 = st.tabs(["💰資產", "🎯亮點", "🆚比較", "📈技術", "🏆績效", "🧩成分", "📖心得", "📝管理"])

with tab1:
    with st.spinner("算資產中..."):
        usdtwd = get_usdtwd()
        total_market_value, total_div_2026, total_div_1y = 0, 0, 0
        asset_alloc = {}
        
        for item in PORTFOLIO_TW:
            tk = str(item.get('Ticker', '')).strip()
            if tk:
                cat = str(item.get('類別', '台股')).strip()
                p, d26, d1y = get_basic_data(get_yf_ticker_tw(tk))
                sh = safe_float(item.get('Shares')) + safe_float(item.get('出借'))
                if p > 0 and sh > 0:
                    val = p * sh
                    total_market_value += val
                    total_div_2026 += d26 * sh
                    total_div_1y += d1y * sh
                    asset_alloc[cat] = asset_alloc.get(cat, 0) + val
                    
        for item in PORTFOLIO_US:
            tk = str(item.get('Ticker', '')).strip()
            if tk:
                cat = str(item.get('類別', '美股')).strip()
                p, d26, d1y = get_basic_data(tk)
                sh = safe_float(item.get('Shares')) + safe_float(item.get('複委託'))
                if p > 0 and sh > 0:
                    val = p * sh * usdtwd
                    total_market_value += val
                    total_div_2026 += d26 * sh * usdtwd
                    total_div_1y += d1y * sh * usdtwd
                    asset_alloc[cat] = asset_alloc.get(cat, 0) + val

        c1, c2 = st.columns(2)
        c1.metric("總市值", f"${total_market_value:,.0f}")
        c2.metric("匯率", f"{usdtwd:.3f}")
        
        df_hist = load_value_history()
        if not df_hist.empty and 'Date' in df_hist.columns:
            df_hist['Date'] = pd.to_datetime(df_hist['Date'], errors='coerce').dt.strftime('%m/%d')
            df_hist['Total_Value'] = pd.to_numeric(df_hist['Total_Value'].astype(str).str.replace(r'[^\d.-]', '', regex=True), errors='coerce').fillna(0)
            if len(df_hist) > 1:
                st.caption("📈 市值變化")
                fig = px.line(df_hist, x='Date', y='Total_Value', markers=True)
                fig.update_layout(height=200, margin=dict(t=0,b=0,l=0,r=0), yaxis_title=None, xaxis_title=None)
                st.plotly_chart(fig, use_container_width=True)

with tab_hl:
    with st.spinner("掃描技術訊號..."):
        df_db = load_technical_db()
        if not df_db.empty:
            for col in ['bull_score', 'bear_score']: df_db[col] = pd.to_numeric(df_db.get(col, 0), errors='coerce').fillna(0)
            df_db['_raw_pe'] = pd.to_numeric(df_db.get('_raw_pe'), errors='coerce')
            
            df_db['tags_str'] = df_db.get('tags', '').astype(str)
            df_db['策略'] = df_db.get('策略', '').astype(str)
            df_db['顯示名稱'] = df_db.apply(lambda r: format_display_name(r.get('_name'), r.get('_sym')), axis=1)

            is_short = df_db['策略'].str.contains('短', case=False, na=False)
            df_short, df_long = df_db[is_short].copy(), df_db[~is_short].copy()

            def format_mobile_items(sub_df):
                if sub_df.empty: return "> 👻 無符合標的"
                res = ""
                for _, r in sub_df.iterrows():
                    pe = r.get('_raw_pe')
                    pe_str = f"PE:{float(pe):.1f}" if pd.notna(pe) else "PE:無"
                    b_s, br_s = int(r.get('bull_score', 0)), int(r.get('bear_score', 0))
                    res += f"- **{r.get('顯示名稱', '')}** (多:{b_s} 空:{br_s} | {pe_str})\n  - `[{r.get('tags', '')}]`\n"
                return res

            st.markdown("#### ⚡ 短線區 (MA5/MA10/創高)")
            if not df_short.empty:
                s_bull_cond = df_short['tags_str'].str.contains('創20日|創50日', regex=True) | ((df_short['bull_score'] >= 2) & (df_short['bear_score'] == 0))
                s_bear_cond = df_short['tags_str'].str.contains('破20日|破50日', regex=True) | ((df_short['bear_score'] >= 2) & (df_short['bull_score'] == 0))
                df_s_bull = df_short[s_bull_cond]
                df_s_bear = df_short[s_bear_cond]
                st.success(f"**🚀 偏多/創高動能**\n{format_mobile_items(df_s_bull)}")
                st.error(f"**🩸 偏空/破底風險**\n{format_mobile_items(df_s_bear)}")
            else: st.info("無短線標的。")

            st.divider()
            st.markdown("#### 📈 波段投資 (Top 10)")
            
            l_bull_cond = df_long['tags_str'].str.contains('創52週收盤高', regex=True) | ((df_long['bull_score'] >= 3) & df_long['tags_str'].str.contains('週KD低檔金叉|週MACD零下金叉', regex=True)) | ((df_long['bull_score'] >= 3) & (df_long['bear_score'] == 0))
            l_bear_cond = df_long['tags_str'].str.contains('破52週收盤低', regex=True) | ((df_long['bear_score'] >= 3) & df_long['tags_str'].str.contains('週KD高檔死叉|週MACD零上死叉', regex=True)) | ((df_long['bear_score'] >= 3) & (df_long['bull_score'] == 0))
            
            df_l_bull = df_long[l_bull_cond].copy()
            df_l_bear = df_long[l_bear_cond].copy()
            
            if not df_l_bull.empty:
                df_l_bull['sort'] = df_l_bull['bull_score'] - df_l_bull['bear_score']
                df_l_bull = df_l_bull.sort_values(by=['市場', 'sort', '_raw_pe'], ascending=[False, False, True]).groupby('市場').head(10)
            if not df_l_bear.empty:
                df_l_bear['sort'] = df_l_bear['bear_score'] - df_l_bear['bull_score']
                df_l_bear = df_l_bear.sort_values(by=['市場', 'sort', '_raw_pe'], ascending=[False, False, True]).groupby('市場').head(10)

            st.success(f"**🚀 長多波段 / 攻擊轉折**\n{format_mobile_items(df_l_bull)}")
            st.error(f"**🛑 波段轉弱 / 長期風險**\n{format_mobile_items(df_l_bear)}")
        else: st.warning("未讀取到 Technical_DB。")

with tab_comp:
    st.markdown("### 🆚 多檔走勢比較")
    opts = {format_display_name(r.get('名稱'), r.get('Ticker')): get_yf_ticker_tw(r.get('Ticker', '')) for r in PORTFOLIO_TW if r.get('Ticker')}
    opts.update({format_display_name(r.get('名稱'), r.get('Ticker')): str(r.get('Ticker', '')).strip() for r in PORTFOLIO_US if r.get('Ticker')})
    
    if opts:
        tgts = st.multiselect("選標的(最多4檔)", list(opts.keys()), max_selections=4)
        if tgts:
            with st.spinner("載入數據..."):
                pcts = {}
                for t in tgts:
                    try:
                        h = yf.Ticker(opts[t]).history(period="1y")
                        if not h.empty:
                            s = h['Close'].dropna()
                            if not s.empty and s.iloc[0] > 0: pcts[t] = ((s / s.iloc[0]) - 1) * 100
                    except: pass
                if pcts:
                    df_p = pd.DataFrame(pcts).ffill()
                    fig = px.line(df_p)
                    fig.update_layout(height=250, margin=dict(t=0,b=0,l=0,r=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                    st.plotly_chart(fig, use_container_width=True)

            st.divider()
            df_etf = load_etf_holdings()
            if not df_etf.empty and len(df_etf.columns) >= 3:
                ec, nc, wc = df_etf.columns[0], df_etf.columns[1], df_etf.columns[2]
                for t in tgts:
                    c_code = opts[t].split('.')[0]
                    sub = df_etf[df_etf[ec].astype(str).str.replace(r'\.TW.*', '', regex=True) == c_code].copy()
                    if not sub.empty:
                        sub[wc] = pd.to_numeric(sub[wc].astype(str).str.replace(r'[^\d.-]', '', regex=True), errors='coerce')
                        sub = sub.dropna(subset=[wc]).sort_values(by=wc, ascending=False).drop_duplicates(subset=[nc]).head(10)
                        st.markdown(f"**📌 {t} (Top10: {sub[wc].sum():.2f}%)**")
                        sub[wc] = sub[wc].apply(lambda x: f"{x:.2f}%")
                        st.dataframe(sub[[nc, wc]].rename(columns={nc:"成分", wc:"%"}), hide_index=True, use_container_width=True)
            else: st.caption("無 ETF 庫資料。")

with tab2:
    if 'df_db' in locals() and not df_db.empty:
        st.dataframe(df_db[["顯示名稱", "狀態警示"]], hide_index=True, use_container_width=True, height=300)
        sel = st.selectbox("看線圖", df_db["顯示名稱"].tolist())
        if sel:
            sym = df_db[df_db["顯示名稱"] == sel]['_sym'].iloc[0]
            df_c = get_single_stock_chart_data(sym)
            if df_c is not None:
                df_c = df_c.tail(80)
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
                fig.add_trace(go.Scatter(x=df_c.index, y=df_c['Close'], name='價'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_c.index, y=df_c['MA20'], name='M20'), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_c.index, y=df_c['K_d'], name='K'), row=2, col=1)
                fig.add_trace(go.Scatter(x=df_c.index, y=df_c['D_d'], name='D'), row=2, col=1)
                fig.update_layout(height=350, margin=dict(t=0,b=0,l=0,r=0), showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.markdown("### 🏆 績效總覽")
    with st.spinner("計算中..."):
        br = get_benchmark_returns()
        res_list = []
        for i in PORTFOLIO_TW:
            if i.get('Ticker'): res_list.append(get_perf_div_data(get_yf_ticker_tw(i['Ticker']), i['Ticker'], '台股', br))
        for i in PORTFOLIO_US:
            if i.get('Ticker'): res_list.append(get_perf_div_data(i['Ticker'], i['Ticker'], '美股', br))
        
        res_list = [r for r in res_list if r]
        if res_list:
            st.dataframe(
                pd.DataFrame(res_list)[["代號", "收盤價", "近一季含息報酬", "近一年含息報酬", "近一年殖利率"]],
                hide_index=True, use_container_width=True, height=400,
                column_config={"近一季含息報酬": st.column_config.NumberColumn("季(%)", format="%+.1f"), "近一年含息報酬": st.column_config.NumberColumn("年(%)", format="%+.1f"), "近一年殖利率": st.column_config.NumberColumn("殖利率", format="%.1f")}
            )

with tab_etf:
    st.markdown("### 🧩 ETF 持股")
    df_etf = load_etf_holdings()
    if not df_etf.empty:
        ec, nc, wc = df_etf.columns[0], df_etf.columns[1], df_etf.columns[2]
        opts = [x for x in df_etf[ec].dropna().unique() if x.lower() not in ['etf', 'nan']]
        sel = st.selectbox("選 ETF", opts)
        if sel:
            sub = df_etf[df_etf[ec].astype(str).str.strip() == sel].copy()
            sub[wc] = pd.to_numeric(sub[wc].astype(str).str.replace(r'[^\d.-]', '', regex=True), errors='coerce')
            sub = sub.dropna(subset=[wc]).drop_duplicates(subset=[nc]).sort_values(by=wc, ascending=True).tail(10)
            if not sub.empty:
                st.caption(f"Top10合: {sub[wc].sum():.2f}%")
                fig = px.bar(sub, x=wc, y=nc, orientation='h', text_auto='.2f')
                fig.update_layout(height=350, margin=dict(t=0,b=0,l=0,r=0), yaxis_title=None, xaxis_title=None)
                st.plotly_chart(fig, use_container_width=True)

with tab4:
    @st.fragment
    def manage_mobile_journal():
        st.markdown("### 📖 看盤心得")
        dj = load_trading_journal()
        today = datetime.now().strftime('%Y-%m-%d')
        tm = datetime.now().strftime('%H:%M:%S')
        
        exist_n = ""
        if not dj.empty and 'Date' in dj.columns and today in dj['Date'].values:
            exist_n = str(dj.loc[dj['Date']==today, 'Notes'].iloc[0])
            
        with st.form("j_form"):
            txt = st.text_area("紀錄:", value=exist_n if exist_n!='nan' else "", height=120)
            if st.form_submit_button("💾 儲存"):
                if today in dj['Date'].values:
                    idx = dj.index[dj['Date']==today].tolist()[0]
                    dj.at[idx, 'Notes'] = txt
                    dj.at[idx, 'Last_Updated'] = tm
                else:
                    dj = pd.concat([dj, pd.DataFrame([{'Date': today, 'Notes': txt, 'Last_Updated': tm}])], ignore_index=True)
                conn.update(worksheet="Trading_Journal", data=dj.fillna(""))
                st.cache_data.clear()
                st.rerun()
                
        if not dj.empty:
            for _, r in dj.sort_values(by='Date', ascending=False).head(5).iterrows():
                with st.expander(f"📅 {r.get('Date', '')}"): st.write(r.get('Notes', ''))
    manage_mobile_journal()

with tab5:
    st.markdown("### 📝 管理清單")
    @st.fragment
    def manage_tw():
        with st.form("tw_form"):
            tw_ed = st.data_editor(df_tw, num_rows="dynamic", use_container_width=True)
            if st.form_submit_button("💾 存台股"):
                tw_ed['Ticker'] = tw_ed['Ticker'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True).apply(lambda x: x.zfill(4) if x.isdigit() and len(x)<4 else x)
                conn.update(worksheet="TW_Portfolio", data=tw_ed[~tw_ed['Ticker'].str.lower().isin(['nan', ''])].fillna(""))
                st.cache_data.clear(); st.rerun()
    manage_tw()
    
    @st.fragment
    def manage_us():
        with st.form("us_form"):
            us_ed = st.data_editor(df_us, num_rows="dynamic", use_container_width=True)
            if st.form_submit_button("💾 存美股"):
                us_ed['Ticker'] = us_ed['Ticker'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
                conn.update(worksheet="US_Portfolio", data=us_ed[~us_ed['Ticker'].str.lower().isin(['nan', ''])].fillna(""))
                st.cache_data.clear(); st.rerun()
    manage_us()
