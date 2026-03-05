import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import time
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

# --- 1. 配置與環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# --- 2. 觀察清單 ---
TARGET_LIST = [
    # 美股 Top 10 市值巨頭
    "AAPL:蘋果", "MSFT:微軟", "NVDA:輝達", "GOOGL:谷歌", "AMZN:亞馬遜", 
    "META:Meta", "BRK-B:波克夏", "LLY:禮來", "AVGO:博通", "TSLA:特斯拉",

    # Top 20 台股 ETF
    "0050.TW:元大台灣50", "0056.TW:元大高股息", "00878.TW:國泰永續高股息", "00919.TW:群益台灣精選高息", 
    "00929.TW:復華台灣科技優息", "00713.TW:元大台灣高息低波", "006208.TW:富邦台50", "00939.TW:統一台灣高息動能", 
    "00940.TW:元大台灣價值高息", "00679B.TWO:元大20年美債", "00687B.TWO:國泰20年美債", "00937B.TWO:群益ESG投等債20+",
    "00772B.TWO:中信高評級公司債", "00751B.TWO:元大AAA至A公司債", "00720B.TWO:元大投資級公司債", 
    "00692.TW:富邦公司治理", "00881.TW:國泰台灣5G+", "00915.TW:凱基優選高股息30", "00918.TW:大華優利高填息30", "00922.TW:國泰台灣領袖50",
    
    # 台股權值股 (僅保留電子股：半導體/電腦週邊/網通/光電/電子零組件等)
    "2330.TW:台積電", "2317.TW:鴻海", "2454.TW:聯發科", "2308.TW:台達電", "2382.TW:廣達", 
    "3711.TW:日月光投控", "2303.TW:聯電", "2345.TW:智邦", "2357.TW:華碩", "2379.TW:瑞昱", 
    "2395.TW:研華", "3008.TW:大立光", "3034.TW:聯詠", "3045.TW:台灣大", "3231.TW:緯創", 
    "3661.TW:世芯-KY", "4904.TW:遠傳", "4938.TW:和碩", "6669.TW:緯穎", "2301.TW:光寶科", 
    "2324.TW:仁寶", "2353.TW:宏碁", "2356.TW:英業達", "2383.TW:台光電", "2408.TW:南亞科", 
    "2409.TW:友達", "3017.TW:奇鋐", "3037.TW:欣興", "3481.TW:群創", "3702.TW:大聯大", 
    "4915.TW:致伸", "5347.TWO:世界", "6239.TW:力成", "8046.TW:南電", "8299.TWO:群聯", 
    "2313.TW:華通", "2344.TW:華邦電", "2376.TW:技嘉", "2412.TW:中華電", "2449.TW:京元電子", 
    "3044.TW:健鼎", "3532.TW:台勝科", "3653.TW:健策", "4958.TW:臻鼎-KY", "5483.TWO:中美晶", 
    "6147.TWO:頎邦", "6176.TW:瑞儀", "6269.TW:台郡", "6285.TW:啟碁", "6415.TW:矽力*-KY", 
    "6488.TWO:環球晶", "6770.TW:力積電", "8069.TWO:元太"
]

# --- 3. 核心運算與發送功能 ---
def send_tg_summary(msg):
    if not TG_TOKEN or not TG_CHAT_ID: 
        print("❌ 錯誤：找不到 Telegram Token 或 Chat ID")
        return
        
    print(f"\n準備發送 Telegram... 訊息總字元數: {len(msg)}")
    if len(msg) > 4000:
        print("⚠️ 警告：訊息長度逼近或超過 Telegram 4096 字元上限，可能會遭到截斷或拒絕！")
        
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        response = requests.post(url, data={'chat_id':TG_CHAT_ID, 'text':msg, 'parse_mode':'HTML', 'disable_web_page_preview':True})
        
        # ⚠️ 【Debug 核心】把 Telegram 伺服器的回應印出來
        if response.status_code == 200:
            print("✅ Telegram 發送成功！")
        else:
            print(f"❌ Telegram 發送失敗！")
            print(f"錯誤碼 HTTP Status Code: {response.status_code}")
            print(f"錯誤詳細內容 Response: {response.text}")
            
    except Exception as e:
        print(f"❌ 網路連線或 Telegram 發送發生例外錯誤: {e}")

