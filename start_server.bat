@echo off
REM Medical Legal PDF Processor - Server Startup Script (Windows)
REM Optimized for large file uploads (5000-10,000 pages)

echo ==========================================
echo Medical Legal PDF Processor
echo Large File Support Enabled
echo ==========================================
echo.

REM Check if .env file exists
if not exist .env (
    echo Warning: .env file not found!
    echo Create a .env file with:
    echo   OPENAI_API_KEY=your_key_here
    echo   SECRET_KEY=your_secret_key_here
    echo.
    set /p continue="Continue anyway? (y/n) "
    if /i not "%continue%"=="y" exit /b 1
)

REM Check if virtual environment exists
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat

REM Install/upgrade dependencies
echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

REM Check if gunicorn is installed
where gunicorn >nul 2>nul
if %errorlevel% neq 0 (
    echo Gunicorn not found. Installing...
    pip install gunicorn
)

REM Get port from environment or use default
if "%PORT%"=="" set PORT=8080

echo.
echo ==========================================
echo Configuration:
echo    - Port: %PORT%
echo    - Workers: Auto (CPU based)
echo    - Timeout: 600s (10 minutes)
echo    - Max file size: 2GB
echo    - Config: gunicorn_config.py
echo ==========================================
echo.
echo Starting server...
echo    Access at: http://127.0.0.1:%PORT%
echo.
echo Logs will appear below...
echo    Press Ctrl+C to stop
echo.
echo ==========================================
echo.

REM Start gunicorn with the configuration file
gunicorn -c gunicorn_config.py app:app
