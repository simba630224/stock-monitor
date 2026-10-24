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
# 2. 替身備案字典 (Plan B 備援專用)
# ==========================================
FEEDER_PROXY_MAP = {
    '009813': 'XLG',    # 貝萊德 S&P 500 Top 50
    '009815': 'MAGS',   # 大華美國 MAG7+
    '00646': 'IVV',     # 元大 S&P 500
    '00662': 'QQQ',     # 富邦 NASDAQ
    '00830': 'SOXX',    # 國泰費城半導體
    '00757': 'FNGS',    # 統一 FANG+
}

# ==========================================
# 3. 精準補零與個股判定
# ==========================================
def normalize_tw_ticker(ticker):
    """
    精準還原台股代號：
    - 若為 2~3 位純數字 -> 補 '00' (如 '50' -> '0050')
    - 若為 4 位純數字且 >= 1000 -> 視為個股，不補零 (如 '2330' -> '2330')
    - 若為 4 位純數字且 < 1000 -> 補滿 '00'
    - 若為 9 開頭的 ETF -> 補 '00' (如 '9816' -> '009816')
    """
    t = str(ticker).strip().upper().replace('.TW', '').replace('.TWO', '')
    if not t:
        return ""
    
    if t.startswith('00'):
        return t
    
    if t.startswith('0'):
        return '0' + t
        
    if t.isdigit():
        val = int(t)
        # 一般個股代號通常 >= 1101
        if len(t) == 4 and val >= 1000:
            # 針對 9 開頭的 ETF 進行特判 (例如 9816)
            if t.startswith('9'):
                 return '00' + t
            return t  
        if val < 1000:
            return '00' + t
        if len(t) == 4 and t.startswith('98'):
            return '00' + t
        return t

    if re.match(r'^\d{3,4}[A-Z]$', t):
        return '00' + t
        
    return t

def is_tw_stock_etf(clean_ticker, category_str=""):
    """判斷是否為需要抓成分股的台股『股票型/主動型 ETF』（排除一般個股與債券B）"""
    if '個股' in str(category_str) or '債' in str(category_str):
        return False
    if clean_ticker.startswith('00') and not clean_ticker.endswith('B'):
        return True
    return False

def clean_holding_name(raw_name):
    """最高規格防雜訊黑名單 (清理代號後綴、外幣與產業分類)"""
    name = str(raw_name).strip().replace('\n', '').replace('\r', '')
    
    name = re.sub(r'^[\d\.,、\s]+', '', name)
    name = re.sub(r'\s+\d{4,6}[A-Z]*$', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'（.*?）', '', name)
    name = re.sub(r'\*+$', '', name)
    name = name.strip()
    
    if len(name) < 2: return None
    if re.fullmatch(r'^[0-9,\.\-\+%]+$', name.replace(' ', '')): return None
    
    if re.search(r'[A-Z]{3}/[A-Z]{3}', name): return None
    if any(k in name.upper() for k in ['CASH', 'RECEIVABLE', 'PAYABLE', 'MARGIN', 'FUTURES']): return None
    if any(k in name for k in ['現金', '應收', '應付', '保證金', '期貨', '附買回']): return None
        
    bad_exact = {
        '台灣', '臺灣', '美國', '日本', '中國', '香港', '韓國', '歐洲', '亞洲', '全球', '美洲', 
        '股票', '債券', '期貨', '選擇權', '基金', '合計', '小計', '總計', '資產', '其他', '行業', 
        '存款', '附買回', '流動準備', '名稱', '股票名稱', '權重', '比例', '明細', '比重', '佔比', '發行公司', 
        '投資明細', '受益憑證', '外幣', '市值', '指數', '報酬', '綜合', '能源', '工業', '原材料', 
        '半導體', '金融', '光電', '航運', '鋼鐵', '塑膠', '橡膠', '造紙', '水泥', '食品', '汽車', '電子'
    }
    if name.replace(' ', '') in bad_exact: return None
        
    if name.startswith('電子-') or name.startswith('上市') or name.startswith('上櫃'): return None
    if name.endswith('消費品') or name.endswith('服務'): return None
        
    bad_substrings = [
        '通信網路', '運動休閒', '資訊科技', '綠能環保', '數位雲端', '居家生活', '農業科技', 
        '金融保險', '生技醫療', '觀光餐旅', '電子零組件', '半導體業', '建材營造', '貿易百貨', 
        '油電燃氣', '化學工業', '電器電纜', '電機機械', '紡織纖維', '玻璃陶瓷', '電子通路', 
        '資訊服務', '醫療保健', '通訊服務', '非核心消費', '核心消費', '公用事業', '房地產',
        '週邊設備', '日常消費', '原物料', '文化創意', '其他電子'
    ]
    if any(bad in name for bad in bad_substrings): return None
    
    if name.endswith('業') and name not in ['統一實業', '大成實業', '勤益控', '神達電腦', '廣達電腦', '仁寶電腦', '精誠資訊', '台達電子工業', '健策精密工業', '仁寶電腦工業', '嘉澤端子工業', '聯亞光電工業', '中國砂輪企業']:
        return None
            
    return name

