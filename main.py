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
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
SHEET_CSV_TW_URL = os.getenv('SHEET_CSV_TW_URL')
SHEET_CSV_US_URL = os.getenv('SHEET_CSV_US_URL')

# --- 2. 輔助與技術指標函式 ---
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
            ticker = str(row_dict.get('ticker') or '').strip()
            name = str(row_dict.get('名稱') or row_dict.get('name') or '').strip()
            if not ticker or ticker.lower() == 'nan': continue
            display_name = name if name and name != 'nan' else ticker
            
            if is_tw:
                data.append({'symbol': get_yf_ticker_tw(ticker), 'name': display_name})
            else:
                data[ticker] = display_name
        return data
    except Exception as e:
        return [] if is_tw else {}

def process_target(sym, name, category):
    try:
        # 統一抓取最長 3 年資料以確保週線準確，若上市不滿三年 yfinance 會自動回傳現有資料
        df = yf.download(sym, period="3y", progress=False, threads=False) 
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df[['Open', 'High', 'Low', 'Close']].dropna()
        if len(df) < 35: return None # 資料過短無法計算指標
        
        last_p = df['Close'].iloc[-1]
        
        # --- 日線指標 ---
        low_min = df['Low'].rolling(9, min_periods=1).min()
        high_max = df['High'].rolling(9, min_periods=1).max()
        rsv = (df['Close'] - low_min) / (high_max - low_min + 1e-9) * 100
        df['K_d'] = rsv.ewm(com=2, adjust=False).mean()
        df['D_d'] = df['K_d'].ewm(com=2, adjust=False).mean()
        
        df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
        df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = df['EMA12'] - df['EMA26']
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
        # --- 週線指標 ---
        df_w = df.resample('W-FRI').agg({'Open':'first', 'High':'max', 'Low':'min', 'Close':'last'}).dropna()
        has_enough_weekly = len(df_w) >= 15 # 若上市時間不足15週，捨棄週線指標避免失真
        
        if has_enough_weekly:
            low_min_w = df_w['Low'].rolling(9, min_periods=1).min()
            high_max_w = df_w['High'].rolling(9, min_periods=1).max()
            rsv_w = (df_w['Close'] - low_min_w) / (high_max_w - low_min_w + 1e-9) * 100
            df_w['K_w'] = rsv_w.ewm(com=2, adjust=False).mean()
            df_w['D_w'] = df_w['K_w'].ewm(com=2, adjust=False).mean()
            
            df_w['EMA12'] = df_w['Close'].ewm(span=12, adjust=False).mean()
            df_w['EMA26'] = df_w['Close'].ewm(span=26, adjust=False).mean()
            df_w['MACD'] = df_w['EMA12'] - df_w['EMA26']
            df_w['MACD_Signal'] = df_w['MACD'].ewm(span=9, adjust=False).mean()
        else:
            df_w = pd.DataFrame()
            
        # --- 嚴格的高低檔金/死叉判斷函式 ---
        def is_gold_low(fast, slow, is_macd=False):
            if len(fast) < 2: return False
            cross_up = (fast.iloc[-1] > slow.iloc[-1]) and (fast.iloc[-2] <= slow.iloc[-2])
            if not cross_up: return False
            return fast.iloc[-1] < 0 if is_macd else fast.iloc[-1] < 30
            
        def is_death_high(fast, slow, is_macd=False):
            if len(fast) < 2: return False
            cross_down = (fast.iloc[-1] < slow.iloc[-1]) and (fast.iloc[-2] >= slow.iloc[-2])
            if not cross_down: return False
            return fast.iloc[-1] > 0 if is_macd else fast.iloc[-1] > 70

        w_macd_gold = is_gold_low(df_w['MACD'], df_w['MACD_Signal'], True) if has_enough_weekly else False
        w_kd_gold = is_gold_low(df_w['K_w'], df_w['D_w'], False) if has_enough_weekly else False
        d_macd_gold = is_gold_low(df['MACD'], df['MACD_Signal'], True)
        d_kd_gold = is_gold_low(df['K_d'], df['D_d'], False)

        w_macd_death = is_death_high(df_w['MACD'], df_w['MACD_Signal'], True) if has_enough_weekly else False
        w_kd_death = is_death_high(df_w['K_w'], df_w['D_w'], False) if has_enough_weekly else False
        d_macd_death = is_death_high(df['MACD'], df['MACD_Signal'], True)
        d_kd_death = is_death_high(df['K_d'], df['D_d'], False)
        
        # --- 判斷跌破季線 ---
        season_len = 60 if category == '台股' else 50
        df['MA_season'] = df['Close'].rolling(season_len).mean()
        is_break = False
        if len(df) >= 2 and pd.notna(df['MA_season'].iloc[-2]):
            is_break = (df['Close'].iloc[-1] < df['MA_season'].iloc[-1]) and (df['Close'].iloc[-2] >= df['MA_season'].iloc[-2])

        # --- 取得本益比 ---
        try:
            info = yf.Ticker(sym).info
            pe = info.get('trailingPE') or info.get('forwardPE', 999)
        except:
            pe = 999
            
        # --- 生成精準標籤 ---
        tags = []
        if w_macd_gold: tags.append("週MACD零下金叉")
        if w_kd_gold: tags.append("週KD低檔金叉")
        if d_macd_gold: tags.append("日MACD零下金叉")
        if d_kd_gold: tags.append("日KD低檔金叉")
        
        if w_macd_death: tags.append("週MACD零上死叉")
        if w_kd_death: tags.append("週KD高檔死叉")
        if d_macd_death: tags.append("日MACD零上死叉")
        if d_kd_death: tags.append("日KD高檔死叉")
        if is_break: tags.append("跌破季線")

        # --- 技術面評分 (權重：週>日, MACD>KD) ---
        bull_score = (w_macd_gold * 4) + (w_kd_gold * 3) + (d_macd_gold * 2) + (d_kd_gold * 1)
        bear_score = (w_macd_death * 4) + (w_kd_death * 3) + (d_macd_death * 2) + (d_kd_death * 1) + (is_break * 1)
        
        return {
            'sym': sym, 'name': name, 'category': category, 
            'pe': pe, 'pe_str': f"{pe:.1f}" if pe != 999 else "無PE",
            'tags': tags, 'bull_score': bull_score, 'bear_score': bear_score,
            'last_p': last_p,
            'df': df.tail(150) # 儲存供繪圖的歷史資料
        }
    except Exception:
        return None

