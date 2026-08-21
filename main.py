import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import os
import time
import json
from datetime import datetime
import warnings
import gspread
from google.oauth2.service_account import Credentials

warnings.filterwarnings('ignore')

# ==========================================
# 1. 環境變數與設定
# ==========================================
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
SHEET_CSV_TW_URL = os.getenv('SHEET_CSV_TW_URL')
SHEET_CSV_US_URL = os.getenv('SHEET_CSV_US_URL')
GCP_CREDENTIALS = os.getenv('GCP_CREDENTIALS')
TECHNICAL_DB_URL = os.getenv('TECHNICAL_DB_URL')

DEFAULT_TW = [
    {'symbol': '2330.TW', 'name': '台積電', 'strategy': ''},
    {'symbol': '0050.TW', 'name': '元大台灣50', 'strategy': ''}
]

DEFAULT_US = [
    {'symbol': 'AAPL', 'name': 'Apple', 'strategy': ''},
    {'symbol': 'QQQ', 'name': 'Invesco QQQ', 'strategy': ''}
]

# ==========================================
# 2. 輔助函式與資料讀寫
# ==========================================
def get_sheet_data(url, default_data, default_market):
    if not url: return [{'symbol': d['symbol'], 'name': d['name'], 'market': default_market, 'strategy': d.get('strategy','')} for d in default_data]
    try:
        df = pd.read_csv(url)
        df.columns = [str(c).strip() for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]
        
        col_map = {}
        for c in df.columns:
            cl = c.lower()
            if cl in ['ticker', 'symbol', '代號', '股票代號', '標的代號']: col_map[c] = 'symbol'
            elif cl in ['name', '名稱', '標的名稱', '股票名稱']: col_map[c] = 'name'
            elif cl in ['策略', '短線', '屬性', '交易屬性']: col_map[c] = 'strategy'
            
        df = df.rename(columns=col_map)
        if 'strategy' not in df.columns: df['strategy'] = ''
        
        if 'symbol' in df.columns:
            df = df.dropna(subset=['symbol'])
            df = df[df['symbol'].astype(str).str.strip() != '']
            if 'name' not in df.columns: df['name'] = df['symbol']
            
            records = []
            for _, row in df.iterrows():
                # 防呆：清洗 nan 字串
                sym = str(row['symbol']).strip()
                name = str(row['name']).strip()
                strat = str(row.get('strategy', '')).strip()
                
                if sym.lower() in ['nan', 'none', 'null', '']: continue
                if name.lower() in ['nan', 'none', 'null', '']: name = ""
                if strat.lower() in ['nan', 'none', 'null', '']: strat = ""
                
                records.append({
                    'symbol': sym,
                    'name': name,
                    'market': default_market,
                    'strategy': strat
                })
            return records
    except Exception as e:
        print(f"❌ 讀取清單失敗 {url}: {e}")
    return [{'symbol': d['symbol'], 'name': d['name'], 'market': default_market, 'strategy': d.get('strategy','')} for d in default_data]

def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip().upper()
    if ticker.endswith('.TW') or ticker.endswith('.TWO'): return ticker
    if ticker.endswith('B') or ticker.endswith('C') or ticker == '009815': return f"{ticker}.TWO"
    return f"{ticker}.TW"

def analyze_ma_relation(price, ma_s1, ma_s2, ma_l1, ma_l2):
    short_term_name = "月/季線" if pd.notna(ma_s1) and ma_s2 != ma_l1 else "短中線"
    status = ""
    if pd.notna(ma_s1) and pd.notna(ma_s2) and ma_s1 > 0 and ma_s2 > 0:
        if price > ma_s1 and price > ma_s2: status += f"🟢 站穩 {short_term_name}"
        elif price < ma_s1 and price < ma_s2: status += f"🔴 {short_term_name} 之下"
        elif price > ma_s2 and price < ma_s1: status += f"🟡 守季線，受月線壓"
        elif price > ma_s1 and price < ma_s2: status += f"🔵 站月線，臨季線壓"
    else: status += "均線不足"
    status += " | "
    if pd.notna(ma_l1) and pd.notna(ma_l2) and ma_l1 > 0 and ma_l2 > 0:
        if price > ma_l1 and price > ma_l2: status += f"🟢 長線多頭"
        elif price < ma_l1 and price < ma_l2: status += f"🔴 長線空頭"
        elif price > ma_l2 and price < ma_l1: status += f"🟡 守年線"
        elif price > ma_l1 and price < ma_l2: status += f"🔵 臨年線壓"
    else: status += "均線不足"
    return status

