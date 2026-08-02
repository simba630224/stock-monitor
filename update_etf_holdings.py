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
# 2. 爬蟲核心函式與小工具
# ==========================================

def pad_tw_ticker(ticker):
    """將 '50' 轉回 '0050'"""
    t = str(ticker).strip().upper().replace('.TW', '').replace('.TWO', '')
    if t.isdigit():
        if len(t) == 2: return "00" + t  
        if len(t) == 3: return "00" + t  
    else:
        if len(t) == 4 and t[0] in '123456789': return "00" + t 
    return t

def get_us_etf_holdings(ticker):
    """海外 ETF 爬蟲 (YFinance)"""
    print(f"🔍 正在檢查海外標的: {ticker}")
    try:
        etf = yf.Ticker(ticker)
        funds_data = etf.get_funds_data()
        
        if funds_data and funds_data.top_holdings is not None and not funds_data.top_holdings.empty:
            source_len = len(funds_data.top_holdings)
            print(f"ℹ️ [資料源] yfinance 實際提供 {source_len} 筆")
            
            holdings = funds_data.top_holdings.head(20) # 擴大至 20 筆
            result = []
            for symbol, row in holdings.iterrows():
                weight = row.get('Holding Percent', 0)
                if pd.isna(weight): weight = 0 
                
                result.append({
                    "ETF代號": ticker,
                    "成分股名稱": row.get('Name', symbol),
                    "權重(%)": round(weight * 100, 2)
                })
            print(f"✅ 成功抓取海外 ETF: {ticker}，共 {len(result)} 檔入庫")
            return result
    except Exception:
        pass
    print(f"⚠️ {ticker} 系統無提供成分股明細。")
    return []

