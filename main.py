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

warnings.filterwarnings('ignore')

# --- 1. 配置與環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
SHEET_CSV_TW_URL = os.getenv('SHEET_CSV_TW_URL')
SHEET_CSV_US_URL = os.getenv('SHEET_CSV_US_URL')

# 預設備用清單
DEFAULT_TW = [
    {'symbol': '2330.TW', 'name': '台積電'},
    {'symbol': '2317.TW', 'name': '鴻海'},
    {'symbol': '2454.TW', 'name': '聯發科'},
    {'symbol': '2308.TW', 'name': '台達電'},
    {'symbol': '3008.TW', 'name': '大立光'},
    {'symbol': '0050.TW', 'name': '元大台灣50'},
    {'symbol': '0056.TW', 'name': '元大高股息'},
    {'symbol': '00878.TW', 'name': '國泰永續高股息'},
    {'symbol': '00713.TW', 'name': '元大台灣高息低波'},
    {'symbol': '00919.TW', 'name': '群益台灣精選高息'},
    {'symbol': '00922.TW', 'name': '國泰台灣領袖50'},
    {'symbol': '00923.TW', 'name': '群益台灣ESG低碳'},
    {'symbol': '00830.TW', 'name': '國泰費城半導體'},
    {'symbol': '00981A.TW', 'name': '主動統一台股增長'},
    {'symbol': '00988A.TW', 'name': '主動統一全球創新'},
    {'symbol': '009815.TWO', 'name': '大華美國MAG7+'}
]

DEFAULT_US = {
    'NVDA': '輝達 Nvidia',
    'MSFT': '微軟 Microsoft',
    'GOOGL': '谷歌 Google',
    'VOO': '標普500 VOO',
    'QQQ': '納斯達克 QQQ',
    'VT': 'Vanguard 全球股票 ETF',
    'META': 'Meta'
}

# --- 2. 資料載入與技術指標計算 (100% 對齊 Dashboard) ---
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip().upper()
    if ticker.endswith(('.TW', '.TWO')): return ticker
    return f"{ticker}.TWO" if (ticker.endswith(('B', 'C')) or ticker == '009815') else f"{ticker}.TW"

def load_csv_list(url, is_tw=True):
    try:
        if not url: return [] if is_tw else {}
        response = requests.get(url, timeout=30)
        df = pd.read_csv(io.StringIO(response.text), on_bad_lines='skip')
        df.columns = [str(c).strip().replace('\ufeff', '').lower() for c in df.columns]
        data = [] if is_tw else {}
        for _, row in df.iterrows():
            row_dict = {str(k).strip().lower(): v for k, v in row.items()}
            ticker = str(row_dict.get('ticker', '')).strip().upper()
            name = str(row_dict.get('name', ticker)).strip()
            if not ticker or ticker == 'NAN': continue
            if is_tw:
                data.append({'symbol': get_yf_ticker_tw(ticker), 'name': name, 'raw_ticker': ticker})
            else:
                data[ticker] = name
        return data
    except: return [] if is_tw else {}

def get_stock_data(sym, is_tw):
    try:
        df = yf.download(sym, period="3y", progress=False, threads=False)
        if df.empty or len(df) < 2: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None: df.index = df.index.tz_convert(None)
        
        available_cols = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume'] if c in df.columns]
        df = df[available_cols].astype(float).dropna(subset=['Close'])
        if 'Close' not in df.columns: return None
        
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
    except: return None

# --- 3. Telegram 傳送模組 ---
def send_tg_text(msg):
    if not TG_TOKEN or not TG_CHAT_ID or not msg.strip(): return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        if len(msg) > 3800:
            chunks, curr = [], ""
            for line in msg.split('\n'):
                if len(curr) + len(line) + 1 > 3800:
                    chunks.append(curr); curr = line + '\n'
                else: curr += line + '\n'
            if curr.strip(): chunks.append(curr)
            for chunk in chunks:
                requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': chunk, 'parse_mode': 'HTML', 'disable_web_page_preview': True}, timeout=15)
                time.sleep(1)
        else:
            requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML', 'disable_web_page_preview': True}, timeout=15)
    except Exception as e: print(f"❌ Telegram 發送失敗: {e}")

def send_tg_album(image_paths, caption=""):
    if not TG_TOKEN or not TG_CHAT_ID or not image_paths: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMediaGroup"
    media, files = [], {}
    for i, path in enumerate(image_paths):
        file_key = f"photo_{i}"
        m_item = {"type": "photo", "media": f"attach://{file_key}"}
        if i == 0 and caption: m_item.update({"caption": caption, "parse_mode": "HTML"})
        media.append(m_item)
        files[file_key] = open(path, 'rb')
    try:
        requests.post(url, data={'chat_id': TG_CHAT_ID, 'media': json.dumps(media)}, files=files, timeout=30)
    except: pass
    finally:
        for f in files.values(): f.close()

