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
# 2. 嚴格過濾與「外科手術級」表格解析
# ==========================================
def clean_holding_name(raw_name):
    """終極黑名單，剃除所有代號、產業與數字雜訊"""
    name = str(raw_name).strip().replace('\n', '').replace(' ', '')
    
    # 1. 移除開頭數字 (如 "1.台積電" -> "台積電") 與結尾星號
    name = re.sub(r'^[\d\.、\s]+', '', name)
    name = re.sub(r'\*+$', '', name)
    # 2. 移除括號內的代號 (如 "聯發科(2454.TW)" -> "聯發科")
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'（.*?）', '', name)
    
    # 3. 拒絕長度過短 (消滅 "A") 與純數字/標點 (消滅 "865,733.10")
    if len(name) < 2: return None
    if re.fullmatch(r'^[0-9,\.\-]+$', name): return None
        
    # 4. 拒絕國家與地區
    if name in ['台灣', '美國', '日本', '中國', '香港', '韓國', '歐洲', '亞洲', '全球']:
        return None
        
    # 5. 拒絕資產分類與欄位名稱
    bad_exact = ['股票', '債券', '現金', '期貨', '選擇權', '基金', '合計', '小計', '總計', '資產', '其他', '行業', '存款', '附買回', '流動準備', '名稱', '權重', '比例', '明細', '比重', '佔比', '發行公司', '持股', '市值', '受益憑證']
    if name in bad_exact: return None
        
    # 6. 拒絕產業分類 (專殺 0050 表格的分類列)
    bad_industries = ['半導體', '金融保險', '電子零組件', '電腦及週邊', '通信網路', '光電', '航運', '生技醫療', '塑膠', '電機機械', '電器電纜', '化學工業', '建材營造', '貿易百貨', '油電燃氣', '橡膠', '造紙', '玻璃陶瓷', '水泥', '食品', '汽車', '類指數', '電子通路', '資訊服務']
    if any(k in name for k in bad_industries): return None
    
    if name.endswith('業'):
        if name not in ['統一實業', '大成實業', '勤益控', '神達電腦', '廣達電腦', '仁寶電腦', '精誠資訊']:
            return None
            
    return name

def extract_table_holdings(html_text):
    """回歸最扎實的 HTML 表格逐欄解析，不掃描非欄位資料"""
    soup = BeautifulSoup(html_text, 'html.parser')
    results = []
    
    # 掃描網頁上的所有表格
    for table in soup.find_all('table'):
        name_idx = -1
        weight_idx = -1
        
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all(['th', 'td'])
            cell_texts = [c.text.strip().replace(' ', '').replace('\n', '') for c in cells]
            
            # 第一步：尋找該表格哪一欄是名稱，哪一欄是權重
            if name_idx == -1 or weight_idx == -1:
                for i, txt in enumerate(cell_texts):
                    if any(k in txt for k in ['名稱', '股票', '標的', '成分股', '發行公司']):
                        name_idx = i
                    if any(k in txt for k in ['權重', '比例', '比重', '佔比', '%', '佔資產']):
                        weight_idx = i
            
            # 第二步：找到欄位後，開始逐行萃取資料
            else:
                if len(cells) > max(name_idx, weight_idx):
                    raw_name = cell_texts[name_idx]
                    raw_weight = cell_texts[weight_idx]
                    
                    name = clean_holding_name(raw_name)
                    if name:
                        try:
                            # 確保權重欄位真的是數字，過濾掉表頭重複或雜訊
                            w_str = raw_weight.replace('%', '').replace(',', '').strip()
                            weight = float(w_str)
                            if 0 < weight <= 100:
                                results.append({"成分股名稱": name, "權重(%)": weight})
                        except ValueError:
                            pass
                            
    return results

def extract_yahoo_holdings(html_text):
    """Yahoo 專用的 div 列表解析"""
    soup = BeautifulSoup(html_text, 'html.parser')
    results = []
    for item in soup.find_all('li'):
        divs = item.find_all('div')
        if len(divs) >= 2:
            raw_n = divs[0].text.strip()
            name = clean_holding_name(raw_n.split(' ')[0])
            if not name: continue
            
            for d in divs[1:]:
                if '%' in d.text:
                    w_str = d.text.replace('%', '').replace(',', '').strip()
                    try:
                        weight = float(w_str)
                        if 0 < weight <= 100:
                            results.append({"成分股名稱": name, "權重(%)": weight})
                            break 
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
# 3. 爬蟲引擎配置 (雙管齊下)
# ==========================================
def get_us_etf_holdings(ticker):
    print(f"🔍 正在檢查美股 ETF: {ticker}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.cmoney.tw/"
    }
    
    # 引擎 1：CMoney (若未被擋則能抓取完整列表)
    try:
        url = f"https://www.cmoney.tw/etf/us/{ticker}/fundholding"
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            holdings = extract_table_holdings(res.text)
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
    
    # 第一順位：CMoney (直接訪問 /fundholding 取得 Top 20)
    try:
        url_c = f"https://www.cmoney.tw/etf/tw/{clean_ticker}/fundholding"
        res = requests.get(url_c, headers=headers, timeout=10)
        res.encoding = 'utf-8'
        if res.status_code == 200:
            holdings = extract_table_holdings(res.text)
            if holdings:
                res_list = process_holdings(clean_ticker, holdings)
                if len(res_list) > 0:
                    print(f"✅ [來源: CMoney] 成功抓取 {clean_ticker}，共 {len(res_list)} 檔")
                    time.sleep(1)
                    return res_list
    except Exception: pass

    # 第二順位：MoneyDJ (.TW 與 .TWO 雙引擎，專攻 0050 與 009815)
    for suffix in ['.TW', '.TWO']:
        try:
            url_m = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}{suffix}"
            res = requests.get(url_m, headers=headers, timeout=10)
            res.encoding = 'utf-8'
            if res.status_code == 200:
                holdings = extract_table_holdings(res.text)
                if holdings:
                    res_list = process_holdings(clean_ticker, holdings)
                    if len(res_list) > 0:
                        print(f"✅ [來源: MoneyDJ] 成功抓取 {clean_ticker}，共 {len(res_list)} 檔")
                        time.sleep(1)
                        return res_list
        except Exception: pass

    # 第三順位：Yahoo 股市
    for suffix in ['.TW', '.TWO']:
        try:
            url_y = f"https://tw.stock.yahoo.com/quote/{clean_ticker}{suffix}/holding"
            res = requests.get(url_y, headers=headers, timeout=10)
            if res.status_code == 200:
                holdings = extract_yahoo_holdings(res.text)
                if holdings:
                    res_list = process_holdings(clean_ticker, holdings)
                    if len(res_list) > 0:
                        print(f"✅ [來源: Yahoo 備援] 成功抓取 {clean_ticker}，共 {len(res_list)} 檔")
                        time.sleep(1)
                        return res_list
        except Exception: pass
            
    print(f"⚠️ {clean_ticker} 查無明細 (可能為剛上市或平台防爬蟲阻攔)。")
    time.sleep(1)
    return []

# ==========================================
# 4. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (外科手術級解析純淨版)...")
    
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