# ==========================================
# 3. 核心技術分析引擎 (🚀 導入嚴格收盤價判定邏輯)
# ==========================================
def get_fundamental_info(sym):
    try:
        info = yf.Ticker(sym).info
        return {
            'beta': info.get('beta'),
            'trailingPE': info.get('trailingPE'),
            'forwardPE': info.get('forwardPE')
        }
    except: return {}

def get_stock_data(sym):
    is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
    for _ in range(3):
        try:
            df = yf.download(sym, period="3y", progress=False, threads=False)
            if not df.empty and len(df) >= 2:
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None: df.index = df.index.tz_convert(None)
                available_cols = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume'] if c in df.columns]
                df = df[available_cols].astype(float).dropna(subset=['Close'])
                if 'Close' not in df.columns: continue
                
                df['MA10'] = df['Close'].rolling(10, min_periods=1).mean()
                df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
                if is_tw:
                    df['季線'] = df['Close'].rolling(60, min_periods=1).mean()
                    df['半年線'] = df['Close'].rolling(120, min_periods=1).mean()
                    df['年線'] = df['Close'].rolling(240, min_periods=1).mean()
                else:
                    df['季線'] = df['Close'].rolling(50, min_periods=1).mean()
                    df['半年線'] = df['Close'].rolling(100, min_periods=1).mean()
                    df['年線'] = df['Close'].rolling(200, min_periods=1).mean()
                
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
        except: time.sleep(1)
    return None

