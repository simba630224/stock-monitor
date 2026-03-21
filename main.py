import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import time
import json
import matplotlib
matplotlib.use('Agg') # 設定背景繪圖，避免 GitHub Actions 報錯
import mplfinance as mpf
from datetime import datetime
import xml.etree.ElementTree as ET
import warnings

warnings.filterwarnings('ignore')

# --- 1. 配置與環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

TW_CORE = [
    {'symbol': '2330.TW', 'name': '台積電'},
    {'symbol': '2317.TW', 'name': '鴻海'},
    {'symbol': '2454.TW', 'name': '聯發科'},
    {'symbol': '2308.TW', 'name': '台達電'},
    {'symbol': '0050.TW', 'name': '元大台灣50'},
    {'symbol': '00878.TW', 'name': '國泰永續高股息'},
    {'symbol': '00713.TW', 'name': '元大台灣高息低波'},
    {'symbol': '00919.TW', 'name': '群益台灣精選高息'},
    {'symbol': '009812.TW', 'name': '野村日本東證ETF'}
]

US_WATCH = {
    '^GSPC': '標普500 S&P500 指數', 
    '^IXIC': '納斯達克 Nasdaq', 
    '^SOX': '費城半導體 SOX',
    'NVDA': '輝達 Nvidia',
    'AAPL': '蘋果 Apple',
    'MSFT': '微軟 Microsoft',
    'GOOGL': '谷歌 Google'
}

# --- 2. 輔助功能 ---
def get_filtered_news(name):
    topic_limit = "(intitle:股市 OR intitle:股價 OR intitle:財經 OR intitle:ETF OR intitle:債券 OR intitle:美股)"
    exclude_list = "-娛樂 -明星 -藝人 -影視 -大S -小S -汪小菲 -具俊曄 -許雅鈞 -綜藝 -緋聞 -穿搭 -八卦"
    media_limit = "(經濟日報 OR 工商日報 OR 華爾街日報)"
    
    query = f"{name} {topic_limit} {media_limit} {exclude_list}"
    url = f"https://news.google.com/rss/search?q={query}+when:48h&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    
    try:
        r = requests.get(url, timeout=10)
        root = ET.fromstring(r.text)
        items = []
        for item in root.findall('.//item')[:2]:
            title = item.find('title').text
            link = item.find('link').text
            if any(bad in title for bad in ["大S", "小S", "汪小菲", "婚姻", "婆婆"]):
                continue
            safe_title = title.replace('<', '〈').replace('>', '〉').replace('&', '＆')
            items.append(f"🔹 {safe_title}\n   <a href='{link}'>[閱讀原文]</a>")
        return "\n".join(items) if items else "近期無指定權威報系之重大財經報導。"
    except: 
        return "新聞載入暫時失敗。"

def analyze_ma_relation(price, ma_short, ma_long, market):
    # 依據市場設定均線文字
    s_name = "MA20"
    l_name = "MA60" if market == '台股' else "MA50"
    
    if pd.isna(ma_short) or pd.isna(ma_long): return "均線資料不足"
    if price > ma_short and price > ma_long: return f"🟢 站穩 {s_name} 與 {l_name} (強勢排列)"
    if price < ma_short and price < ma_long: return f"🔴 位於 {s_name} 與 {l_name} 之下 (偏空格局)"
    if price > ma_long and price < ma_short: return f"🟡 守住 {l_name}，但上方受 {s_name} 壓制 (築底中)"
    if price > ma_short and price < ma_long: return f"🔵 突破 {s_name}，但面臨 {l_name} 挑戰 (反彈中)"
    return "均線交纏整理中"

