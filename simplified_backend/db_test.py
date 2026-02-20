import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

db_config = {
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'queueup_db')
}

print(f"Testing connection with config: {db_config}")

try:
    conn = mysql.connector.connect(**db_config)
    print("✅ Standalone connection successful")
    conn.close()
except mysql.connector.Error as err:
    print(f"❌ Standalone connection error: {err}")

# Try with 127.0.0.1
db_config['host'] = '127.0.0.1'
print(f"Testing connection with config: {db_config}")
try:
    conn = mysql.connector.connect(**db_config)
    print("✅ Standalone connection (127.0.0.1) successful")
    conn.close()
except mysql.connector.Error as err:
    print(f"❌ Standalone connection (127.0.0.1) error: {err}")
