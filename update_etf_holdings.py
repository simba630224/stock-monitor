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
from io import StringIO
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
# 2. 工業級資料清洗與 Pandas 解析引擎
# ==========================================
def clean_and_validate_holding(raw_name):
    """最嚴格的資料濾網，徹底消滅亂碼、股數、產業與地區"""
    name = str(raw_name).strip().replace('\n', '').replace('\r', '').replace(' ', '')
    
    # 1. 移除開頭數字、編號 (如 "1.台積電" -> "台積電") 與結尾星號
    name = re.sub(r'^\d+[.、\s]*', '', name)
    name = re.sub(r'\*+$', '', name)
    
    # 2. 長度與格式防呆 (消滅 "A" 或 ",865,733.10")
    if len(name) < 2: 
        return None
    # 如果整個字串只有數字、逗號、小數點組成，絕對是雜訊
    if re.fullmatch(r'^[0-9,\.]+$', name): 
        return None
        
    # 3. 拒絕國家與地區 (消滅 "台灣")
    if name in ['台灣', '美國', '日本', '中國', '香港', '韓國', '歐洲', '亞洲']:
        return None
        
    # 4. 拒絕包含特定字眼的資產分類
    bad_keywords = ['股票', '債券', '現金', '期貨', '選擇權', '基金', '合計', '小計', '總計', '資產', '其他', '行業', '存款', '附買回', '流動準備', '名稱', '權重', '比例', '明細', '比重', '佔比']
    if any(k in name for k in bad_keywords):
        return None
        
    # 5. 拒絕產業分類 (專殺 "半導體業", "金融保險")
    if name.endswith('業'):
        if name not in ['統一實業', '大成實業', '勤益控', '神達電腦', '廣達電腦', '仁寶電腦']:
            return None
            
    industry_names = ['金融保險', '生技醫療', '通信網路', '觀光餐旅', '電子零組件', '半導體', '電腦及週邊設備', '光電', '航運', '鋼鐵', '塑膠', '紡織纖維', '電機機械', '電器電纜', '化學工業', '建材營造', '貿易百貨', '油電燃氣', '橡膠', '造紙', '玻璃陶瓷', '水泥', '食品', '汽車', '電子通路', '資訊服務']
    if name in industry_names:
        return None
        
    return name

def parse_with_pandas(html_text):
    """利用 Pandas 精準抓取真正的欄位，不再全行盲掃"""
    try:
        dfs = pd.read_html(StringIO(html_text))
        results = []
        for df in dfs:
            df = df.astype(str)
            name_col, weight_col = None, None
            
            # 尋找欄位
            for col in df.columns:
                col_str = str(col).replace(' ', '')
                if any(k in col_str for k in ['名稱', '股票', '標的', '成分股', '發行公司']):
                    name_col = col
                if any(k in col_str for k in ['權重', '比例', '比重', '佔比', '%', '佔資產']):
                    weight_col = col
                    
            # 處理表頭藏在表格內部的狀況
            if name_col is None or weight_col is None:
                for i in range(min(5, len(df))):
                    row = df.iloc[i]
                    for j, val in enumerate(row):
                        val_str = str(val).replace(' ', '')
                        if any(k in val_str for k in ['名稱', '股票', '標的', '成分股']):
                            name_col = df.columns[j]
                        if any(k in val_str for k in ['權重', '比例', '比重', '%']):
                            weight_col = df.columns[j]
                    if name_col is not None and weight_col is not None:
                        df = df.iloc[i+1:] # 剃除表頭以上的雜訊
                        break

            # 成功定位欄位後，開始萃取數據
            if name_col is not None and weight_col is not None:
                for idx, row in df.iterrows():
                    raw_name = row[name_col]
                    raw_weight = row[weight_col]
                    
                    name = clean_and_validate_holding(raw_name)
                    if name:
                        try:
                            w_str = str(raw_weight).replace('%', '').replace(',', '').strip()
                            weight = float(w_str)
                            if 0 < weight <= 100:
                                results.append({"成分股名稱": name, "權重(%)": weight})
                        except ValueError:
                            pass
        return results
    except Exception:
        return []

