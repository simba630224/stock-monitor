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
# 2. 工業級資料清洗 (集大成最強濾網)
# ==========================================
def clean_holding_name(raw_name):
    """最嚴格的資料濾網，徹底消滅亂碼、股數、產業與地區"""
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
        
    # 4. 拒絕包含特定字眼的資產分類
    bad_keywords = ['股票', '債券', '現金', '期貨', '選擇權', '基金', '合計', '小計', '總計', '資產', '其他', '行業', '存款', '附買回', '流動準備', '名稱', '權重', '比例', '明細', '比重', '佔比', '受益憑證', '市值']
    if any(k in name for k in bad_keywords):
        return None
        
    # 5. 拒絕產業分類 
    if name.endswith('業'):
        if name not in ['統一實業', '大成實業', '勤益控', '神達電腦', '廣達電腦', '仁寶電腦', '精誠資訊']:
            return None
            
    industry_names = ['金融保險', '生技醫療', '通信網路', '觀光餐旅', '電子零組件', '半導體', '電腦及週邊設備', '光電', '航運', '鋼鐵', '塑膠', '紡織纖維', '電機機械', '電器電纜', '化學工業', '建材營造', '貿易百貨', '油電燃氣', '橡膠', '造紙', '玻璃陶瓷', '水泥', '食品', '汽車', '電子通路', '資訊服務', '類指數']
    if name in industry_names:
        return None
        
    return name

# ==========================================
# 3. 混合解析引擎 (JSON + Pandas + 貪婪掃描)
# ==========================================
def extract_yahoo_json(html_text):
    """大絕招：攔截 Yahoo 後台完整 JSON (突破 10 檔限制)"""
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
                        weight = float(r_match.group(1))
                        if 0 < weight <= 100:
                            results.append({"成分股名稱": name, "權重(%)": weight})
                    except ValueError:
                        pass
    return results

def parse_with_pandas(html_text):
    """常規 Pandas 表格解析"""
    try:
        dfs = pd.read_html(StringIO(html_text))
        results = []
        for df in dfs:
            df = df.astype(str)
            name_col, weight_col = None, None
            
            for col in df.columns:
                col_str = str(col).replace(' ', '')
                if any(k in col_str for k in ['名稱', '股票', '標的', '成分股', '發行公司', '投資明細']):
                    name_col = col
                if any(k in col_str for k in ['權重', '比例', '比重', '佔比', '%', '佔資產']):
                    weight_col = col
                    
            if name_col is None or weight_col is None:
                for i in range(min(5, len(df))):
                    row = df.iloc[i]
                    for j, val in enumerate(row):
                        val_str = str(val).replace(' ', '')
                        if any(k in val_str for k in ['名稱', '股票', '標的', '成分股', '投資明細']):
                            name_col = df.columns[j]
                        if any(k in val_str for k in ['權重', '比例', '比重', '%']):
                            weight_col = df.columns[j]
                    if name_col and weight_col:
                        df = df.iloc[i+1:]
                        break

            if name_col and weight_col:
                for idx, row in df.iterrows():
                    name = clean_holding_name(row[name_col])
                    if name:
                        try:
                            weight = float(str(row[weight_col]).replace('%', '').replace(',', '').strip())
                            if 0 < weight <= 100:
                                results.append({"成分股名稱": name, "權重(%)": weight})
                        except ValueError:
                            pass
        return results
    except Exception:
        return []

def extract_texts_greedily(html_text):
    """終極備援：無差別文字掃描 (專剋 009815 異常排版)"""
    soup = BeautifulSoup(html_text, 'html.parser')
    blocks = list(soup.stripped_strings)
    results = []
    
    for i, block in enumerate(blocks):
        if '%' in block:
            w_str = block.replace('%', '').replace(',', '').strip()
        elif i + 1 < len(blocks) and blocks[i+1] == '%':
            w_str = blocks[i].replace(',', '').strip()
        else:
            continue
            
        try:
            weight = float(w_str)
            if not (0 < weight <= 100): continue
        except ValueError:
            continue
            
        name = None
        for j in range(1, 6):
            if i - j < 0: break
            candidate = clean_holding_name(blocks[i-j])
            if candidate:
                name = candidate
                break
                
        if name and weight:
            results.append({"成分股名稱": name, "權重(%)": weight})
    return results

def process_holdings(ticker, holdings_list):
    """綁定代號並移除重複項，嚴格鎖定 Top 20"""
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
# 4. 爬蟲引擎配置
# ==========================================
def get_us_etf_holdings(ticker):
    print(f"🔍 正在檢查美股 ETF: {ticker}")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    # 引擎 1：CMoney (直接 Pandas 解析)
    try:
        url_c = f"https://www.cmoney.tw/etf/us/{ticker}/fundholding"
        res = requests.get(url_c, headers=headers, timeout=10)
        holdings = parse_with_pandas(res.text)
        if holdings:
            res_list = process_holdings(ticker, holdings)
            print(f"✅ [來源: CMoney] 成功抓取美股 {ticker}，共 {len(res_list)} 檔")
            time.sleep(1)
            return res_list
    except Exception: pass

    # 引擎 2：YFinance
    try:
        etf = yf.Ticker(ticker)
        funds_data = etf.get_funds_data()
        if funds_data and funds_data.top_holdings is not None and not funds_data.top_holdings.empty:
            df = funds_data.top_holdings.head(20) 
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
        "Referer": "https://tw.stock.yahoo.com/"
    }
    
    # 優先引擎：Yahoo JSON 後台數據 (專攻 0050, 00713 突破 Top 20)
    for suffix in ['.TW', '.TWO']:
        try:
            url_y = f"https://tw.stock.yahoo.com/quote/{clean_ticker}{suffix}/holding"
            res = requests.get(url_y, headers=headers, timeout=10)
            if res.status_code == 200:
                holdings = extract_yahoo_json(res.text)
                if len(holdings) >= 5: # 確保 JSON 有回傳足夠數量的資料
                    res_list = process_holdings(clean_ticker, holdings)
                    print(f"✅ [來源: Yahoo JSON] 成功抓取 {clean_ticker}，共 {len(res_list)} 檔")
                    time.sleep(1)
                    return res_list
        except Exception: pass

    # 備援引擎：MoneyDJ 雙模式解析 (專攻 009815, 009812 等 Yahoo 尚未建檔之新股)
    for suffix in ['.TW', '.TWO']:
        try:
            url_m = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}{suffix}"
            res = requests.get(url_m, headers=headers, timeout=10)
            res.encoding = 'utf-8'
            if res.status_code == 200:
                # 模式 A: 嘗試 Pandas 表格解析
                holdings = parse_with_pandas(res.text)
                # 模式 B: 若找不到表格 (如 009815)，啟動貪婪掃描
                if not holdings or len(holdings) < 3:
                    holdings = extract_texts_greedily(res.text)
                    
                if holdings:
                    res_list = process_holdings(clean_ticker, holdings)
                    if len(res_list) > 0:
                        print(f"✅ [來源: MoneyDJ] 成功抓取 {clean_ticker}，共 {len(res_list)} 檔")
                        time.sleep(1)
                        return res_list
        except Exception: pass
            
    print(f"⚠️ {clean_ticker} 查無明細 (可能為剛上市或平台防爬蟲阻攔)。")
    time.sleep(1)
    return []

# ==========================================
# 5. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (混合解析與最強濾網最終版)...")
    
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