# --- 4. 核心邏輯與評分 (100% 複製 Dashboard 演算法) ---
def process_target(sym, name, market='台股'):
    try:
        is_tw = (market == '台股')
        df = get_stock_data(sym, is_tw)
        if df is None or df.empty or len(df) < 2: return None

        has_enough_weekly = False
        k_w, d_w, macd_w, macds_w = 0.0, 0.0, 0.0, 0.0
        
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
        
        ma20 = float(df['MA20'].iloc[-1]) if pd.notna(df['MA20'].iloc[-1]) else 0.0
        ma_season = float(df['季線'].iloc[-1]) if pd.notna(df['季線'].iloc[-1]) else 0.0
        prev_ma20 = float(df['MA20'].iloc[-2]) if len(df) > 1 and pd.notna(df['MA20'].iloc[-2]) else 0.0
        prev_ma_season = float(df['季線'].iloc[-2]) if len(df) > 1 and pd.notna(df['季線'].iloc[-2]) else 0.0

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
        bull_score, bear_score = 0, 0

        # Dashboard 精確計分邏輯
        has_w_macd_low_gold = w_macd_gold and (macd_w < 0)
        has_w_kd_low_gold = w_kd_gold and (k_w < 30)
        has_w_macd_high_death = w_macd_death and (macd_w > 0)
        has_w_kd_high_death = w_kd_death and (k_w > 70)

        if w_macd_gold: tags.append("週MACD零下金叉" if has_w_macd_low_gold else "週MACD一般金叉"); bull_score += 4
        if w_kd_gold: tags.append("週KD低檔金叉" if has_w_kd_low_gold else "週KD一般金叉"); bull_score += 3
        if d_macd_gold: tags.append("日MACD零下金叉" if macd_d < 0 else "日MACD一般金叉"); bull_score += 2
        if d_kd_gold: tags.append("日KD低檔金叉" if k_d < 30 else "日KD一般金叉"); bull_score += 1
            
        if ma20_up_5d and ma_s_up_5d: tags.append("月季線雙上彎≥5日"); bull_score += 2
        elif ma20_up_5d: tags.append("月線上彎≥5日"); bull_score += 1
        elif ma_s_up_5d: tags.append("季線上彎≥5日"); bull_score += 1
        
        if above_ma20_5d and above_mas_5d: tags.append("站上月季線≥5日"); bull_score += 2
        elif above_ma20_5d: tags.append("站上月線≥5日"); bull_score += 1
        elif above_mas_5d: tags.append("站上季線≥5日"); bull_score += 1
        
        if has_ret_5d and ret_5d >= 5.0: tags.append(f"近5日上漲{ret_5d:.1f}%"); bull_score += 1

        if w_macd_death: tags.append("週MACD零上死叉" if has_w_macd_high_death else "週MACD一般死叉"); bear_score += 4
        if w_kd_death: tags.append("週KD高檔死叉" if has_w_kd_high_death else "週KD一般死叉"); bear_score += 3
        if d_macd_death: tags.append("日MACD零上死叉" if macd_d > 0 else "日MACD一般死叉"); bear_score += 2
        if d_kd_death: tags.append("日KD高檔死叉" if k_d > 70 else "日KD一般死叉"); bear_score += 1
            
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
            if amp_20d <= 0.07: tags.append(f"💤20日窄幅盤整")

        # 🚀 嚴謹判定 Dashboard 行為
        is_strong_buy_eligible = has_w_macd_low_gold or has_w_kd_low_gold
        is_strong_sell_eligible = has_w_macd_high_death or has_w_kd_high_death

        action = ""
        if bull_score > bear_score:
            if bull_score >= 3 and is_strong_buy_eligible: action = "[🚀 強勢買進]"
            else: action = "[📈 短多轉折]"
        elif bear_score > bull_score:
            if bear_score >= 3 and is_strong_sell_eligible: action = "[🛑 強制賣出]"
            else: action = "[⚠️ 弱勢減碼]"

        pe_val, pe_str = 999.0, "無"
        try:
            t_pe = yf.Ticker(sym).info.get('trailingPE')
            if isinstance(t_pe, (int, float)) and not np.isnan(t_pe) and t_pe > 0:
                pe_val, pe_str = float(t_pe), f"{t_pe:.1f}"
        except: pass

        return {
            'symbol': sym, 'name': name, 'category': market, 'pe': pe_val, 'pe_str': pe_str, 'tags': tags,
            'bull_score': bull_score, 'bear_score': bear_score, 'action': action, 'df': df
        }
    except Exception as e:
        print(f"解析 {sym} ({name}) 時發生錯誤: {e}")
        return None

