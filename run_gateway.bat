@echo off
cd /d "%~dp0"
python Gateway/gateway.py --DEBUG_LEVEL=DEBUG
pause
