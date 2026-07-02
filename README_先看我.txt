使用方式：
1. 建議先雙擊 download_common_stocks.bat（英文檔名，最不會亂碼）。
2. 若你的 Windows 解壓縮工具可正常顯示中文，也可以雙擊「下載普通股全市場.bat」。
3. 下載完成會產生 history.csv。
4. 開啟「台股六脈神劍選股系統.html」，到「上傳離線下載的 CSV 資料」選擇 history.csv。

若看不到中文 bat，請用英文版：
- download_common_stocks.bat = 下載普通股全市場
- download_otc_common_stocks.bat = 只下載上櫃普通股
- download_common_plus_etf.bat = 普通股加 ETF


新版提醒：tw_stock_downloader.py 會同時輸出 history.csv 與 stock_meta.csv。history.csv 已包含 capital 股本欄位，HTML 匯入後可離線計算週轉率。