# ==========================================
# 4. 四大網頁解析引擎
# ==========================================
def parse_generic_html_tables(html_text):
    """通用工業級 HTML 表格解析器 (適用 MoneyDJ、玩股網、CMoney、口袋證券)"""
    soup = BeautifulSoup(html_text, 'html.parser')
    results = []
    
    for tbl in soup.find_all('table'):
        name_idx, weight_idx = -1, -1
        rows = tbl.find_all('tr')
        
        for row in rows:
            cols = row.find_all(['th', 'td'])
            if len(cols) < 2: continue
            texts = [c.text.strip().replace(' ', '').replace('\n', '') for c in cols]
            
            if name_idx == -1 or weight_idx == -1:
                for i, t in enumerate(texts):
                    if any(k in t for k in ['股票名稱', '成分股', '標的名稱', '名稱', '股票', '投資標的']):
                        if name_idx == -1: name_idx = i
                    if any(k in t for k in ['權重', '持股比例', '比重', '比例', '佔比']):
                        if '增減' not in t and '漲跌' not in t:
                            weight_idx = i
            else:
                if len(cols) > max(name_idx, weight_idx):
                    raw_name = cols[name_idx].text.strip()
                    name = clean_holding_name(raw_name)
                    if name:
                        w_str = cols[weight_idx].text.replace('%', '').replace(',', '').strip()
                        try:
                            w = float(w_str)
                            if 0 < w <= 100:
                                results.append({"成分股名稱": name, "權重(%)": w})
                        except ValueError: pass
    return results

def parse_yahoo_json(html_text):
    """攔截 Yahoo 隱藏 JSON"""
    results = []
    match = re.search(r'"holdings":\[(.*?)\](?=,"[a-zA-Z]+":)', html_text)
    if not match:
        match = re.search(r'"holdings":\[(.*?)\]', html_text)
        
    if match:
        items = re.findall(r'{[^}]+}', match.group(1))
        for item in items:
            n_match = re.search(r'"name":"([^"]+)"', item)
            r_match = re.search(r'"ratio":([0-9.]+)', item)
            if n_match and r_match:
                name = clean_holding_name(n_match.group(1).encode('utf-8').decode('unicode_escape', errors='ignore'))
                if name:
                    try:
                        w = float(r_match.group(1))
                        if 0 < w <= 100:
                            results.append({"成分股名稱": name, "權重(%)": w})
                    except ValueError: pass
    return results

def process_holdings(ticker, holdings_list):
    """綁定代號並移除重複項，上限切齊 Top 20"""
    unique_dict = {}
    for h in holdings_list:
        name = h["成分股名稱"]
        if name not in unique_dict or h["權重(%)"] > unique_dict[name]["權重(%)"]:
            unique_dict[name] = h
            
    res = list(unique_dict.values())
    res = sorted(res, key=lambda x: x['權重(%)'], reverse=True)[:20]
    
    return [{
        "ETF代號": ticker,
        "成分股名稱": h["成分股名稱"],
        "權重(%)": h["權重(%)"]
    } for h in res]