def process_technical_analysis(sym, name, market, strategy):
    try:
        df = get_stock_data(sym)
        if df is None or df.empty or len(df) < 2: return None
            
        has_enough_weekly = False
        k_w, d_w, macd_w, macds_w = 50.0, 50.0, 0.0, 0.0
        
        try:
            agg_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
            available_cols = [c for c in agg_dict.keys() if c in df.columns]
            agg_dict = {c: agg_dict[c] for c in available_cols}
            
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
                
                k_w = float(df_w['K_w'].iloc[-1]) if pd.notna(df_w['K_w'].iloc[-1]) else 50.0
                d_w = float(df_w['D_w'].iloc[-1]) if pd.notna(df_w['D_w'].iloc[-1]) else 50.0
                macd_w = float(df_w['MACD'].iloc[-1]) if pd.notna(df_w['MACD'].iloc[-1]) else 0.0
                macds_w = float(df_w['MACD_Signal'].iloc[-1]) if pd.notna(df_w['MACD_Signal'].iloc[-1]) else 0.0
        except: pass
        
        last_p = float(df['Close'].iloc[-1])
        prev_p = float(df['Close'].iloc[-2]) if len(df) > 1 else last_p
        
        ma10 = float(df['MA10'].iloc[-1]) if pd.notna(df['MA10'].iloc[-1]) else 0.0
        ma20 = float(df['MA20'].iloc[-1]) if pd.notna(df['MA20'].iloc[-1]) else 0.0
        ma_season = float(df['季線'].iloc[-1]) if pd.notna(df['季線'].iloc[-1]) else 0.0
        ma_half = float(df['半年線'].iloc[-1]) if pd.notna(df['半年線'].iloc[-1]) else 0.0
        ma_year = float(df['年線'].iloc[-1]) if pd.notna(df['年線'].iloc[-1]) else 0.0
        
        prev_ma20 = float(df['MA20'].iloc[-2]) if len(df) > 1 and pd.notna(df['MA20'].iloc[-2]) else 0.0
        prev_ma_season = float(df['季線'].iloc[-2]) if len(df) > 1 and pd.notna(df['季線'].iloc[-2]) else 0.0

        ma_status_str = analyze_ma_relation(last_p, ma20, ma_season, ma_half, ma_year)
        is_break_ma = (last_p < ma20 and prev_p >= prev_ma20) or (last_p < ma_season and prev_p >= prev_ma_season)

        ma20_up_5d, ma_s_up_5d = False, False
        ma20_dn_5d, ma_s_dn_5d = False, False
        above_ma20_5d, below_ma20_5d = False, False
        above_mas_5d, below_mas_5d = False, False

        if len(df) >= 6:
            if pd.notna(df['MA20'].iloc[-6]):
                ma20_up_5d = all(df['MA20'].iloc[i] > df['MA20'].iloc[i-1] for i in range(-1, -6, -1))
                ma20_dn_5d = all(df['MA20'].iloc[i] < df['MA20'].iloc[i-1] for i in range(-1, -6, -1))
                above_ma20_5d = all(df['Close'].iloc[i] > df['MA20'].iloc[i] for i in range(-5, 0))
                below_ma20_5d = all(df['Close'].iloc[i] < df['MA20'].iloc[i] for i in range(-5, 0))
            if pd.notna(df['季線'].iloc[-6]):
                ma_s_up_5d = all(df['季線'].iloc[i] > df['季線'].iloc[i-1] for i in range(-1, -6, -1))
                ma_s_dn_5d = all(df['季線'].iloc[i] < df['季線'].iloc[i-1] for i in range(-1, -6, -1))
                above_mas_5d = all(df['Close'].iloc[i] > df['季線'].iloc[i] for i in range(-5, 0))
                below_mas_5d = all(df['Close'].iloc[i] < df['季線'].iloc[i] for i in range(-5, 0))

        ret_5d = 0.0
        has_ret_5d = False
        if len(df) >= 6 and pd.notna(df['Close'].iloc[-6]) and df['Close'].iloc[-6] > 0:
            ret_5d = ((last_p - df['Close'].iloc[-6]) / df['Close'].iloc[-6]) * 100
            has_ret_5d = True

        high_52w = df['High'].tail(252).max() if 'High' in df.columns else 0.0
        low_52w = df['Low'].tail(252).min() if 'Low' in df.columns else 0.0
        pos_52w = ((last_p - low_52w) / (high_52w - low_52w + 1e-9) * 100) if (high_52w - low_52w) > 0 else 50.0

        high_20d = df['High'].tail(20).max() if 'High' in df.columns else 0.0
        low_20d = df['Low'].tail(20).min() if 'Low' in df.columns else 0.0
        
        k_d = float(df['K_d'].iloc[-1]) if 'K_d' in df.columns and pd.notna(df['K_d'].iloc[-1]) else 50.0
        d_d = float(df['D_d'].iloc[-1]) if 'D_d' in df.columns and pd.notna(df['D_d'].iloc[-1]) else 50.0
        
        macd_d = float(df['MACD'].iloc[-1]) if pd.notna(df['MACD'].iloc[-1]) else 0.0
        macds_d = float(df['MACD_Signal'].iloc[-1]) if pd.notna(df['MACD_Signal'].iloc[-1]) else 0.0

        w_macd_gold, w_kd_gold = False, False
        d_macd_gold, d_kd_gold = False, False
        w_macd_death, w_kd_death = False, False
        d_macd_death, d_kd_death = False, False

        if has_enough_weekly and len(df_w) > 1:
            w_macd_gold = macd_w > macds_w and float(df_w['MACD'].iloc[-2]) <= float(df_w['MACD_Signal'].iloc[-2])
            w_kd_gold = k_w > d_w and float(df_w['K_w'].iloc[-2]) <= float(df_w['D_w'].iloc[-2])
            w_macd_death = macd_w < macds_w and float(df_w['MACD'].iloc[-2]) >= float(df_w['MACD_Signal'].iloc[-2])
            w_kd_death = k_w < d_w and float(df_w['K_w'].iloc[-2]) >= float(df_w['D_w'].iloc[-2])

        if len(df) > 1:
            d_macd_gold = macd_d > macds_d and float(df['MACD'].iloc[-2]) <= float(df['MACD_Signal'].iloc[-2])
            d_kd_gold = k_d > d_d and float(df['K_d'].iloc[-2]) <= float(df['D_d'].iloc[-2])
            d_macd_death = macd_d < macds_d and float(df['MACD'].iloc[-2]) >= float(df['MACD_Signal'].iloc[-2])
            d_kd_death = k_d < d_d and float(df['K_d'].iloc[-2]) >= float(df['D_d'].iloc[-2])

        tags = []
        bull_score = 0
        bear_score = 0

        # 🚀 嚴格版：全面改用「收盤價 (Close)」判斷創高與破底
        if 'Close' in df.columns:
            if len(df) >= 20:
                hc_20 = df['Close'].tail(20).max()
                lc_20 = df['Close'].tail(20).min()
                if last_p >= hc_20:
                    tags.append("🔥創20日收盤高")
                    bull_score += 1
                elif last_p <= lc_20:
                    tags.append("🩸破20日收盤低")
                    bear_score += 1
                    
            if len(df) >= 50:
                hc_50 = df['Close'].tail(50).max()
                lc_50 = df['Close'].tail(50).min()
                if last_p >= hc_50:
                    tags.append("🚀創50日收盤高")
                    bull_score += 2
                elif last_p <= lc_50:
                    tags.append("☠️破50日收盤低")
                    bear_score += 2
                    
            if len(df) >= 252:
                hc_252 = df['Close'].tail(252).max()
                lc_252 = df['Close'].tail(252).min()
                if last_p >= hc_252:
                    tags.append("🔥創52週收盤高")
                    bull_score += 3
                elif last_p <= lc_252:
                    tags.append("🩸破52週收盤低")
                    bear_score += 3

        has_w_macd_low_gold = w_macd_gold and (macd_w < 0)
        has_w_kd_low_gold = w_kd_gold and (k_w < 30)
        has_w_macd_high_death = w_macd_death and (macd_w > 0)
        has_w_kd_high_death = w_kd_death and (k_w > 70)

        if w_macd_gold:
            tags.append("週MACD零下金叉" if has_w_macd_low_gold else "週MACD一般金叉")
            bull_score += 4
        if w_kd_gold:
            tags.append("週KD低檔金叉" if has_w_kd_low_gold else "週KD一般金叉")
            bull_score += 3
        if d_macd_gold:
            tags.append("日MACD零下金叉" if macd_d < 0 else "日MACD一般金叉")
            bull_score += 2
        if d_kd_gold:
            tags.append("日KD低檔金叉" if k_d < 30 else "日KD一般金叉")
            bull_score += 1
            
        if ma20_up_5d and ma_s_up_5d: tags.append("月季線雙上彎≥5日"); bull_score += 2
        elif ma20_up_5d: tags.append("月線上彎≥5日"); bull_score += 1
        elif ma_s_up_5d: tags.append("季線上彎≥5日"); bull_score += 1
        
        if above_ma20_5d and above_mas_5d: tags.append("站上月季線≥5日"); bull_score += 2
        elif above_ma20_5d: tags.append("站上月線≥5日"); bull_score += 1
        elif above_mas_5d: tags.append("站上季線≥5日"); bull_score += 1
        
        if has_ret_5d and ret_5d >= 5.0: tags.append(f"近5日上漲{ret_5d:.1f}%"); bull_score += 1

        if w_macd_death:
            tags.append("週MACD零上死叉" if has_w_macd_high_death else "週MACD一般死叉")
            bear_score += 4
        if w_kd_death:
            tags.append("週KD高檔死叉" if has_w_kd_high_death else "週KD一般死叉")
            bear_score += 3
        if d_macd_death:
            tags.append("日MACD零上死叉" if macd_d > 0 else "日MACD一般死叉")
            bear_score += 2
        if d_kd_death:
            tags.append("日KD高檔死叉" if k_d > 70 else "日KD一般死叉")
            bear_score += 1
            
        if is_break_ma: tags.append("跌破短中線"); bear_score += 1
        
        if ma20_dn_5d and ma_s_dn_5d: tags.append("月季線雙下彎≥5日"); bear_score += 2
        elif ma20_dn_5d: tags.append("月線下彎≥5日"); bear_score += 1
        elif ma_s_dn_5d: tags.append("季線下彎≥5日"); bear_score += 1
        
        if below_ma20_5d and below_mas_5d: tags.append("跌破月季線≥5日"); bear_score += 2
        elif below_ma20_5d: tags.append("跌破月線≥5日"); bear_score += 1
        elif below_mas_5d: tags.append("跌破季線≥5日"); bear_score += 1
        
        if has_ret_5d and ret_5d <= -5.0: tags.append(f"近5日下跌{abs(ret_5d):.1f}%"); bear_score += 1

        if high_52w > 0 and (high_52w - last_p) / high_52w >= 0.15:
            tags.append(f"近高點回落{((high_52w - last_p) / high_52w)*100:.1f}%"); bear_score += 2
        if high_20d > 0 and (high_20d - last_p) / high_20d >= 0.10:
            tags.append(f"20日回落{((high_20d - last_p) / high_20d)*100:.1f}%"); bear_score += 1
            
        if len(df) >= 20 and high_20d > 0 and low_20d > 0:
            amp_20d = (high_20d - low_20d) / low_20d
            if amp_20d <= 0.07: tags.append(f"20日窄幅盤整")

        # 這裡的 action 僅作為總表的快速參考，實際推播將使用嚴格篩選邏輯
        is_strong_buy_eligible = has_w_macd_low_gold or has_w_kd_low_gold
        is_strong_sell_eligible = has_w_macd_high_death or has_w_kd_high_death

        if bull_score > bear_score:
            if bull_score >= 3 and is_strong_buy_eligible:
                action = "[🚀 強勢買進]"
            else:
                action = "[📈 短多轉折]"
        elif bear_score > bull_score:
            if bear_score >= 3 and is_strong_sell_eligible:
                action = "[🛑 強制賣出]"
            else:
                action = "[⚠️ 弱勢減碼]"
        else:
            if bull_score == 0 and bear_score == 0: 
                action = "[➖ 趨勢延續]"
            elif bull_score >= 3 and is_strong_buy_eligible: 
                action = "[⚔️ 多空交戰(偏強)]"
            elif bear_score >= 3 and is_strong_sell_eligible:
                action = "[⚔️ 多空交戰(偏弱)]"
            elif bull_score > 0:
                action = "[⚔️ 多空交戰(震盪)]"
            else:
                action = "[⚔️ 多空交戰]"

        alert_str = f"{action} " + ", ".join(tags) if tags else action

        f_info = get_fundamental_info(sym)
        pe_val = f_info.get('trailingPE')
        try:
            pe_val = float(pe_val)
            pe_str = f"{pe_val:.1f}" if pd.notna(pe_val) else "無"
        except:
            pe_val = None
            pe_str = "無"
            
        beta_val = f_info.get('beta')
        try:
            beta_str = f"{float(beta_val):.2f}" if pd.notna(float(beta_val)) else "無"
        except:
            beta_str = "無"

        return {
            "市場": market, "標的": f"{name} ({sym})", "代號": sym.split('.')[0], 
            "狀態警示": alert_str, "🚨警示": alert_str, "均線位階": ma_status_str,
            "52週位置": f"{pos_52w:.1f} %", "Beta": beta_str, 
            "日KD": f"K:{k_d:.1f}/D:{d_d:.1f}",
            "週KD": f"K:{k_w:.1f}/D:{d_w:.1f}",
            "日MACD": f"DIF:{macd_d:.2f}",
            "週MACD": f"DIF:{macd_w:.2f}",
            "P/E": pe_str, "收盤價": last_p, "MA20": ma20, "季線": ma_season,
            "tags": tags, "bull_score": bull_score, "bear_score": bear_score, "action": action,
            "_raw_pe": pe_val, "_sym": sym, "_name": name, "策略": strategy
        }
    except Exception as e:
        print(f"處理 {sym} 發生錯誤: {e}")
        return None

