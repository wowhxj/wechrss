@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 scripts\bootstrap.py %*
goto finished

:try_python
where python >nul 2>nul
if errorlevel 1 goto no_python
python scripts\bootstrap.py %*
goto finished

:no_python
echo.
echo 未检测到 Python 3.10 或更高版本。
echo 请先从 https://www.python.org/downloads/ 安装 Python，
echo 安装时勾选 "Add Python to PATH"，然后重新双击此文件。
echo.
pause
exit /b 1

:finished
set "WERSS_EXIT=%errorlevel%"
if not "%WERSS_EXIT%"=="0" pause
exit /b %WERSS_EXIT%