def calculate_indicators(df, market):
    # 1. 均線計算 (台股與美股不同)
    if market == '台股':
        df['MA_S1'] = df['Close'].rolling(20).mean()   # 月線
        df['MA_S2'] = df['Close'].rolling(60).mean()   # 季線
        df['MA_L1'] = df['Close'].rolling(120).mean()  # 半年線
        df['MA_L2'] = df['Close'].rolling(240).mean()  # 年線
    else:
        df['MA_S1'] = df['Close'].rolling(20).mean()   # 月線
        df['MA_S2'] = df['Close'].rolling(50).mean()   # 季線 (美股慣用)
        df['MA_L1'] = df['Close'].rolling(100).mean()  # 半年線 (美股慣用)
        df['MA_L2'] = df['Close'].rolling(200).mean()  # 年線 (美股慣用)

    # 2. 日線 KD 計算
    ln_d = df['Low'].rolling(9).min()
    hn_d = df['High'].rolling(9).max()
    rsv_d = (df['Close'] - ln_d) / (hn_d - ln_d) * 100
    df['K_d'] = rsv_d.ewm(com=2, adjust=False).mean()
    df['D_d'] = df['K_d'].ewm(com=2, adjust=False).mean()

    # 3. 週線 KD 計算
    df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    ln_w = df_w['Low'].rolling(9).min()
    hn_w = df_w['High'].rolling(9).max()
    rsv_w = (df_w['Close'] - ln_w) / (hn_w - ln_w) * 100
    df_w['K_w'] = rsv_w.ewm(com=2, adjust=False).mean()
    df_w['D_w'] = df_w['K_w'].ewm(com=2, adjust=False).mean()

    return df, df_w

def fmt_val(val):
    """將數值格式化，處理 NaN 情況"""
    return f"{val:.2f}" if pd.notna(val) else "無"

# --- Telegram 傳送模組 ---
def send_tg_text(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, data={'chat_id':TG_CHAT_ID, 'text':msg, 'parse_mode':'HTML', 'disable_web_page_preview':True})
    except Exception as e:
        print(f"Telegram Text 發送失敗: {e}")

def send_tg_album(image_paths):
    if not TG_TOKEN or not TG_CHAT_ID or not image_paths: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMediaGroup"
    
    for i in range(0, len(image_paths), 10):
        chunk = image_paths[i:i+10]
        media = []
        files = {}
        for j, path in enumerate(chunk):
            file_key = f"photo_{j}"
            media.append({"type": "photo", "media": f"attach://{file_key}"})
            files[file_key] = open(path, 'rb')
        try:
            requests.post(url, data={'chat_id': TG_CHAT_ID, 'media': json.dumps(media)}, files=files)
        except Exception as e:
            print(f"Telegram Album 發送失敗: {e}")
        finally:
            for f in files.values(): f.close()
        time.sleep(1)

def send_grouped_messages_and_charts(category_name, results_list):
    if not results_list: return
    
    current_chunk = f"📁 <b>【{category_name}】監控彙整報告</b>\n\n"
    for res in results_list:
        msg = res['detail_msg']
        if len(current_chunk) + len(msg) > 3800:
            send_tg_text(current_chunk)
            time.sleep(1)
            current_chunk = f"📁 <b>【{category_name}】監控彙整報告 (續)</b>\n\n"
        current_chunk += msg + "\n\n"
        
    if current_chunk.strip():
        send_tg_text(current_chunk)
        time.sleep(1)
        
    chart_fns = [res['chart_fn'] for res in results_list if res['chart_fn'] and os.path.exists(res['chart_fn'])]
    if chart_fns:
        send_tg_album(chart_fns)
        for fn in chart_fns:
            try: os.remove(fn)
            except: pass

# --- 3. 核心處理邏輯 ---
def classify_target(sym):
    if sym.endswith('.TW') or sym.endswith('.TWO'): return '台股'
    return '美股'