def process_holdings(ticker, holdings_list):
    """綁定代號並移除重複項，設定上限 50 筆"""
    unique_dict = {}
    for h in holdings_list:
        name = h["成分股名稱"]
        if name not in unique_dict:
            unique_dict[name] = h
            
    res = list(unique_dict.values())
    res = sorted(res, key=lambda x: x['權重(%)'], reverse=True)[:50]
    
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
# 3. 爬蟲引擎配置
# ==========================================
def get_us_etf_holdings(ticker):
    print(f"🔍 正在檢查美股 ETF: {ticker}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    }
    
    # 引擎 1：CMoney
    try:
        url_c = f"https://www.cmoney.tw/etf/us/{ticker}/fundholding"
        res = requests.get(url_c, headers=headers, timeout=10)
        holdings = parse_with_pandas(res.text)
        if holdings:
            holdings = process_holdings(ticker, holdings)
            print(f"✅ [來源: CMoney] 成功抓取美股 {ticker}，共 {len(holdings)} 檔純淨資料")
            time.sleep(1)
            return holdings
    except Exception:
        pass

    # 引擎 2：YFinance
    try:
        etf = yf.Ticker(ticker)
        funds_data = etf.get_funds_data()
        if funds_data and funds_data.top_holdings is not None and not funds_data.top_holdings.empty:
            df = funds_data.top_holdings.head(50) 
            result = []
            for symbol, row in df.iterrows():
                weight = row.get('Holding Percent', 0)
                if pd.notna(weight) and weight > 0:
                    result.append({"成分股名稱": row.get('Name', symbol), "權重(%)": round(weight * 100, 2)})
            if result:
                print(f"✅ [來源: YFinance] 成功抓取美股 {ticker}，共 {len(result)} 檔純淨資料")
                return process_holdings(ticker, result)
    except Exception:
        pass
        
    print(f"⚠️ {ticker} 系統無提供成分股明細。")
    return []

def get_tw_etf_holdings(raw_ticker):
    clean_ticker = pad_tw_ticker(raw_ticker)
    print(f"🔍 正在抓取台股 ETF: {clean_ticker}")
    
    # 強化偽裝，試圖突破 CMoney 防護
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
        "Upgrade-Insecure-Requests": "1"
    }
    
    urls_to_try = [
        (f"https://www.cmoney.tw/etf/tw/{clean_ticker}/fundholding", "CMoney"),
        (f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}.TW", "MoneyDJ (.TW)"),
        (f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}.TWO", "MoneyDJ (.TWO)")
    ]
    
    for url, source_name in urls_to_try:
        try:
            res = requests.get(url, headers=headers, timeout=10)
            res.encoding = 'utf-8' if 'moneydj' in url else res.apparent_encoding
            
            holdings = parse_with_pandas(res.text)
            if holdings:
                holdings = process_holdings(clean_ticker, holdings)
                if len(holdings) > 0:
                    print(f"✅ [來源: {source_name}] 成功抓取 {clean_ticker}，共 {len(holdings)} 檔 (精準解析過濾)")
                    time.sleep(1)
                    return holdings
        except Exception:
            pass

    # 終極備援：Yahoo 股市
    for suffix in ['.TW', '.TWO']:
        try:
            url_y = f"https://tw.stock.yahoo.com/quote/{clean_ticker}{suffix}/holding"
            res = requests.get(url_y, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            results = []
            for item in soup.find_all('li'):
                divs = item.find_all('div')
                if len(divs) >= 2:
                    raw_n = divs[0].text.strip()
                    name = clean_and_validate_holding(raw_n.split(' ')[0])
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
            if results:
                results = process_holdings(clean_ticker, results)
                print(f"✅ [來源: Yahoo 備援] 成功抓取 {clean_ticker}，共 {len(results)} 檔純淨資料")
                time.sleep(1)
                return results
        except Exception:
            pass
            
    print(f"⚠️ {clean_ticker} 查無明細 (可能為剛上市無資料，或平台防爬蟲阻攔)。")
    time.sleep(1)
    return []

# ==========================================
# 4. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (工業級濾網純淨版)...")
    
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
    sheet_title = current_date.strftime("%Y_%m_Top50")
    
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
