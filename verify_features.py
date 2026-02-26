import sys
import os
import unittest
import json
from datetime import datetime

# Add the backend directory to sys.path
sys.path.append(os.path.join(os.getcwd(), 'simplified_backend'))

from app import app, db_pool, init_db, SERVICE_TYPES

class TestQueueFeatures(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.secret_key = 'test-secret'
        self.client = app.test_client()
        
        # Ensure DB is initialized and test user exists
        with app.app_context():
            init_db()
            conn = db_pool.get_connection()
            cursor = conn.cursor()
            try:
                # Use INSERT IGNORE to avoid duplicate error
                cursor.execute("""
                    INSERT IGNORE INTO users (id, email, password, name, role)
                    VALUES (%s, %s, %s, %s, %s)
                """, ('test-student-id', 'test@student.com', 'hashed', 'Test Student', 'student'))
                conn.commit()
            finally:
                cursor.close()
                conn.close()

    def test_service_settings_table_exists(self):
        """Verify service_settings table and initial seeding."""
        conn = db_pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT COUNT(*) as count FROM service_settings")
            count = cursor.fetchone()['count']
            self.assertGreaterEqual(count, len(SERVICE_TYPES))
            
            cursor.execute("SELECT * FROM service_settings LIMIT 1")
            setting = cursor.fetchone()
            self.assertIn('service_type', setting)
            self.assertIn('is_open', setting)
            self.assertIn('daily_limit', setting)
        finally:
            cursor.close()
            conn.close()

    def test_join_queue_when_closed(self):
        """Test that a student cannot join a closed queue."""
        service = SERVICE_TYPES[0]
        
        # Close the service
        conn = db_pool.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE service_settings SET is_open = %s WHERE service_type = %s", (False, service))
            conn.commit()
        finally:
            cursor.close()
            conn.close()

        # Mock login/session
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'test-student-id'
            sess['user_role'] = 'student'

        # Try to join
        response = self.client.post('/api/queue/join', 
                                    data=json.dumps({'service_type': service}),
                                    content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('currently closed', data['error'])

    def test_join_queue_with_daily_limit(self):
        """Test that a student cannot join if daily limit is reached."""
        service = SERVICE_TYPES[1]
        
        # Set limit to 0
        conn = db_pool.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE service_settings SET is_open = %s, daily_limit = %s WHERE service_type = %s", (True, 0, service))
            conn.commit()
        finally:
            cursor.close()
            conn.close()

        # Mock login/session
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'test-student-id'
            sess['user_role'] = 'student'

        # Try to join
        response = self.client.post('/api/queue/join', 
                                    data=json.dumps({'service_type': service}),
                                    content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn('daily limit', data['error'])

if __name__ == '__main__':
    unittest.main()