def calc_days_since(df_bool_series):
    """計算最後一次發生 True 到現在經過了幾個「交易週期」"""
    if not df_bool_series.any(): return -1
    last_idx = df_bool_series[df_bool_series].index[-1]
    return len(df_bool_series.loc[last_idx:]) - 1

def scan_target(sym, name):
    is_tw = sym.endswith('.TW') or sym.endswith('.TWO')
    is_etf = is_tw and sym.startswith('00')
    is_us = not is_tw
    
    result = {
        'name': name, 
        'is_etf': is_etf,
        'is_tw': is_tw,
        'is_us': is_us,
        'kd_golden_days': -1, 
        'kd_death_days': -1,
        'break_ma20_days': -1,
        'above_ma20_days': -1,
        'trailing_pe': None,
        'forward_pe': None,
        'market_cap': 0
    }
    
    try:
        df = yf.download(sym, period="1y", progress=False)
        if df.empty: return result
        if isinstance(df.columns, pd.MultiIndex): 
            df.columns = df.columns.get_level_values(0)
            
        df = df.dropna()
        if len(df) < 20: return result

        # 1. 日線 MA20 判斷
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['Break_MA20'] = (df['Close'] < df['MA20']) & (df['Close'].shift(1) >= df['MA20'].shift(1))
        df['Above_MA20'] = (df['Close'] > df['MA20']) & (df['Close'].shift(1) <= df['MA20'].shift(1))
        
        last_close = df['Close'].iloc[-1]
        last_ma20 = df['MA20'].iloc[-1]
        
        if last_close < last_ma20: result['break_ma20_days'] = calc_days_since(df['Break_MA20'])
        elif last_close > last_ma20: result['above_ma20_days'] = calc_days_since(df['Above_MA20'])

        # 2. 週線 KD 判斷
        df_w = df.resample('W-FRI').agg({'High':'max','Low':'min','Close':'last'}).dropna()
        ln = df_w['Low'].rolling(9).min()
        hn = df_w['High'].rolling(9).max()
        rsv = (df_w['Close'] - ln) / (hn - ln) * 100
        df_w['K'] = rsv.ewm(com=2, adjust=False).mean()
        df_w['D'] = df_w['K'].ewm(com=2, adjust=False).mean()
        
        df_w['Golden_Cross'] = (df_w['K'] > df_w['D']) & (df_w['K'].shift(1) <= df_w['D'].shift(1))
        df_w['Death_Cross'] = (df_w['K'] < df_w['D']) & (df_w['K'].shift(1) >= df_w['D'].shift(1))
        
        last_k, last_d = df_w['K'].iloc[-1], df_w['D'].iloc[-1]
        
        if last_k > last_d:
            if df_w['Golden_Cross'].any():
                last_gc_idx = df_w[df_w['Golden_Cross']].index[-1]
                if df_w.loc[last_gc_idx, 'K'] < 30: result['kd_golden_days'] = calc_days_since(df_w['Golden_Cross'])
        elif last_k < last_d:
            if df_w['Death_Cross'].any():
                last_dc_idx = df_w[df_w['Death_Cross']].index[-1]
                if df_w.loc[last_dc_idx, 'K'] > 70: result['kd_death_days'] = calc_days_since(df_w['Death_Cross'])

        # 3. 基本面數據
        ticker_obj = yf.Ticker(sym)
        info = ticker_obj.info
        t_pe = info.get('trailingPE')
        f_pe = info.get('forwardPE')
        m_cap = info.get('marketCap') or info.get('totalAssets') or 0
        
        if isinstance(t_pe, (int, float)): result['trailing_pe'] = t_pe
        if isinstance(f_pe, (int, float)): result['forward_pe'] = f_pe
        if isinstance(m_cap, (int, float)): result['market_cap'] = m_cap

    except Exception as e:
        pass
    
    return result

def format_pe_item(item, days, unit="天"):
    t_pe_str = f"{item['trailing_pe']:.1f}" if item['trailing_pe'] is not None else "無"
    f_pe_str = f"{item['forward_pe']:.1f}" if item['forward_pe'] is not None else "無"
    day_str = "<b>(今日)</b>" if days == 0 else f"({days}{unit}前)"
    # 為避免 HTML 格式錯誤，將可能干擾的特殊字元替換掉
    safe_name = item['name'].replace('<', '').replace('>', '')
    return f"{safe_name} {day_str} [P/E {t_pe_str} / {f_pe_str}]"

