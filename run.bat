@echo off
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%venv\Scripts\activate.bat"
python "%SCRIPT_DIR%main.py"
pause
