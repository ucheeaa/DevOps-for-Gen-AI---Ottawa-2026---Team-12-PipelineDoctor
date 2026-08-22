@echo off
REM =============================================================================
REM Pipeline Doctor - Windows Setup
REM =============================================================================
REM Run this from the project root:
REM   setup.bat
REM
REM Prerequisites:
REM   - Python 3.11+ (python.org or Microsoft Store)
REM   - Node.js 18+ (nodejs.org)
REM   - AWS CLI v2 (aws.amazon.com/cli)
REM   - Run: aws configure (with shared team credentials)
REM =============================================================================

echo =========================================
echo  Pipeline Doctor - Windows Setup
echo =========================================

REM --- Check Python ---
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install from python.org
    exit /b 1
)
echo Found Python:
python --version

REM --- Create venv ---
echo.
echo [1/5] Creating Python virtual environment...
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip -q

REM --- Install deps ---
echo [2/5] Installing Python dependencies...
pip install -r requirements.txt -q

REM --- Install as package ---
echo [3/5] Installing pipeline-doctor package...
pip install -e . -q

REM --- Setup .env ---
echo [4/5] Checking .env...
if not exist .env (
    copy .env.example .env
    echo   Created .env from template - EDIT IT with your AWS credentials!
) else (
    echo   .env already exists, skipping.
)

REM --- Frontend ---
echo [5/5] Installing frontend dependencies...
cd frontend
call npm install --silent
cd ..

echo.
echo =========================================
echo  Setup complete!
echo =========================================
echo.
echo  BEFORE RUNNING: Make sure you have:
echo    1. AWS credentials: aws configure
echo    2. Bedrock access enabled in us-east-1
echo.
echo  TO START (two terminals):
echo    Terminal 1: .venv\Scripts\activate ^&^& python -m uvicorn backend.app:app --port 8000 --reload
echo    Terminal 2: cd frontend ^&^& npm run dev
echo.
echo  Then open: http://localhost:3000
echo =========================================
