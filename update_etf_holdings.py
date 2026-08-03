import os
import time
import json
import gspread
import pandas as pd
import numpy as np
import yfinance as yf
import requests
import re
from bs4 import BeautifulSoup
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 設定與環境變數
# ==========================================
PORTFOLIO_SHEET_URL = "https://docs.google.com/spreadsheets/d/16EgWvmGUPfOrDKGiefWCovNQNYf-E4RAVDGu7zx1BI4/edit?gid=818275503#gid=818275503"
HOLDINGS_SHEET_URL = "https://docs.google.com/spreadsheets/d/1_crBmjMxgm9qpYeycg_TnLStt3phN6vM4XILmD9x0Yc/edit?gid=1748501668#gid=1748501668"

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = os.getenv("GCP_CREDENTIALS") 

if not creds_json:
    raise ValueError("找不到 GCP_CREDENTIALS，請確認 GitHub Secrets 設定。")

creds_dict = json.loads(creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# ==========================================
# 2. 終極工業級濾網 (消滅所有雜訊與產業分類)
# ==========================================
def clean_holding_name(raw_name):
    """最嚴苛的黑名單，針對各網站混雜在表格中的雜訊進行深度清洗"""
    # 注意：這裡不直接移除所有空格，以免將英文公司名 (如 NVIDIA CORP) 黏在一起
    name = str(raw_name).strip().replace('\n', '').replace('\r', '')
    
    # 1. 移除開頭的數字、標點與空格 (如 "1. 台積電" -> "台積電")
    name = re.sub(r'^[\d\.,、\s]+', '', name)
    # 2. 移除結尾的代號或星號 (如 "聯發科(2454.TW)" -> "聯發科")
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'（.*?）', '', name)
    name = re.sub(r'\*+$', '', name)
    name = name.strip()
    
    # 3. 拒絕長度過短 (消滅 "A")
    if len(name) < 2: 
        return None
        
    # 4. 拒絕純數字與標點符號 (消滅 ",865,733.10")
    if re.fullmatch(r'^[0-9,\.\-\+%]+$', name.replace(' ', '')): 
        return None
        
    # 5. 拒絕國家地區與資產分類
    bad_exact = {
        '台灣', '臺灣', '美國', '日本', '中國', '香港', '韓國', '歐洲', '亞洲', '全球', '美洲', 
        '股票', '債券', '現金', '期貨', '選擇權', '基金', '合計', '小計', '總計', '資產', '其他', '行業', 
        '存款', '附買回', '流動準備', '名稱', '權重', '比例', '明細', '比重', '佔比', '發行公司', 
        '投資明細', '受益憑證', '外幣', '市值', '指數', '報酬'
    }
    if name.replace(' ', '') in bad_exact: 
        return None
        
    # 6. 拒絕國內外所有產業分類 (全面封殺 "資訊科技", "運動休閒", "半導體業")
    industries_exact = {
        # 台股分類
        '金融保險', '生技醫療', '通信網路', '觀光餐旅', '電子零組件', '半導體', '電腦及週邊設備', '電腦及週邊', 
        '光電', '航運', '鋼鐵', '塑膠', '紡織纖維', '電機機械', '電器電纜', '化學工業', '建材營造', '貿易百貨', 
        '油電燃氣', '橡膠', '造紙', '玻璃陶瓷', '水泥', '食品', '汽車', '電子通路', '資訊服務', '類指數',
        '綠能環保', '數位雲端', '運動休閒', '居家生活', '農業科技', '綜合',
        # 美股/GICS 國際分類
        '資訊科技', '通訊服務', '非核心消費', '核心消費', '醫療保健', '工業', '原材料', '房地產', '公用事業', '金融', '能源'
    }
    
    if name.replace('業', '') in industries_exact or name in industries_exact:
        return None
    
    # 阻擋以"業"結尾的產業分類，但放行真正的公司
    if name.endswith('業'):
        if name not in ['統一實業', '大成實業', '勤益控', '神達電腦', '廣達電腦', '仁寶電腦', '精誠資訊']:
            return None
            
    return name

