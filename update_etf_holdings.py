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
# 2. 核心清洗與「相鄰單元格配對法」解析
# ==========================================
def clean_holding_name(raw_name):
    """終極黑名單濾網，確保只留下純淨個股名稱"""
    name = str(raw_name).strip().replace('\n', '').replace('\r', '').replace(' ', '')
    
    # 1. 移除開頭數字、編號與結尾星號/代號
    name = re.sub(r'^[\d\.、\s]+', '', name)
    name = re.sub(r'\*+$', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'（.*?）', '', name)
    
    # 2. 長度與格式防呆 (消滅 "A", "865,733")
    if len(name) < 2: return None
    if re.fullmatch(r'^[0-9,\.\-]+$', name): return None
        
    # 3. 拒絕國家與地區
    if name in ['台灣', '美國', '日本', '中國', '香港', '韓國', '歐洲', '亞洲', '全球', '美洲']:
        return None
        
    # 4. 拒絕包含特定字眼的資產分類與無效字眼
    bad_keywords = ['股票', '債券', '現金', '期貨', '選擇權', '基金', '合計', '小計', '總計', '資產', '其他', '行業', '存款', '附買回', '流動準備', '名稱', '權重', '比例', '明細', '比重', '佔比', '受益憑證', '市值', '外幣']
    if any(k in name for k in bad_keywords):
        return None
        
    # 5. 拒絕產業分類 (放行少數真正以"業"結尾的公司)
    if name.endswith('業'):
        if name not in ['統一實業', '大成實業', '勤益控', '神達電腦', '廣達電腦', '仁寶電腦', '精誠資訊']:
            return None
            
    industry_names = ['金融保險', '生技醫療', '通信網路', '觀光餐旅', '電子零組件', '半導體', '電腦及週邊設備', '光電', '航運', '鋼鐵', '塑膠', '紡織纖維', '電機機械', '電器電纜', '化學工業', '建材營造', '貿易百貨', '油電燃氣', '橡膠', '造紙', '玻璃陶瓷', '水泥', '食品', '汽車', '電子通路', '資訊服務', '類指數']
    if any(k in name for k in industry_names):
        return None
        
    return name

def extract_from_any_table(html_text):
    """
    最穩定的解析法：掃描表格每一列。
    只要找到合法的股票名稱，就往右找小於 100 的數字當作權重，無視表頭。
    """
    soup = BeautifulSoup(html_text, 'html.parser')
    results = []
    
    for tbl in soup.find_all('table'):
        for row in tbl.find_all('tr'):
            cols = [c.text.strip() for c in row.find_all(['td', 'th'])]
            if len(cols) < 2: continue
            
            # 遍歷該列每一個儲存格
            for i, col_text in enumerate(cols):
                candidate_name = clean_holding_name(col_text)
                
                # 如果這格是合法的股票名稱
                if candidate_name:
                    name = candidate_name
                    weight = None
                    
                    # 往該格的「右邊」尋找合理的權重數字
                    for w_text in cols[i+1:]:
                        w_val = w_text.replace('%', '').replace(',', '').strip()
                        try:
                            w = float(w_val)
                            # 必須是大於 0 且小於等於 100 的百分比
                            if 0 < w <= 100:
                                weight = w
                                break
                        except ValueError:
                            continue
                    
                    if name and weight:
                        results.append({"成分股名稱": name, "權重(%)": weight})
                    
                    break # 這一列已經找到目標，換下一列
    return results

def extract_yahoo_list(html_text):
    """Yahoo 專屬清單解析"""
    soup = BeautifulSoup(html_text, 'html.parser')
    results = []
    for li in soup.find_all('li'):
        divs = [d.text.strip() for d in li.find_all('div')]
        if not divs: continue
            
        for i, text in enumerate(divs):
            name = clean_holding_name(text.split(' ')[0])
            if name:
                for w_text in divs[i+1:]:
                    if '%' in w_text:
                        w_val = w_text.replace('%', '').replace(',', '').strip()
                        try:
                            w = float(w_val)
                            if 0 < w <= 100:
                                results.append({"成分股名稱": name, "權重(%)": w})
                                break
                        except ValueError:
                            continue
                break
    return results