def format_items(items):
    return "\n".join([f"• <b>{x['name']} (PE:{x['pe_str']})</b>\n  └ <code>[{', '.join(x['tags'])}]</code>" for x in items])

def generate_kline_chart(res):
    sym, name, df = res['symbol'], res['name'], res['df'].tail(120)
    fn = f"chart_{sym.replace('^','').replace('.','_')}.png"
    ap = []
    if 'MA20' in df and pd.notna(df['MA20'].iloc[-1]): ap.append(mpf.make_addplot(df['MA20'], color='blue', width=1.0))
    if '季線' in df and pd.notna(df['季線'].iloc[-1]): ap.append(mpf.make_addplot(df['季線'], color='orange', width=1.0))
    if '半年線' in df and pd.notna(df['半年線'].iloc[-1]): ap.append(mpf.make_addplot(df['半年線'], color='green', width=1.2, linestyle='--'))
    if '年線' in df and pd.notna(df['年線'].iloc[-1]): ap.append(mpf.make_addplot(df['年線'], color='red', width=1.2, linestyle='--'))
    try:
        mpf.plot(df, type='candle', style='charles', addplot=ap, title=f"{name} ({sym})", savefig=fn)
        return fn
    except: return None

# --- 5. 主程式 ---
def main():
    now_str = datetime.now().strftime('%Y/%m/%d')
    print(f"🚀 啟動盤前股市掃描 ({now_str})...")

    targets = []
    for item in (load_csv_list(SHEET_CSV_TW_URL, True) or DEFAULT_TW): targets.append((item['symbol'], item['name'], '台股'))
    for ticker, name in (load_csv_list(SHEET_CSV_US_URL, False) or DEFAULT_US).items(): targets.append((ticker, name, '美股'))

    categorized = {
        '台股': {'strong_buy': [], 'short_bull': [], 'forced_sell': [], 'weak_reduce': []},
        '美股': {'strong_buy': [], 'short_bull': [], 'forced_sell': [], 'weak_reduce': []}
    }
    all_bull_candidates = []

    for sym, name, market in targets:
        res = process_target(sym, name, market)
        if res:
            cat = res['category']
            act = res['action']
            if "[🚀 強勢買進]" in act:
                categorized[cat]['strong_buy'].append(res)
                all_bull_candidates.append(res)
            elif "[📈 短多轉折]" in act:
                categorized[cat]['short_bull'].append(res)
                all_bull_candidates.append(res)
            elif "[🛑 強制賣出]" in act: categorized[cat]['forced_sell'].append(res)
            elif "[⚠️ 弱勢減碼]" in act: categorized[cat]['weak_reduce'].append(res)
        time.sleep(0.2)

    # --- 💡 統一發送第 1 通：所有文字報告整合 ---
    combined_msg = f"🏆 <b>盤前亮點摘要與警示 ({now_str})</b>\n\n"
    has_content = False

    for cat in ['台股', '美股']:
        data = categorized[cat]
        sb = sorted(data['strong_buy'], key=lambda x: (-x['bull_score'], x['pe']))[:10]
        shb = sorted(data['short_bull'], key=lambda x: (-x['bull_score'], x['pe']))[:10]
        fs = sorted(data['forced_sell'], key=lambda x: (-x['bear_score'], x['pe']))[:10]
        wr = sorted(data['weak_reduce'], key=lambda x: (-x['bear_score'], x['pe']))[:10]

        if not any([sb, shb, fs, wr]): continue
        has_content = True
        combined_msg += f"📁 <b>【{cat}】技術判定</b>\n\n"
        if sb: combined_msg += f"🔥 <b>[🚀 強勢買進] Top 10</b>\n{format_items(sb)}\n\n"
        if shb: combined_msg += f"📈 <b>[📈 短多轉折] Top 10</b>\n{format_items(shb)}\n\n"
        if fs: combined_msg += f"🛑 <b>[🛑 強制賣出] Top 10</b>\n{format_items(fs)}\n\n"
        if wr: combined_msg += f"⚠️ <b>[⚠️ 弱勢減碼] Top 10</b>\n{format_items(wr)}\n\n"

    if has_content:
        send_tg_text(combined_msg.strip())
        time.sleep(1)

    # --- 📊 統一發送第 2 通：最強前三檔 K 線圖 ---
    all_bull_candidates = sorted(all_bull_candidates, key=lambda x: (-x['bull_score'], x['pe']))[:3]
    chart_files = []
    for item in all_bull_candidates:
        fn = generate_kline_chart(item)
        if fn and os.path.exists(fn): chart_files.append(fn)

    if chart_files:
        send_tg_album(chart_files, caption=f"📊 <b>盤前多方精選 Top {len(chart_files)} K 線圖</b>")
        for fn in chart_files:
            try: os.remove(fn)
            except: pass

if __name__ == "__main__":
    main()
