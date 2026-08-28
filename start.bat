@echo off
title iCloud Check LINE Bot Server
echo ==========================================
echo   Starting iCloud Check LINE Bot Server...
echo ==========================================
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
pause
