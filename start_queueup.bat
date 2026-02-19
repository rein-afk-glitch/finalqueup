@echo off
set PORT=5001
echo Starting Backend...
start cmd /k "cd simplified_backend && venv\Scripts\activate && python app.py"
echo Starting Frontend...
start cmd /k "cd simplified_frontend && python -m http.server 8080"
echo.
echo ========================================
echo System starting!
echo Backend: http://localhost:5001
echo Frontend: http://localhost:8080
echo ========================================
echo.
pause
