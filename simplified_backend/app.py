from flask import Flask, request, jsonify, session
from flask_cors import CORS
import mysql.connector
from mysql.connector import pooling
import os
from dotenv import load_dotenv
import bcrypt
import uuid
from datetime import datetime
import json
from werkzeug.utils import secure_filename
from functools import wraps
import google.generativeai as genai
import base64
from io import BytesIO
from PIL import Image
from flask import send_from_directory
# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
# Session cookie security for production HTTPS (Railway, etc.)
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

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
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'queueup_db'),
    'pool_name': 'queueup_pool',
    'pool_size': 5
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
        return db_pool.get_connection()
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
                called_at TIMESTAMP NULL,
                completed_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                INDEX idx_status (status),
                INDEX idx_service_type (service_type),
                INDEX idx_user_id (user_id)
            )
        """)
        
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
                INSERT INTO users (id, email, password, name, role, admin_type, admin_service)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (user_id, STATIC_ADMIN_EMAIL, hashed_password, STATIC_ADMIN_NAME, 'admin', 'static', None))
        # Backfill admin_type for existing admins
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
    
    # Set session
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
    service_type = data.get('service_type')
    priority = data.get('priority', 'regular')
    
    if not service_type:
        return jsonify({'error': 'Service type is required'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    cursor = conn.cursor(dictionary=True)
    
    try:
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
        today = datetime.now().date()
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
                ORDER BY created_at ASC
            """, (service_type,))
        else:
            cursor.execute("""
                SELECT * FROM queue_entries 
                WHERE status IN ('waiting', 'called', 'serving')
                ORDER BY created_at ASC
            """)
        
        entries = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return jsonify(entries), 200
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
                SET status = 'serving' 
                WHERE id = %s
            """, (queue_id,))
        elif action == 'complete':
            # Calculate wait time (join to completion) and service time (called to completion)
            wait_time = None
            service_time = None
            if queue_entry['called_at']:
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
    reference_number = request.form.get('reference_number')
    account_number = request.form.get('account_number')
    
    if not reference_number or not account_number:
        return jsonify({'error': 'Reference number and account number are required'}), 400
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        # Read image
        image_data = file.read()
        image = Image.open(BytesIO(image_data))
        
        # Verify with Google Generative AI
        if not os.getenv('GOOGLE_API_KEY'):
            return jsonify({'error': 'AI verification not configured'}), 500
        
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        
        prompt = f"""Please analyze this receipt image and verify if it matches:
Reference Number: {reference_number}
Account Number: {account_number}

Extract the following information:
1. Reference Number (looking for: {reference_number})
2. Account Number (looking for: {account_number})
3. Amount paid
4. Payment date
5. Payment method
6. Institution/Bank name

Compare the extracted reference number and account number with the provided values. 
Determine if this is a valid receipt for the University of San Agustin accounting office."""
        
        response = model.generate_content([prompt, image])
        response_text = response.text
        
        # Determine verification status
        verified = (reference_number.upper() in response_text.upper() or 
                   account_number in response_text)
        confidence_score = 95.0 if verified else 25.0
        verification_status = "VERIFIED" if verified else "NOT_VERIFIED"
        
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
            'account_number': account_number,
            'verification_status': verification_status,
            'sheets_verified': True  # Mock - would check Google Sheets in production
        })
        
        cursor.execute("""
            INSERT INTO document_verifications 
            (id, user_id, document_type, verification_result, confidence_score, extracted_data)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (verification_id, user['id'], 'payment_receipt', response_text, confidence_score, extracted_data))
        
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
        if user['role'] == 'admin':
            if user.get('admin_type') == 'appointed':
                if not user.get('admin_service'):
                    cursor.close()
                    conn.close()
                    return jsonify({'error': 'Admin service role missing'}), 403
                cursor.execute("""
                    SELECT * FROM transaction_history 
                    WHERE service_type = %s
                    ORDER BY completed_at DESC LIMIT 100
                """, (user['admin_service'],))
            else:
                cursor.execute("""
                    SELECT * FROM transaction_history 
                    ORDER BY completed_at DESC LIMIT 100
                """)
        else:
            cursor.execute("""
                SELECT * FROM transaction_history 
                WHERE user_id = %s 
                ORDER BY completed_at DESC LIMIT 100
            """, (user['id'],))
        
        transactions = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Convert datetime objects to strings
        for trans in transactions:
            if trans.get('completed_at'):
                trans['completed_at'] = trans['completed_at'].isoformat()
            if trans.get('created_at'):
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
        today = datetime.now().date()
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
                ROUND(AVG(COALESCE(service_time_minutes, wait_time_minutes)), 1) as avg_service_minutes
            FROM transaction_history
            WHERE served_by IS NOT NULL 
              AND served_by != ''
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
        SELECT id, email, name, role, admin_type, admin_service, created_at
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

    if not name or not email or not password or admin_service not in ADMIN_SERVICE_TYPES:
        return jsonify({'error': 'Name, email, password, and valid admin_service are required'}), 400

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

        user_id = str(uuid.uuid4())
        hashed_password = hash_password(password)
        cursor.execute("""
            INSERT INTO users (id, email, password, name, role, admin_type, admin_service)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (user_id, email, hashed_password, name, 'admin', 'appointed', admin_service))
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
    if admin_service not in ADMIN_SERVICE_TYPES:
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

# Health check
@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()}), 200
# Serve frontend files
@app.route('/')
def serve_frontend():
    return send_from_directory('../simplified_frontend', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('../simplified_frontend', path)

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)


