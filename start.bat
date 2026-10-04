@echo off
setlocal
title DV365 - Lossless PDF Compressor
cd /d "%~dp0"
if errorlevel 1 goto failed
set PYTHONUTF8=1
where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if errorlevel 1 goto try_python
py -3 "%~dp0bootstrap.py" %*
if errorlevel 1 goto failed
exit /b 0

:try_python
where python >nul 2>nul
if errorlevel 1 goto missing_python
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if errorlevel 1 goto missing_python
python "%~dp0bootstrap.py" %*
if errorlevel 1 goto failed
exit /b 0

:missing_python
echo Python 3.10 or newer is required.
echo Install Python from https://www.python.org/downloads/
echo Enable "Add Python to PATH" during installation.
pause
exit /b 1

:failed
echo.
echo Startup failed. See the message above, then try again.
pause
exit /b 1
