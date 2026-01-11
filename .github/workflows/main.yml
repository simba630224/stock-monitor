name: 每日股票監控

on:
  schedule:
    # 設定每天 UTC 09:00 執行 (即台灣時間下午 17:00)
    - cron: '0 9 * * *'
  workflow_dispatch: # 允許手動測試

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - name: 下載程式碼
        uses: actions/checkout@v3

      - name: 設定 Python 環境
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'

      - name: 安裝必要套件
        run: |
          pip install yfinance pandas requests pytz

      - name: 執行監控程式
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          python daily_stock.py
