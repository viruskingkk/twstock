@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo 啟動本機網頁伺服器：http://127.0.0.1:8765/
echo 請不要關閉這個視窗。
echo.
start "" "http://127.0.0.1:8765/台股六脈神劍選股系統.html"
python -m http.server 8765 --bind 127.0.0.1
pause
