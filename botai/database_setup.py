#!/usr/bin/env python3
import os
import sys
import io
from datetime import datetime
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

# Reconfigure stdout/stderr encoding for robust terminal output on Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Setup path so we can import from botai package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from botai.config import settings
from botai.config.mongodb_config import get_db, close_db
from botai.utils.auth_utils import hash_password
from botai.models.user import User

def create_user_helper(db, email, password=None, name=None, login_method='email', google_id=None, profile_picture=None, is_admin=False, is_approved=None):
    """Create a new user document helper matching original signature"""
    try:
        password_hash = hash_password(password) if password else None
        
        if is_approved is None:
            is_approved = True  # All users are auto-approved by default

        user_doc = {
            "email": email.strip().lower(),
            "password_hash": password_hash,
            "name": name.strip() if name else None,
            "profile_picture": profile_picture,
            "login_method": login_method,
            "is_approved": is_approved,
            "token_limit": 1000000,
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
        
        result = db.users.insert_one(user_doc)
        print(f"[OK] User created successfully: {email}")
        return result.inserted_id
        
    except DuplicateKeyError:
        print(f"[WARN] User with email/google_id already exists: {email}")
        return None
    except Exception as e:
        print(f"[ERROR] Error creating user: {e}")
        return None

def setup_database():
    """Setup the complete MongoDB database collections and seed data"""
    print("[START] Setting up Claude Chatbot Database on MongoDB Atlas...")
    
    db = get_db()
    if db is not None:
        try:
            # Connect/ping check
            db.command('ping')
            print("[OK] Connected to MongoDB Atlas successfully")
            
            # 1. Users collection indexes
            db.users.create_index([("email", ASCENDING)], unique=True)
            db.users.create_index([("google_id", ASCENDING)], unique=True, sparse=True)
            print("[OK] 'users' collection indexes verified")
            
            # 2. User sessions collection indexes
            db.user_sessions.create_index([("session_token", ASCENDING)], unique=True)
            db.user_sessions.create_index([("user_id", ASCENDING)])
            print("[OK] 'user_sessions' collection indexes verified")
            
            # 3. Conversations collection indexes
            db.conversations.create_index([("user_id", ASCENDING)])
            db.conversations.create_index([("updated_at", ASCENDING)])
            print("[OK] 'conversations' collection indexes verified")
            
            # 4. Messages collection indexes
            db.messages.create_index([("conversation_id", ASCENDING)])
            db.messages.create_index([("user_id", ASCENDING)])
            print("[OK] 'messages' collection indexes verified")
            
            # 5. Token usage collection indexes
            db.token_usage.create_index([("user_id", ASCENDING)])
            db.token_usage.create_index([("created_at", ASCENDING)])
            print("[OK] 'token_usage' collection indexes verified")

            # 6. Google Drive Knowledge Base — index for fast lookup of conversations with KB loaded
            db.conversations.create_index([("gdrive_loaded_at", ASCENDING)], sparse=True)
            print("[OK] 'conversations' gdrive_loaded_at index verified")
            
            print("[OK] MongoDB Database collections and indexes built successfully!")
            
            # Check if seeded test user already exists
            test_user = db.users.find_one({"email": "test@example.com", "is_active": True})
            if not test_user:
                test_user_id = create_user_helper(
                    db,
                    email="test@example.com",
                    password="test123",
                    name="Test User",
                    login_method="email",
                    is_admin=False
                )
                if test_user_id:
                    print(f"[OK] Test user seeded successfully with ID: {test_user_id}")
            else:
                print("[INFO] Seed user 'test@example.com' already exists")
            
            # Backfill is_admin: False on existing users that do not have this field
            res_backfill = db.users.update_many(
                {"is_admin": {"$exists": False}},
                {"$set": {"is_admin": False}}
            )
            if res_backfill.modified_count > 0:
                print(f"[OK] Backfilled is_admin: False on {res_backfill.modified_count} users")

            # Backfill is_approved: True on existing users that are not approved
            res_approve = db.users.update_many(
                {"is_approved": {"$ne": True}},
                {"$set": {"is_approved": True}}
            )
            if res_approve.modified_count > 0:
                print(f"[OK] Backfilled is_approved: True on {res_approve.modified_count} users")

            # Backfill token_limit: 1000000 on existing users that do not have this field
            res_limit = db.users.update_many(
                {"token_limit": {"$exists": False}},
                {"$set": {"token_limit": 1000000}}
            )
            if res_limit.modified_count > 0:
                print(f"[OK] Backfilled token_limit: 1000000 on {res_limit.modified_count} users")
            
            # Ensure the admin account is seeded
            admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
            admin_user = db.users.find_one({"email": "secure_admin", "is_active": True})
            if not admin_user:
                admin_id = create_user_helper(
                    db,
                    email="secure_admin",
                    password=admin_password,
                    name="System Admin",
                    login_method="email",
                    is_admin=True
                )
                if admin_id:
                    print(f"[OK] Admin account seeded (email=secure_admin, password from ADMIN_PASSWORD in .env)")
            else:
                # Only ensure the is_admin flag is correct - do NOT reset the password
                db.users.update_one(
                    {"email": "secure_admin"},
                    {"$set": {"is_admin": True, "name": "System Admin"}}
                )
                print("[INFO] Admin account 'secure_admin' verified (password NOT reset - change via .env ADMIN_PASSWORD)")
            
            # Ensure regular Google/Email users do not have admin privileges (Aditya Sah set to False)
            db.users.update_one(
                {"email": "221801380012@cutmap.ac.in"},
                {"$set": {"is_admin": False}}
            )
            print("[OK] Revoked admin privileges from Google Sign-In user '221801380012@cutmap.ac.in' (set to normal user)")
            
        except Exception as e:
            print(f"[ERROR] Error during database setup: {e}")
        finally:
            close_db()
    else:
        print("[ERROR] MongoDB Atlas database initialization failed!")

if __name__ == "__main__":
    setup_database()