def get_tw_etf_holdings(raw_ticker):
    """台股 ETF 爬蟲 (CMoney -> MoneyDJ -> Yahoo)"""
    clean_ticker = pad_tw_ticker(raw_ticker)
    print(f"🔍 正在抓取台股 ETF: {clean_ticker}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    result = []

    # ==================================
    # 引擎 1：CMoney (主力，可突破 Top 10)
    # ==================================
    try:
        url_c = f"https://www.cmoney.tw/etf/tw/{clean_ticker}/fundholding"
        res_c = requests.get(url_c, headers=headers, timeout=10)
        soup_c = BeautifulSoup(res_c.text, 'html.parser')
        
        tables = soup_c.find_all('table')
        for tbl in tables:
            header_row = tbl.find('tr')
            if not header_row: continue
            
            h_text = [c.text.strip().replace(' ', '') for c in header_row.find_all(['th', 'td'])]
            name_idx, weight_idx = -1, -1
            
            for i, h in enumerate(h_text):
                if any(k in h for k in ['名稱', '股票', '標的']): name_idx = i
                if any(k in h for k in ['權重', '比例', '比重', '佔比', '%']): weight_idx = i
                    
            if name_idx != -1 and weight_idx != -1:
                for row in tbl.find_all('tr')[1:]:
                    cols = row.find_all(['td', 'th'])
                    if len(cols) > max(name_idx, weight_idx):
                        name = cols[name_idx].text.strip()
                        weight_str = cols[weight_idx].text.replace('%', '').replace(',', '').strip()
                        try:
                            weight = float(weight_str)
                            if 0 < weight <= 100 and name:
                                result.append({"ETF代號": clean_ticker, "成分股名稱": name, "權重(%)": weight})
                        except ValueError:
                            continue
                break 
                
        if len(result) > 0:
            print(f"ℹ️ [資料源] CMoney 實際提供 {len(result)} 筆")
            result = sorted(result, key=lambda x: x['權重(%)'], reverse=True)[:20]
            print(f"✅ [來源: CMoney] 成功抓取 {clean_ticker}，共 {len(result)} 檔入庫")
            time.sleep(1)
            return result
    except Exception as e:
        pass

    # ==================================
    # 引擎 2：MoneyDJ (強制綁定 .TW)
    # ==================================
    try:
        # 依照您的觀察，MoneyDJ 無論上市櫃一律使用 .TW
        url_mdj = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}.TW"
        res_mdj = requests.get(url_mdj, headers=headers, timeout=10)
        res_mdj.encoding = 'utf-8'
        soup_mdj = BeautifulSoup(res_mdj.text, 'html.parser')
        
        tables = soup_mdj.find_all('table')
        for tbl in tables:
            header_row = tbl.find('tr')
            if not header_row: continue
            
            h_text = [c.text.strip().replace(' ', '') for c in header_row.find_all(['th', 'td'])]
            name_idx, weight_idx = -1, -1
            
            for i, h in enumerate(h_text):
                if any(k in h for k in ['名稱', '股票', '標的']): name_idx = i
                if any(k in h for k in ['權重', '比例', '比重', '佔比', '%']): weight_idx = i
                    
            if name_idx != -1 and weight_idx != -1:
                for row in tbl.find_all('tr')[1:]:
                    cols = row.find_all(['td', 'th'])
                    if len(cols) > max(name_idx, weight_idx):
                        name = cols[name_idx].text.strip()
                        weight_str = cols[weight_idx].text.replace('%', '').replace(',', '').strip()
                        try:
                            weight = float(weight_str)
                            if 0 < weight <= 100 and name and '名稱' not in name:
                                result.append({"ETF代號": clean_ticker, "成分股名稱": name, "權重(%)": weight})
                        except ValueError:
                            continue
                break 
                
        if len(result) > 0:
            print(f"ℹ️ [資料源] MoneyDJ 實際提供 {len(result)} 筆")
            result = sorted(result, key=lambda x: x['權重(%)'], reverse=True)[:20]
            print(f"✅ [來源: MoneyDJ] 成功抓取 {clean_ticker}，共 {len(result)} 檔入庫")
            time.sleep(1)
            return result
    except Exception:
        pass

    # ==================================
    # 引擎 3：Yahoo 股市 (備援，嘗試雙後綴)
    # ==================================
    for suffix in ['.TW', '.TWO']:
        try:
            url_yahoo = f"https://tw.stock.yahoo.com/quote/{clean_ticker}{suffix}/holding"
            res_y = requests.get(url_yahoo, headers=headers, timeout=10)
            soup_y = BeautifulSoup(res_y.text, 'html.parser')
            
            list_items = soup_y.find_all('li')
            for item in list_items:
                divs = item.find_all('div')
                if len(divs) >= 2:
                    name = divs[0].text.strip()
                    if not name or name in ['持股名稱', '股票名稱', '標的'] or len(name) > 20:
                        continue
                    
                    for d in divs[1:]:
                        txt = d.text.strip()
                        if '%' in txt and len(txt) < 15:
                            try:
                                weight = float(txt.replace('%', '').replace(',', ''))
                                if 0 < weight <= 100:
                                     result.append({"ETF代號": clean_ticker, "成分股名稱": name.split(' ')[0], "權重(%)": weight})
                                     break 
                            except ValueError:
                                pass

            if len(result) > 0:
                unique_result = list({v['成分股名稱']:v for v in result}.values())
                print(f"ℹ️ [資料源] Yahoo 網頁實際顯示 {len(unique_result)} 筆")
                result = sorted(unique_result, key=lambda x: x['權重(%)'], reverse=True)[:20]
                print(f"✅ [來源: Yahoo] 成功抓取 {clean_ticker}，共 {len(result)} 檔入庫")
                time.sleep(1)
                return result
        except Exception:
            pass
            
    print(f"⚠️ {clean_ticker} 各大網站無提供明細 (可能為剛上市之新股，或連結型基金)。")
    time.sleep(1)
    return []

# ==========================================
# 3. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (CMoney 突破 Top10 版)...")
    
    try:
        portfolio_sheet = client.open_by_url(PORTFOLIO_SHEET_URL)
        tw_records = portfolio_sheet.worksheet("TW_Portfolio").get_all_records()
        us_records = portfolio_sheet.worksheet("US_Portfolio").get_all_records()
    except Exception as e:
        print(f"❌ 讀取 Portfolio_streamlit 失敗: {e}")
        return

    all_holdings = []

    for row in tw_records:
        raw_ticker = str(row.get('Ticker', '')).strip().upper()
        if not raw_ticker: continue
        clean_ticker = pad_tw_ticker(raw_ticker)
        
        if clean_ticker.startswith('00') and not clean_ticker.endswith('B'):
            holdings = get_tw_etf_holdings(clean_ticker)
            if holdings:
                all_holdings.extend(holdings)

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
