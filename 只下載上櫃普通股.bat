@echo off
chcp 65001 >nul
cd /d %~dp0
python tw_stock_downloader.py --all --only-tpex --out otc_history.csv --months 4 --sleep 1 --resume
pause
