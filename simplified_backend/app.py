from flask import Flask, request, jsonify, session
import re
from flask_cors import CORS
import mysql.connector
from mysql.connector import pooling
import os
from dotenv import load_dotenv
import bcrypt
import uuid
from datetime import datetime, timedelta, timezone

# Philippine Standard Time (UTC+8)
PHT = timezone(timedelta(hours=8))

def now_pht():
    """Return current datetime in Philippine Standard Time."""
    return datetime.now(PHT)
import json
from werkzeug.utils import secure_filename
from functools import wraps
import google.generativeai as genai
import base64
from io import BytesIO
from PIL import Image
from flask import send_from_directory
import requests
from pywebpush import webpush, WebPushException
# Load environment variables
load_dotenv()


app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Session persistence configuration
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Only set Secure=True in production HTTPS (not localhost)
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'

# Static admin credentials (first admin)
STATIC_ADMIN_EMAIL = 'admin'
STATIC_ADMIN_PASSWORD = 'admin'
STATIC_ADMIN_NAME = 'admin'

SERVICE_TYPES = [
    'submission_of_application_forms',
    'application_assessment_of_school_records',
    'releasing_of_school_records',
    'inquiry_follow_up',
    'faculty_tagging_room_assignments',
    'payment',
    'balance_inquiry',
    'claims'
]
ADMIN_SERVICE_TYPES = SERVICE_TYPES
SERVICE_CODES = {
    'submission_of_application_forms': 'AF',
    'application_assessment_of_school_records': 'AS',
    'releasing_of_school_records': 'RS',
    'inquiry_follow_up': 'IF',
    'faculty_tagging_room_assignments': 'FR',
    'payment': 'PY',
    'balance_inquiry': 'BL',
    'claims': 'CL'
}
ADMIN_SERVICE_ENUM = ", ".join([f"'{service}'" for service in ADMIN_SERVICE_TYPES])

# CORS configuration
# NOTE: Because we use cookie-based sessions (`credentials: 'include'` on the frontend),
# we should NOT use wildcard '*' with credentials. Instead, allow specific origins.
# CORS_ORIGINS env var: comma-separated list for production (e.g. https://yourapp.railway.app)
_DEFAULT_ORIGINS = [
    r"http://localhost:8080",
    r"http://127\.0\.0\.1:8080",
    r"http://localhost:5000",
    r"http://127\.0\.0\.1:5000",
    r"http://localhost:5001",
    r"http://127\.0\.0\.1:5001",
    r"https?://[a-zA-Z0-9.-]+\.railway\.app",
    r"https?://[a-zA-Z0-9.-]+\.up\.railway\.app",
    r"http://192\.168\.\d+\.\d+(:\d+)?",
    r"http://10\.\d+\.\d+\.\d+(:\d+)?",
    r"http://172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+(:\d+)?",
]
_cors_env = os.getenv('CORS_ORIGINS', '').strip()
_ALLOWED_ORIGINS = [o.strip() for o in _cors_env.split(',') if o.strip()] if _cors_env else _DEFAULT_ORIGINS

CORS(
    app,
    supports_credentials=True,
    origins=_ALLOWED_ORIGINS,
    resources={r"/api/*": {"origins": _ALLOWED_ORIGINS}},
)

# Configure Google Generative AI
if os.getenv('GOOGLE_API_KEY'):
    genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))

# Database connection pool
db_config = {
    'user': os.getenv('DB_USER') or os.getenv('MYSQLUSER', 'root'),
    'password': os.getenv('DB_PASSWORD') or os.getenv('MYSQLPASSWORD', ''),
    'host': os.getenv('DB_HOST') or os.getenv('MYSQLHOST', 'localhost'),
    'port': int(os.getenv('DB_PORT') or os.getenv('MYSQLPORT', 3306)),
    'database': os.getenv('DB_NAME') or os.getenv('MYSQLDATABASE', 'queup_db'),
    'pool_name': 'queup_pool',
    'pool_size': 32
}

try:
    db_pool = pooling.MySQLConnectionPool(**db_config)
    # Test connection
    test_conn = db_pool.get_connection()
    test_conn.close()
    print("✅ Database connection successful")
except mysql.connector.Error as err:
    print(f"❌ Database connection error: {err}")
    print(f"   Please check:")
    print(f"   1. MySQL is running in XAMPP")
    print(f"   2. Database '{db_config['database']}' exists")
    print(f"   3. Credentials in .env file are correct")
    db_pool = None
except Exception as e:
    print(f"❌ Error initializing database pool: {e}")
    db_pool = None

def get_db_connection():
    """Get database connection from pool"""
    if db_pool:
        conn = db_pool.get_connection()
        cursor = conn.cursor()
        cursor.execute("SET time_zone = '+08:00'")
        cursor.close()
        return conn
    return None

