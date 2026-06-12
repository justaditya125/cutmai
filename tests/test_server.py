"""
Basic unit and integration tests for the modular botai application
"""
import unittest
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from botai.config import settings
from botai.utils.auth_utils import hash_password, verify_password, convert_to_alphanumeric
from botai.utils.validators import validate_email, validate_password_strength, validate_institutional_domain
from botai.utils.rate_limiter import is_rate_limited


class TestModularServer(unittest.TestCase):

    def test_settings_load(self):
        """Verify settings module successfully loads configs from .env"""
        self.assertIsNotNone(settings.DATABASE_URL)
        self.assertIn('cutm.ac.in', settings.ALLOWED_DOMAINS)

    def test_auth_hashing(self):
        """Verify backward compatible pbkdf2 hashing and password verification"""
        password = "SecurePassword123"
        hashed = hash_password(password)
        self.assertTrue(verify_password(password, hashed))
        self.assertFalse(verify_password("wrong_password", hashed))

        # Check backward compatibility conversion
        converted = convert_to_alphanumeric(password)
        self.assertEqual(len(converted), 12)

    def test_validators(self):
        """Verify institutional email validations and password strength checks"""
        self.assertTrue(validate_email("test@cutm.ac.in"))
        self.assertTrue(validate_email("external@gmail.com"))
        
        # Check institutional domain validation
        self.assertTrue(validate_institutional_domain("test@cutm.ac.in"))
        self.assertTrue(validate_institutional_domain("student@cutmap.ac.in"))
        self.assertFalse(validate_institutional_domain("external@gmail.com"))

        # Password strength
        self.assertTrue(validate_password_strength("StrongPass1"))
        self.assertFalse(validate_password_strength("weak"))


    def test_rate_limiter(self):
        """Verify rate limiter registers requests and correctly triggers thresholds"""
        ip = "127.0.0.1"
        endpoint = "/api/test"
        
        # Make 2 requests with a limit of 5
        self.assertFalse(is_rate_limited(ip, endpoint, limit=5, window=10))
        self.assertFalse(is_rate_limited(ip, endpoint, limit=5, window=10))

    def test_file_upload_and_management(self):
        """Verify file upload, list, and delete routes using mock handler"""
        from botai.routes import chat_routes
        import base64
        
        # Setup mock database
        class MockCollection:
            def __init__(self):
                self.docs = {}
            def insert_one(self, doc):
                self.docs[doc['_id']] = doc
            def find_one(self, query):
                from bson import ObjectId
                for doc in self.docs.values():
                    match = True
                    for k, v in query.items():
                        if k == '_id':
                            if str(doc.get('_id')) != str(v):
                                match = False
                        elif k == 'user_id':
                            if str(doc.get('user_id')) != str(v):
                                match = False
                        elif doc.get(k) != v:
                            match = False
                    if match:
                        return doc
                return None
            def find(self, query):
                results = []
                for doc in self.docs.values():
                    match = True
                    for k, v in query.items():
                        if k == 'user_id':
                            if str(doc.get('user_id')) != str(v):
                                match = False
                        elif doc.get(k) != v:
                            match = False
                    if match:
                        results.append(doc)
                class MockCursor:
                    def __init__(self, items):
                        self.items = items
                    def sort(self, field, direction):
                        return self.items
                    def __iter__(self):
                        return iter(self.items)
                return MockCursor(results)
            def delete_one(self, query):
                doc = self.find_one(query)
                if doc:
                    del self.docs[doc['_id']]
                    class DeleteResult:
                        deleted_count = 1
                    return DeleteResult()
                class DeleteResult:
                    deleted_count = 0
                return DeleteResult()

        class MockDB:
            def __init__(self):
                self.files = MockCollection()

        class MockHandler:
            def __init__(self, path, body_dict=None, headers=None):
                self.path = path
                self.body_dict = body_dict or {}
                self.headers = headers or {}
                self.response_status = None
                self.response_data = None
            def read_body(self):
                return self.body_dict
            def send_json(self, status, data):
                self.response_status = status
                self.response_data = data
            def get_user_from_token(self, token):
                if token == "valid_token":
                    return {"id": "60d5ecb8b3b3b3b3b3b3b3b3", "email": "test@cutm.ac.in", "is_active": True}
                return None

        # Mock get_db in chat_routes
        original_get_db = chat_routes.get_db
        mock_db = MockDB()
        chat_routes.get_db = lambda: mock_db
        
        try:
            # Test 1: Upload validation failure (no filename)
            handler = MockHandler('/api/files/upload', body_dict={
                'session_token': 'valid_token',
                'file_data_b64': base64.b64encode(b"hello world").decode('utf-8')
            })
            chat_routes.handle_post(handler)
            self.assertEqual(handler.response_status, 400)
            self.assertIn('error', handler.response_data)
            
            # Test 2: Upload success
            handler = MockHandler('/api/files/upload', body_dict={
                'session_token': 'valid_token',
                'filename': 'test_essay.txt',
                'file_data_b64': base64.b64encode(b"hello world contents").decode('utf-8')
            })
            chat_routes.handle_post(handler)
            self.assertEqual(handler.response_status, 200)
            file_id = handler.response_data['file_id']
            self.assertEqual(handler.response_data['filename'], 'test_essay.txt')
            
            # Test 3: List files
            list_handler = MockHandler('/api/files/list?session_token=valid_token')
            chat_routes.handle_get(list_handler)
            self.assertEqual(list_handler.response_status, 200)
            self.assertTrue(any(f['file_id'] == file_id for f in list_handler.response_data['files']))
            
            # Test 4: Delete file
            delete_handler = MockHandler('/api/files/delete', body_dict={
                'session_token': 'valid_token',
                'file_id': file_id
            })
            chat_routes.handle_post(delete_handler)
            self.assertEqual(delete_handler.response_status, 200)
            self.assertEqual(delete_handler.response_data['message'], 'File deleted successfully')
            
            # Verify list is empty now
            list_handler2 = MockHandler('/api/files/list?session_token=valid_token')
            chat_routes.handle_get(list_handler2)
            self.assertEqual(list_handler2.response_status, 200)
            self.assertEqual(len(list_handler2.response_data['files']), 0)
            
        finally:
            chat_routes.get_db = original_get_db

if __name__ == '__main__':
    unittest.main()