def main():
    print(f"啟動市場掃描... 共計 {len(TARGET_LIST)} 檔標的")
    
    golden_cross_list = []
    death_cross_list = []
    break_ma20_list = []
    above_ma20_list = []
    pe_etfs = []
    pe_tw_stocks = []
    pe_us_stocks = []
    
    for idx, item in enumerate(TARGET_LIST, 1):
        parts = item.split(':')
        sym, name = parts[0], parts[1]
        
        if idx % 10 == 0:
            print(f"進度: 掃描中... ({idx}/{len(TARGET_LIST)})")
            
        res = scan_target(sym, name)
        
        if 0 <= res['kd_golden_days'] <= 5: golden_cross_list.append(res)
        if 0 <= res['kd_death_days'] <= 5: death_cross_list.append(res)
        if 0 <= res['break_ma20_days'] <= 10: break_ma20_list.append(res)
        if 0 <= res['above_ma20_days'] <= 10: above_ma20_list.append(res)
            
        if res['trailing_pe'] is not None and res['trailing_pe'] < 20:
            if res['is_etf']: pe_etfs.append(res)
            elif res['is_tw']: pe_tw_stocks.append(res)
            elif res['is_us']: pe_us_stocks.append(res)
                
        time.sleep(0.2) 

    # --- 排序 ---
    golden_cross_list.sort(key=lambda x: x['kd_golden_days'])
    death_cross_list.sort(key=lambda x: x['kd_death_days'])
    break_ma20_list.sort(key=lambda x: x['break_ma20_days'])
    above_ma20_list.sort(key=lambda x: x['above_ma20_days'])
    
    pe_etfs.sort(key=lambda x: x['market_cap'], reverse=True)
    pe_tw_stocks.sort(key=lambda x: x['market_cap'], reverse=True)
    pe_us_stocks.sort(key=lambda x: x['market_cap'], reverse=True)

    print(f"\n資料蒐集完畢！找到 {len(golden_cross_list)} 個金叉, {len(death_cross_list)} 個死叉, {len(above_ma20_list)} 個站上月線, {len(break_ma20_list)} 個跌破月線。")

    # --- 組合 Telegram 訊息 ---
    now_str = datetime.now().strftime('%Y/%m/%d')
    msg = f"🏆 <b>大盤百大/ETF/美巨頭 盤前掃描 ({now_str})</b>\n\n"
    
    msg += "📈 <b>低檔週KD金叉 (K&lt;30)：</b>\n"
    if golden_cross_list:
        for item in golden_cross_list: msg += f"• {format_pe_item(item, item['kd_golden_days'], '週')}\n"
    else: msg += "無符合標的\n"

    msg += "\n📉 <b>高檔週KD死叉 (K&gt;70)：</b>\n"
    if death_cross_list:
        for item in death_cross_list: msg += f"• {format_pe_item(item, item['kd_death_days'], '週')}\n"
    else: msg += "無符合標的\n"

    msg += "\n🟢 <b>強勢站上月線 (MA20)：</b>\n"
    if above_ma20_list:
        for item in above_ma20_list: msg += f"• {format_pe_item(item, item['above_ma20_days'], '日')}\n"
    else: msg += "無符合標的\n"

    msg += "\n🔴 <b>弱勢跌破月線 (MA20)：</b>\n"
    if break_ma20_list:
        for item in break_ma20_list: msg += f"• {format_pe_item(item, item['break_ma20_days'], '日')}\n"
    else: msg += "無符合標的\n"
        
    msg += "\n💡 <b>歷史本益比 &lt; 20 倍 (依市值Top 5)：</b>\n"
    msg += "📍 <b>【台股 ETF】</b>\n"
    for idx, item in enumerate(pe_etfs[:5], 1): msg += f"{idx}. {item['name']} [P/E {item['trailing_pe']:.1f}]\n"
    msg += "📍 <b>【台股 個股】</b>\n"
    for idx, item in enumerate(pe_tw_stocks[:5], 1): msg += f"{idx}. {item['name']} [P/E {item['trailing_pe']:.1f}]\n"
    msg += "📍 <b>【美股 個股】</b>\n"
    for idx, item in enumerate(pe_us_stocks[:5], 1): msg += f"{idx}. {item['name']} [P/E {item['trailing_pe']:.1f}]\n"

    send_tg_summary(msg)

if __name__ == "__main__":
    main()