# ==========================================
# 4. Google Sheets 資料庫寫入防呆保護
# ==========================================
def update_technical_db(ta_results):
    if not GCP_CREDENTIALS or not TECHNICAL_DB_URL:
        print("⚠️ 未設定 GCP_CREDENTIALS 或 TECHNICAL_DB_URL，略過寫入資料庫。")
        return
    try:
        print("開始連線寫入 Technical_DB...")
        creds_dict = json.loads(GCP_CREDENTIALS)
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
        sh = gc.open_by_url(TECHNICAL_DB_URL)
        worksheet = sh.sheet1
        
        if not ta_results:
            print("無技術分析結果可寫入。")
            return
            
        df = pd.DataFrame(ta_results)
        
        if 'tags' in df.columns:
            df['tags'] = df['tags'].apply(lambda x: ", ".join(x) if isinstance(x, list) else x)
            
        clean_df = df.fillna("").astype(str)
        data_to_write = [clean_df.columns.values.tolist()] + clean_df.values.tolist()
        
        worksheet.clear()
        try:
            worksheet.update(values=data_to_write, range_name="A1")
        except TypeError:
            worksheet.update("A1", data_to_write)
            
        print("✅ 成功同步所有指標至 Technical_DB！")
    except Exception as e:
        print(f"❌ 寫入 Technical_DB 失敗: {e}")

