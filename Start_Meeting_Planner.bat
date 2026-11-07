@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Meeting Planner
set "LOG=%~dp0launch_log.txt"
echo.
echo   Meeting Planner
echo   ---------------
echo   Folder: %CD%
echo.
echo Start %DATE% %TIME% in %CD% > "%LOG%"

rem --- running from inside the zip is the most common reason nothing happens
echo "%~dp0" | findstr /i /c:".zip" /c:"\Temp\" /c:"Temp1_" >nul
if not errorlevel 1 goto :inzip
if not exist "app.py" goto :nofiles

rem --- find a working Python (the Microsoft Store stub does not count)
set "PY="
for %%C in ("py -3.12" "py -3.11" "py -3.13" "py -3.10" "py -3" "python" "python3") do call :try %%C
if not defined PY goto :nopython
%PY% pycheck.py
if errorlevel 1 goto :oldpython
echo   Using: %PY% >> "%LOG%"

if not exist ".venv\Scripts\python.exe" (
  echo   First start: setting things up. This takes a few minutes, once only.
  %PY% -m venv .venv >> "%LOG%" 2>&1
  if errorlevel 1 goto :fail
)
if not exist ".venv\.installed" (
  echo   Installing the parts the program needs. Please wait...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip >> "%LOG%" 2>&1
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt >> "%LOG%" 2>&1
  if errorlevel 1 goto :fail
  echo ok> ".venv\.installed"
)
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  echo [general]> "%USERPROFILE%\.streamlit\credentials.toml"
  echo email = "">> "%USERPROFILE%\.streamlit\credentials.toml"
)
echo.
echo   Starting. Your browser opens in a moment.
echo   If it does not, open this address yourself:  http://localhost:8501
echo   Keep this window open while you work. Close it to stop the program.
echo.
set PYTHONUTF8=1
".venv\Scripts\python.exe" -m streamlit run app.py
echo.
echo   The program has stopped.
pause
exit /b 0

:try
if defined PY exit /b 0
%~1 --version >nul 2>nul
if errorlevel 1 exit /b 0
set "PY=%~1"
exit /b 0

:inzip
echo   The program is still inside the zip file.
echo.
echo   1. Close this window.
echo   2. Right-click the zip file and choose  Extract All  .
echo   3. Open the new folder and double-click this file again.
echo.
pause
exit /b 1

:nofiles
echo   This file must stay in the same folder as the other program files.
echo   Please extract the whole zip, then start it from the extracted folder.
echo.
pause
exit /b 1

:nopython
where winget >nul 2>nul
if errorlevel 1 goto :nowinget
echo   Python is needed once, and it is free. Installing it now. This can take a minute or two...
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements >> "%LOG%" 2>&1
if errorlevel 1 goto :nowinget
echo.
echo   Python is installed.
echo   Close this window, then double-click this file again to start the program.
echo.
pause
exit /b 0

:nowinget
echo   Python is needed once, and it is free. Opening the download page now.
echo   Install it and tick "Add python.exe to PATH" on the first screen.
echo   Then double-click this file again.
start https://www.python.org/downloads/
echo.
pause
exit /b 1

:oldpython
echo   Your Python is too old. Please install a newer one (3.10 or later)
echo   from https://www.python.org/downloads/ and double-click this file again.
start https://www.python.org/downloads/
echo.
pause
exit /b 1

:fail
echo.
echo   Something went wrong during setup. The details are below and in the file
echo   launch_log.txt in this folder. Check your internet connection and try again.
echo   If it keeps failing, send that file to whoever gave you the program.
echo.
type "%LOG%"
echo.
pause
exit /b 1