# ==========================================
# 3. 雙核心解析引擎
# ==========================================
def parse_moneydj_rows(html_text):
    """針對 MoneyDJ 特製的逐列掃描器，無視表頭直接配對名稱與數字"""
    soup = BeautifulSoup(html_text, 'html.parser')
    results = []
    
    for tr in soup.find_all('tr'):
        tds = tr.find_all(['td', 'th'])
        if len(tds) < 2: continue
            
        texts = [td.text.strip() for td in tds]
        
        # 尋找該列是否有合法的個股名稱
        for i, txt in enumerate(texts):
            name = clean_holding_name(txt)
            if name:
                # 找到名稱後，往右側尋找合理的權重數字
                for w_txt in texts[i+1:]:
                    w_val = w_txt.replace('%', '').replace(',', '').strip()
                    try:
                        w = float(w_val)
                        if 0 < w <= 100:
                            results.append({"成分股名稱": name, "權重(%)": w})
                            break
                    except ValueError:
                        pass
                break # 換下一列
    return results

def parse_yahoo_json(html_text):
    """攔截 Yahoo 隱藏 JSON，無痛直取 Top 50"""
    results = []
    match = re.search(r'"holdings":\[(.*?)\]', html_text)
    if match:
        block = match.group(1)
        items = re.findall(r'{[^}]+}', block)
        for item in items:
            n_match = re.search(r'"name":"([^"]+)"', item)
            r_match = re.search(r'"ratio":([0-9.]+)', item)
            if n_match and r_match:
                name = clean_holding_name(n_match.group(1))
                if name:
                    try:
                        w = float(r_match.group(1))
                        if 0 < w <= 100:
                            results.append({"成分股名稱": name, "權重(%)": w})
                    except ValueError:
                        pass
    return results

def process_holdings(ticker, holdings_list):
    """綁定代號並移除重複項，嚴格鎖定輸出為 Top 20"""
    unique_dict = {}
    for h in holdings_list:
        name = h["成分股名稱"]
        if name not in unique_dict or h["權重(%)"] > unique_dict[name]["權重(%)"]:
            unique_dict[name] = h
            
    res = list(unique_dict.values())
    # 確保最多輸出 20 檔，並依照權重排序
    res = sorted(res, key=lambda x: x['權重(%)'], reverse=True)[:20]
    
    final_res = []
    for h in res:
        final_res.append({
            "ETF代號": ticker,
            "成分股名稱": h["成分股名稱"],
            "權重(%)": h["權重(%)"]
        })
    return final_res

def pad_tw_ticker(ticker):
    t = str(ticker).strip().upper().replace('.TW', '').replace('.TWO', '')
    if t.isdigit():
        if len(t) == 2: return "00" + t  
        if len(t) == 3: return "00" + t  
    else:
        if len(t) == 4 and t[0] in '123456789': return "00" + t 
    return t

# ==========================================
# 4. 爬蟲引擎配置
# ==========================================
def get_us_etf_holdings(ticker):
    print(f"🔍 正在檢查美股 ETF: {ticker}")
    
    try:
        etf = yf.Ticker(ticker)
        fd = etf.get_funds_data()
        if fd and fd.top_holdings is not None and not fd.top_holdings.empty:
            df = fd.top_holdings.head(20) 
            result = []
            for symbol, row in df.iterrows():
                w = row.get('Holding Percent', 0)
                if pd.notna(w) and w > 0:
                    name = clean_holding_name(row.get('Name', symbol))
                    if name: result.append({"成分股名稱": name, "權重(%)": round(w * 100, 2)})
            if result:
                res_list = process_holdings(ticker, result)
                print(f"✅ [來源: YFinance] 成功抓取美股 {ticker}，共 {len(res_list)} 檔")
                return res_list
    except Exception: pass
        
    print(f"⚠️ {ticker} 系統無提供成分股明細。")
    return []