def process_holdings(ticker, holdings_list):
    """綁定代號、去重複、嚴格鎖定 Top 20"""
    unique_dict = {}
    for h in holdings_list:
        name = h["成分股名稱"]
        if name not in unique_dict or h["權重(%)"] > unique_dict[name]["權重(%)"]:
            unique_dict[name] = h
            
    res = list(unique_dict.values())
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
# 3. 爬蟲引擎調度
# ==========================================
def get_us_etf_holdings(ticker):
    print(f"🔍 正在檢查美股 ETF: {ticker}")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    # 引擎 1：CMoney
    try:
        url_c = f"https://www.cmoney.tw/etf/us/{ticker}/fundholding"
        res = requests.get(url_c, headers=headers, timeout=10)
        if res.status_code == 200:
            holdings = extract_from_any_table(res.text)
            if holdings:
                res_list = process_holdings(ticker, holdings)
                print(f"✅ [來源: CMoney] 成功抓取美股 {ticker}，共 {len(res_list)} 檔")
                time.sleep(1)
                return res_list
    except Exception: pass

    # 引擎 2：YFinance
    try:
        etf = yf.Ticker(ticker)
        fd = etf.get_funds_data()
        if fd and fd.top_holdings is not None and not fd.top_holdings.empty:
            df = fd.top_holdings.head(20) 
            result = []
            for symbol, row in df.iterrows():
                weight = row.get('Holding Percent', 0)
                if pd.notna(weight) and weight > 0:
                    name = clean_holding_name(row.get('Name', symbol))
                    if name: result.append({"成分股名稱": name, "權重(%)": round(weight * 100, 2)})
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.moneydj.com/"
    }
    
    # 第一順位：MoneyDJ (穩定性最高，且擁有絕大多數 Top 20)
    for suffix in ['.TW', '.TWO']:
        try:
            url_m = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}{suffix}"
            res = requests.get(url_m, headers=headers, timeout=10)
            res.encoding = 'utf-8'
            if res.status_code == 200:
                holdings = extract_from_any_table(res.text)
                if holdings:
                    res_list = process_holdings(clean_ticker, holdings)
                    if len(res_list) > 0:
                        print(f"✅ [來源: MoneyDJ] 成功抓取 {clean_ticker}，共 {len(res_list)} 檔")
                        time.sleep(1)
                        return res_list
        except Exception: pass

    # 第二順位：CMoney
    try:
        url_c = f"https://www.cmoney.tw/etf/tw/{clean_ticker}/fundholding"
        res = requests.get(url_c, headers=headers, timeout=10)
        res.encoding = 'utf-8'
        if res.status_code == 200:
            holdings = extract_from_any_table(res.text)
            if holdings:
                res_list = process_holdings(clean_ticker, holdings)
                if len(res_list) > 0:
                    print(f"✅ [來源: CMoney] 成功抓取 {clean_ticker}，共 {len(res_list)} 檔")
                    time.sleep(1)
                    return res_list
    except Exception: pass

    # 第三順位：Yahoo 股市
    for suffix in ['.TW', '.TWO']:
        try:
            url_y = f"https://tw.stock.yahoo.com/quote/{clean_ticker}{suffix}/holding"
            res = requests.get(url_y, headers=headers, timeout=10)
            if res.status_code == 200:
                holdings = extract_yahoo_list(res.text)
                if holdings:
                    res_list = process_holdings(clean_ticker, holdings)
                    if len(res_list) > 0:
                        print(f"✅ [來源: Yahoo 備援] 成功抓取 {clean_ticker}，共 {len(res_list)} 檔")
                        time.sleep(1)
                        return res_list
        except Exception: pass
            
    print(f"⚠️ {clean_ticker} 查無明細 (可能為剛上市或受限於平台保護機制)。")
    time.sleep(1)
    return []

# ==========================================
# 4. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (高穩定相鄰配對版)...")
    
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