def init_db():
    """Initialize database tables"""
    conn = get_db_connection()
    if not conn:
        return False
    
    cursor = conn.cursor()
    
    try:
        # Users table
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(36) PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                name VARCHAR(255) NOT NULL,
                role ENUM('admin', 'student') NOT NULL,
                admin_type ENUM('static', 'appointed') NULL,
                admin_service ENUM({ADMIN_SERVICE_ENUM}) NULL,
                student_id VARCHAR(50),
                course VARCHAR(100),
                year VARCHAR(50),
                plaintext_password VARCHAR(255) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Ensure new admin columns exist for existing databases
        cursor.execute("SHOW COLUMNS FROM users LIKE 'admin_type'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN admin_type ENUM('static', 'appointed') NULL")
        cursor.execute("SHOW COLUMNS FROM users LIKE 'admin_service'")
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE users ADD COLUMN admin_service ENUM({ADMIN_SERVICE_ENUM}) NULL")
        else:
            cursor.execute(f"ALTER TABLE users MODIFY COLUMN admin_service ENUM({ADMIN_SERVICE_ENUM}) NULL")
        
        cursor.execute("SHOW COLUMNS FROM users LIKE 'plaintext_password'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN plaintext_password VARCHAR(255) NULL")
        
        # Queue entries table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS queue_entries (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                user_name VARCHAR(255) NOT NULL,
                user_email VARCHAR(255) NOT NULL,
                service_type VARCHAR(50) NOT NULL,
                queue_number VARCHAR(20) NOT NULL,
                priority VARCHAR(20) DEFAULT 'regular',
                status VARCHAR(20) DEFAULT 'waiting',
                estimated_wait_time INT,
                notified_five_away TINYINT(1) DEFAULT 0,
                notified_called TINYINT(1) DEFAULT 0,
                called_at TIMESTAMP NULL,
                completed_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                INDEX idx_status (status),
                INDEX idx_service_type (service_type),
                INDEX idx_user_id (user_id)
            )
        """)
        cursor.execute("SHOW COLUMNS FROM queue_entries LIKE 'notified_five_away'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE queue_entries ADD COLUMN notified_five_away TINYINT(1) DEFAULT 0")
        cursor.execute("SHOW COLUMNS FROM queue_entries LIKE 'notified_called'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE queue_entries ADD COLUMN notified_called TINYINT(1) DEFAULT 0")
        
        # Transaction history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transaction_history (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                user_name VARCHAR(255) NOT NULL,
                service_type VARCHAR(50) NOT NULL,
                queue_number VARCHAR(20) NOT NULL,
                priority VARCHAR(20) NOT NULL,
                status VARCHAR(20) NOT NULL,
                wait_time_minutes INT,
                service_time_minutes INT,
                served_by VARCHAR(255),
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                INDEX idx_user_id (user_id),
                INDEX idx_completed_at (completed_at),
                INDEX idx_served_by (served_by)
            )
        """)
        cursor.execute("SHOW COLUMNS FROM transaction_history LIKE 'service_time_minutes'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE transaction_history ADD COLUMN service_time_minutes INT NULL")
        
        # Document verifications table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_verifications (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                document_type VARCHAR(50) NOT NULL,
                verification_result TEXT,
                confidence_score DECIMAL(5,2),
                extracted_data JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                INDEX idx_user_id (user_id)
            )
        """)

        # Table to store officially verified payments (Integrity Check)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS verified_payments (
                reference_number VARCHAR(50) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                account_number VARCHAR(50) NOT NULL,
                payment_method VARCHAR(50) NOT NULL,
                amount DECIMAL(10, 2) NOT NULL,
                payment_date DATE NOT NULL,
                verification_id VARCHAR(36) NOT NULL,
                verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_user_id (user_id),
                INDEX idx_reference (reference_number)
            )
        """)
        
        # Service settings table (Add this)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS service_settings (
                service_type VARCHAR(50) PRIMARY KEY,
                is_open BOOLEAN DEFAULT TRUE,
                daily_limit INT DEFAULT NULL,
                pending_daily_limit INT DEFAULT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        
        # Ensure pending_daily_limit column exists for existing databases
        cursor.execute("SHOW COLUMNS FROM service_settings LIKE 'pending_daily_limit'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE service_settings ADD COLUMN pending_daily_limit INT DEFAULT NULL")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                endpoint VARCHAR(1024) NOT NULL,
                p256dh VARCHAR(255) NOT NULL,
                auth VARCHAR(255) NOT NULL,
                user_agent VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_endpoint (endpoint(255)),
                INDEX idx_user_id (user_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        # Seed service settings if empty
        cursor.execute("SELECT COUNT(*) as count FROM service_settings")
        if cursor.fetchone()[0] == 0:
            for svc in SERVICE_TYPES:
                cursor.execute("INSERT INTO service_settings (service_type, is_open) VALUES (%s, %s)", (svc, True))
        else:
            # Ensure all SERVICE_TYPES exist in settings
            for svc in SERVICE_TYPES:
                cursor.execute("INSERT IGNORE INTO service_settings (service_type, is_open) VALUES (%s, %s)", (svc, True))

        conn.commit()
        return True
    except mysql.connector.Error as err:
        print(f"Error initializing database: {err}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

def hash_password(password):
    """Hash password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(password, hashed):
    """Check password against hash"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def ensure_static_admin():
    """Ensure the static admin account exists"""
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM users WHERE email = %s", (STATIC_ADMIN_EMAIL,))
        existing = cursor.fetchone()
        if not existing:
            user_id = str(uuid.uuid4())
            hashed_password = hash_password(STATIC_ADMIN_PASSWORD)
            cursor.execute("""
                INSERT INTO users (id, email, password, name, role, admin_type, admin_service, plaintext_password)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, STATIC_ADMIN_EMAIL, hashed_password, STATIC_ADMIN_NAME, 'admin', 'static', None, STATIC_ADMIN_PASSWORD))
        # Backfill plaintext_password for static admin if null
        cursor.execute("""
            UPDATE users SET plaintext_password = %s WHERE email = %s AND plaintext_password IS NULL
        """, (STATIC_ADMIN_PASSWORD, STATIC_ADMIN_EMAIL))
        
        cursor.execute("""
            UPDATE users
            SET admin_type = 'appointed'
            WHERE role = 'admin' AND admin_type IS NULL AND email != %s
        """, (STATIC_ADMIN_EMAIL,))
        # Ensure static admin row is marked static
        cursor.execute("""
            UPDATE users
            SET admin_type = 'static', admin_service = NULL
            WHERE email = %s
        """, (STATIC_ADMIN_EMAIL,))
        conn.commit()
    except mysql.connector.Error as err:
        conn.rollback()
        print(f"Error ensuring static admin: {err}")
    finally:
        cursor.close()
        conn.close()

# Initialize database on startup (only if DB connection works)
if db_pool:
    if init_db():
        print("✅ Database tables initialized")
        ensure_static_admin()
    else:
        print("⚠️  Database tables may already exist or initialization failed")
else:
    print("⚠️  Skipping database initialization - no database connection")

def require_auth(f):
    """Decorator to require authentication"""
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def require_admin(f):
    """Decorator to require admin role"""
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('user_role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def get_current_user():
    """Get current user from session"""
    if 'user_id' not in session:
        return None
    conn = get_db_connection()
    if not conn:
        return None
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if user:
        user.pop('password', None)  # Remove password from response
    return user

def get_vapid_config():
    public_key = os.getenv('VAPID_PUBLIC_KEY')
    private_key = os.getenv('VAPID_PRIVATE_KEY')
    subject = os.getenv('VAPID_SUBJECT', 'mailto:queup@example.com')
    if not public_key or not private_key:
        return None
    return public_key, private_key, subject

def parse_queue_numeric(queue_number):
    if not queue_number:
        return None
    match = re.search(r'(\d+)$', str(queue_number))
    return int(match.group(1)) if match else None

def mix_priority_waiting(waiting_entries):
    regular = [entry for entry in waiting_entries if entry.get('priority') != 'senior_pwd']
    senior = [entry for entry in waiting_entries if entry.get('priority') == 'senior_pwd']
    mixed = []
    reg_idx = 0
    sen_idx = 0

    while reg_idx < len(regular) or sen_idx < len(senior):
        for _ in range(3):
            if reg_idx < len(regular):
                mixed.append(regular[reg_idx])
                reg_idx += 1
        if sen_idx < len(senior):
            mixed.append(senior[sen_idx])
            sen_idx += 1
        if reg_idx >= len(regular) and sen_idx < len(senior):
            mixed.extend(senior[sen_idx:])
            break
    return mixed

def order_queue_entries(entries):
    waiting = [entry for entry in entries if entry.get('status') == 'waiting']
    active = [entry for entry in entries if entry.get('status') != 'waiting']
    return active + mix_priority_waiting(waiting)

def get_user_subscriptions(user_id):
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT endpoint, p256dh, auth
        FROM push_subscriptions
        WHERE user_id = %s
    """, (user_id,))
    subs = cursor.fetchall()
    cursor.close()
    conn.close()
    return subs

def upsert_push_subscription(user_id, subscription, user_agent=None):
    endpoint = subscription.get('endpoint')
    keys = subscription.get('keys') or {}
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')
    if not endpoint or not p256dh or not auth:
        return False
    conn = get_db_connection()
    if not conn:
        return False
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                user_id = VALUES(user_id),
                p256dh = VALUES(p256dh),
                auth = VALUES(auth),
                user_agent = VALUES(user_agent)
        """, (str(uuid.uuid4()), user_id, endpoint, p256dh, auth, user_agent))
        conn.commit()
        return True
    except mysql.connector.Error:
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

def remove_push_subscription(user_id, endpoint):
    conn = get_db_connection()
    if not conn:
        return False
    cursor = conn.cursor()
    try:
        cursor.execute("""
            DELETE FROM push_subscriptions
            WHERE user_id = %s AND endpoint = %s
        """, (user_id, endpoint))
        conn.commit()
        return True
    except mysql.connector.Error:
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

def send_push_to_user(user_id, payload):
    vapid = get_vapid_config()
    if not vapid:
        return
    public_key, private_key, subject = vapid
    subscriptions = get_user_subscriptions(user_id)
    for sub in subscriptions:
        sub_info = {
            "endpoint": sub['endpoint'],
            "keys": {"p256dh": sub['p256dh'], "auth": sub['auth']}
        }
        try:
            webpush(
                subscription_info=sub_info,
                data=json.dumps(payload),
                vapid_private_key=private_key,
                vapid_claims={"sub": subject}
            )
        except WebPushException as ex:
            response = getattr(ex, 'response', None)
            if response is not None and response.status_code in (404, 410):
                remove_push_subscription(user_id, sub['endpoint'])

def mark_queue_notified(queue_id, field_name):
    if field_name not in ('notified_five_away', 'notified_called'):
        return
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()
    try:
        cursor.execute(f"UPDATE queue_entries SET {field_name} = 1 WHERE id = %s", (queue_id,))
        conn.commit()
    except mysql.connector.Error:
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def notify_queue_called(queue_id):
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM queue_entries WHERE id = %s", (queue_id,))
    entry = cursor.fetchone()
    cursor.close()
    conn.close()
    if not entry:
        return
    if entry.get('notified_called'):
        return
    if entry.get('status') not in ('called', 'serving'):
        return
    service_label = entry.get('service_type', '').replace('_', ' ').title()
    payload = {
        "title": "Queue Called",
        "body": f"Queue {entry.get('queue_number')} ({service_label}) is now being called.",
        "tag": f"queup-called-{entry.get('id')}",
        "url": "/",
        "vibrate": [300, 150, 300, 150, 300]
    }
    send_push_to_user(entry.get('user_id'), payload)
    mark_queue_notified(entry.get('id'), 'notified_called')

def notify_five_away_for_service(service_type):
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT * FROM queue_entries
            WHERE status IN ('called', 'serving') AND service_type = %s
            ORDER BY called_at ASC
            LIMIT 1
        """, (service_type,))
        current = cursor.fetchone()
        if not current:
            return
        cursor.execute("""
            SELECT * FROM queue_entries
            WHERE status = 'waiting' AND service_type = %s
            ORDER BY created_at ASC
        """, (service_type,))
        waiting = cursor.fetchall()
        mixed_waiting = mix_priority_waiting(waiting)
        if len(mixed_waiting) < 5:
            return

        for entry in waiting:
            entry_number = parse_queue_numeric(entry.get('queue_number'))
            if entry_number is None or entry_number > target_number:
                continue
            service_label = entry.get('service_type', '').replace('_', ' ').title()
            payload = {
                "title": "Almost your turn!",
                "body": f"Queue {entry.get('queue_number')} ({service_label}) — you're 5 away.",
                "tag": f"queup-five-away-{entry.get('id')}",
                "url": "/",
                "vibrate": [200, 100, 200, 100, 200]
            }
            send_push_to_user(entry.get('user_id'), payload)
            mark_queue_notified(entry.get('id'), 'notified_five_away')
    finally:
        cursor.close()
        conn.close()

# Authentication routes
@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    name = data.get('name')
    role = 'student'
    student_id = data.get('student_id')
    course = data.get('course')
    year = data.get('year')
    
    if not email or not password or not name:
        return jsonify({'error': 'Email, password, and name are required'}), 400
        
    complexity_regex = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>\-_+=\[\]~`\/]).{8,}$')
    if not complexity_regex.match(password):
        return jsonify({'error': 'Password does not meet complexity requirements.'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Check if user exists
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'error': 'Email already registered'}), 400
        
        # Create user
        user_id = str(uuid.uuid4())
        hashed_password = hash_password(password)
        
        cursor.execute("""
            INSERT INTO users (id, email, password, name, role, admin_type, admin_service, student_id, course, year)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (user_id, email, hashed_password, name, role, None, None, student_id, course, year))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({
            'id': user_id,
            'email': email,
            'name': name,
            'role': role,
            'student_id': student_id,
            'course': course,
            'year': year
        }), 201
    except mysql.connector.Error as err:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'error': str(err)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not user or not check_password(password, user['password']):
        return jsonify({'error': 'Invalid email or password'}), 401
    
    # Set session and make it permanent (survives browser refresh)
    session.permanent = True
    session['user_id'] = user['id']
    session['user_role'] = user['role']
    session['user_email'] = user['email']
    session['admin_type'] = user.get('admin_type')
    session['admin_service'] = user.get('admin_service')
    
    user.pop('password', None)  # Remove password from response
    
    return jsonify(user), 200

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out successfully'}), 200

@app.route('/api/auth/me', methods=['GET'])
@require_auth
def get_current_user_info():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(user), 200

@app.route('/api/notifications/vapid-public-key', methods=['GET'])
def get_vapid_public_key():
    vapid = get_vapid_config()
    if not vapid:
        return jsonify({'error': 'Push notifications are not configured'}), 503
    public_key, _, _ = vapid
    return jsonify({'public_key': public_key}), 200

@app.route('/api/notifications/subscribe', methods=['POST'])
@require_auth
def subscribe_notifications():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    data = request.json or {}
    subscription = data.get('subscription') or {}
    user_agent = request.headers.get('User-Agent')
    if not subscription:
        return jsonify({'error': 'Subscription payload is required'}), 400
    if not upsert_push_subscription(user['id'], subscription, user_agent):
        return jsonify({'error': 'Failed to save subscription'}), 500
    return jsonify({'message': 'Subscription saved'}), 200

@app.route('/api/notifications/unsubscribe', methods=['POST'])
@require_auth
def unsubscribe_notifications():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    data = request.json or {}
    endpoint = data.get('endpoint')
    if not endpoint:
        return jsonify({'error': 'Endpoint is required'}), 400
    if not remove_push_subscription(user['id'], endpoint):
        return jsonify({'error': 'Failed to remove subscription'}), 500
    return jsonify({'message': 'Subscription removed'}), 200

# Queue management routes
@app.route('/api/queue/join', methods=['POST'])
@require_auth
def join_queue():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    if user['role'] != 'student':
        return jsonify({'error': 'Only students can join queues'}), 403
    
    data = request.json
    expected_user_id = data.get('expected_user_id')
    if expected_user_id and str(user['id']) != str(expected_user_id):
        return jsonify({'error': 'Session mismatch detected. Please refresh the page.'}), 400
        
    service_type = data.get('service_type')
    priority = data.get('priority', 'regular')
    
    if not service_type:
        return jsonify({'error': 'Service type is required'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Check service settings
        cursor.execute("SELECT * FROM service_settings WHERE service_type = %s", (service_type,))
        settings = cursor.fetchone()
        
        if settings:
            if not settings['is_open']:
                cursor.close()
                conn.close()
                svc_name = service_type.replace('_', ' ').title()
                return jsonify({'error': f'The {svc_name} queue is currently closed.'}), 400
            
            if settings['daily_limit'] is not None:
                today = now_pht().date()
                cursor.execute("""
                    SELECT COUNT(*) as count FROM queue_entries 
                    WHERE service_type = %s AND DATE(created_at) = %s
                """, (service_type, today))
                daily_count = cursor.fetchone()['count']
                
                if daily_count >= settings['daily_limit']:
                    cursor.close()
                    conn.close()
                    svc_name = service_type.replace('_', ' ').title()
                    return jsonify({'error': f'The daily limit for {svc_name} has been reached.'}), 400

        # Check if user is already in a queue
        cursor.execute("""
            SELECT * FROM queue_entries 
            WHERE user_id = %s AND status IN ('waiting', 'called', 'serving')
        """, (user['id'],))
        existing = cursor.fetchone()
        
        if existing:
            if existing['service_type'] == service_type:
                cursor.close()
                conn.close()
                return jsonify(existing), 200
            else:
                cursor.close()
                conn.close()
                return jsonify({'error': f'You are already in the {existing["service_type"]} queue'}), 400
        
        # Generate queue number
        today = now_pht().date()
        cursor.execute("""
            SELECT COUNT(*) as count FROM queue_entries 
            WHERE service_type = %s AND DATE(created_at) = %s
        """, (service_type, today))
        count = cursor.fetchone()['count']
        
        code = SERVICE_CODES.get(service_type, 'GN')
        queue_number = f"{code}{count + 1:02d}"
        
        # Calculate estimated wait time
        cursor.execute("""
            SELECT COUNT(*) as count FROM queue_entries 
            WHERE service_type = %s AND status = 'waiting'
        """, (service_type,))
        waiting_count = cursor.fetchone()['count']
        estimated_wait = waiting_count * 5  # 5 minutes per person
        
        # Create queue entry
        queue_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO queue_entries 
            (id, user_id, user_name, user_email, service_type, queue_number, priority, status, estimated_wait_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (queue_id, user['id'], user['name'], user['email'], service_type, queue_number, priority, 'waiting', estimated_wait))
        
        conn.commit()
        
        # Get created entry
        cursor.execute("SELECT * FROM queue_entries WHERE id = %s", (queue_id,))
        queue_entry = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        notify_five_away_for_service(service_type)
        return jsonify(queue_entry), 201
    except mysql.connector.Error as err:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'error': str(err)}), 500

@app.route('/api/queue/status', methods=['GET'])
def get_queue_status():
    service_type = request.args.get('service_type')
    if session.get('user_role') == 'admin':
        admin_type = session.get('admin_type')
        admin_service = session.get('admin_service')
        if admin_type == 'appointed' and admin_service:
            service_type = admin_service
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        if service_type:
            cursor.execute("""
                SELECT * FROM queue_entries 
                WHERE status IN ('waiting', 'called', 'serving') AND service_type = %s
                ORDER BY priority = 'senior_pwd' DESC, created_at ASC
            """, (service_type,))
        else:
            cursor.execute("""
                SELECT * FROM queue_entries 
                WHERE status IN ('waiting', 'called', 'serving')
                ORDER BY priority = 'senior_pwd' DESC, created_at ASC
            """)
        
        entries = cursor.fetchall()
        cursor.close()
        conn.close()

        if service_type:
            ordered = order_queue_entries(entries)
        else:
            grouped = {}
            for entry in entries:
                grouped.setdefault(entry.get('service_type'), []).append(entry)
            ordered = []
            for svc in SERVICE_TYPES:
                if svc in grouped:
                    ordered.extend(order_queue_entries(grouped.pop(svc)))
            for svc_entries in grouped.values():
                ordered.extend(order_queue_entries(svc_entries))
        return jsonify(ordered), 200
    except mysql.connector.Error as err:
        cursor.close()
        conn.close()
        return jsonify({'error': str(err)}), 500

@app.route('/api/queue/my-queue', methods=['GET'])
@require_auth
def get_my_queue():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT * FROM queue_entries 
        WHERE user_id = %s AND status IN ('waiting', 'called', 'serving')
        ORDER BY created_at DESC LIMIT 1
    """, (user['id'],))
    entry = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return jsonify(entry) if entry else jsonify(None), 200

@app.route('/api/queue/action', methods=['POST'])
@require_auth
@require_admin
def queue_action():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.json
    expected_user_id = data.get('expected_user_id')
    if expected_user_id and str(user['id']) != str(expected_user_id):
        return jsonify({'error': 'Session mismatch detected. Please refresh the page.'}), 400

    queue_id = data.get('queue_id')
    action = data.get('action')
    
    if not queue_id or not action:
        return jsonify({'error': 'Queue ID and action are required'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("SELECT * FROM queue_entries WHERE id = %s", (queue_id,))
        queue_entry = cursor.fetchone()
        
        if not queue_entry:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Queue entry not found'}), 404

        if user.get('admin_type') == 'appointed':
            if not user.get('admin_service') or queue_entry['service_type'] != user.get('admin_service'):
                cursor.close()
                conn.close()
                return jsonify({'error': 'Not authorized for this service'}), 403
        
        if action == 'call':
            cursor.execute("""
                UPDATE queue_entries 
                SET status = 'called', called_at = NOW() 
                WHERE id = %s
            """, (queue_id,))
        elif action == 'next':
            cursor.execute("""
                UPDATE queue_entries 
                SET status = 'serving', 
                    called_at = IFNULL(called_at, NOW()) 
                WHERE id = %s
            """, (queue_id,))
        elif action == 'complete':
            # Calculate wait time (join to completion) and service time (called to completion)
            wait_time = None
            service_time = None
            
            # If called_at is still NULL, set it now to current time (0 min service time)
            if not queue_entry['called_at']:
                cursor.execute("UPDATE queue_entries SET called_at = CONVERT_TZ(NOW(), @@session.time_zone, '+08:00') WHERE id = %s", (queue_id,))
                queue_entry['called_at'] = now_pht()

            cursor.execute("""
                SELECT TIMESTAMPDIFF(MINUTE, created_at, NOW()) as wait_time,
                       TIMESTAMPDIFF(MINUTE, called_at, NOW()) as service_time
                FROM queue_entries WHERE id = %s
            """, (queue_id,))
            result = cursor.fetchone()
            wait_time = result['wait_time'] if result else None
            service_time = result['service_time'] if result else None
            
            # Move to transaction history
            cursor.execute("""
                INSERT INTO transaction_history 
                (id, user_id, user_name, service_type, queue_number, priority, status, wait_time_minutes, service_time_minutes, served_by, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """, (
                str(uuid.uuid4()),
                queue_entry['user_id'],
                queue_entry['user_name'],
                queue_entry['service_type'],
                queue_entry['queue_number'],
                queue_entry['priority'],
                'completed',
                wait_time,
                service_time,
                user['name']
            ))
            
            cursor.execute("""
                UPDATE queue_entries 
                SET status = 'completed', completed_at = NOW() 
                WHERE id = %s
            """, (queue_id,))
        elif action == 'no_show':
            cursor.execute("""
                UPDATE queue_entries 
                SET status = 'no_show', completed_at = NOW() 
                WHERE id = %s
            """, (queue_id,))
        
        conn.commit()
        cursor.close()
        conn.close()

        if action == 'call':
            notify_queue_called(queue_id)
        if action in ('call', 'next', 'complete', 'no_show'):
            notify_five_away_for_service(queue_entry['service_type'])
        
        return jsonify({'message': f'Action {action} completed successfully'}), 200
    except mysql.connector.Error as err:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'error': str(err)}), 500

@app.route('/api/queue/now-serving', methods=['GET'])
def get_now_serving():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT * FROM queue_entries 
            WHERE status IN ('called', 'serving')
            ORDER BY called_at ASC
        """)
        serving = cursor.fetchall()
        
        cursor.execute("""
            SELECT * FROM queue_entries 
            WHERE status = 'completed'
            ORDER BY completed_at DESC LIMIT 20
        """)
        recent = cursor.fetchall()
        
        # Organize by service type
        result = {service: {'serving': [], 'recent': []} for service in SERVICE_TYPES}
        
        for entry in serving:
            service = entry['service_type']
            if service in result:
                result[service]['serving'].append({
                    'queue_number': entry['queue_number'],
                    'status': entry['status'],
                    'user_name': entry['user_name'],
                    'called_at': entry['called_at'].isoformat() if entry['called_at'] else None,
                    'priority': entry['priority']
                })
        
        service_counts = {service: 0 for service in SERVICE_TYPES}
        for entry in recent:
            service = entry['service_type']
            if service in result and service_counts[service] < 2:
                result[service]['recent'].append({
                    'queue_number': entry['queue_number'],
                    'user_name': entry['user_name'],
                    'completed_at': entry['completed_at'].isoformat() if entry['completed_at'] else None
                })
                service_counts[service] += 1
        
        cursor.close()
        conn.close()
        return jsonify(result), 200
    except mysql.connector.Error as err:
        cursor.close()
        conn.close()
        return jsonify({'error': str(err)}), 500

# Receipt verification route
@app.route('/api/receipts/verify', methods=['POST'])
@require_auth
def verify_receipt():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    payment_method = request.form.get('payment_method')
    
    # These are now optional as they will be extracted from the image
    reference_number = request.form.get('reference_number')
    payment_amount = request.form.get('payment_amount')
    payment_date = request.form.get('payment_date')
    
    # Use the student_id stored in the user's account (trusted source)
    student_id = user.get('student_id', '')
    
    if not payment_method:
        return jsonify({'error': 'Payment method is required'}), 400
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        # Read image
        image_data = file.read()
        image = Image.open(BytesIO(image_data))
        
        # Verify with Google Generative AI
        response_text = "AI Verification skipped (No API Key)"
        verified = False
        confidence_score = 0.0
        verification_status = "PENDING"
        
        n8n_url = os.getenv('N8N_WEBHOOK_URL')
        n8n_api_key = os.getenv('N8N_API_KEY')
        
        google_key = os.getenv('GOOGLE_API_KEY')
        if google_key:
            try:
                model = genai.GenerativeModel('gemini-3-flash-preview')
                
                prompt = f"""Analyze this receipt image for University of San Agustin payment and EXTRACT the following:
1. Reference Number / Transaction ID (Look for: Ref No, Trace No, or similar)
2. Exact Amount Paid
3. Date of Payment
4. Payment Method (GCash, Maya, Landbank, etc.)
5. Student ID (Look for: {student_id} or ID numbers)

Verification Goal:
- Verify if this is a valid payment and extract the data accurately.
- Reference number must be clearly readable.

RESPOND ONLY WITH THE EXTRACTED DATA AND VERIFICATION SUMMARY."""
                
                response = model.generate_content([prompt, image])
                response_text = response.text
                print(f"--- AI Response ---\n{response_text}\n------------------")
                
                # Try to parse JSON from response if it exists
                import json
                try:
                    # Clean the response text to find JSON
                    # Look for JSON blocks in markdown
                    json_matches = re.findall(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                    if not json_matches:
                        json_matches = re.findall(r'(\{.*?\})', response_text, re.DOTALL)
                    
                    if json_matches:
                        ai_data = json.loads(json_matches[0])
                        print(f"Parsed AI JSON: {ai_data}")
                        if not reference_number: 
                            reference_number = ai_data.get('reference_number') or ai_data.get('transaction_id') or ai_data.get('reference')
                        if not payment_amount: 
                            payment_amount = ai_data.get('amount') or ai_data.get('payment_amount')
                        if not payment_date: 
                            payment_date = ai_data.get('date') or ai_data.get('payment_date')
                except Exception as e:
                    print(f"JSON Parse Error: {e}")

                # Fallback to Regex if JSON parsing failed or missed fields
                if not reference_number:
                    ref_matches = re.findall(r'(?i)(?:ref|trace|trans|no\.?|id)[:\s]*(\d{9,13})', response_text)
                    if not ref_matches:
                        ref_matches = re.findall(r'(\d{9,13})', response_text)
                    if ref_matches:
                        reference_number = ref_matches[0]
                
                # Extract amount if not provided
                if not payment_amount:
                    amount_matches = re.findall(r'(?i)(?:amt|amount|total|paid)[:\s]*₱?\s*([\d,]+\.?\d*)', response_text)
                    if amount_matches:
                        payment_amount = amount_matches[0].replace(',', '')

                # Extract date if not provided
                if not payment_date:
                    date_matches = re.findall(r'(\d{1,2}[\s\-/]\d{1,2}[\s\-/]\d{2,4})|(\d{4}[\s\-/]\d{1,2}[\s\-/]\d{1,2})', response_text)
                    if date_matches:
                        payment_date = next((m for m in date_matches[0] if m), None)
                
                print(f"Extracted: Ref={reference_number}, Amt={payment_amount}, Date={payment_date}")
                
                # Update extraction logic to trust AI findings
                verified = True if reference_number else False
                confidence_score = 90.0 if verified else 10.0
                verification_status = "VERIFIED" if verified else "NOT_VERIFIED"
            except Exception as ai_err:
                response_text = f"AI Error: {str(ai_err)}"
                print(f"Gemini AI error: {ai_err}")

        # 1. INTEGRITY CHECK (Moved after extraction if needed)
        if reference_number:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT user_id FROM verified_payments WHERE reference_number = %s", (reference_number,))
                existing_payment = cursor.fetchone()
                
                if existing_payment and existing_payment['user_id'] != user['id']:
                    cursor.close()
                    conn.close()
                    return jsonify({
                        'error': 'Receipt Already Used',
                        'message': f'This receipt (Ref No. {reference_number}) has already been used by another account.'
                    }), 400
                cursor.close()
                conn.close()
        elif not n8n_url: # If no ref number and no n8n fallthrough, we fail
             return jsonify({
                'error': 'Could Not Read Receipt',
                'message': 'Our AI could not find a clear Reference Number in the photo. Please ensure it is clearly visible and try again.'
             }), 400
        
        # Optional: Secondary verification with n8n (if configured)
        n8n_verified = False
        if n8n_url:
            try:
                # Prepare data for n8n
                file.seek(0)
                
                headers = {}
                if n8n_api_key:
                    # Support both common ways n8n might expect the key
                    headers['Authorization'] = f'Bearer {n8n_api_key}'
                    headers['X-N8N-API-KEY'] = n8n_api_key
                    
                n8n_response = requests.post(
                    n8n_url,
                    headers=headers,
                    data={
                        'reference_number': reference_number or "",
                        'student_id': student_id or "",
                        'payment_method': payment_method or "",
                        'payment_amount': payment_amount or "",
                        'payment_date': payment_date or "",
                        'user_id': user.get('id', ""),
                        'user_name': user.get('name', "")
                    },
                    files={'file': (file.filename, image_data, file.content_type)},
                    timeout=30 # Increased timeout for n8n processing
                )
                
                print(f"n8n Response Status: {n8n_response.status_code}")
                print(f"n8n Response Body: {n8n_response.text}")
                
                if n8n_response.status_code == 200:
                    n8n_data = n8n_response.json()
                    n8n_verified = n8n_data.get('verified', False)
                    
                    if n8n_verified:
                        confidence_score = 100.0
                        verification_status = "VERIFIED"
                        verified = True
                    else:
                        confidence_score = 0.0
                        verification_status = "NOT_VERIFIED"
                        verified = False
                else:
                    # If n8n errors out, we don't assume verified
                    verification_status = "NOT_VERIFIED"
                    confidence_score = 0.0
                    verified = False
            except Exception as n8n_err:
                print(f"n8n integration error: {n8n_err}")
                # Keep existing Gemini status but maybe lower confidence if n8n-dependent
                if verification_status == "VERIFIED":
                     confidence_score = 85.0 # Pre-verified but record match failed/timed out
        
        # Final safety check: if n8n is configured, it MUST be the source of truth
        if n8n_url and not n8n_verified:
            verification_status = "NOT_VERIFIED"
            confidence_score = min(confidence_score, 40.0)
            verified = False

        # Save verification
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = conn.cursor()
        
        verification_id = str(uuid.uuid4())
        extracted_data = json.dumps({
            'filename': file.filename,
            'size': len(image_data),
            'reference_number': reference_number,
            'student_id': student_id,
            'payment_method': payment_method,
            'payment_amount': payment_amount,
            'payment_date': payment_date,
            'verification_status': verification_status,
            'n8n_verified': n8n_verified,
            'sheets_verified': n8n_verified # n8n handles the sheet check
        })
        
        cursor.execute("""
            INSERT INTO document_verifications 
            (id, user_id, document_type, verification_result, confidence_score, extracted_data)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (verification_id, user['id'], 'payment_receipt', response_text, confidence_score, extracted_data))

        history_status = 'verified' if verification_status == 'VERIFIED' else 'not_verified'
        history_queue_number = reference_number or f'AI-{verification_id[:8]}'
        history_notes = (
            f"Receipt verification ({verification_status}). Ref: {reference_number}, "
            f"Student ID: {student_id}, Method: {payment_method}, "
            f"Amount: {payment_amount}, Date: {payment_date}"
        )
        cursor.execute("""
            INSERT INTO transaction_history
            (id, user_id, user_name, service_type, queue_number, priority, status, wait_time_minutes,
             service_time_minutes, served_by, notes, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            str(uuid.uuid4()),
            user['id'],
            user['name'],
            'receipt_verification',
            history_queue_number,
            'regular',
            history_status,
            None,
            None,
            'AI Verification',
            history_notes
        ))
        
        # If verified, save to verified_payments table to prevent future reuse by others
        if verified:
            try:
                cursor.execute("""
                    INSERT INTO verified_payments 
                    (reference_number, user_id, account_number, payment_method, amount, payment_date, verification_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        user_id = VALUES(user_id),
                        account_number = VALUES(account_number),
                        verification_id = VALUES(verification_id)
                """, (
                    reference_number,
                    user['id'],
                    student_id,  # store student_id in account_number column
                    payment_method,
                    payment_amount,
                    payment_date,
                    verification_id
                ))
            except mysql.connector.Error as db_err:
                print(f"Error saving to verified_payments: {db_err}")
                # We don't fail the request here as the history was already saved, 
                # but we should log it.

        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({
            'id': verification_id,
            'user_id': user['id'],
            'document_type': 'payment_receipt',
            'verification_result': response_text,
            'confidence_score': confidence_score,
            'extracted_data': json.loads(extracted_data)
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Verification failed: {str(e)}'}), 500

# Transaction history routes
@app.route('/api/transactions/history', methods=['GET'])
@require_auth
def get_transaction_history():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        transactions = []
        if user['role'] == 'admin':
            if user.get('admin_type') == 'appointed':
                if not user.get('admin_service'):
                    cursor.close()
                    conn.close()
                    return jsonify({'error': 'Admin service role missing'}), 403
                cursor.execute("""
                    SELECT id, user_name, service_type, queue_number, status, wait_time_minutes, completed_at, 'queue' as type 
                    FROM transaction_history 
                    WHERE service_type = %s
                    ORDER BY completed_at DESC LIMIT 100
                """, (user['admin_service'],))
                transactions = list(cursor.fetchall())
                
                # Payment Admin also gets to see ALL AI Verifications
                if user.get('admin_service') == 'payment':
                    cursor.execute("""
                        SELECT dv.id, u.name as user_name, dv.document_type as service_type, 
                               'VERIFY' as queue_number, dv.verification_result as status, 
                               CASE WHEN dv.confidence_score >= 50 OR dv.verification_result LIKE '%%matched%%' OR dv.verification_result LIKE '%%verified%%' OR dv.verification_result LIKE '%%successfully%%' THEN 'verified' ELSE 'not_verified' END as ai_verification_status,
                               NULL as wait_time_minutes, dv.created_at as completed_at, 'verification' as type
                        FROM document_verifications dv
                        JOIN users u ON dv.user_id = u.id
                        ORDER BY dv.created_at DESC LIMIT 100
                    """)
                    verifications = list(cursor.fetchall())
                    transactions.extend(verifications)
            else:
                cursor.execute("""
                    SELECT id, user_name, service_type, queue_number, status, wait_time_minutes, completed_at, 'queue' as type
                    FROM transaction_history 
                    ORDER BY completed_at DESC LIMIT 100
                """)
                transactions = list(cursor.fetchall())
                
                cursor.execute("""
                    SELECT dv.id, u.name as user_name, dv.document_type as service_type, 
                           'VERIFY' as queue_number, dv.verification_result as status, 
                           CASE WHEN dv.confidence_score >= 50 OR dv.verification_result LIKE '%%matched%%' OR dv.verification_result LIKE '%%verified%%' OR dv.verification_result LIKE '%%successfully%%' THEN 'verified' ELSE 'not_verified' END as ai_verification_status,
                           NULL as wait_time_minutes, dv.created_at as completed_at, 'verification' as type
                    FROM document_verifications dv
                    JOIN users u ON dv.user_id = u.id
                    ORDER BY dv.created_at DESC LIMIT 100
                """)
                verifications = list(cursor.fetchall())
                transactions.extend(verifications)
        else:
            cursor.execute("""
                SELECT id, user_name, service_type, queue_number, status, wait_time_minutes, completed_at, 'queue' as type
                FROM transaction_history 
                WHERE user_id = %s OR user_name = %s
                ORDER BY completed_at DESC LIMIT 100
            """, (user['id'], user['email']))
            transactions = list(cursor.fetchall())
            
            cursor.execute("""
                SELECT dv.id, %s as user_name, dv.document_type as service_type, 
                       'VERIFY' as queue_number, dv.verification_result as status, 
                       CASE WHEN dv.confidence_score >= 50 OR dv.verification_result LIKE '%%matched%%' OR dv.verification_result LIKE '%%verified%%' OR dv.verification_result LIKE '%%successfully%%' THEN 'verified' ELSE 'not_verified' END as ai_verification_status,
                       NULL as wait_time_minutes, dv.created_at as completed_at, 'verification' as type
                FROM document_verifications dv
                WHERE dv.user_id = %s OR dv.user_id IN (
                    SELECT id FROM users WHERE email = %s
                )
                ORDER BY dv.created_at DESC LIMIT 100
            """, (user['name'], user['id'], user['email']))
            verifications = list(cursor.fetchall())
            transactions.extend(verifications)
            
        # Sort combined list by date descending using ISO string sort logic (safe for None or dates)
        transactions.sort(key=lambda x: str(x['completed_at']) if x['completed_at'] else '', reverse=True)
        # Trim to 100 elements max
        transactions = transactions[:100]

        cursor.close()
        conn.close()
        
        # Convert datetime objects to strings
        for trans in transactions:
            if trans.get('completed_at'):
                import datetime
                if isinstance(trans['completed_at'], datetime.datetime):
                    trans['completed_at'] = trans['completed_at'].isoformat()
            if trans.get('created_at'):
                import datetime
                if isinstance(trans['created_at'], datetime.datetime):
                    trans['created_at'] = trans['created_at'].isoformat()
        
        return jsonify(transactions), 200
    except mysql.connector.Error as err:
        cursor.close()
        conn.close()
        return jsonify({'error': str(err)}), 500

# Admin stats route
@app.route('/api/admin/stats', methods=['GET'])
@require_auth
@require_admin
def get_admin_stats():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        today = now_pht().date()
        admin_service = None
        if session.get('admin_type') == 'appointed':
            admin_service = session.get('admin_service')

        if admin_service:
            cursor.execute("""
                SELECT COUNT(*) as count FROM queue_entries
                WHERE status = 'waiting' AND service_type = %s
            """, (admin_service,))
            total_waiting = cursor.fetchone()['count']

            cursor.execute("""
                SELECT COUNT(*) as count FROM transaction_history
                WHERE DATE(completed_at) = %s AND service_type = %s
            """, (today, admin_service))
            total_served_today = cursor.fetchone()['count']

            services_count = {service: 0 for service in SERVICE_TYPES}
            services_count[admin_service] = total_waiting
        else:
            cursor.execute("SELECT COUNT(*) as count FROM queue_entries WHERE status = 'waiting'")
            total_waiting = cursor.fetchone()['count']

            cursor.execute("""
                SELECT COUNT(*) as count FROM transaction_history 
                WHERE DATE(completed_at) = %s
            """, (today,))
            total_served_today = cursor.fetchone()['count']

            services_count = {}
            for service_type in SERVICE_TYPES:
                cursor.execute("""
                    SELECT COUNT(*) as count FROM queue_entries 
                    WHERE service_type = %s AND status = 'waiting'
                """, (service_type,))
                services_count[service_type] = cursor.fetchone()['count']
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'total_waiting': total_waiting,
            'total_served_today': total_served_today,
            'services_count': services_count
        }), 200
    except mysql.connector.Error as err:
        cursor.close()
        conn.close()
        return jsonify({'error': str(err)}), 500

# Performance analytics (SuperAdmin / static admin only)
@app.route('/api/admin/analytics', methods=['GET'])
@require_auth
@require_admin
def get_admin_analytics():
    user = get_current_user()
    if not user or user.get('admin_type') != 'static':
        return jsonify({'error': 'SuperAdmin access required'}), 403

    days = int(request.args.get('days', 30))
    if days < 1 or days > 365:
        days = 30

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    cursor = conn.cursor(dictionary=True)
    try:
        # Admin performance: numbers served, average service time per admin
        cursor.execute("""
            SELECT 
                served_by as admin_name,
                COUNT(*) as numbers_served,
                ROUND(AVG(service_time_minutes), 1) as avg_service_minutes
            FROM transaction_history
            WHERE served_by IS NOT NULL 
              AND served_by != ''
              AND status = 'completed'
              AND service_time_minutes IS NOT NULL
              AND completed_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            GROUP BY served_by
            ORDER BY numbers_served DESC
        """, (days,))
        admin_performance = cursor.fetchall()

        # Peak hours: completions per hour of day (0-23)
        cursor.execute("""
            SELECT 
                HOUR(completed_at) as hour,
                COUNT(*) as count
            FROM transaction_history
            WHERE completed_at IS NOT NULL
              AND completed_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            GROUP BY HOUR(completed_at)
            ORDER BY hour
        """, (days,))
        peak_rows = cursor.fetchall()
        # Fill missing hours with 0
        hour_counts = {r['hour']: r['count'] for r in peak_rows}
        peak_hours = [{'hour': h, 'hour_label': f'{h:02d}:00', 'count': hour_counts.get(h, 0)} for h in range(24)]

        cursor.close()
        conn.close()

        return jsonify({
            'admin_performance': admin_performance,
            'peak_hours': peak_hours,
            'period_days': days
        }), 200
    except mysql.connector.Error as err:
        cursor.close()
        conn.close()
        return jsonify({'error': str(err)}), 500

# Admin management routes
@app.route('/api/admin/admins', methods=['GET'])
@require_auth
@require_admin
def list_admins():
    user = get_current_user()
    if not user or user.get('admin_type') != 'static':
        return jsonify({'error': 'Static admin access required'}), 403
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, email, name, role, admin_type, admin_service, created_at, plaintext_password
        FROM users
        WHERE role = 'admin'
        ORDER BY created_at DESC
    """)
    admins = cursor.fetchall()
    cursor.close()
    conn.close()
    for admin in admins:
        if admin.get('created_at'):
            admin['created_at'] = admin['created_at'].isoformat()
    return jsonify(admins), 200

@app.route('/api/admin/admins', methods=['POST'])
@require_auth
@require_admin
def create_admin():
    user = get_current_user()
    if not user or user.get('admin_type') != 'static':
        return jsonify({'error': 'Static admin access required'}), 403

    data = request.json or {}
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    admin_service = data.get('admin_service')

    if not name or not email or not password:
        return jsonify({'error': 'Name, email, and password are required'}), 400
    if admin_service is not None and admin_service not in ADMIN_SERVICE_TYPES:
        return jsonify({'error': 'Valid admin_service is required'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'error': 'Email already registered'}), 400
        if admin_service:
            cursor.execute("""
                UPDATE users
                SET admin_service = NULL
                WHERE role = 'admin'
                  AND admin_type = 'appointed'
                  AND admin_service = %s
            """, (admin_service,))

        user_id = str(uuid.uuid4())
        hashed_password = hash_password(password)
        cursor.execute("""
            INSERT INTO users (id, email, password, name, role, admin_type, admin_service, plaintext_password)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (user_id, email, hashed_password, name, 'admin', 'appointed', admin_service, password))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'id': user_id}), 201
    except mysql.connector.Error as err:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'error': str(err)}), 500

@app.route('/api/admin/admins/<admin_id>', methods=['PATCH'])
@require_auth
@require_admin
def update_admin_role(admin_id):
    user = get_current_user()
    if not user or user.get('admin_type') != 'static':
        return jsonify({'error': 'Static admin access required'}), 403

    data = request.json or {}
    admin_service = data.get('admin_service')
    if admin_service is not None and admin_service not in ADMIN_SERVICE_TYPES:
        return jsonify({'error': 'Valid admin_service is required'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, admin_type FROM users WHERE id = %s AND role = 'admin'", (admin_id,))
        target = cursor.fetchone()
        if not target:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Admin not found'}), 404
        if target.get('admin_type') == 'static':
            cursor.close()
            conn.close()
            return jsonify({'error': 'Cannot modify static admin'}), 403
        if admin_service:
            cursor.execute("""
                UPDATE users
                SET admin_service = NULL
                WHERE role = 'admin'
                  AND admin_type = 'appointed'
                  AND admin_service = %s
                  AND id != %s
            """, (admin_service, admin_id))
        cursor.execute("""
            UPDATE users SET admin_service = %s WHERE id = %s
        """, (admin_service, admin_id))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'message': 'Admin role updated'}), 200
    except mysql.connector.Error as err:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'error': str(err)}), 500

@app.route('/api/admin/admins/<admin_id>', methods=['DELETE'])
@require_auth
@require_admin
def delete_admin(admin_id):
    user = get_current_user()
    if not user or user.get('admin_type') != 'static':
        return jsonify({'error': 'Static admin access required'}), 403

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, admin_type FROM users WHERE id = %s AND role = 'admin'", (admin_id,))
        target = cursor.fetchone()
        if not target:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Admin not found'}), 404
        if target.get('admin_type') == 'static':
            cursor.close()
            conn.close()
            return jsonify({'error': 'Cannot delete static admin'}), 403
        cursor.execute("DELETE FROM users WHERE id = %s", (admin_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'message': 'Admin deleted'}), 200
    except mysql.connector.Error as err:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'error': str(err)}), 500

@app.route('/api/admin/users', methods=['GET'])
@require_auth
@require_admin
def list_users():
    user = get_current_user()
    if not user or user.get('admin_type') != 'static':
        return jsonify({'error': 'Static admin access required'}), 403
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, email, name, role, created_at
        FROM users
        WHERE role = 'student'
        ORDER BY created_at DESC
    """)
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    for item in users:
        if item.get('created_at'):
            item['created_at'] = item['created_at'].isoformat()
    return jsonify(users), 200


@app.route('/api/admin/users/<user_id>', methods=['DELETE'])
@require_auth
@require_admin
def delete_user(user_id):
    user = get_current_user()
    if not user or user.get('admin_type') != 'static':
        return jsonify({'error': 'Static admin access required'}), 403
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, role FROM users WHERE id = %s", (user_id,))
        target = cursor.fetchone()
        if not target:
            cursor.close()
            conn.close()
            return jsonify({'error': 'User not found'}), 404
        if target.get('role') != 'student':
            cursor.close()
            conn.close()
            return jsonify({'error': 'Only students can be deleted here'}), 403
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'message': 'User deleted'}), 200
    except mysql.connector.Error as err:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'error': str(err)}), 500

# Admin service settings routes
@app.route('/api/admin/service-settings', methods=['GET'])
@require_auth
@require_admin
def get_service_settings():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM service_settings")
        settings = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(settings), 200
    except mysql.connector.Error as err:
        cursor.close()
        conn.close()
        return jsonify({'error': str(err)}), 500

@app.route('/api/admin/service-settings/<service_type>', methods=['PATCH'])
@require_auth
@require_admin
def update_service_settings(service_type):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
        
    # Appointed admins can only change their own service
    if user.get('admin_type') == 'appointed':
        if user.get('admin_service') != service_type:
            return jsonify({'error': 'Not authorized for this service'}), 403
            
    data = request.json or {}
    is_open = data.get('is_open')
    daily_limit = data.get('daily_limit')
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        updates = []
        params = []
        if is_open is not None:
            updates.append("is_open = %s")
            params.append(is_open)
        if 'daily_limit' in data: # Active daily limit (can still be set directly if needed)
            updates.append("daily_limit = %s")
            params.append(daily_limit)
        if 'pending_daily_limit' in data: # Pending limit from "Save" button
            updates.append("pending_daily_limit = %s")
            params.append(data.get('pending_daily_limit'))
            
        if not updates:
            return jsonify({'error': 'No updates provided'}), 400
            
        params.append(service_type)
        cursor.execute(f"UPDATE service_settings SET {', '.join(updates)} WHERE service_type = %s", tuple(params))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'message': 'Settings updated successfully'}), 200
    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': str(err)}), 500

@app.route('/api/admin/service-settings/<service_type>/sync', methods=['POST'])
@require_auth
@require_admin
def sync_service_settings(service_type):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
        
    if user.get('admin_type') == 'appointed' and user.get('admin_service') != service_type:
        return jsonify({'error': 'Not authorized for this service'}), 403
        
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        # Check if service exists
        cursor.execute("SELECT pending_daily_limit FROM service_settings WHERE service_type = %s", (service_type,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Service not found'}), 404
            
        # Sync pending to active
        cursor.execute("""
            UPDATE service_settings 
            SET daily_limit = pending_daily_limit 
            WHERE service_type = %s
        """, (service_type,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'message': 'Settings synced successfully'}), 200
    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': str(err)}), 500

# Health check
@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': now_pht().isoformat()}), 200
# Serve frontend files
@app.route('/')
def serve_frontend():
    return send_from_directory('../simplified_frontend', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('../simplified_frontend', path)

with app.app_context():
    init_db()
    ensure_static_admin()
    
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)


