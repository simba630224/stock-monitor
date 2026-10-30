"""Daily Taiwan/US large-cap stock research digest -> Google Sheets."""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

import feedparser
import gspread
import numpy as np
import pandas as pd
import yfinance as yf
from google.oauth2.service_account import Credentials

tz_tw = timezone(timedelta(hours=8))

SHEET_TAB_PREFIX = "Daily Report"
HEADERS = [
    "執行日期", "市場", "排名", "代號", "公司", "收盤價",
    "日變動%", "MA20", "MA50", "MACD", "20／50日新高低",
    "技術訊號", "判斷依據", "公開研究／新聞", "來源連結", "50字摘要",
]

DEFAULT_TW = "2330.TW,2317.TW,2454.TW,2308.TW,2382.TW,2881.TW,2882.TW,2891.TW,2303.TW,3711.TW"
DEFAULT_US = "NVDA,MSFT,AAPL,AMZN,GOOGL,META,TSLA,LLY,AVGO,JPM"

def fmt(val: Any, decimals: int = 2) -> str:
    try: return f"{float(val):.{decimals}f}"
    except: return ""

def high_low_status(d: dict[str, Any]) -> str:
    labels = []
    if d.get("new_high_50"): labels.append("🚀創50日收高")
    elif d.get("new_high_20"): labels.append("🔥創20日收高")
    if d.get("new_low_50"): labels.append("☠️破50日收低")
    elif d.get("new_low_20"): labels.append("🩸破20日收低")
    if d.get("narrow_20d"): labels.append("💤20日窄幅盤整")
    return "；".join(labels) or "—"

def research_news(company: str, symbol: str) -> tuple[str, str]:
    query = f'"{company}" {symbol} (analyst OR research OR earnings OR 分析 OR 研究 OR 財報 OR 營收 OR 展望)'
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    entries = feedparser.parse(url).entries[:2]
    if not entries: return "近期無重大財經報導", ""
    return "；".join(re.sub(r"\s+", " ", e.get("title", "")) for e in entries)[:180], entries[0].get("link", "")

def fallback_summary(company: str, d: dict, technical: str, news: str) -> str:
    trend = "均線偏多" if technical == "偏多" else "走勢偏弱" if technical == "偏空／過熱" else "訊號分歧"
    return (f"{trend}，RSI {fmt(d.get('rsi', 50), 0)}。" + ("近期有公開資訊。" if news else "資訊有限。"))[:50]

def ai_summary(company: str, d: dict, technical: str, news: str) -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key: return fallback_summary(company, d, technical, news)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        prompt = (f"以繁體中文寫不超過50個字的中性投資訊報摘要，不得下交易指令，不得提及公司名稱或代號。"
                  f"公司:{company}; 技術訊號:{technical}; RSI:{fmt(d.get('rsi',50),0)}; 公開資訊:{news[:180]}")
        res = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100
        )
        return re.sub(r"\s+", " ", res.choices[0].message.content).strip()[:50]
    except Exception as e:
        print(f"AI摘要失敗 {company}: {e}")
        return fallback_summary(company, d, technical, news)

def indicators(symbol: str) -> dict:
    # 🚀 根據歷史經驗，改用 history() 避免 yf.download 被 Yahoo 阻擋
    tk = yf.Ticker(symbol)
    df = tk.history(period="6mo")
    if df.empty or len(df) < 50: 
        raise ValueError(f"取得資料不足 (長度: {len(df)})")
    
    c, h, l = df['Close'].dropna(), df['High'].dropna(), df['Low'].dropna()
    
    last_p = float(c.iloc[-1])
    ma20 = float(c.rolling(20).mean().iloc[-1])
    ma50 = float(c.rolling(50).mean().iloc[-1])
    
    macd = c.ewm(span=12).mean() - c.ewm(span=26).mean()
    delta = c.diff()
    
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - (100 / (1 + rs))).fillna(50)
    
    return {
        "close": last_p, "change": ((last_p - float(c.iloc[-2])) / float(c.iloc[-2])) * 100 if len(c)>1 else 0,
        "ma20": ma20, "ma50": ma50, "macd": float(macd.iloc[-1]), "rsi": float(rsi.iloc[-1]),
        "new_high_50": last_p >= float(c.tail(50).max()), "new_high_20": last_p >= float(c.tail(20).max()) and last_p < float(c.tail(50).max()),
        "new_low_50": last_p <= float(c.tail(50).min()), "new_low_20": last_p <= float(c.tail(20).min()) and last_p > float(c.tail(50).min()),
        "narrow_20d": ((h.tail(20).max() - l.tail(20).min()) / l.tail(20).min()) <= 0.07
    }

def make_rows(market: str, tickers: str) -> list:
    report_date = datetime.now(tz_tw).strftime("%Y-%m-%d")
    rows = []
    for rank, sym in enumerate(tickers.split(","), 1):
        try:
            d = indicators(sym)
            tech = "偏多" if d['close']>d['ma20']>d['ma50'] else "偏空／過熱" if d['close']<d['ma20']<d['ma50'] else "震盪整理"
            news, link = research_news(sym, sym)
            rows.append([report_date, market, rank, sym, sym, fmt(d["close"]), fmt(d["change"]), fmt(d["ma20"]),
                         fmt(d["ma50"]), fmt(d["macd"]), high_low_status(d), tech, "", news, link, ai_summary(sym, d, tech, news)])
            time.sleep(0.5)
        except Exception as e:
            print(f"❌ 處理 {sym} 失敗: {e}")
    return rows

def write_to_sheets(rows: list):
    creds = os.getenv('GCP_CREDENTIALS')
    if not creds: return print("未設定 GCP 憑證")
    try:
        creds_dict = json.loads(creds)
        # 🕵️ 讓機器人自己報上名來！
        print(f"🕵️ 正在嘗試寫入的機器人帳號是：{creds_dict.get('client_email')}")
        
        # 💡 擴展權限範圍：包含 Drive 權限，避免建立新分頁被擋
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        gc = gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes))
        sh = gc.open_by_url("https://docs.google.com/spreadsheets/d/1StOQTEpoTNSLU140CnOeUO94m0dZ5imX4oH0wlqAQZw/edit")
        sheet_name = f"{SHEET_TAB_PREFIX} {datetime.now(tz_tw).strftime('%Y-%m')}"
        
        try: ws = sh.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=sheet_name, rows="1000", cols="20")
            ws.append_row(HEADERS)
            
        if rows:
            ws.append_rows(rows, value_input_option='USER_ENTERED')
            print(f"✅ 成功寫入 {len(rows)} 筆至 {sheet_name}")
        else:
            print("⚠️ 警告：沒有產生任何資料列，跳過寫入。")
    except Exception as e: print(f"❌ 寫入 Google Sheets 失敗: {e}")
