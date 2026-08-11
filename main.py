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

# --- 2. 資料載入與技術指標計算 ---
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
    except Exception as e:
        print(f"⚠️ 載入線上清單失敗: {e}，切換至預設清單。")
        return [] if is_tw else {}

def calculate_indicators(df, market='台股'):
    if market == '台股':
        df['MA_S1'], df['MA_S2'] = df['Close'].rolling(20).mean(), df['Close'].rolling(60).mean()
        df['MA_L1'], df['MA_L2'] = df['Close'].rolling(120).mean(), df['Close'].rolling(240).mean()
    else:
        df['MA_S1'], df['MA_S2'] = df['Close'].rolling(20).mean(), df['Close'].rolling(50).mean()
        df['MA_L1'], df['MA_L2'] = df['Close'].rolling(100).mean(), df['Close'].rolling(200).mean()

    # 日 KD
    ln_d = df['Low'].rolling(9).min()
    hn_d = df['High'].rolling(9).max()
    df['K_d'] = ((df['Close'] - ln_d) / (hn_d - ln_d + 1e-9) * 100).ewm(com=2, adjust=False).mean()
    df['D_d'] = df['K_d'].ewm(com=2, adjust=False).mean()

    # 日 MACD
    df['DIF_d'] = df['Close'].ewm(span=12, adjust=False).mean() - df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD_d'] = df['DIF_d'].ewm(span=9, adjust=False).mean()
    df['OSC_d'] = df['DIF_d'] - df['MACD_d']

    # 週線
    df_w = df.resample('W-FRI').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
    if len(df_w) >= 9:
        ln_w = df_w['Low'].rolling(9).min()
        hn_w = df_w['High'].rolling(9).max()
        df_w['K_w'] = ((df_w['Close'] - ln_w) / (hn_w - ln_w + 1e-9) * 100).ewm(com=2, adjust=False).mean()
        df_w['D_w'] = df_w['K_w'].ewm(com=2, adjust=False).mean()
        df_w['DIF_w'] = df_w['Close'].ewm(span=12, adjust=False).mean() - df_w['Close'].ewm(span=26, adjust=False).mean()
        df_w['MACD_w'] = df_w['DIF_w'].ewm(span=9, adjust=False).mean()
        df_w['OSC_w'] = df_w['DIF_w'] - df_w['MACD_w']
    else:
        df_w['K_w'], df_w['D_w'], df_w['OSC_w'] = 50.0, 50.0, 0.0

    return df, df_w

# --- 3. Telegram 傳送模組 ---
def send_tg_text(msg):
    if not TG_TOKEN or not TG_CHAT_ID or not msg.strip(): return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        if len(msg) > 3800:
            chunks, curr = [], ""
            for line in msg.split('\n'):
                if len(curr) + len(line) + 1 > 3800:
                    chunks.append(curr)
                    curr = line + '\n'
                else: curr += line + '\n'
            if curr.strip(): chunks.append(curr)
            for chunk in chunks:
                requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': chunk, 'parse_mode': 'HTML', 'disable_web_page_preview': True}, timeout=15)
                time.sleep(1)
        else:
            requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML', 'disable_web_page_preview': True}, timeout=15)
    except Exception as e:
        print(f"❌ Telegram 發送失敗: {e}")

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
    except Exception as e:
        print(f"❌ Telegram 圖片發送失敗: {e}")
    finally:
        for f in files.values(): f.close()

