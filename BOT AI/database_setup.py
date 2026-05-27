#!/usr/bin/env python3
import hashlib
import secrets
import os
from datetime import datetime, timedelta
from pymongo import MongoClient, ASCENDING
from pymongo.errors import ConnectionFailure, DuplicateKeyError

# Load secrets from .env file (keeps credentials out of source code)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# MongoDB Atlas configuration
MONGO_URI = os.environ.get('MONGO_URI', '')
if not MONGO_URI:
    raise RuntimeError('MONGO_URI not set! Add it to your .env file before running.')
DB_NAME = 'cutm_ai'

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
        
    def connect(self):
        """Connect to MongoDB Atlas database"""
        try:
            self.client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            # Trigger connection check
            self.client.admin.command('ping')
            self.db = self.client[DB_NAME]
            print("✅ Connected to MongoDB Atlas successfully")
            return True
        except ConnectionFailure as e:
            print(f"❌ Error connecting to MongoDB Atlas: {e}")
            return False
        except Exception as e:
            print(f"❌ Unexpected connection error: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from MongoDB Atlas"""
        if self.client:
            self.client.close()
            print("🔌 MongoDB client connection closed")
    
    def create_collections_and_indexes(self):
        """Create necessary collections and build search/unique indexes"""
        if self.db is None:
            print("❌ No active database connection")
            return False
            
        try:
            # 1. Users collection indexes
            self.db.users.create_index([("email", ASCENDING)], unique=True)
            self.db.users.create_index([("google_id", ASCENDING)], unique=True, sparse=True)
            print("✅ 'users' collection indexes verified")
            
            # 2. User sessions collection indexes
            self.db.user_sessions.create_index([("session_token", ASCENDING)], unique=True)
            self.db.user_sessions.create_index([("user_id", ASCENDING)])
            print("✅ 'user_sessions' collection indexes verified")
            
            # 3. Conversations collection indexes
            self.db.conversations.create_index([("user_id", ASCENDING)])
            self.db.conversations.create_index([("updated_at", ASCENDING)])
            print("✅ 'conversations' collection indexes verified")
            
            # 4. Messages collection indexes
            self.db.messages.create_index([("conversation_id", ASCENDING)])
            self.db.messages.create_index([("user_id", ASCENDING)])
            print("✅ 'messages' collection indexes verified")
            
            # 5. Token usage collection indexes
            self.db.token_usage.create_index([("user_id", ASCENDING)])
            self.db.token_usage.create_index([("created_at", ASCENDING)])
            print("✅ 'token_usage' collection indexes verified")
            
            return True
            
        except Exception as e:
            print(f"❌ Error building database indexes: {e}")
            return False
    
    def hash_password(self, password):
        """Hash password with salt"""
        salt = secrets.token_hex(16)
        password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return f"{salt}:{password_hash.hex()}"
    
    def verify_password(self, password, stored_hash):
        """Verify password against stored hash"""
        try:
            salt, hash_hex = stored_hash.split(':')
            password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
            return password_hash.hex() == hash_hex
        except Exception:
            return False
    
    def create_user(self, email, password=None, name=None, login_method='email', google_id=None, profile_picture=None, is_admin=False):
        """Create a new user document"""
        if self.db is None:
            return None
            
        try:
            # Hash password if standard login
            password_hash = self.hash_password(password) if password else None
            
            user_doc = {
                "email": email.strip().lower(),
                "password_hash": password_hash,
                "name": name.strip() if name else None,
                "profile_picture": profile_picture,
                "login_method": login_method,
                "is_active": True,
                "is_admin": is_admin,
                "total_tokens_used": 0,
                "total_messages": 0,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "last_login": None
            }
            if google_id is not None:
                user_doc["google_id"] = google_id
            
            result = self.db.users.insert_one(user_doc)
            print(f"✅ User created successfully: {email}")
            return result.inserted_id
            
        except DuplicateKeyError:
            print(f"⚠️ User with email/google_id already exists: {email}")
            return None
        except Exception as e:
            print(f"❌ Error creating user: {e}")
            return None
    
    def get_user_by_email(self, email):
        """Get user document by email"""
        if self.db is None:
            return None
        try:
            return self.db.users.find_one({"email": email.strip().lower(), "is_active": True})
        except Exception as e:
            print(f"❌ Error getting user: {e}")
            return None
    
    def get_user_by_google_id(self, google_id):
        """Get user document by Google ID"""
        if self.db is None:
            return None
        try:
            return self.db.users.find_one({"google_id": google_id, "is_active": True})
        except Exception as e:
            print(f"❌ Error getting user by Google ID: {e}")
            return None
    
    def authenticate_user(self, email, password):
        """Authenticate user with email and password"""
        user = self.get_user_by_email(email)
        if user and user.get('password_hash'):
            if self.verify_password(password, user['password_hash']):
                self.update_last_login(user['_id'])
                return user
        return None
    
    def update_last_login(self, user_id):
        """Update user's last login timestamp"""
        if self.db is None:
            return False
        try:
            self.db.users.update_one(
                {"_id": user_id},
                {"$set": {"last_login": datetime.now(), "updated_at": datetime.now()}}
            )
            return True
        except Exception as e:
            print(f"❌ Error updating last login: {e}")
            return False
    
    def create_session(self, user_id, ip_address=None, user_agent=None):
        """Create a new user session document"""
        if self.db is None:
            return None
            
        try:
            session_token = secrets.token_urlsafe(32)
            expires_at = datetime.now() + timedelta(days=30)
            
            session_doc = {
                "user_id": user_id,
                "session_token": session_token,
                "expires_at": expires_at,
                "created_at": datetime.now(),
                "ip_address": ip_address,
                "user_agent": user_agent
            }
            
            self.db.user_sessions.insert_one(session_doc)
            return session_token
            
        except Exception as e:
            print(f"❌ Error creating session: {e}")
            return None
    
    def get_user_by_session(self, session_token):
        """Get user by session token"""
        if self.db is None:
            return None
            
        try:
            session = self.db.user_sessions.find_one({
                "session_token": session_token,
                "expires_at": {"$gt": datetime.now()}
            })
            if session:
                return self.db.users.find_one({"_id": session['user_id'], "is_active": True})
            return None
        except Exception as e:
            print(f"❌ Error getting user by session: {e}")
            return None

def setup_database():
    """Setup the complete MongoDB database collections and seed data"""
    print("🚀 Setting up Claude Chatbot Database on MongoDB Atlas...")
    
    db_mgr = DatabaseManager()
    
    # Connect and configure database
    if db_mgr.connect():
        # Setup collections and indexes
        if db_mgr.create_collections_and_indexes():
            print("✅ MongoDB Database collections and indexes built successfully!")
            
            # Check if seeded test user already exists
            test_user = db_mgr.get_user_by_email("test@example.com")
            if not test_user:
                test_user_id = db_mgr.create_user(
                    email="test@example.com",
                    password="test123",
                    name="Test User",
                    login_method="email",
                    is_admin=False
                )
                if test_user_id:
                    print(f"✅ Test user seeded successfully with ID: {test_user_id}")
            else:
                print("ℹ️ Seed user 'test@example.com' already exists")
            
            # Backfill is_admin: False on existing users that do not have this field
            res_backfill = db_mgr.db.users.update_many(
                {"is_admin": {"$exists": False}},
                {"$set": {"is_admin": False}}
            )
            if res_backfill.modified_count > 0:
                print(f"✅ Backfilled is_admin: False on {res_backfill.modified_count} users")
            
            # Ensure the admin account is seeded (only on first run — never resets password)
            admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
            admin_user = db_mgr.get_user_by_email("admin")
            if not admin_user:
                admin_id = db_mgr.create_user(
                    email="admin",
                    password=admin_password,
                    name="System Admin",
                    login_method="email",
                    is_admin=True
                )
                if admin_id:
                    print(f"✅ Admin account seeded (email=admin, password from ADMIN_PASSWORD in .env)")
            else:
                # Only ensure the is_admin flag is correct — do NOT reset the password
                db_mgr.db.users.update_one(
                    {"email": "admin"},
                    {"$set": {"is_admin": True, "name": "System Admin"}}
                )
                print("ℹ️  Admin account 'admin' verified (password NOT reset — change via .env ADMIN_PASSWORD)")
            
            # Ensure regular Google/Email users do not have admin privileges (Aditya Sah set to False)
            db_mgr.db.users.update_one(
                {"email": "221801380012@cutmap.ac.in"},
                {"$set": {"is_admin": False}}
            )
            print("✅ Revoked admin privileges from Google Sign-In user '221801380012@cutmap.ac.in' (set to normal user)")
                
        db_mgr.disconnect()
    else:
        print("❌ MongoDB Atlas database initialization failed!")

if __name__ == "__main__":
    setup_database()