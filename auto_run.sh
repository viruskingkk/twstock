#!/bin/bash

# 切換到專案根目錄（確保路徑正確）
cd /home/albert/twstock

# 1. 執行 Python 爬蟲
echo "開始執行爬蟲..."
python3 tw_stock_downloader.py --all

# 2. 檢查 history.csv 是否成功產生
if [ -f "history.csv" ]; then
    # 取得當前月份與日期（例如 7 月 2 日會變成 0702）
    DATE_SUFFIX=$(date +"%m%d")
    NEW_FILENAME="history${DATE_SUFFIX}.csv"

    echo "重新命名並搬移檔案至 history 根目錄..."
    mv history.csv history/$NEW_FILENAME
else
    echo "錯誤：找不到 history.csv，跳過搬移步驟。"
fi

# 3. Git 提交並推送到遠端
echo "開始進行 Git push..."
git add .
git commit -m "Auto update stock data: $(date +'%Y-%m-%d %H:%M:%S')"
git push origin main # 如果你的分支不是 main，請改成 master 或相應的分支名稱

echo "自動化流程執行完畢！"
