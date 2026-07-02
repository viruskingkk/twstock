@echo off
chcp 65001 >nul
cd /d %~dp0
python tw_stock_downloader.py --all --out history.csv --meta-out stock_meta.csv --months 4 --sleep 0.8 --resume
pause