# ==========================================
# 5. 台美股 ETF 抓取主流程
# ==========================================
def get_us_etf_holdings(ticker, override_ticker=None):
    target_output_ticker = override_ticker if override_ticker else ticker
    
    try:
        etf = yf.Ticker(ticker)
        if not override_ticker:
            try:
                q_type = etf.fast_info.get('quoteType', '') or etf.info.get('quoteType', '')
                if str(q_type).upper() == 'EQUITY':
                    return []  
            except Exception:
                pass

        msg = f"🔍 正在抓取海外 ETF: {ticker}"
        if override_ticker:
            msg = f"🔄 [特例/備案啟動]: 透過 {ticker} 抓取 {override_ticker} 的底層資料..."
        print(msg)

        fd = etf.get_funds_data()
        if fd and fd.top_holdings is not None and not fd.top_holdings.empty:
            df = fd.top_holdings.head(20) 
            result = []
            for symbol, row in df.iterrows():
                w = row.get('Holding Percent', 0)
                if pd.notna(w) and w > 0:
                    raw_name = row.get('Name', symbol)
                    name = clean_holding_name(raw_name) if clean_holding_name(raw_name) else symbol
                    if name:
                        result.append({"成分股名稱": name, "權重(%)": round(w * 100, 2)})
            if result:
                res_list = process_holdings(target_output_ticker, result)
                print(f"✅ [來源: YFinance] 成功抓取 {target_output_ticker}，共 {len(res_list)} 檔")
                return res_list
    except Exception:
        pass
    
    if override_ticker:
        print(f"⚠️ 海外替身 {ticker} 亦無提供成分股明細。")
    return []

