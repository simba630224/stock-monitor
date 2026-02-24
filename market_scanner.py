import yfinance as yf
import pandas as pd
import requests
import os
import time
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

# --- 1. 配置與環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# --- 2. 觀察清單 (台股市值 Top 100 權值股 + Top 20 規模 ETF) ---
# 註：為確保程式執行穩定且無須付費 API，此處採用靜態名單，涵蓋目前市場最具代表性的大型標的。
TARGET_LIST = [
    # Top 20 ETF (市值與熱門度前段班，含高股息、市值型、美債)
    "0050.TW:元大台灣50", "0056.TW:元大高股息", "00878.TW:國泰永續高股息", "00919.TW:群益台灣精選高息", 
    "00929.TW:復華台灣科技優息", "00713.TW:元大台灣高息低波", "006208.TW:富邦台50", "00939.TW:統一台灣高息動能", 
    "00940.TW:元大台灣價值高息", "00679B.TWO:元大20年美債", "00687B.TWO:國泰20年美債", "00937B.TWO:群益ESG投等債20+",
    "00772B.TWO:中信高評級公司債", "00751B.TWO:元大AAA至A公司債", "00720B.TWO:元大投資級公司債", 
    "00692.TW:富邦公司治理", "00881.TW:國泰台灣5G+", "00915.TW:凱基優選高股息30", "00918.TW:大華優利高填息30", "00922.TW:國泰台灣領袖50",
    
    # Top 100 個股 (涵蓋台灣50與中型100前段班大型權值股)
    "2330.TW:台積電", "2317.TW:鴻海", "2454.TW:聯發科", "2308.TW:台達電", "2382.TW:廣達", 
    "2881.TW:富邦金", "2882.TW:國泰金", "2891.TW:中信金", "2886.TW:兆豐金", "1216.TW:統一", 
    "3711.TW:日月光投控", "2884.TW:玉山金", "2002.TW:中鋼", "2303.TW:聯電", "2885.TW:元大金", 
    "2892.TW:第一金", "5871.TW:中租-KY", "2880.TW:華南金", "2883.TW:開發金", "2887.TW:台新金", 
    "2912.TW:統一超", "1301.TW:台塑", "1303.TW:南亞", "2345.TW:智邦", "2357.TW:華碩", 
    "2379.TW:瑞昱", "2395.TW:研華", "3008.TW:大立光", "3034.TW:聯詠", "3045.TW:台灣大", 
    "3231.TW:緯創", "3661.TW:世芯-KY", "4904.TW:遠傳", "4938.TW:和碩", "5880.TW:合庫金", 
    "6505.TW:台塑化", "6669.TW:緯穎", "8454.TW:富邦媒", "9910.TW:豐泰", "2603.TW:長榮", 
    "2609.TW:陽明", "2615.TW:萬海", "1590.TW:亞德客-KY", "2301.TW:光寶科", "2324.TW:仁寶",
    "2353.TW:宏碁", "2356.TW:英業達", "2371.TW:大同", "2383.TW:台光電", "2408.TW:南亞科",
    "2409.TW:友達", "2618.TW:長榮航", "2890.TW:永豐金", "3017.TW:奇鋐", "3037.TW:欣興",
    "3293.TW:鈊象", "3481.TW:群創", "3702.TW:大聯大", "4915.TW:致伸", "5347.TWO:世界",
    "6239.TW:力成", "8046.TW:南電", "8299.TWO:群聯", "9921.TW:巨大", "1101.TW:台泥",
    "1102.TW:亞泥", "1402.TW:遠東新", "1476.TW:儒鴻", "1504.TW:東元", "1605.TW:華新",
    "2105.TW:正新", "2207.TW:和泰車", "2313.TW:華通", "2344.TW:華邦電", "2376.TW:技嘉",
    "2412.TW:中華電", "2449.TW:京元電子", "2606.TW:裕民", "2801.TW:彰銀", "2834.TW:臺企銀",
    "3044.TW:健鼎", "3532.TW:台勝科", "3653.TW:健策", "4958.TW:臻鼎-KY", "5483.TWO:中美晶",
    "6147.TWO:頎邦", "6176.TW:瑞儀", "6269.TW:台郡", "6285.TW:啟碁", "6415.TW:矽力*-KY",
    "6488.TW:環球晶", "6770.TW:力積電", "8069.TWO:元太", "8464.TW:億豐", "9904.TW:寶成",
    "9914.TW:美利達", "9941.TW:裕融", "9945.TW:潤泰新"
]

