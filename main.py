import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import os
import time
import json
import matplotlib
matplotlib.use('Agg')
import mplfinance as mpf
from datetime import datetime
import warnings
import gspread
from google.oauth2.service_account import Credentials

warnings.filterwarnings('ignore')

# --- 1. 配置與環境變數 ---
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

# --- 2. 資料載入與輔助函式 ---
def get_sheet_data(url, default_data, default_market):
    if not url:
        return [{'symbol': d['symbol'], 'name': d['name'], 'market': default_market, 'strategy': d.get('strategy', '')} for d in default_data]
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
    return [{'symbol': d['symbol'], 'name': d['name'], 'market': default_market, 'strategy': d.get('strategy', '')} for d in default_data]

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

def get_fundamental_info(sym):
    try:
        info = yf.Ticker(sym).info
        return {
            'beta': info.get('beta'),
            'trailingPE': info.get('trailingPE'),
            'forwardPE': info.get('forwardPE')
        }
    except: return {}

# --- 3. 核心技術分析引擎 ---
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
                
                df['MA5'] = df['Close'].rolling(5, min_periods=1).mean()
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
                df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
                return df
        except: time.sleep(1)
    return None

def process_technical_analysis(sym, name, market, strategy):
    try:
        df = get_stock_data(sym)
        if df is None or df.empty or len(df) < 2: return None
            
        has_enough_weekly = False
        k_w, d_w, macd_w, macds_w, macd_hist_w = 50.0, 50.0, 0.0, 0.0, 0.0
        
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
                df_w['MACD_Hist'] = df_w['MACD'] - df_w['MACD_Signal']
                
                k_w = float(df_w['K_w'].iloc[-1]) if pd.notna(df_w['K_w'].iloc[-1]) else 50.0
                d_w = float(df_w['D_w'].iloc[-1]) if pd.notna(df_w['D_w'].iloc[-1]) else 50.0
                macd_w = float(df_w['MACD'].iloc[-1]) if pd.notna(df_w['MACD'].iloc[-1]) else 0.0
                macds_w = float(df_w['MACD_Signal'].iloc[-1]) if pd.notna(df_w['MACD_Signal'].iloc[-1]) else 0.0
                macd_hist_w = float(df_w['MACD_Hist'].iloc[-1]) if pd.notna(df_w['MACD_Hist'].iloc[-1]) else 0.0
        except: pass
        
        last_p = float(df['Close'].iloc[-1])
        prev_p = float(df['Close'].iloc[-2]) if len(df) > 1 else last_p
        
        ma5 = float(df['MA5'].iloc[-1]) if pd.notna(df['MA5'].iloc[-1]) else 0.0
        ma10 = float(df['MA10'].iloc[-1]) if pd.notna(df['MA10'].iloc[-1]) else 0.0
        ma20 = float(df['MA20'].iloc[-1]) if pd.notna(df['MA20'].iloc[-1]) else 0.0
        ma_season = float(df['季線'].iloc[-1]) if pd.notna(df['季線'].iloc[-1]) else 0.0
        ma_half = float(df['半年線'].iloc[-1]) if pd.notna(df['半年線'].iloc[-1]) else 0.0
        ma_year = float(df['年線'].iloc[-1]) if pd.notna(df['年線'].iloc[-1]) else 0.0
        
        prev_ma5 = float(df['MA5'].iloc[-2]) if len(df) > 1 and pd.notna(df['MA5'].iloc[-2]) else 0.0
        prev_ma10 = float(df['MA10'].iloc[-2]) if len(df) > 1 and pd.notna(df['MA10'].iloc[-2]) else 0.0
        prev_ma20 = float(df['MA20'].iloc[-2]) if len(df) > 1 and pd.notna(df['MA20'].iloc[-2]) else 0.0
        prev_ma_season = float(df['季線'].iloc[-2]) if len(df) > 1 and pd.notna(df['季線'].iloc[-2]) else 0.0

        ma_status_str = analyze_ma_relation(last_p, ma20, ma_season, ma_half, ma_year)
        
        ma20_up = ma20 > prev_ma20
        ma60_up = ma_season > prev_ma_season
        ma20_up_5d, ma_s_up_5d = False, False
        if len(df) >= 6:
            if pd.notna(df['MA20'].iloc[-6]):
                ma20_up_5d = all(df['MA20'].iloc[i] > df['MA20'].iloc[i-1] for i in range(-1, -6, -1))
            if pd.notna(df['季線'].iloc[-6]):
                ma_s_up_5d = all(df['季線'].iloc[i] > df['季線'].iloc[i-1] for i in range(-1, -6, -1))

        high_52w = df['High'].tail(252).max() if 'High' in df.columns else 0.0
        low_52w = df['Low'].tail(252).min() if 'Low' in df.columns else 0.0
        pos_52w = ((last_p - low_52w) / (high_52w - low_52w + 1e-9) * 100) if (high_52w - low_52w) > 0 else 50.0

        k_d = float(df['K_d'].iloc[-1]) if 'K_d' in df.columns and pd.notna(df['K_d'].iloc[-1]) else 50.0
        d_d = float(df['D_d'].iloc[-1]) if 'D_d' in df.columns and pd.notna(df['D_d'].iloc[-1]) else 50.0
        macd_d = float(df['MACD'].iloc[-1]) if pd.notna(df['MACD'].iloc[-1]) else 0.0
        macds_d = float(df['MACD_Signal'].iloc[-1]) if pd.notna(df['MACD_Signal'].iloc[-1]) else 0.0
        macd_hist_d = float(df['MACD_Hist'].iloc[-1]) if pd.notna(df['MACD_Hist'].iloc[-1]) else 0.0

        w_macd_gold, w_kd_gold = False, False
        d_macd_gold, d_kd_gold = False, False
        w_macd_death, w_kd_death = False, False
        d_macd_death, d_kd_death = False, False
        w_osc_turn_red, d_osc_turn_red = False, False

        if has_enough_weekly and len(df_w) > 1:
            w_macd_gold = macd_w > macds_w and float(df_w['MACD'].iloc[-2]) <= float(df_w['MACD_Signal'].iloc[-2])
            w_kd_gold = k_w > d_w and float(df_w['K_w'].iloc[-2]) <= float(df_w['D_w'].iloc[-2])
            w_macd_death = macd_w < macds_w and float(df_w['MACD'].iloc[-2]) >= float(df_w['MACD_Signal'].iloc[-2])
            w_kd_death = k_w < d_w and float(df_w['K_w'].iloc[-2]) >= float(df_w['D_w'].iloc[-2])
            w_osc_turn_red = macd_hist_w > 0 and float(df_w['MACD_Hist'].iloc[-2]) <= 0

        if len(df) > 1:
            d_macd_gold = macd_d > macds_d and float(df['MACD'].iloc[-2]) <= float(df['MACD_Signal'].iloc[-2])
            d_kd_gold = k_d > d_d and float(df['K_d'].iloc[-2]) <= float(df['D_d'].iloc[-2])
            d_macd_death = macd_d < macds_d and float(df['MACD'].iloc[-2]) >= float(df['MACD_Signal'].iloc[-2])
            d_kd_death = k_d < d_d and float(df['K_d'].iloc[-2]) >= float(df['D_d'].iloc[-2])
            d_osc_turn_red = macd_hist_d > 0 and float(df['MACD_Hist'].iloc[-2]) <= 0

        tags = []
        bull_score = 0
        bear_score = 0
        
        # 🚀 【多方加分模組】
        if d_osc_turn_red:
            tags.append("日OSC翻紅")
            bull_score += 1
            
        if d_kd_gold:
            if k_d < 30:
                tags.append("日KD低檔金叉")
                bull_score += 2
            else:
                tags.append("日KD一般金叉")
                bull_score += 1
                
        if d_macd_gold:
            tags.append("日MACD零下金叉" if macd_d < 0 else "日MACD一般金叉")
            bull_score += 2
            
        if w_kd_gold:
            tags.append("週KD低檔金叉" if k_w < 30 else "週KD一般金叉")
            bull_score += 3
            
        if w_macd_gold:
            tags.append("週MACD零下金叉" if macd_w < 0 else "週MACD一般金叉")
            bull_score += 4

        if ma20 > 0 and ma5 > ma10 and ma10 > ma20:
            tags.append("三線多頭排列")
            bull_score += 2
            
        if ma5 > ma10 and prev_ma5 <= prev_ma10:
            tags.append("短線均線金叉")
            bull_score += 1
            
        if last_p > ma20 and prev_p <= prev_ma20:
            tags.append("剛站上月線")
            bull_score += 2
            
        if last_p > ma5 and prev_p <= prev_ma5 and ma20_up and k_d < 50:
            tags.append("回後重新站上MA5")
            bull_score += 2
            
        if ma20_up_5d and ma_s_up_5d:
            tags.append("月季線雙上彎≥5日")
            bull_score += 2
        elif ma20_up_5d:
            tags.append("月線上彎≥5日")
            bull_score += 1
        elif ma_s_up_5d:
            tags.append("季線上彎≥5日")
            bull_score += 1

        if 'Close' in df.columns:
            if len(df) >= 20:
                hc_20 = df['Close'].tail(20).max()
                if last_p >= hc_20: tags.append("🔥創20日收高")
            if len(df) >= 50:
                hc_50 = df['Close'].tail(50).max()
                if last_p >= hc_50: tags.append("🚀創50日收高")
            if len(df) >= 252:
                hc_252 = df['Close'].tail(252).max()
                if last_p >= hc_252: tags.append("🔥創52週收高")

        # 🚀 【空方加分模組】
        if 'Close' in df.columns:
            if len(df) >= 20:
                lc_20 = df['Close'].tail(20).min()
                if last_p <= lc_20: tags.append("🩸破20日收低")
            if len(df) >= 50:
                lc_50 = df['Close'].tail(50).min()
                if last_p <= lc_50: tags.append("☠️破50日收低")
            if len(df) >= 252:
                lc_252 = df['Close'].tail(252).min()
                if last_p <= lc_252: tags.append("🩸破52週收低")

        if k_d > 70 and last_p < ma5 and prev_p >= prev_ma5:
            tags.append("高檔跌破MA5")
            bear_score += 2

        is_protected_by_ma = (last_p > ma10 and last_p > ma20)
        
        if d_kd_death:
            if is_protected_by_ma:
                tags.append("日KD死叉(均線保護)")
                bear_score += 0
            else:
                tags.append("日KD高檔死叉" if k_d > 70 else "日KD一般死叉")
                bear_score += 1
                
        if d_macd_death:
            if is_protected_by_ma:
                tags.append("日MACD死叉(均線保護)")
                bear_score += 0
            else:
                tags.append("日MACD零上死叉" if macd_d > 0 else "日MACD一般死叉")
                bear_score += 2
                
        if w_kd_death:
            tags.append("週KD高檔死叉" if k_w > 70 else "週KD一般死叉")
            bear_score += 3
            
        if w_macd_death:
            tags.append("週MACD零上死叉" if macd_w > 0 else "週MACD一般死叉")
            bear_score += 4

        if last_p < ma20 and prev_p >= prev_ma20 and df['High'].iloc[-1] < ma20:
            if ma60_up:
                tags.append("跌破月線(季線護體)")
                bear_score += 1
            else:
                tags.append("實體跌破月線")
                bear_score += 3
        
        below_ma20_3d = False
        if len(df) >= 3 and pd.notna(df['MA20'].iloc[-3]):
            below_ma20_3d = all(df['Close'].iloc[i] < df['MA20'].iloc[i] for i in range(-3, 0))
            if below_ma20_3d:
                tags.append("連3日破月線")
                bear_score += 3

        if ma20 > 0 and ma5 < ma10 and ma10 < ma20:
            tags.append("三線空頭排列")
            bear_score += 3

        # 動作標籤判定
        is_strong_buy_eligible = (w_macd_gold and macd_w < 0) or (w_kd_gold and k_w < 30) or (bull_score >= 3 and bear_score == 0)
        is_strong_sell_eligible = (w_macd_death and macd_w > 0) or (w_kd_death and k_w > 70) or (bear_score >= 3 and bull_score == 0)

        if bull_score > bear_score:
            if bull_score >= 3 and is_strong_buy_eligible: action = "[🚀 強勢買進]"
            else: action = "[📈 短多轉折]"
        elif bear_score > bull_score:
            if bear_score >= 3 and is_strong_sell_eligible: action = "[🛑 強制賣出]"
            else: action = "[⚠️ 弱勢減碼]"
        else:
            if bull_score == 0 and bear_score == 0: action = "[➖ 趨勢延續]"
            elif bull_score >= 3 and is_strong_buy_eligible: action = "[⚔️ 多空交戰(偏強)]"
            elif bear_score >= 3 and is_strong_sell_eligible: action = "[⚔️ 多空交戰(偏弱)]"
            elif bull_score > 0: action = "[⚔️ 多空交戰(震盪)]"
            else: action = "[⚔️ 多空交戰]"

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
            "_raw_pe": pe_val, "_sym": sym, "_name": name, "策略": strategy, "df": df
        }
    except Exception as e:
        print(f"處理 {sym} 發生錯誤: {e}")
        return None

# --- 4. Google Sheets 資料庫寫入防呆保護 ---
def update_technical_db(ta_results):
    if not GCP_CREDENTIALS or not TECHNICAL_DB_URL:
        print("⚠️ 未設定 GCP_CREDENTIALS 或 TECHNICAL_DB_URL，略過寫入資料庫。")
        return
    try:
        print("開始連線寫入 Technical_DB...")
        creds_dict = json.loads(GCP_CREDENTIALS)
