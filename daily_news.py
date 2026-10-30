"""Daily Taiwan/US large-cap stock research digest -> Google Sheets.
Market-data feeds are delayed/variable. All output is informational, not investment advice. """
from __future__ import annotations
import json
import logging
import os
import random
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import feedparser
import gspread
import numpy as np
import yfinance as yf
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError

SHEET_TAB_PREFIX = "Daily Report"
TW_TOP_N = 20
US_TOP_N = 10
HEADERS = [
    "執行日期", "市場", "排名", "代號", "公司", "收盤價",
    "日變動%", "MA20", "MA50", "MACD", "20／50日新高低",
    "技術訊號", "判斷依據", "公開研究／新聞", "來源連結", "50字摘要",
]

DEFAULT_TW_TICKERS = "2330.TW,2317.TW,2454.TW,2308.TW,2382.TW,2881.TW,2882.TW,2891.TW,2886.TW,2884.TW,2303.TW,2412.TW,3711.TW,2301.TW,6505.TW,1301.TW,1303.TW,2002.TW,3008.TW,2357.TW,2327.TW,2880.TW,2885.TW,5880.TW,3034.TW,3045.TW,3231.TW,2379.TW,4904.TW,6669.TW"
DEFAULT_US_TICKERS = "NVDA,MSFT,AAPL,AMZN,GOOGL,GOOG,META,BRK-B,AVGO,TSLA,LLY,JPM,WMT,V,MA,XOM,ORCL,COST,NFLX,PLTR,JNJ,HD,PG,ABBV,BAC,KO,CRM,UNH,CSCO"
RETRYABLE_GOOGLE_STATUS_CODES = {429, 500, 502, 503, 504}

def fmt(val: Any, decimals: int = 2) -> str:
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return ""

def high_low_status(d: dict[str, Any]) -> str:
    """完全對齊 main.py 的短線 Emoji 標籤"""
    labels = []
    if d.get("new_high_50"):
        labels.append("🚀創50日收高")
    elif d.get("new_high_20"):
        labels.append("🔥創20日收高")
        
    if d.get("new_low_50"):
        labels.append("☠️破50日收低")
    elif d.get("new_low_20"):
        labels.append("🩸破20日收低")
        
    if d.get("narrow_20d"):
        labels.append("💤20日窄幅盤整")
        
    return "；".join(labels) or "—"

def research_news(company: str, symbol: str) -> tuple[str, str]:
    """擴大雙語關鍵字，移除特定報系限制"""
    query = f'"{company}" {symbol} (analyst OR research OR earnings OR 分析 OR 研究 OR 財報 OR 營收 OR 評級 OR 展望)'
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    feed = feedparser.parse(url)
    entries = feed.entries[:2]
    if not entries:
        return "近期無重大財經報導", ""
    titles = "；".join(re.sub(r"\s+", " ", e.get("title", "")) for e in entries)
    return titles[:180], entries[0].get("link", "")

def fallback_summary(company: str, d: dict[str, Any], technical: str, news: str) -> str:
    trend = "均線偏多" if technical == "偏多" else "走勢偏弱" if technical == "偏空／過熱" else "訊號分歧"
    text = f"{trend}，RSI {fmt(d.get('rsi', 50), 0)}。" + ("近期有公開資訊可覆核。" if news else "公開研究資訊有限。")
    return text[:50]

def ai_summary(company: str, d: dict[str, Any], technical: str, news: str) -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return fallback_summary(company, d, technical, news)
    try:
        from openai import OpenAI
        prompt = (f"以繁體中文寫不超過50個字的中性投資訊報摘要，不得下交易指令，且不得提及公司名稱或股票代號。"
                  f"公司:{company}; 技術訊號:{technical}; RSI:{fmt(d.get('rsi', 50), 0)}; "
                  f"MA20:{fmt(d.get('ma20', 0))}; MA50:{fmt(d.get('ma50', 0))}; 公開資訊:{news[:180]}")
        response = OpenAI(api_key=key).responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            input=prompt,
            max_output_tokens=100
        )
        return re.sub(r"\s+", " ", response.output_text).strip()[:50] or fallback_summary(company, d, technical, news)
    except Exception as exc:
        logging.warning("AI summary failed for %s: %s", company, exc)
        return fallback_summary(company, d, technical, news)

def indicators(symbol: str) -> dict[str, Any]:
    """獲取技術指標的基本封裝"""
    df = yf.download(symbol, period="6mo", progress=False)
    if df.empty or len(df) < 50:
        raise ValueError("Insufficient data")
        
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    close = df['Close'].dropna()
    high = df['High'].dropna()
    low = df['Low'].dropna()
    
    last_p = float(close.iloc[-1])
    prev_p = float(close.iloc[-2]) if len(close) > 1 else last_p
    
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1])
    
    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_val = float(macd.iloc[-1])
    
    # RSI
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    rsi_val = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0
    
    h_20 = float(close.tail(20).max())
    l_20 = float(close.tail(20).min())
    h_50 = float(close.tail(50).max())
    l_50 = float(close.tail(50).min())
    
    return {
        "close": last_p,
        "change": ((last_p - prev_p) / prev_p) * 100,
        "ma20": ma20,
        "ma50": ma50,
        "macd": macd_val,
        "rsi": rsi_val,
        "new_high_50": last_p >= h_50,
        "new_high_20": last_p >= h_20 and last_p < h_50,
        "new_low_50": last_p <= l_50,
        "new_low_20": last_p <= l_20 and last_p > l_50,
        "narrow_20d": ((high.tail(20).max() - low.tail(20).min()) / low.tail(20).min()) <= 0.07
    }

def signal(d: dict[str, Any]) -> tuple[str, str]:
    if d['close'] > d['ma20'] and d['ma20'] > d['ma50']:
        return "偏多", "月季線多頭排列"
    elif d['close'] < d['ma20'] and d['ma20'] < d['ma50']:
        return "偏空／過熱", "月季線空頭排列"
    else:
        return "震盪整理", "均線交纏或破線"

def make_rows(market: str, top: list[dict[str, Any]]) -> list[list[str]]:
    report_date = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
    rows: list[list[str]] = []
    
    for rank, item in enumerate(top, start=1):
        symbol = item["symbol"]
        company = symbol
        try:
            ticker = yf.Ticker(symbol)
            try:
                metadata = ticker.get_info()
                company = metadata.get("shortName") or symbol
            except Exception as exc:
                logging.warning("Name lookup failed for %s: %s", symbol, exc)
                
            d = indicators(symbol)
            technical, basis = signal(d)
            news, link = research_news(company, symbol)
            summary = ai_summary(company, d, technical, news)
            
            rows.append([
                report_date, market, rank, symbol, company,
                fmt(d["close"]), fmt(d["change"]), fmt(d["ma20"]),
                fmt(d["ma50"]), fmt(d["macd"]), high_low_status(d),
                technical, basis, news, link, summary
            ])
        except Exception as exc:
            logging.exception("Unable to build %s", symbol)
            rows.append([
                report_date, market, rank, symbol, company,
                "", "", "", "", "", "", "資料取得失敗",
                "市場資料暫時無法取得", "", "", "市場資料暫時無法取得。"
            ])
    return rows

def main():
    print(f"開始執行每日快報掃描... {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    # 這裡請補上您寫入 Google Sheets 的憑證與 gspread 邏輯
    # rows_tw = make_rows("台股", [{"symbol": s} for s in DEFAULT_TW_TICKERS.split(",")])
    # rows_us = make_rows("美股", [{"symbol": s} for s in DEFAULT_US_TICKERS.split(",")])
    
if __name__ == "__main__":
    main()
