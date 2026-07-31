import os
import time
import json
import gspread
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# 1. 設定與環境變數
# ==========================================
# 請將這裡換成您實際的 Google Sheets 網址
PORTFOLIO_SHEET_URL = "https://docs.google.com/spreadsheets/d/16EgWvmGUPfOrDKGiefWCovNQNYf-E4RAVDGu7zx1BI4/edit?gid=0#gid=0"
HOLDINGS_SHEET_URL = "https://docs.google.com/spreadsheets/d/1_crBmjMxgm9qpYeycg_TnLStt3phN6vM4XILmD9x0Yc/edit?gid=1970038349#gid=1970038349"

# Google Sheets API 授權
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = os.getenv("GCP_CREDENTIALS") # 從 GitHub Secrets 讀取

if not creds_json:
    raise ValueError("找不到 GCP_CREDENTIALS，請確認 GitHub Secrets 設定。")

creds_dict = json.loads(creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# ==========================================
# 2. 爬蟲核心函式
# ==========================================

def get_us_etf_holdings(ticker):
    """使用 yfinance 抓取美股 ETF Top 20 持股"""
    print(f"🔍 正在抓取美股 ETF: {ticker}")
    try:
        etf = yf.Ticker(ticker)
        funds_data = etf.get_funds_data()
        if funds_data and funds_data.top_holdings is not None:
            # 修改為 head(20) 抓取前 20 大
            holdings = funds_data.top_holdings.head(20)
            result = []
            for symbol, row in holdings.iterrows():
                result.append({
                    "ETF代號": ticker,
                    "成分股代號": symbol,
                    "成分股名稱": row.get('Name', symbol),
                    "權重(%)": round(row.get('Holding Percent', 0) * 100, 2)
                })
            print(f"✅ 成功抓取美股 ETF: {ticker}，共 {len(result)} 檔成分股")
            return result
    except Exception as e:
        print(f"❌ 抓取 {ticker} 失敗: {e}")
    return []

def get_tw_etf_holdings(ticker):
    """
    台股 ETF Top 20 持股爬蟲 (雙引擎備援：MoneyDJ -> Yahoo)
    """
    clean_ticker = str(ticker).replace('.TW', '').replace('.TWO', '')
    print(f"🔍 正在抓取台股 ETF: {clean_ticker}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    # ==========================================
    # 引擎 1：嘗試 MoneyDJ (模糊搜尋)
    # ==========================================
    result = []
    try:
        url_mdj = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}.TW"
        res = requests.get(url_mdj, headers=headers, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        tables = soup.find_all('table')
        for tbl in tables:
            if '權重' in tbl.text or '比例' in tbl.text or '持股' in tbl.text:
                for row in tbl.find_all('tr'):
                    cols = [c.text.strip() for c in row.find_all(['td', 'th'])]
                    if len(cols) >= 3:
                        name = cols[0]
                        weight_str = cols[-1].replace('%', '').strip()
                        try:
                            weight = float(weight_str)
                            if weight > 0 and name != '股票名稱' and name != '名稱':
                                result.append({
                                    "ETF代號": clean_ticker,
                                    "成分股名稱": name,
                                    "權重(%)": weight
                                })
                        except ValueError:
                            continue
                break # 找到目標表格就跳出
                
        if len(result) > 0:
            # 排序並截取前 20 大
            result = sorted(result, key=lambda x: x['權重(%)'], reverse=True)[:20]
            print(f"✅ [來源: MoneyDJ] 成功抓取 {clean_ticker}，共 {len(result)} 檔成分股")
            time.sleep(2)
            return result
            
    except Exception as e:
        print(f"⚠️ MoneyDJ 抓取異常: {e}")

    # ==========================================
    # 引擎 2：若 MoneyDJ 失敗，啟動備援 Yahoo 股市
    # ==========================================
    print(f"🔄 MoneyDJ 無法取得資料，啟動備援機制 (Yahoo 股市)...")
    result = []
    try:
        url_yahoo = f"https://tw.stock.yahoo.com/quote/{clean_ticker}.TW/holding"
        res = requests.get(url_yahoo, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        list_items = soup.find_all('li', class_=lambda x: x and 'List(n)' in x)
        
        for item in list_items:
            text_blocks = item.find_all('div')
            if len(text_blocks) >= 2:
                name = text_blocks[0].text.strip()
                weight_block = item.find(text=lambda t: '%' in t if t else False)
                
                if weight_block:
                    weight_str = weight_block.replace('%', '').strip()
                    try:
                        weight = float(weight_str)
                        if weight > 0 and len(name) > 0 and name != '持股名稱':
                             result.append({
                                "ETF代號": clean_ticker,
                                "成分股名稱": name.split(' ')[0], # 切開代號取名稱
                                "權重(%)": weight
                            })
                    except ValueError:
                        pass
        
        if len(result) > 0:
            unique_result = {v['成分股名稱']:v for v in result}.values()
            # 排序並截取前 20 大
            result = sorted(list(unique_result), key=lambda x: x['權重(%)'], reverse=True)[:20]
            print(f"✅ [來源: Yahoo] 成功抓取 {clean_ticker}，共 {len(result)} 檔成分股")
            time.sleep(2)
            return result

    except Exception as e:
        print(f"❌ Yahoo 抓取異常: {e}")

    print(f"⚠️ {clean_ticker} 所有備援來源皆抓取失敗。")
    return []

# ==========================================
# 3. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (Top 20)...")
    
    # 1. 讀取現有投資組合
    try:
        portfolio_sheet = client.open_by_url(PORTFOLIO_SHEET_URL)
        tw_records = portfolio_sheet.worksheet("TW_Portfolio").get_all_records()
        us_records = portfolio_sheet.worksheet("US_Portfolio").get_all_records()
    except Exception as e:
        print(f"讀取 Portfolio_streamlit 失敗: {e}")
        return

    all_holdings = []

    # 2. 處理台股 ETF (過濾出 00 開頭的 ETF)
    for row in tw_records:
        ticker = str(row.get('Ticker', ''))
        if ticker.startswith('00'): 
            holdings = get_tw_etf_holdings(ticker)
            all_holdings.extend(holdings)

    # 3. 處理美股 ETF (過濾掉個股，您可以自行增減此清單)
    us_etf_list = ['VOO', 'QQQ', 'VT', 'BND', 'BNDW', 'BNDX', 'IEF', 'VNQ', 'VXUS']
    for row in us_records:
        ticker = str(row.get('Ticker', '')).upper()
        if ticker in us_etf_list:
            holdings = get_us_etf_holdings(ticker)
            all_holdings.extend(holdings)

    if not all_holdings:
        print("⚠️ 未抓取到任何持股資料。")
        return

    # 4. 轉換為 DataFrame 並寫入新的 Google Sheet
    df_holdings = pd.DataFrame(all_holdings)
    
    try:
        db_sheet = client.open_by_url(HOLDINGS_SHEET_URL)
        
        # 檢查工作表是否存在，不存在則建立 (名稱改為 Top20_Holdings)
        try:
            ws = db_sheet.worksheet("Top20_Holdings")
        except gspread.exceptions.WorksheetNotFound:
            ws = db_sheet.add_worksheet(title="Top20_Holdings", rows="2000", cols="10")
            
        # 清空舊資料並寫入新資料
        ws.clear()
        ws.update([df_holdings.columns.values.tolist()] + df_holdings.values.tolist())
        print("✅ 成功將所有 ETF 前 20 大持股寫入 Google Sheets！")
        
    except Exception as e:
        print(f"❌ 寫入 ETF_Holdings_DB 失敗: {e}")

if __name__ == "__main__":
    main()
