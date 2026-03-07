#!/bin/zsh

# QUEUP - macOS start script
# -----------------------------
# This script starts:
# - Backend (Flask) on http://localhost:5001
# - Frontend (static) on http://localhost:8080
#
# Usage (from the project root):
#   chmod +x start_queueup_mac.sh
#   ./start_queueup_mac.sh
#
# Requirements:
# - Python 3.10+ installed and available as `python3`
# - MySQL running via XAMPP (database: queup_db)

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/simplified_backend"
FRONTEND_DIR="$ROOT_DIR/simplified_frontend"

echo "== QUEUP macOS starter =="
echo "Project root: $ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found in PATH. Please install Python 3 and try again."
  exit 1
fi

cd "$BACKEND_DIR"

if [ ! -d "venv" ]; then
  echo "Creating Python virtual environment in simplified_backend/venv ..."
  python3 -m venv venv
fi

echo "Activating virtual environment ..."
source venv/bin/activate

echo "Installing backend dependencies (pip install -r requirements.txt) ..."
pip install -r requirements.txt

echo "Starting backend (Flask) on http://localhost:5001 ..."
python app.py &
BACKEND_PID=$!

cd "$FRONTEND_DIR"
echo "Starting frontend (static) on http://localhost:8080 ..."
python3 -m http.server 8080 &
FRONTEND_PID=$!

echo ""
echo "Backend PID:  $BACKEND_PID"
echo "Frontend PID: $FRONTEND_PID"
echo ""
echo "Open http://localhost:8080 in your browser to use QUEUP."
echo ""
echo "To stop both servers, press Ctrl+C in this terminal."

trap 'echo "Stopping servers..."; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true; exit 0' INT

wait

