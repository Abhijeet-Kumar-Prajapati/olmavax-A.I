@echo off
title Open Charvis
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if "%PY%"=="" (
  where python >nul 2>nul && set "PY=python"
)
if "%PY%"=="" (
  echo.
  echo   Python was not found on this machine.
  echo   Install it from https://python.org  (tick "Add Python to PATH")
  echo.
  pause
  exit /b 1
)

if "%~1"=="" goto menu

%PY% charvis.py %*
goto end

:menu
cls
echo.
echo    ==========================================
echo      O P E N   C H A R V I S
echo    ==========================================
echo.
echo    1  Text chat            5  Run the test suite
echo    2  Voice (wake word)    6  Memory dashboard
echo    3  3D interface         7  Security report
echo    4  Doctor / diagnose    8  Skills
echo.
echo    0  Exit
echo.
set /p "choice=  Choose: "

if "%choice%"=="1" %PY% charvis.py chat
if "%choice%"=="2" %PY% charvis.py voice --allow-typed
if "%choice%"=="3" %PY% charvis.py ui --open
if "%choice%"=="4" %PY% charvis.py doctor
if "%choice%"=="5" %PY% charvis.py test
if "%choice%"=="6" %PY% charvis.py memory
if "%choice%"=="7" %PY% charvis.py security
if "%choice%"=="8" %PY% charvis.py skills

echo.
pause
goto menu

:end