def get_tw_etf_holdings(clean_ticker):
    if clean_ticker == '009812':
        print(f"⚡ 觸發特例規則：{clean_ticker} 迴避台灣網站，直接穿透至日股 1306.T")
        return get_us_etf_holdings('1306.T', override_ticker='009812')
        
    print(f"🔍 正在抓取台股 ETF: {clean_ticker}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    # ----------------------------------------------------
    # [引擎 1]：玩股網 Wantgoo 
    # ----------------------------------------------------
    try:
        url_w = f"https://www.wantgoo.com/stock/etf/{clean_ticker}/constituent"
        res = requests.get(url_w, headers=headers, timeout=12)
        if res.status_code == 200:
            holdings = parse_generic_html_tables(res.text)
            if len(holdings) >= 3:
                final_results = process_holdings(clean_ticker, holdings)
                print(f"✅ [來源: 玩股網 Wantgoo] 成功抓取 {clean_ticker}，共 {len(final_results)} 檔純淨資料")
                time.sleep(1)
                return final_results
    except Exception:
        pass

    # ----------------------------------------------------
    # [引擎 2]：MoneyDJ 改良版 
    # ----------------------------------------------------
    endpoints = ['Basic0007.xdjhtm', 'Basic0007B.xdjhtm', 'Basic0007A.xdjhtm']
    suffixes = ['.tw', '.TW', '.two', '.TWO']
    for endpoint in endpoints:
        for suffix in suffixes:
            try:
                url_m = f"https://www.moneydj.com/etf/x/basic/{endpoint}?etfid={clean_ticker}{suffix}"
                res = requests.get(url_m, headers=headers, timeout=10)
                res.encoding = 'utf-8'
                if res.status_code == 200:
                    holdings = parse_generic_html_tables(res.text)
                    if len(holdings) >= 2:
                        final_results = process_holdings(clean_ticker, holdings)
                        print(f"✅ [來源: MoneyDJ ({endpoint})] 成功抓取 {clean_ticker}，共 {len(final_results)} 檔純淨資料")
                        time.sleep(1)
                        return final_results
            except Exception:
                pass

    # ----------------------------------------------------
    # [引擎 3]：CMoney 與 口袋證券 
    # ----------------------------------------------------
    cmoney_urls = [
        (f"https://www.pocket.tw/etf/tw/{clean_ticker}", "口袋證券"),
        (f"https://www.cmoney.tw/etf/tw/{clean_ticker}", "CMoney")
    ]
    for url_c, src_name in cmoney_urls:
        try:
            res = requests.get(url_c, headers=headers, timeout=10)
            res.encoding = 'utf-8'
            if res.status_code == 200:
                holdings = parse_generic_html_tables(res.text)
                if len(holdings) >= 2:
                    final_results = process_holdings(clean_ticker, holdings)
                    print(f"✅ [來源: {src_name}] 成功抓取 {clean_ticker}，共 {len(final_results)} 檔純淨資料")
                    time.sleep(1)
                    return final_results
        except Exception:
            pass

    # ----------------------------------------------------
    # [引擎 4]：Yahoo JSON 攔截
    # ----------------------------------------------------
    for suffix in ['.TW', '.TWO']:
        try:
            url_y = f"https://tw.stock.yahoo.com/quote/{clean_ticker}{suffix}/holding"
            res = requests.get(url_y, headers=headers, timeout=10)
            if res.status_code == 200:
                holdings = parse_yahoo_json(res.text)
                if len(holdings) >= 3:
                    final_results = process_holdings(clean_ticker, holdings)
                    print(f"✅ [來源: Yahoo JSON] 成功抓取 {clean_ticker}，共 {len(final_results)} 檔純淨資料")
                    time.sleep(1)
                    return final_results
        except Exception:
            pass

    # ----------------------------------------------------
    # [最後備案 Plan B]：海外替身字典
    # ----------------------------------------------------
    if clean_ticker in FEEDER_PROXY_MAP:
        proxy_ticker = FEEDER_PROXY_MAP[clean_ticker]
        print(f"⚠️ 台灣網站查無 {clean_ticker} 資料，啟動海外替身備案 ({proxy_ticker})...")
        proxy_results = get_us_etf_holdings(proxy_ticker, override_ticker=clean_ticker)
        if proxy_results:
            return proxy_results

    print(f"⚠️ {clean_ticker} 查無明細 (可能為純期貨/主動型未揭露或新股空窗期)。")
    time.sleep(1)
    return []

# ==========================================
# 6. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (四大引擎 + 精準過濾個股版)...")
    
    try:
        portfolio_sheet = client.open_by_url(PORTFOLIO_SHEET_URL)
        tw_records = portfolio_sheet.worksheet("TW_Portfolio").get_all_records()
        us_records = portfolio_sheet.worksheet("US_Portfolio").get_all_records()
    except Exception as e:
        print(f"❌ 讀取 Portfolio_streamlit 失敗: {e}")
        return

    all_holdings = []
    visited_tw = set()
    visited_us = set()

    # 1. 處理台股 (自動跳過個股)
    for row in tw_records:
        raw_ticker = str(row.get('Ticker', '')).strip().upper()
        if not raw_ticker or raw_ticker in ['NAN', 'NONE']:
            continue
        category_str = str(row.get('類別', '')).strip()
        clean_ticker = normalize_tw_ticker(raw_ticker)
        
        if clean_ticker in visited_tw:
            continue
            
        if is_tw_stock_etf(clean_ticker, category_str):
            visited_tw.add(clean_ticker)
            holdings = get_tw_etf_holdings(clean_ticker)
            if holdings:
                all_holdings.extend(holdings)

    # 2. 處理美股/英股
    for row in us_records:
        ticker = str(row.get('Ticker', '')).strip().upper()
        if not ticker or ticker in ['NAN', 'NONE'] or ticker in visited_us:
            continue
        category_str = str(row.get('類別', '')).strip()
        if '個股' in category_str:
            continue
            
        visited_us.add(ticker)
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
        data_to_write = [df_holdings.columns.values.tolist()] + df_holdings.values.tolist()
        try:
            ws.update(values=data_to_write, range_name="A1")
        except TypeError:
            ws.update("A1", data_to_write)
            
        print(f"✅ 成功將所有 ETF 持股寫入 Google Sheets ({sheet_title})！")
    except Exception as e:
        print(f"❌ 寫入 ETF_Holdings_DB 失敗: {e}")

if __name__ == "__main__":
    main()
