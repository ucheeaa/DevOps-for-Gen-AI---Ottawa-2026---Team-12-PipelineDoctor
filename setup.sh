#!/bin/bash
# =============================================================================
# Pipeline Doctor - One-Command Setup
# =============================================================================
# Run this script from the project root:
#   chmod +x setup.sh && ./setup.sh
#
# Prerequisites:
#   - Python 3.11+ (brew install python@3.13)
#   - Node.js 18+  (brew install node)
#   - AWS CLI v2 configured (run: aws login)
#   - Bedrock model access enabled in us-east-1
# =============================================================================

set -e

echo "========================================="
echo " Pipeline Doctor - Setup"
echo "========================================="

# --- Detect Python ---
PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" --version 2>&1 | awk '{print $2}')
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -eq 3 ] && [ "$minor" -ge 11 ] && [ "$minor" -le 13 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.11-3.13 not found. Install with: brew install python@3.13"
    exit 1
fi
echo "Using Python: $PYTHON ($($PYTHON --version))"

# --- Create Python venv ---
echo ""
echo "[1/5] Creating Python virtual environment..."
$PYTHON -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q

# --- Install Python deps ---
echo "[2/5] Installing Python dependencies..."
pip install boto3 fastapi uvicorn pydantic httpx structlog PyGithub python-dotenv pyyaml "botocore[crt]" -q

# --- Install as editable package ---
echo "[3/5] Installing pipeline-doctor package..."
pip install -e . -q

# --- Setup .env if not exists ---
if [ ! -f .env ]; then
    echo "[4/5] Creating .env from template..."
    cp .env.example .env
    echo "  >> EDIT .env with your AWS/GitHub credentials before running!"
else
    echo "[4/5] .env already exists, skipping."
fi

# --- Install frontend ---
echo "[5/5] Installing frontend dependencies..."
cd frontend
npm install --silent
cd ..

echo ""
echo "========================================="
echo " Setup complete!"
echo "========================================="
echo ""
echo " BEFORE RUNNING: Make sure you have:"
echo "   1. AWS credentials active:  aws sts get-caller-identity"
echo "   2. Bedrock access enabled in us-east-1 for Claude Sonnet"
echo ""
echo " TO START (two terminals):"
echo "   Terminal 1 (backend):  source .venv/bin/activate && python3 -m uvicorn backend.app:app --port 8000 --reload"
echo "   Terminal 2 (frontend): cd frontend && npm run dev"
echo ""
echo " Then open: http://localhost:3000"
echo ""
echo " TO TEST: Click any scenario button in the Demo Panel on the dashboard."
echo "========================================="
