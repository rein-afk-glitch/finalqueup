import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv('simplified_backend/.env')

try:
    conn = mysql.connector.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'queueup_db')
    )
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM users WHERE role = 'admin' LIMIT 1")
    user = cursor.fetchone()
    if user:
        print(f"Found admin user: {user[0]}")
    else:
        print("No admin user found.")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