# --- 3. Telegram 傳送與相簿繪製模組 ---
def send_tg_text(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                  data={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'})

def send_tg_album(buffers, caption=""):
    if not TG_TOKEN or not TG_CHAT_ID or not buffers: return
    if len(buffers) == 1:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
        files = {'photo': ('chart.png', buffers[0].getvalue(), 'image/png')}
        requests.post(url, data={'chat_id': TG_CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}, files=files)
        return

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMediaGroup"
    media = []
    files = {}
    for i, buf in enumerate(buffers):
        filename = f"image{i}.png"
        media_dict = {"type": "photo", "media": f"attach://{filename}"}
        if i == 0 and caption:
            media_dict["caption"] = caption
            media_dict["parse_mode"] = "HTML"
        media.append(media_dict)
        files[filename] = (filename, buf.getvalue(), 'image/png')
    
    requests.post(url, data={"chat_id": TG_CHAT_ID, "media": json.dumps(media)}, files=files)

def generate_chart(item):
    try:
        df = item['df'].copy()
        if len(df) < 30: return None
        
        macd = df['Close'].ewm(span=12, adjust=False).mean() - df['Close'].ewm(span=26, adjust=False).mean()
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        
        low_min = df['Low'].rolling(9, min_periods=1).min()
        high_max = df['High'].rolling(9, min_periods=1).max()
        rsv = (df['Close'] - low_min) / (high_max - low_min + 1e-9) * 100
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        
        mc = mpf.make_marketcolors(up='r', down='g', edge='inherit', wick='inherit', volume='in')
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle=':')
        macd_colors = ['r' if val >= 0 else 'g' for val in hist]
        
        apds = [
            mpf.make_addplot(df['Close'].rolling(20).mean(), color='blue', width=1),
            mpf.make_addplot(k, panel=1, color='blue', ylabel='KD'),
            mpf.make_addplot(d, panel=1, color='orange'),
            mpf.make_addplot(macd, panel=2, color='blue', ylabel='MACD'),
            mpf.make_addplot(signal, panel=2, color='orange'),
            mpf.make_addplot(hist, type='bar', panel=2, color=macd_colors)
        ]
        
        buf = io.BytesIO()
        title = f"{item['name']} ({item['sym']}) - {'+'.join(item['tags'])}"
        mpf.plot(df, type='candle', addplot=apds, figscale=1.0, figratio=(10, 8), 
                 title=title, style=s, savefig=dict(fname=buf, dpi=120, bbox_inches='tight'))
        buf.seek(0)
        return buf
    except Exception:
        return None

# --- 4. 主程式 ---
def main():
    TW_CORE = load_csv_list(SHEET_CSV_TW_URL, True)
    US_WATCH = load_csv_list(SHEET_CSV_US_URL, False)
    if not TW_CORE and not US_WATCH: return

    all_targets = [(item['symbol'], item['name'], '台股') for item in TW_CORE] + [(sym, name, '美股') for sym, name in US_WATCH.items()]
    categorized = {'台股': {'bull_strong':[], 'bull_daily':[], 'bear':[]}, '美股': {'bull_strong':[], 'bull_daily':[], 'bear':[]}}
    top_chart_candidates = [] 

    for sym, name, cat in all_targets:
        res = process_target(sym, name, cat)
        if not res: continue
        
        # 互斥分流
        if res['bear_score'] >= 3:
            categorized[cat]['bear'].append(res)
        elif res['bull_score'] >= 3:
            categorized[cat]['bull_strong'].append(res)
            top_chart_candidates.append(res)
        elif res['bear_score'] > 0:
            categorized[cat]['bear'].append(res)
        elif res['bull_score'] > 0:
            categorized[cat]['bull_daily'].append(res)
            top_chart_candidates.append(res)
        time.sleep(0.5) 

    send_tg_text("🚀 <b>盤後亮點摘要與警示 (Top 10)</b>")
    
    def format_items(items):
        if not items: return "無"
        return "\n".join([f"• <b>{x['name']} (PE:{x['pe_str']})</b>\n  └ <code>[{', '.join(x['tags'])}]</code>" for x in items])

    for cat in ['台股', '美股']:
        data = categorized[cat]
        b_strong = sorted(data['bull_strong'], key=lambda x: (-x['bull_score'], x['pe']))[:10]
        b_daily = sorted(data['bull_daily'], key=lambda x: (-x['bull_score'], x['pe']))[:10]
        bear = sorted(data['bear'], key=lambda x: (-x['bear_score'], x['pe']))[:10]
        
        if not b_strong and not b_daily and not bear: continue
        
        msg = f"📁 <b>【{cat}】技術掃描</b>\n\n"
        if b_strong: msg += f"🔥 <b>週線級別 (波段強勢區)</b>\n{format_items(b_strong)}\n\n"
        if b_daily: msg += f"📈 <b>日線級別 (短線轉折區)</b>\n{format_items(b_daily)}\n\n"
        if bear: msg += f"⚠️ <b>空方風險警示 (破線/死叉)</b>\n{format_items(bear)}\n"
        
        send_tg_text(msg)

    # 繪製 Top 3 相簿
    top_chart_candidates = sorted(top_chart_candidates, key=lambda x: (-x['bull_score'], x['pe']))[:3]
    if top_chart_candidates:
        image_buffers = []
        chart_names = []
        for item in top_chart_candidates:
            buf = generate_chart(item)
            if buf:
                image_buffers.append(buf)
                chart_names.append(item['name'])
        
        if image_buffers:
            caption = f"📊 <b>本日最強勢 Top {len(image_buffers)} 技術線圖</b>\n" + ", ".join(chart_names)
            send_tg_album(image_buffers, caption)

    send_tg_text(f"🏁 <b>每日掃描完成 ({datetime.now().strftime('%Y/%m/%d')})</b>")

if __name__ == "__main__":
    main()
