import os
import time
import json
import gspread
import pandas as pd
import numpy as np
import yfinance as yf
import requests
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
# 2. 萬用表格解析器 (無懼網頁排版變更)
# ==========================================
def parse_html_table(html_text):
    """動態往下掃描尋找標題列，避開 MoneyDJ 等網站的跨欄標題陷阱"""
    soup = BeautifulSoup(html_text, 'html.parser')
    tables = soup.find_all('table')
    
    for tbl in tables:
        rows = tbl.find_all('tr')
        name_idx, weight_idx = -1, -1
        data_start_idx = -1
        
        # 1. 掃描表格前 5 列，尋找真正的欄位名稱
        for r_idx, row in enumerate(rows[:5]):
            cells = row.find_all(['th', 'td'])
            c_texts = [c.text.strip().replace(' ', '').replace('\n', '') for c in cells]
            
            for i, txt in enumerate(c_texts):
                if any(k in txt for k in ['名稱', '股票', '標的', '成分股', '持股']):
                    if name_idx == -1: name_idx = i
                if any(k in txt for k in ['權重', '比例', '比重', '佔比', '%']):
                    if weight_idx == -1: weight_idx = i
                    
            if name_idx != -1 and weight_idx != -1:
                data_start_idx = r_idx + 1
                break
        
        # 2. 開始抓取數據 (完全解除 Top 10 限制)
        holdings = []
        if data_start_idx != -1:
            for row in rows[data_start_idx:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) > max(name_idx, weight_idx):
                    name = cells[name_idx].text.strip()
                    w_str = cells[weight_idx].text.replace('%', '').replace(',', '').strip()
                    
                    # 過濾雜訊與合計列
                    if not name or name in ['小計', '總計', '基金', '合計'] or '名稱' in name:
                        continue
                        
                    try:
                        weight = float(w_str)
                        if 0 < weight <= 100:
                            holdings.append({"成分股名稱": name, "權重(%)": weight})
                    except ValueError:
                        continue
            
            if holdings:
                return holdings
    return []

def parse_yahoo_html(html_text):
    """Yahoo 專屬 DIV 清單解析器"""
    soup = BeautifulSoup(html_text, 'html.parser')
    list_items = soup.find_all('li')
    holdings = []
    for item in list_items:
        divs = item.find_all('div')
        if len(divs) >= 2:
            name = divs[0].text.strip()
            if not name or name in ['持股名稱', '股票名稱', '標的'] or len(name) > 30:
                continue
            for d in divs[1:]:
                txt = d.text.strip()
                if '%' in txt and len(txt) < 15:
                    try:
                        weight = float(txt.replace('%', '').replace(',', ''))
                        if 0 < weight <= 100:
                            holdings.append({"成分股名稱": name.split(' ')[0], "權重(%)": weight})
                            break 
                    except ValueError:
                        pass
    return holdings

def process_holdings(ticker, holdings_list):
    """綁定 ETF 代號並允許最大抓取 50 筆"""
    res = []
    for h in holdings_list[:50]:
        res.append({
            "ETF代號": ticker,
            "成分股名稱": h["成分股名稱"],
            "權重(%)": h["權重(%)"]
        })
    return res

def pad_tw_ticker(ticker):
    t = str(ticker).strip().upper().replace('.TW', '').replace('.TWO', '')
    if t.isdigit():
        if len(t) == 2: return "00" + t  
        if len(t) == 3: return "00" + t  
    else:
        if len(t) == 4 and t[0] in '123456789': return "00" + t 
    return t

# ==========================================
# 3. 各市場爬蟲引擎
# ==========================================
def get_us_etf_holdings(ticker):
    print(f"🔍 正在檢查海外標的: {ticker}")
    try:
        etf = yf.Ticker(ticker)
        funds_data = etf.get_funds_data()
        if funds_data and funds_data.top_holdings is not None and not funds_data.top_holdings.empty:
            holdings = funds_data.top_holdings.head(50) # 放寬到 50 筆
            result = []
            for symbol, row in holdings.iterrows():
                weight = row.get('Holding Percent', 0)
                if pd.isna(weight): weight = 0 
                result.append({"成分股名稱": row.get('Name', symbol), "權重(%)": round(weight * 100, 2)})
            print(f"✅ 成功抓取海外 ETF: {ticker}，共 {len(result)} 檔")
            return process_holdings(ticker, result)
    except Exception:
        pass
    print(f"⚠️ {ticker} 系統無提供成分股明細。")
    return []

def get_tw_etf_holdings(raw_ticker):
    clean_ticker = pad_tw_ticker(raw_ticker)
    print(f"🔍 正在抓取台股 ETF: {clean_ticker}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    # 引擎 1：MoneyDJ (感謝您發現的關鍵，強制綁定 .TW)
    try:
        url_mdj = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}.TW"
        res = requests.get(url_mdj, headers=headers, timeout=10)
        res.encoding = 'utf-8'
        holdings = parse_html_table(res.text)
        if holdings:
            holdings = sorted(holdings, key=lambda x: x['權重(%)'], reverse=True)
            print(f"✅ [來源: MoneyDJ] 成功抓取 {clean_ticker}，共 {len(holdings)} 檔")
            time.sleep(1)
            return process_holdings(clean_ticker, holdings)
    except Exception:
        pass

    # 引擎 2：CMoney (備援)
    try:
        url_c = f"https://www.cmoney.tw/etf/tw/{clean_ticker}/fundholding"
        res = requests.get(url_c, headers=headers, timeout=10)
        holdings = parse_html_table(res.text)
        if holdings:
            holdings = sorted(holdings, key=lambda x: x['權重(%)'], reverse=True)
            print(f"✅ [來源: CMoney] 成功抓取 {clean_ticker}，共 {len(holdings)} 檔")
            time.sleep(1)
            return process_holdings(clean_ticker, holdings)
    except Exception:
        pass

    # 引擎 3：Yahoo 股市 (雙後綴備援)
    for suffix in ['.TW', '.TWO']:
        try:
            url_y = f"https://tw.stock.yahoo.com/quote/{clean_ticker}{suffix}/holding"
            res = requests.get(url_y, headers=headers, timeout=10)
            holdings = parse_yahoo_html(res.text)
            if holdings:
                unique_holdings = list({v['成分股名稱']:v for v in holdings}.values())
                unique_holdings = sorted(unique_holdings, key=lambda x: x['權重(%)'], reverse=True)
                print(f"✅ [來源: Yahoo] 成功抓取 {clean_ticker}，共 {len(unique_holdings)} 檔")
                time.sleep(1)
                return process_holdings(clean_ticker, unique_holdings)
        except Exception:
            pass
            
    print(f"⚠️ {clean_ticker} 各大網站無提供明細 (可能為剛上市或資料空窗期)。")
    time.sleep(1)
    return []

# ==========================================
# 4. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (萬用解析突破 Top10 版)...")
    
    try:
        portfolio_sheet = client.open_by_url(PORTFOLIO_SHEET_URL)
        tw_records = portfolio_sheet.worksheet("TW_Portfolio").get_all_records()
        us_records = portfolio_sheet.worksheet("US_Portfolio").get_all_records()
    except Exception as e:
        print(f"❌ 讀取 Portfolio_streamlit 失敗: {e}")
        return

    all_holdings = []

    # 處理台股 (已拔除無效的 YFinance 查詢)
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
    sheet_title = current_date.strftime("%Y_%m_Top50") # 標題改為 Top 50
    
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