def process_target(sym, name):
    try:
        df_raw = yf.download(sym, period="2y", progress=False)
        if df_raw.empty: return None
        if isinstance(df_raw.columns, pd.MultiIndex): 
            df_raw.columns = df_raw.columns.get_level_values(0)
            
        market = classify_target(sym)
        df, df_w = calculate_indicators(df_raw.astype(float).dropna(), market)
        
        t_pe, t_pe_str, f_pe_str = None, "無", "無"
        try:
            ticker_obj = yf.Ticker(sym)
            info = ticker_obj.info
            t_pe = info.get('trailingPE')
            f_pe = info.get('forwardPE')
            if isinstance(t_pe, (int, float)): t_pe_str = f"{t_pe:.2f}"
            if isinstance(f_pe, (int, float)): f_pe_str = f"{f_pe:.2f}"
        except: pass 
        
        last_p = df['Close'].iloc[-1]
        
        # 取得最後的均線數值
        ma_s1 = df['MA_S1'].iloc[-1]
        ma_s2 = df['MA_S2'].iloc[-1]
        ma_l1 = df['MA_L1'].iloc[-1]
        ma_l2 = df['MA_L2'].iloc[-1]
        
        # 判斷均線格局
        ma_status = analyze_ma_relation(last_p, ma_s1, ma_s2, market)
        
        # 組合均線數值字串
        if market == '台股':
            ma_val_str = f"MA20: {fmt_val(ma_s1)} | MA60: {fmt_val(ma_s2)}\nMA120: {fmt_val(ma_l1)} | MA240: {fmt_val(ma_l2)}"
        else:
            ma_val_str = f"MA20: {fmt_val(ma_s1)} | MA50: {fmt_val(ma_s2)}\nMA100: {fmt_val(ma_l1)} | MA200: {fmt_val(ma_l2)}"
        
        # 判斷 日KD
        k_d, d_d = df['K_d'].iloc[-1], df['D_d'].iloc[-1]
        pk_d, pd_d = df['K_d'].iloc[-2], df['D_d'].iloc[-2]
        kd_text_d = "金叉轉強" if k_d > d_d and pk_d <= pd_d else "死亡交叉" if k_d < d_d and pk_d >= pd_d else "趨勢延續"
        
        # 判斷 週KD
        k_w, d_w = df_w['K_w'].iloc[-1], df_w['D_w'].iloc[-1]
        pk_w, pd_w = df_w['K_w'].iloc[-2], df_w['D_w'].iloc[-2]
        kd_text_w = "金叉轉強" if k_w > d_w and pk_w <= pd_w else "死亡交叉" if k_w < d_w and pk_w >= pd_w else "趨勢延續"
        
        # 繪圖 (只畫短天期避免畫面過度混亂)
        fn = f"chart_{sym.replace('^','').replace('.','_')}.png"
        pdf = df.tail(60)
        
        ap = []
        if pd.notna(pdf['MA_S1'].iloc[-1]): ap.append(mpf.make_addplot(pdf['MA_S1'], color='blue', width=1.2))
        if pd.notna(pdf['MA_S2'].iloc[-1]): ap.append(mpf.make_addplot(pdf['MA_S2'], color='orange', width=1.2))
        if pd.notna(pdf['MA_L1'].iloc[-1]): ap.append(mpf.make_addplot(pdf['MA_L1'], color='green', width=1.2))
        if pd.notna(pdf['MA_L2'].iloc[-1]): ap.append(mpf.make_addplot(pdf['MA_L2'], color='red', width=1.2))
        
        if ap:
            mpf.plot(pdf, type='candle', style='charles', addplot=ap, title=f"{name} ({sym})", savefig=fn)
        else:
            mpf.plot(pdf, type='candle', style='charles', title=f"{name} ({sym})", savefig=fn)
        
        news = get_filtered_news(name)
        
        msg = (f"📊 <b>{name} ({sym})</b>\n"
               f"目前價位: {last_p:.2f} | P/E: 歷史 {t_pe_str} / 預估 {f_pe_str}\n"
               f"均線位置: {ma_status}\n"
               f"[{market}均線數值]\n{ma_val_str}\n"
               f"日線 KD: {k_d:.1f}/{d_d:.1f} ({kd_text_d})\n"
               f"週線 KD: {k_w:.1f}/{d_w:.1f} ({kd_text_w})\n\n"
               f"📰 <b>核心財經頭條：</b>\n{news}")
        
        return {
            'name': name,
            'category': market,
            'detail_msg': msg,
            'chart_fn': fn,
            'k_d': k_d, 'kd_text_d': kd_text_d,
            'k_w': k_w, 'kd_text_w': kd_text_w,
            'trailing_pe': t_pe
        }
        
    except Exception as e: 
        print(f"Error {sym}: {e}")
        return None