# --- 3. 核心運算與發送功能 ---
def send_tg_summary(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, data={'chat_id':TG_CHAT_ID, 'text':msg, 'parse_mode':'HTML', 'disable_web_page_preview':True})
    except Exception as e:
        print(f"Telegram發送失敗: {e}")

def get_weekly_kd(df):
    """計算週線KD"""
    df_w = df.resample('W-FRI').agg({'High':'max','Low':'min','Close':'last'}).dropna()
    ln = df_w['Low'].rolling(9).min()
    hn = df_w['High'].rolling(9).max()
    rsv = (df_w['Close'] - ln) / (hn - ln) * 100
    df_w['K'] = rsv.ewm(com=2, adjust=False).mean()
    df_w['D'] = df_w['K'].ewm(com=2, adjust=False).mean()
    return df_w

def scan_target(sym, name):
    result = {'name': name, 'golden_cross': False, 'trailing_pe': None}
    try:
        # 1. 計算技術指標
        df_raw = yf.download(sym, period="2y", progress=False)
        if not df_raw.empty:
            if isinstance(df_raw.columns, pd.MultiIndex): 
                df_raw.columns = df_raw.columns.get_level_values(0)
            
            df_w = get_weekly_kd(df_raw.astype(float).dropna())
            if len(df_w) >= 2:
                k, d = df_w['K'].iloc[-1], df_w['D'].iloc[-1]
                pk, pd_v = df_w['K'].iloc[-2], df_w['D'].iloc[-2]
                
                # 判斷低檔週KD金叉 (K大於D，且上週K小於等於D，且目前K值處於低檔區<30)
                if k > d and pk <= pd_v and k < 30:
                    result['golden_cross'] = True

        # 2. 抓取本益比
        ticker_obj = yf.Ticker(sym)
        pe = ticker_obj.info.get('trailingPE')
        if isinstance(pe, (int, float)):
            result['trailing_pe'] = pe

    except Exception as e:
        pass # 掃描模式下忽略錯誤，直接跳過該檔
    
    return result

def main():
    print(f"啟動台股百大掃描... 共計 {len(TARGET_LIST)} 檔標的")
    
    summary_golden_cross = []
    summary_low_pe = []
    
    # 執行掃描迴圈
    for item in TARGET_LIST:
        parts = item.split(':')
        sym, name = parts[0], parts[1]
        
        # 顯示進度
        print(f"Scanning: {sym} {name}")
        
        res = scan_target(sym, name)
        
        # 篩選條件 1: 低檔黃金交叉
        if res['golden_cross']:
            summary_golden_cross.append(name)
            
        # 篩選條件 2: 歷史本益比 < 25
        if res['trailing_pe'] is not None and res['trailing_pe'] < 25:
            summary_low_pe.append(f"{name}({res['trailing_pe']:.1f})")
            
        time.sleep(0.2) # 延遲以避免被 Yahoo API 封鎖

    # --- 組合 Telegram 訊息 ---
    now_str = datetime.now().strftime('%Y/%m/%d')
    
    msg = f"🏆 <b>台股百大權值與熱門ETF掃描 ({now_str})</b>\n\n"
    
    msg += "📈 <b>低檔週KD金叉 (K&lt;30)：</b>\n"
    if summary_golden_cross:
        msg += "、".join(summary_golden_cross)
    else:
        msg += "今日無符合標的"
        
    msg += "\n\n💡 <b>歷史本益比 &lt; 25 倍：</b>\n"
    if summary_low_pe:
        msg += "、".join(summary_low_pe)
    else:
        msg += "今日無符合標的"
        
    msg += "\n\n<i>(註：名單涵蓋台股市值Top100與規模Top20之ETF)</i>"

    send_tg_summary(msg)
    print("掃描完畢，訊息已發送。")

if __name__ == "__main__":
    main()
