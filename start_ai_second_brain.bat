@echo off
title AI Second Brain Server
cd /d "D:\Ai brain"

:restart
echo Starting AI Second Brain...
python -u app.py
echo Server stopped. Restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto restart