# ==========================================
# 5. Telegram 訊息發送與主程式 (🚀 導入嚴格篩選推播邏輯)
# ==========================================
def send_tg_text(text):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("未設定 Telegram 變數，跳過發送。")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code == 200:
            print("✅ 成功發送 TG 訊息。")
        else:
            print(f"❌ TG 發送失敗：{res.text}")
    except Exception as e:
        print(f"❌ TG 請求發生錯誤: {e}")

def format_items(items):
    if not items: return "<i>> 👻 目前無符合條件標的，皆已隱藏</i>"
    res_str = ""
    for x in items:
        tags_str = ", ".join(x['tags'])
        raw_name = str(x.get('_name', '')).strip()
        sym = str(x.get('_sym', '')).strip()
        clean_sym = sym.split('.')[0] 
        
        if raw_name.lower() in ['nan', 'none', '']:
            display_title = clean_sym
        else:
            display_title = f"{raw_name} ({clean_sym})"
            
        safe_name = display_title.replace('<', '').replace('>', '').replace('&', 'and')
        bull = x.get('bull_score', 0)
        bear = x.get('bear_score', 0)
        pe = x.get('P/E', '無')
        
        # 🚀 在 TG 訊息中加入多空分數直觀顯示
        res_str += f"• <b>{safe_name}</b> (多:{bull} 空:{bear} | PE:{pe})\n   └ <code>[{tags_str}]</code>\n"
    return res_str

