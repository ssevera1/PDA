@echo off
title PDAgent — Sophie is ready
cd /d "%~dp0"
call venv\Scripts\activate.bat
python main.py
pause
