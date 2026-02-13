QUEUEUP - RUN LOCALLY ON WINDOWS (FOR COLLEAGUES)
=================================================

This guide is for running the QueueUp system on a Windows PC.

What you will run:
- Backend (Flask/Python) on: http://localhost:5001
- Frontend (static site) on: http://localhost:8080
- Database (MySQL) via XAMPP


1) PREREQUISITES (INSTALL ON WINDOWS)
------------------------------------
A) Install XAMPP (Windows)
   - Download from: https://www.apachefriends.org/
   - Install and start XAMPP Control Panel.
   - Start "MySQL" (must be running).

B) Install Python 3.10+ (recommended)
   - Download from python.org OR Microsoft Store.
   - IMPORTANT: during install, check "Add Python to PATH".
   - Verify in Command Prompt:
       python --version


2) ONE-TIME DATABASE SETUP (CREATE DB)
--------------------------------------
Option A (phpMyAdmin):
1. Open: http://localhost/phpmyadmin
2. Click "New" on the left sidebar
3. Database name: queueup_db
4. Collation: utf8mb4_general_ci
5. Click "Create"

Option B (Command line):
1. Open Command Prompt or XAMPP Shell.
2. Run:
   mysql -u root -e "CREATE DATABASE IF NOT EXISTS queueup_db;"

NOTE: On many XAMPP installs, MySQL root password is empty by default.


3) ONE-TIME BACKEND SETUP (PYTHON DEPENDENCIES)
-----------------------------------------------
Open Command Prompt (or PowerShell) and run:

   cd C:\queueup_windows\simplified_backend

Create a virtual environment:
   python -m venv venv

Activate it (Command Prompt):
   venv\Scripts\activate.bat

OR (PowerShell):
   .\venv\Scripts\Activate.ps1

If PowerShell blocks activation (Execution Policy), run:
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
Then try activation again.

Install dependencies:
   pip install -r requirements.txt

This will install:
   Flask, flask-cors, mysql-connector-python, python-dotenv, bcrypt,
   google-generativeai, Pillow


4) CREATE BACKEND CONFIG (.env)
-------------------------------
Create this file in: simplified_backend\.env

You can copy the template file:
   simplified_backend\.env.template

Or create manually and paste this:

DB_HOST=localhost
DB_USER=root
DB_PASSWORD=
DB_NAME=queueup_db

GOOGLE_API_KEY=

SECRET_KEY=my-secret-key-change-this

If you have a Google Gemini API key, paste it into GOOGLE_API_KEY.
You can get one from: https://aistudio.google.com/app/apikey


5) RUN THE SYSTEM (EASY WAY - RECOMMENDED)
------------------------------------------
Simply double-click:
   start_queueup.bat

This will start both servers automatically.

Then open in your browser:
   http://localhost:8080

To stop the system, double-click:
   stop_queueup.bat

OR close the two command windows that opened.


6) RUN THE SYSTEM (MANUAL WAY - 2 TERMINALS)
--------------------------------------------
Terminal A (Backend):
1. Open Command Prompt
2. Run:
   cd C:\queueup_windows\simplified_backend
   venv\Scripts\activate.bat
   python app.py

You should see it running on: http://127.0.0.1:5001

Terminal B (Frontend):
1. Open a NEW Command Prompt window
2. Run:
   cd C:\queueup_windows\simplified_frontend
   python -m http.server 8080

Now open in a browser:
   http://localhost:8080


7) TROUBLESHOOTING
------------------
A) "Connection error" on login page
   - Make sure backend is running (check the command window).
   - Test backend in browser:
       http://localhost:5001/api/health
     Should return: {"status":"healthy"}

B) Port already in use (5001 or 8080)
   - Run stop_queueup.bat first to clean up old processes.
   - Or manually close any Python processes using Task Manager.

C) Database connection error
   - Ensure XAMPP MySQL is started (check XAMPP Control Panel).
   - Ensure database exists: queueup_db (see step 2).
   - Ensure .env file is correct (DB_HOST/USER/PASSWORD/DB_NAME).

D) Python venv activation fails (PowerShell)
   - Run: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   - Then try activation again.

E) "python is not recognized"
   - Python is not in PATH. Reinstall Python and check "Add Python to PATH".
   - Or use full path: C:\Python3X\python.exe

F) Virtual environment not found
   - Make sure you completed step 3 (Backend Setup).
   - The venv folder should exist in: simplified_backend\venv\


8) DEFAULT LOGIN CREDENTIALS
----------------------------
After first run, register an account on the login page.

For admin access, you need to manually set admin status in the database:
1. Open phpMyAdmin: http://localhost/phpmyadmin
2. Go to database: queueup_db
3. Go to table: users
4. Find your user, click "Edit"
5. Set is_admin = 1
6. Click "Go"


Done! Enjoy using QueueUp.