def main():
    print(f"開始執行台美股盤後掃描... {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    portfolio_tw = get_sheet_data(SHEET_CSV_TW_URL, DEFAULT_TW, '台股')
    portfolio_us = get_sheet_data(SHEET_CSV_US_URL, DEFAULT_US, '美股')
    
    all_results = []
    
    for item in portfolio_tw:
        sym = get_yf_ticker_tw(item['symbol'])
        res = process_technical_analysis(sym, item['name'], item['market'], item['strategy'])
        if res:
            all_results.append(res)
            time.sleep(0.5)

    for item in portfolio_us:
        sym = item['symbol']
        res = process_technical_analysis(sym, item['name'], item['market'], item['strategy'])
        if res:
            all_results.append(res)
            time.sleep(0.5)

    update_technical_db(all_results)

    # 🚀 Telegram 嚴格推播分類邏輯
    for market in ['台股', '美股']:
        market_results = [x for x in all_results if x['市場'] == market]
        if not market_results: continue
        
        short_term_res = [x for x in market_results if '短' in str(x.get('策略', ''))]
        long_term_res = [x for x in market_results if '短' not in str(x.get('策略', ''))]
        
        def has_tag(item, keywords):
            tags = item.get('tags', [])
            return any(any(kw in t for kw in keywords) for t in tags)
            
        # 1. ⚡ 短線區分類
        short_bull, short_bear, short_cons = [], [], []
        for x in short_term_res:
            bull = x['bull_score']
            bear = x['bear_score']
            is_bull = has_tag(x, ['創20日收盤高', '創50日收盤高']) or (bull >= 2 and bear == 0)
            is_bear = has_tag(x, ['破20日收盤低', '破50日收盤低']) or (bear >= 2 and bull == 0)
            is_cons = not is_bull and not is_bear and has_tag(x, ['20日窄幅盤整'])
            
            x['sort_score'] = bull - bear if is_bull else (bear - bull if is_bear else 0)
            
            if is_bull: short_bull.append(x)
            elif is_bear: short_bear.append(x)
            elif is_cons: short_cons.append(x)

        # 2. 📈 長線區分類
        long_bull, long_bear, long_base = [], [], []
        for x in long_term_res:
            bull = x['bull_score']
            bear = x['bear_score']
            pos_str = str(x.get('52週位置', '50%')).replace('%', '').strip()
            try: pos = float(pos_str)
            except: pos = 50.0
                
            is_bull = has_tag(x, ['創52週收盤高']) or (bull >= 3 and has_tag(x, ['週KD低檔金叉', '週MACD零下金叉'])) or (bull >= 3 and bear == 0)
            is_bear = has_tag(x, ['破52週收盤低']) or (bear >= 3 and has_tag(x, ['週KD高檔死叉', '週MACD零上死叉'])) or (bear >= 3 and bull == 0)
            is_base = not is_bull and not is_bear and not has_tag(x, ['創52週', '破52週']) and pos <= 30.0 and abs(bull - bear) <= 1
            
            x['sort_score'] = bull - bear if is_bull else (bear - bull if is_bear else 0)
            
            if is_bull: long_bull.append(x)
            elif is_bear: long_bear.append(x)
            elif is_base: long_base.append(x)
            
        # 3. 排序 (多空淨分優先，PE次之)
        def sort_func(x):
            pe = x.get('_raw_pe')
            return (-x['sort_score'], pe if pe is not None and not pd.isna(pe) else 9999)
            
        short_bull.sort(key=sort_func)
        short_bear.sort(key=sort_func)
        short_cons.sort(key=lambda x: (x.get('_raw_pe') if x.get('_raw_pe') is not None else 9999))
        
        long_bull.sort(key=sort_func)
        long_bear.sort(key=sort_func)
        long_base.sort(key=lambda x: (x.get('_raw_pe') if x.get('_raw_pe') is not None else 9999))
        
        # 4. 組裝 Telegram 訊息
        msg = f"📁 <b>【{market}】盤後技術判定</b>\n\n"
        has_content = False
        
        if short_bull or short_bear or short_cons:
            msg += f"⚡ <b>短線進出專區 (嚴格篩選版)</b>\n"
            if short_bull: msg += f"🚀 <b>偏多 / 創高動能</b>\n{format_items(short_bull[:10])}\n"
            if short_bear: msg += f"🩸 <b>偏空 / 破底風險</b>\n{format_items(short_bear[:10])}\n"
            if short_cons: msg += f"⚖️ <b>盤整 / 壓縮區</b>\n{format_items(short_cons[:10])}\n"
            has_content = True
            
        if long_bull or long_bear or long_base:
            msg += f"📈 <b>波段與長期投資 (Top 10)</b>\n"
            if long_bull: msg += f"🔥 <b>長多波段 / 攻擊轉折</b>\n{format_items(long_bull[:10])}\n"
            if long_bear: msg += f"🛑 <b>波段轉弱 / 長期風險</b>\n{format_items(long_bear[:10])}\n"
            if long_base: msg += f"⚖️ <b>長線築底 / 壓縮沉澱</b>\n{format_items(long_base[:10])}\n"
            has_content = True
            
        if has_content:
            send_tg_text(msg.strip())
            time.sleep(1)
        
    print("🎉 掃描作業完成！")

if __name__ == "__main__":
    main()
