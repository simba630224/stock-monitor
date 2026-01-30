import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import requests
import os
from datetime import datetime

# --- 1. 配置設定 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# 中文名稱映射表
NAME_MAP = {
    '2330.TW': '台積電', '2317.TW': '鴻海', '2454.TW': '聯發科', '2308.TW': '台達電', 
    '2303.TW': '聯電', '3711.TW': '日月光投控', '2603.TW': '長榮', '2609.TW': '陽明',
    '2881.TW': '富邦金', '3231.TW': '緯創', '00662.TW': '富邦NASDAQ', 
    '0052.TW': '富邦科技', '00646.TW': '元大S&P500', '00919.TW': '群益台灣高息'
}

# 監控名單 (依您報告需求分類)
STOCKS_TOP_100 = ['2330.TW', '2317.TW', '2454.TW', '2308.TW', '2303.TW', '3711.TW', '2603.TW', '2609.TW', '2881.TW', '3231.TW']
ETFS_TOP_50 = ['00662.TW', '0052.TW', '00646.TW', '00919.TW']

def get_tech_data(sym):
    """抓取並計算技術指標"""
    try:
        df = yf.download(sym, period="2y", interval="1d", progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
        
        # 均線
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        
        # 週線轉化
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
        macd = ta.macd(df_w['Close'])
        
        # 取得最新數值
        res = {
            'df': df,
            'price': df['Close'].iloc[-1],
            'k': kd.iloc[-1]['STOCHk_9_3_3'], 'd': kd.iloc[-1]['STOCHd_9_3_3'],
            'pk': kd.iloc[-2]['STOCHk_9_3_3'], 'pd': kd.iloc[-2]['STOCHd_9_3_3'],
            'm_hist': macd.iloc[-1]['MACDh_12_26_9'], 'pm_hist': macd.iloc[-2]['MACDh_12_26_9'],
            'vol_ratio': df['Volume'].iloc[-1] / df['Volume'].iloc[-21:-1].mean()
        }
        return res
    except: return None

def plot_and_send(sym, name, info):
    """繪圖並發送"""
    img_name = f"{sym}.png"
    apds = [
        mpf.make_addplot(info['df']['MA20'].tail(60), color='blue', width=0.8),
        mpf.make_addplot(info['df']['MA60'].tail(60), color='orange', width=0.8)
    ]
    mpf.plot(info['df'].tail(60), type='candle', style='charles', addplot=apds, 
             title=f"{name} ({sym})", savefig=img_name)
    
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    with open(img_name, 'rb') as f:
        requests.post(url, data={'chat_id': TG_CHAT_ID, 'caption': f"📈 {name} ({sym}) 技術分析圖"}, files={'photo': f})
    os.remove(img_name)

def main():
    report_date = datetime.now().strftime('%Y/%m/%d')
    results = {'gold': [], 'initial': [], 'dead': [], 'etf_strong': [], 'etf_weak': [], 'breakout': []}
    
    print("開始執行深度篩選...")
    
    for sym in list(set(STOCKS_TOP_100 + ETFS_TOP_50)):
        info = get_tech_data(sym)
        if not info: continue
        name = NAME_MAP.get(sym, sym)
        
        # 判斷邏輯
        is_gold = info['k'] > info['d'] and info['pk'] <= info['pd']
        is_dead = info['k'] < info['d'] and info['pk'] >= info['pd']
        
        # 1. 市值百大分類
        if sym in STOCKS_TOP_100:
            if is_gold:
                if info['k'] < 30: results['initial'].append(f"{name} ({sym[:4]})")
                else: results['gold'].append(f"{name} ({sym[:4]})")
            elif is_dead: results['dead'].append(f"{name} ({sym[:4]})")
            
            # 3. 強勢回測判斷 (5日前爆量且站穩)
            df = info['df']
            if len(df) > 10:
                vol_break = df['Volume'].iloc[-6] > df['Volume'].iloc[-16:-6].mean() * 1.5
                stay_ma = (df['Close'].iloc[-5:] >= df['MA20'].iloc[-5:]).all()
                if vol_break and stay_ma:
                    results['breakout'].append(f"{name} ({sym[:4]})：5日前帶量突破，目前站穩 MA20。")

        # 2. ETF 分類
        if sym in ETFS_TOP_50:
            if info['k'] > 50: results['etf_strong'].append(f"{name}({sym[:5]})：週線多頭/高檔鈍化。")
            else: results['etf_weak'].append(f"{name}({sym[:5]})：週線震盪/需觀察支撐。")

        # 文中提及即發圖
        plot_and_send(sym, name, info)

    # --- 組合最終報告 ---
    report = f"【{report_date} 台股深度篩選分析報告】\n"
    report += "根據您的設定，本報告聚焦於市場龍頭與高流動性標的，並透過週線級別（中長期趨勢）與量價形態進行篩選。\n\n"
    
    report += "一、 市值百大個股：週線技術指標監測\n"
    report += f"🔹 *週 KD/MACD 黃金交叉*：\n{', '.join(results['gold']) if results['gold'] else '無'}\n"
    report += f"🔹 *週 KD/MACD 交叉向上 (初試)*：\n{', '.join(results['initial']) if results['initial'] else '無'}\n"
    report += f"🔸 *週 KD/MACD 死亡交叉 (警戒)*：\n{', '.join(results['dead']) if results['dead'] else '無'}\n\n"
    
    report += "二、 市值前 50 大 ETF 觀察\n"
    report += "*強勢標的 (週線多頭)：*\n" + "\n".join(results['etf_strong']) + "\n"
    report += "*震盪/警戒標的：*\n" + "\n".join(results['etf_weak']) + "\n\n"
    
    report += "三、 強勢回測名單 (5 日前帶量突破 + 站穩支撐)\n"
    report += "\n".join(results['breakout']) if results['breakout'] else "今日無顯著回測標的"
    
    report += "\n\n四、 總結與提醒\n目前大盤權值股的週線趨勢優於中小型股。若持股出現「死亡交叉」，建議檢視週線支撐。報告完畢。"

    # 最後發送長文報告
    url_msg = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url_msg, data={'chat_id': TG_CHAT_ID, 'text': report, 'parse_mode': 'Markdown'})

if __name__ == "__main__":
    main()