# --- 4. 核心邏輯與評分 (嚴格對齊 Dashboard) ---
def process_target(sym, name, market='台股'):
    try:
        df_raw = yf.download(sym, period="2y", progress=False)
        if df_raw.empty: return None
        if isinstance(df_raw.columns, pd.MultiIndex): df_raw.columns = df_raw.columns.get_level_values(0)
        df_raw.index = df_raw.index.tz_localize(None)
        
        df = df_raw[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
        if len(df) < 40: return None
        df, df_w = calculate_indicators(df, market)
        if len(df_w) < 2: return None

        pe_val, pe_str = 999.0, "無"
        try:
            t_pe = yf.Ticker(sym).info.get('trailingPE')
            if isinstance(t_pe, (int, float)) and not np.isnan(t_pe) and t_pe > 0:
                pe_val, pe_str = float(t_pe), f"{t_pe:.1f}"
        except: pass

        last_p, prev_p = df['Close'].iloc[-1], df['Close'].iloc[-2]
        ma_s1, ma_s2 = df['MA_S1'].iloc[-1], df['MA_S2'].iloc[-1]
        prev_ma_s1, prev_ma_s2 = df['MA_S1'].iloc[-2], df['MA_S2'].iloc[-2]

        k_d, d_d = df['K_d'].iloc[-1], df['D_d'].iloc[-1]
        pk_d, pd_d = df['K_d'].iloc[-2], df['D_d'].iloc[-2]
        k_w, d_w = df_w['K_w'].iloc[-1], df_w['D_w'].iloc[-1]
        pk_w, pd_w = df_w['K_w'].iloc[-2], df_w['D_w'].iloc[-2]

        osc_d, p_osc_d = df['OSC_d'].iloc[-1], df['OSC_d'].iloc[-2]
        osc_w, p_osc_w = df_w['OSC_w'].iloc[-1], df_w['OSC_w'].iloc[-2]

        tags, bull_score, bear_score = [], 0.0, 0.0

        # 多方訊號
        if (k_w > d_w) and (pk_w <= pd_w): tags.append("週KD金叉"); bull_score += 3.0
        elif k_w < 35 and k_w > pk_w: tags.append("週KD低檔築底"); bull_score += 2.0
        if osc_w > 0 and p_osc_w <= 0: tags.append("週MACD翻紅"); bull_score += 2.5
        if last_p > ma_s1 and last_p > ma_s2: tags.append("站穩月季線"); bull_score += 2.0
        
        if (k_d > d_d) and (pk_d <= pd_d):
            if k_d < 35: tags.append("日KD低檔金叉"); bull_score += 3.0
            else: tags.append("日KD金叉"); bull_score += 2.0
        if osc_d > 0 and p_osc_d <= 0: tags.append("日MACD翻紅"); bull_score += 2.0
        if last_p > ma_s1 and prev_p <= prev_ma_s1: tags.append("突破月線"); bull_score += 2.0
        if last_p > ma_s2 and prev_p <= prev_ma_s2: tags.append("突破季線"); bull_score += 2.0

        # 空方訊號
        if (k_w < d_w) and (pk_w >= pd_w): tags.append("週KD死叉"); bear_score += 3.0
        elif k_w > 75 and k_w < pk_w: tags.append("週KD高檔拉回"); bear_score += 2.0
        if (k_d < d_d) and (pk_d >= pd_d):
            if k_d > 70: tags.append("高檔日KD死叉"); bear_score += 3.0
            else: tags.append("日KD死叉"); bear_score += 1.5
        if last_p < ma_s1 and prev_p >= prev_ma_s1: tags.append("跌破月線"); bear_score += 2.5
        if last_p < ma_s2 and prev_p >= prev_ma_s2: tags.append("跌破季線"); bear_score += 2.5
        if osc_d < 0 and p_osc_d >= 0: tags.append("日MACD翻綠"); bear_score += 2.0
        if last_p < ma_s1 and last_p < ma_s2: tags.append("月季線之下"); bear_score += 1.5

        # --- 四大象限判定 ---
        is_strong_buy = (bull_score >= 3.5) and any(t in tags for t in ["週KD金叉", "週KD低檔築底", "週MACD翻紅", "站穩月季線"])
        is_short_bull = (bull_score >= 2.5) and not is_strong_buy and any(t in tags for t in ["日KD低檔金叉", "日KD金叉", "突破月線", "突破季線", "日MACD翻紅"])
        
        # 強制賣出：極端空方或跌破重大支撐
        is_forced_sell = (bear_score >= 3.5) or any(t in tags for t in ["週KD死叉", "高檔日KD死叉", "跌破季線"])
        # 弱勢減碼：輕微空方但未達強制賣出
        is_weak_reduce = (bear_score >= 2.0) and not is_forced_sell and any(t in tags for t in ["跌破月線", "日MACD翻綠", "月季線之下", "週KD高檔拉回"])

        return {
            'symbol': sym, 'name': name, 'category': market,
            'pe': pe_val, 'pe_str': pe_str, 'tags': tags,
            'bull_score': bull_score, 'bear_score': bear_score,
            'is_strong_buy': is_strong_buy, 'is_short_bull': is_short_bull,
            'is_forced_sell': is_forced_sell, 'is_weak_reduce': is_weak_reduce,
            'df': df
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
    if 'MA_S1' in df and pd.notna(df['MA_S1'].iloc[-1]): ap.append(mpf.make_addplot(df['MA_S1'], color='blue', width=1.0))
    if 'MA_S2' in df and pd.notna(df['MA_S2'].iloc[-1]): ap.append(mpf.make_addplot(df['MA_S2'], color='orange', width=1.0))
    if 'MA_L1' in df and pd.notna(df['MA_L1'].iloc[-1]): ap.append(mpf.make_addplot(df['MA_L1'], color='green', width=1.2, linestyle='--'))
    if 'MA_L2' in df and pd.notna(df['MA_L2'].iloc[-1]): ap.append(mpf.make_addplot(df['MA_L2'], color='red', width=1.2, linestyle='--'))
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
            if res['is_strong_buy']: categorized[cat]['strong_buy'].append(res)
            if res['is_short_bull']: categorized[cat]['short_bull'].append(res)
            if res['is_forced_sell']: categorized[cat]['forced_sell'].append(res)
            if res['is_weak_reduce']: categorized[cat]['weak_reduce'].append(res)
            
            # 收集多方標的以備繪圖 (強勢買進 + 短多轉折)
            if res['is_strong_buy'] or res['is_short_bull']:
                all_bull_candidates.append(res)
        time.sleep(0.2)

    # --- 輸出單一整合訊息 ---
    combined_msg = f"🏆 <b>盤前亮點摘要與警示 ({now_str})</b>\n\n"

    for cat in ['台股', '美股']:
        data = categorized[cat]
        sb = sorted(data['strong_buy'], key=lambda x: (-x['bull_score'], x['pe']))[:10]
        shb = sorted(data['short_bull'], key=lambda x: (-x['bull_score'], x['pe']))[:10]
        fs = sorted(data['forced_sell'], key=lambda x: (-x['bear_score'], x['pe']))[:10]
        wr = sorted(data['weak_reduce'], key=lambda x: (-x['bear_score'], x['pe']))[:10]

        if not any([sb, shb, fs, wr]): continue

        combined_msg += f"📁 <b>【{cat}】技術判定</b>\n\n"
        if sb: combined_msg += f"[🚀 強勢買進]\n{format_items(sb)}\n\n"
        if shb: combined_msg += f"[📈 短多轉折]\n{format_items(shb)}\n\n"
        if fs: combined_msg += f"[🛑 強制賣出]\n{format_items(fs)}\n\n"
        if wr: combined_msg += f"[⚠️ 弱勢減碼]\n{format_items(wr)}\n\n"

    send_tg_text(combined_msg)
    time.sleep(1)

    # --- 繪製多方最強 Top 3 走勢圖 ---
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
