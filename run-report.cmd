@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Creating project Python environment...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)

"%PYTHON%" -c "import numpy, oracledb, pandas, plotly, dotenv, sklearn" >nul 2>&1
if errorlevel 1 (
    echo Installing report dependencies...
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

if /i "%~1"=="--dry-run" (
    "%PYTHON%" -u report.py --dry-run
    if errorlevel 1 goto :error
    exit /b 0
)

echo Generating BNPL collection report from DWH...
"%PYTHON%" -u report.py --output output\report.html
if errorlevel 1 goto :error

if not exist "output\report.html" (
    echo ERROR: Report command completed but output\report.html was not created.
    exit /b 1
)

echo Opening report...
start "" "output\report.html"
exit /b 0

:error
echo.
echo Report generation failed. Review the error above.
exit /b 1