def main():
    now_str = datetime.now().strftime('%Y/%m/%d')
    print(f"啟動財經掃描... ({now_str})")
    
    # 建立亮點名單
    summary_golden_d = []
    summary_death_d = []
    summary_golden_w = []
    summary_death_w = []
    summary_low_pe = []
    
    grouped_results = {'台股': [], '美股': []}

    all_targets = []
    for item in TW_CORE: all_targets.append((item['symbol'], item['name']))
    for sym, name in US_WATCH.items(): all_targets.append((sym, name))

    for sym, name in all_targets:
        res = process_target(sym, name)
        if res:
            grouped_results[res['category']].append(res)
            
            pe_val = res['trailing_pe']
            pe_str = f"{pe_val:.1f}" if isinstance(pe_val, (int, float)) else "無"
            
            # 日 KD
            if res['kd_text_d'] == "金叉轉強" and res['k_d'] < 30:
                summary_golden_d.append(f"{res['name']} (P/E: {pe_str})")
            if res['kd_text_d'] == "死亡交叉" and res['k_d'] > 70:
                summary_death_d.append(f"{res['name']} (P/E: {pe_str})")
                
            # 週 KD
            if res['kd_text_w'] == "金叉轉強" and res['k_w'] < 30:
                summary_golden_w.append(f"{res['name']} (P/E: {pe_str})")
            if res['kd_text_w'] == "死亡交叉" and res['k_w'] > 70:
                summary_death_w.append(f"{res['name']} (P/E: {pe_str})")
                
            # 本益比
            if isinstance(pe_val, (int, float)) and pe_val < 25:
                summary_low_pe.append(f"{res['name']} (P/E: {pe_val:.1f})")
                
        time.sleep(0.5)

    # --- 批次發送 (文字 + 圖表相簿) ---
    send_grouped_messages_and_charts("台股", grouped_results['台股'])
    send_grouped_messages_and_charts("美股", grouped_results['美股'])

    # --- 傳送最後的精華摘要 ---
    summary_msg = f"🏁 <b>全球財經深度掃描報告 ({now_str}) - 盤後亮點摘要：</b>\n\n"
    
    summary_msg += "☀️ <b>低檔【日】KD金叉 (K&lt;30)：</b>\n"
    summary_msg += "、\n".join(summary_golden_d) if summary_golden_d else "無"
    
    summary_msg += "\n\n⛈️ <b>高檔【日】KD死叉 (K&gt;70)：</b>\n"
    summary_msg += "、\n".join(summary_death_d) if summary_death_d else "無"
    
    summary_msg += "\n\n📈 <b>低檔【週】KD金叉 (K&lt;30)：</b>\n"
    summary_msg += "、\n".join(summary_golden_w) if summary_golden_w else "無"
    
    summary_msg += "\n\n📉 <b>高檔【週】KD死叉 (K&gt;70)：</b>\n"
    summary_msg += "、\n".join(summary_death_w) if summary_death_w else "無"
    
    summary_msg += "\n\n💡 <b>歷史本益比 &lt; 25 倍：</b>\n"
    summary_msg += "、\n".join(summary_low_pe) if summary_low_pe else "無"

    send_tg_text(summary_msg)

if __name__ == "__main__":
    main()