def get_tw_etf_holdings(raw_ticker):
    clean_ticker = pad_tw_ticker(raw_ticker)
    print(f"🔍 正在抓取台股 ETF: {clean_ticker}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.moneydj.com/"
    }
    
    # 第一順位：Yahoo JSON (專攻 0050, 0056，可無痛取得 Top 20)
    for suffix in ['.TW', '.TWO']:
        try:
            url_y = f"https://tw.stock.yahoo.com/quote/{clean_ticker}{suffix}/holding"
            res = requests.get(url_y, headers=headers, timeout=10)
            if res.status_code == 200:
                holdings = parse_yahoo_json(res.text)
                if len(holdings) >= 10: 
                    res_list = process_holdings(clean_ticker, holdings)
                    print(f"✅ [來源: Yahoo JSON] 成功抓取 {clean_ticker}，共 {len(res_list)} 檔純淨資料")
                    time.sleep(1)
                    return res_list
        except Exception: pass

    # 第二順位：MoneyDJ (專攻 009813, 009815 等新股)
    # 注意：根據回報，全面使用小寫網址 etf/x/basic/basic0007.xdjhtm，並輪詢四種後綴
    suffixes_to_try = ['.tw', '.TW', '.two', '.TWO']
    
    for suffix in suffixes_to_try:
        try:
            url_m = f"https://www.moneydj.com/etf/x/basic/basic0007.xdjhtm?etfid={clean_ticker}{suffix}"
            res = requests.get(url_m, headers=headers, timeout=10)
            res.encoding = 'utf-8'
            if res.status_code == 200:
                holdings = parse_moneydj_rows(res.text)
                if holdings:
                    res_list = process_holdings(clean_ticker, holdings)
                    if len(res_list) > 0:
                        print(f"✅ [來源: MoneyDJ] 成功抓取 {clean_ticker}，共 {len(res_list)} 檔純淨資料")
                        time.sleep(1)
                        return res_list
        except Exception: pass
            
    print(f"⚠️ {clean_ticker} 查無明細 (可能為剛上市或資料空窗期)。")
    time.sleep(1)
    return []

# ==========================================
# 5. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (全網域突破 & 終極純淨版)...")
    
    try:
        portfolio_sheet = client.open_by_url(PORTFOLIO_SHEET_URL)
        tw_records = portfolio_sheet.worksheet("TW_Portfolio").get_all_records()
        us_records = portfolio_sheet.worksheet("US_Portfolio").get_all_records()
    except Exception as e:
        print(f"❌ 讀取 Portfolio_streamlit 失敗: {e}")
        return

    all_holdings = []

    # 處理台股
    for row in tw_records:
        raw_ticker = str(row.get('Ticker', '')).strip().upper()
        if not raw_ticker: continue
        clean_ticker = pad_tw_ticker(raw_ticker)
        
        if clean_ticker.startswith('00') and not clean_ticker.endswith('B'):
            holdings = get_tw_etf_holdings(clean_ticker)
            if holdings:
                all_holdings.extend(holdings)

    # 處理美股
    for row in us_records:
        ticker = str(row.get('Ticker', '')).strip().upper()
        if not ticker: continue
        holdings = get_us_etf_holdings(ticker)
        if holdings:
            all_holdings.extend(holdings)

    if not all_holdings:
        print("⚠️ 最終未取得任何 ETF 的持股資料。")
        return

    df_holdings = pd.DataFrame(all_holdings)
    cols_order = ['ETF代號', '成分股名稱', '權重(%)']
    df_holdings = df_holdings[cols_order]
    
    df_holdings.replace([np.inf, -np.inf], np.nan, inplace=True)
    df_holdings = df_holdings.fillna(0)
    
    tz_tw = timezone(timedelta(hours=8))
    current_date = datetime.now(tz_tw)
    
    sheet_title = current_date.strftime("%Y_%m_Top20")
    
    try:
        db_sheet = client.open_by_url(HOLDINGS_SHEET_URL)
        try:
            ws = db_sheet.worksheet(sheet_title)
            print(f"📝 找到當月工作表 {sheet_title}，準備更新資料...")
        except gspread.exceptions.WorksheetNotFound:
            print(f"✨ 建立新的月份工作表: {sheet_title}")
            ws = db_sheet.add_worksheet(title=sheet_title, rows="2000", cols="10")
            
        ws.clear()
        ws.update([df_holdings.columns.values.tolist()] + df_holdings.values.tolist())
        print(f"✅ 成功將所有 ETF 持股寫入 Google Sheets ({sheet_title})！")
    except Exception as e:
        print(f"❌ 寫入 ETF_Holdings_DB 失敗: {e}")

if __name__ == "__main__":
    main()
