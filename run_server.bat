@echo off
cd /d "%~dp0"
python Server/server_module.py --DEBUG_LEVEL=DEBUG
pause
